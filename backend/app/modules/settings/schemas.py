"""Esquemas de preferencias de usuario."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.base import GenerationParams

ModelName = str
MODEL_NAME_PATTERN = r"^[A-Za-z0-9._:/@-]{1,200}$"
Theme = Literal["dark", "light", "system"]


class SettingsOut(BaseModel):
    theme: Theme
    language: str
    default_model: str | None
    effective_default_model: str
    generation_defaults: GenerationParams


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Theme | None = None
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    default_model: str | None = Field(default=None, pattern=MODEL_NAME_PATTERN)
    generation_defaults: GenerationParams | None = None
