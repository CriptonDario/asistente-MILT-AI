"""Registro, inicio de sesión, rotación de refresh tokens y sesiones."""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.core.state import AppState
from app.db.types import utcnow
from app.modules.auth.context import AuthContext
from app.modules.auth.models import Device, RefreshToken
from app.modules.auth.schemas import LoginRequest, RegisterRequest, SessionOut
from app.modules.users import repository as users_repo
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService
from app.security.passwords import validate_password_strength
from app.security.rbac import Role
from app.security.tokens import generate_refresh_token, hash_token

INVALID_CREDENTIALS = "Correo o contraseña incorrectos, o la cuenta está bloqueada temporalmente."
MAX_LOCKOUT_MINUTES = 60


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    user: User
    session_id: uuid.UUID


def _truncate(value: str | None, length: int) -> str | None:
    return value[:length] if value else None


class AuthService:
    def __init__(self, db: AsyncSession, state: AppState) -> None:
        self.db = db
        self.state = state
        self.settings = state.settings

    # ------------------------------------------------------------------ registro
    async def register(self, data: RegisterRequest, *, ip: str | None) -> User:
        await self.state.rate_limiter.hit(f"register:{ip}", limit=5, window_seconds=3600)
        is_first_user = await users_repo.count_users(self.db) == 0
        if not is_first_user and not self.settings.allow_registration:
            raise ForbiddenError("El registro público está deshabilitado.")
        role = Role.ADMIN if is_first_user else Role.USER
        user = await UserService(self.db, self.state.passwords).create(
            UserCreate(
                email=data.email,
                display_name=data.display_name,
                password=data.password,
                role=role,
            )
        )
        await self.state.audit.record(
            "auth.register",
            user_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=ip,
            details={"role": role.value, "first_user": is_first_user},
        )
        return user

    # ------------------------------------------------------------------ login
    async def login(
        self, data: LoginRequest, *, ip: str | None, user_agent: str | None
    ) -> IssuedTokens:
        limit = self.settings.login_attempts_per_minute
        await self.state.rate_limiter.hit(f"login:ip:{ip}", limit=limit * 4, window_seconds=60)
        await self.state.rate_limiter.hit(
            f"login:email:{data.email}", limit=limit, window_seconds=60
        )

        user = await users_repo.get_by_email(self.db, data.email)
        if user is None:
            await self.state.passwords.verify_dummy(data.password)
            await self._audit_login_failure(None, ip, "unknown_user")
            raise UnauthorizedError(INVALID_CREDENTIALS)

        now = utcnow()
        if user.locked_until is not None and user.locked_until > now:
            await self.state.passwords.verify_dummy(data.password)
            await self._audit_login_failure(user.id, ip, "locked")
            raise UnauthorizedError(INVALID_CREDENTIALS)

        valid = await self.state.passwords.verify(user.password_hash, data.password)
        if not valid or not user.is_active:
            if not valid:
                user.failed_logins += 1
                if user.failed_logins >= self.settings.lockout_threshold:
                    exponent = user.failed_logins - self.settings.lockout_threshold
                    minutes = min(2**exponent, MAX_LOCKOUT_MINUTES)
                    user.locked_until = now + timedelta(minutes=minutes)
                await self.db.commit()
            await self._audit_login_failure(
                user.id, ip, "bad_password" if not valid else "inactive"
            )
            raise UnauthorizedError(INVALID_CREDENTIALS)

        user.failed_logins = 0
        user.locked_until = None
        user.last_login_at = now
        if self.state.passwords.needs_rehash(user.password_hash):
            user.password_hash = await self.state.passwords.hash(data.password)

        device = Device(user_id=user.id, name=data.device_name, platform=data.platform)
        device.last_seen_at = now
        self.db.add(device)
        await self.db.flush()
        tokens = self._issue(
            user, family_id=uuid.uuid4(), device_id=device.id, ip=ip, ua=user_agent
        )
        await self.db.commit()
        await self.state.rate_limiter.reset(f"login:email:{data.email}")
        await self.state.audit.record(
            "auth.login",
            user_id=user.id,
            target_type="session",
            target_id=tokens.session_id,
            ip=ip,
            details={"platform": data.platform},
        )
        return tokens

    async def _audit_login_failure(
        self, user_id: uuid.UUID | None, ip: str | None, reason: str
    ) -> None:
        await self.state.audit.record(
            "auth.login", user_id=user_id, outcome="failure", ip=ip, details={"reason": reason}
        )

    # ------------------------------------------------------------------ tokens
    def _issue(
        self,
        user: User,
        *,
        family_id: uuid.UUID,
        device_id: uuid.UUID | None,
        ip: str | None,
        ua: str | None,
    ) -> IssuedTokens:
        raw, token_hash = generate_refresh_token()
        refresh_expires = utcnow() + timedelta(days=self.settings.refresh_token_ttl_days)
        self.db.add(
            RefreshToken(
                user_id=user.id,
                device_id=device_id,
                token_hash=token_hash,
                family_id=family_id,
                expires_at=refresh_expires,
                ip=_truncate(ip, 64),
                user_agent=_truncate(ua, 300),
            )
        )
        access, access_expires = self.state.tokens.create_access_token(
            user_id=user.id, role=user.role, session_id=family_id
        )
        return IssuedTokens(
            access_token=access,
            access_expires_at=access_expires,
            refresh_token=raw,
            refresh_expires_at=refresh_expires,
            user=user,
            session_id=family_id,
        )

    async def _revoke_family(self, family_id: uuid.UUID) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )

    async def refresh(self, raw: str, *, ip: str | None, user_agent: str | None) -> IssuedTokens:
        await self.state.rate_limiter.hit(f"refresh:{ip}", limit=60, window_seconds=60)
        token = await self.db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
        )
        if token is None:
            raise UnauthorizedError("Refresh token no válido.")

        now = utcnow()
        if token.revoked_at is not None:
            # Reutilización de un token ya rotado: posible robo. Se cierra toda la sesión.
            await self._revoke_family(token.family_id)
            await self.db.commit()
            await self.state.audit.record(
                "auth.refresh_reuse",
                user_id=token.user_id,
                target_type="session",
                target_id=token.family_id,
                outcome="denied",
                ip=ip,
            )
            raise UnauthorizedError("La sesión ha sido revocada por seguridad.")
        if token.expires_at <= now:
            raise UnauthorizedError("El refresh token ha expirado.")

        user = await users_repo.get_by_id(self.db, token.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Usuario no válido o desactivado.")

        token.revoked_at = now
        if token.device_id is not None:
            device = await self.db.get(Device, token.device_id)
            if device is not None:
                device.last_seen_at = now
        tokens = self._issue(
            user, family_id=token.family_id, device_id=token.device_id, ip=ip, ua=user_agent
        )
        await self.db.commit()
        return tokens

    # ------------------------------------------------------------------ sesiones
    async def logout(self, auth: AuthContext, *, ip: str | None) -> None:
        await self._revoke_family(auth.session_id)
        await self.db.commit()
        await self.state.audit.record(
            "auth.logout",
            user_id=auth.user.id,
            target_type="session",
            target_id=auth.session_id,
            ip=ip,
        )

    async def change_password(
        self, auth: AuthContext, current: str, new: str, *, ip: str | None
    ) -> None:
        user = auth.user
        if not await self.state.passwords.verify(user.password_hash, current):
            await self.state.audit.record(
                "auth.password_change", user_id=user.id, outcome="failure", ip=ip
            )
            raise UnauthorizedError("La contraseña actual no es correcta.")
        validate_password_strength(new, email=user.email)
        db_user = await users_repo.get_by_id(self.db, user.id)
        if db_user is None:
            raise UnauthorizedError()
        db_user.password_hash = await self.state.passwords.hash(new)
        await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.family_id != auth.session_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
        await self.db.commit()
        await self.state.audit.record("auth.password_change", user_id=user.id, ip=ip)

    async def list_sessions(self, auth: AuthContext) -> list[SessionOut]:
        rows = (
            await self.db.execute(
                select(RefreshToken, Device)
                .outerjoin(Device, Device.id == RefreshToken.device_id)
                .where(
                    RefreshToken.user_id == auth.user.id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > utcnow(),
                )
                .order_by(RefreshToken.created_at.desc())
            )
        ).all()
        return [
            SessionOut(
                id=token.family_id,
                device_name=device.name if device else None,
                platform=device.platform if device else None,
                started_at=device.created_at if device else token.created_at,
                last_refresh_at=token.created_at,
                expires_at=token.expires_at,
                ip=token.ip,
                user_agent=token.user_agent,
                current=token.family_id == auth.session_id,
            )
            for token, device in rows
        ]

    async def revoke_session(
        self, auth: AuthContext, family_id: uuid.UUID, *, ip: str | None
    ) -> None:
        owned = await self.db.scalar(
            select(RefreshToken.id)
            .where(RefreshToken.family_id == family_id, RefreshToken.user_id == auth.user.id)
            .limit(1)
        )
        if owned is None:
            raise NotFoundError("Sesión no encontrada.")
        await self._revoke_family(family_id)
        await self.db.commit()
        await self.state.audit.record(
            "auth.session_revoke",
            user_id=auth.user.id,
            target_type="session",
            target_id=family_id,
            ip=ip,
        )

    # ------------------------------------------------------------------ perfil local
    async def local_exchange(
        self, token: str, *, ip: str | None, user_agent: str | None
    ) -> IssuedTokens:
        """Intercambia el token de arranque de la app de escritorio por una sesión."""
        expected = self.settings.local_bootstrap_token
        await self.state.rate_limiter.hit(f"local-exchange:{ip}", limit=10, window_seconds=60)
        if expected is None or not hmac.compare_digest(
            token.encode(), expected.get_secret_value().encode()
        ):
            await self.state.audit.record("auth.local_exchange", outcome="denied", ip=ip)
            raise UnauthorizedError("Token local no válido.")
        user = await users_repo.first_admin(self.db)
        if user is None:
            raise ConflictError("Primero debes crear la cuenta de administrador.")
        device = Device(user_id=user.id, name="MILT Escritorio", platform="windows")
        device.last_seen_at = utcnow()
        self.db.add(device)
        await self.db.flush()
        tokens = self._issue(
            user, family_id=uuid.uuid4(), device_id=device.id, ip=ip, ua=user_agent
        )
        await self.db.commit()
        await self.state.audit.record(
            "auth.local_exchange",
            user_id=user.id,
            target_type="session",
            target_id=tokens.session_id,
            ip=ip,
        )
        return tokens
