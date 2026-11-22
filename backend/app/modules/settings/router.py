"""Preferencias del usuario autenticado."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import AuthDep, DbDep, StateDep
from app.modules.settings import service
from app.modules.settings.schemas import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def get_settings(db: DbDep, state: StateDep, auth: AuthDep) -> SettingsOut:
    prefs = await service.get_or_create(db, auth.user.id)
    await db.commit()
    return service.to_out(prefs, state.settings)


@router.patch("", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdate, db: DbDep, state: StateDep, auth: AuthDep
) -> SettingsOut:
    prefs = await service.update(db, auth.user.id, body)
    return service.to_out(prefs, state.settings)
