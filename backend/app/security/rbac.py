"""Control de acceso basado en roles."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class Permission(StrEnum):
    USERS_MANAGE = "users:manage"
    AUDIT_READ_ALL = "audit:read_all"
    MODELS_PULL = "models:pull"
    SCRIPTS_REGISTER = "scripts:register"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.USER: frozenset(),
}


def has_permission(role: str, permission: Permission) -> bool:
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False
