"""Lectura y actualización de preferencias de usuario."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.llm.base import GenerationParams
from app.modules.settings.models import UserSettings
from app.modules.settings.schemas import SettingsOut, SettingsUpdate


async def get_or_create(db: AsyncSession, user_id: uuid.UUID) -> UserSettings:
    prefs = await db.get(UserSettings, user_id)
    if prefs is None:
        prefs = UserSettings(user_id=user_id, theme="system", language="es")
        db.add(prefs)
        await db.flush()
    return prefs


def base_generation_params(settings: Settings, prefs: UserSettings | None) -> GenerationParams:
    """Parámetros globales sobrescritos por las preferencias del usuario."""
    base = GenerationParams(
        temperature=settings.default_temperature,
        num_ctx=settings.default_num_ctx,
        think=settings.llm_think,
    )
    if prefs and prefs.generation_defaults:
        return GenerationParams(**prefs.generation_defaults).merged_over(base)
    return base


def to_out(prefs: UserSettings, settings: Settings) -> SettingsOut:
    return SettingsOut(
        theme=prefs.theme,
        language=prefs.language,
        default_model=prefs.default_model,
        effective_default_model=prefs.default_model or settings.default_model,
        generation_defaults=base_generation_params(settings, prefs),
    )


async def update(db: AsyncSession, user_id: uuid.UUID, data: SettingsUpdate) -> UserSettings:
    prefs = await get_or_create(db, user_id)
    fields = data.model_fields_set
    if "theme" in fields and data.theme is not None:
        prefs.theme = data.theme
    if "language" in fields and data.language is not None:
        prefs.language = data.language
    if "default_model" in fields:
        prefs.default_model = data.default_model
    if "generation_defaults" in fields:
        prefs.generation_defaults = (
            data.generation_defaults.model_dump(exclude_none=True)
            if data.generation_defaults
            else None
        )
    await db.commit()
    return prefs
