"""Hash de contraseñas con Argon2id y política de contraseñas."""

from __future__ import annotations

import secrets

import anyio.to_thread
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import ValidationAppError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128

# Lista mínima local (sin red). Se ampliará con un fichero de contraseñas filtradas.
_COMMON_PASSWORDS = frozenset(
    {
        "123456789012",
        "1234567890123",
        "123456789abc",
        "contraseña123",
        "contrasena123",
        "password1234",
        "password12345",
        "passwordpassword",
        "qwertyuiop12",
        "qwertyuiopasdf",
        "administrador",
        "admin1234567",
        "iloveyou1234",
        "111111111111",
        "000000000000",
        "abcdefghijkl",
        "abc123abc123",
        "letmein12345",
        "welcome12345",
        "bienvenido123",
    }
)


def validate_password_strength(password: str, *, email: str | None = None) -> None:
    """Política NIST SP 800-63B: longitud mínima y sin contraseñas comunes."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationAppError(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValidationAppError(
            f"La contraseña no puede superar {MAX_PASSWORD_LENGTH} caracteres."
        )
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or len(set(password)) < 4:
        raise ValidationAppError("La contraseña es demasiado común o predecible.")
    if email and lowered == email.lower():
        raise ValidationAppError("La contraseña no puede ser igual al correo.")


class PasswordService:
    """Argon2id. Las operaciones costosas se ejecutan en un hilo para no bloquear el loop."""

    def __init__(self, *, time_cost: int, memory_cost_kib: int, parallelism: int) -> None:
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost_kib,
            parallelism=parallelism,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        # Hash señuelo para igualar tiempos cuando el usuario no existe.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))

    async def hash(self, password: str) -> str:
        return await anyio.to_thread.run_sync(self._hasher.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        try:
            return await anyio.to_thread.run_sync(self._hasher.verify, password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    async def verify_dummy(self, password: str) -> None:
        await self.verify(self._dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True
