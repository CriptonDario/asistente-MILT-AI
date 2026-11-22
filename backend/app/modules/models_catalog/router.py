"""Catálogo de modelos disponibles en los proveedores de IA."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.deps import AuthDep, StateDep
from app.llm.base import ModelInfo

router = APIRouter(prefix="/models", tags=["models"])


class ModelOut(BaseModel):
    provider: str
    name: str
    size_bytes: int | None
    family: str | None
    parameter_size: str | None
    quantization: str | None
    context_length: int | None
    capabilities: list[str]
    is_default: bool


def _to_out(info: ModelInfo, default_model: str) -> ModelOut:
    return ModelOut(
        provider=info.provider,
        name=info.name,
        size_bytes=info.size_bytes,
        family=info.family,
        parameter_size=info.parameter_size,
        quantization=info.quantization,
        context_length=info.context_length,
        capabilities=list(info.capabilities),
        is_default=info.name == default_model,
    )


@router.get("", response_model=list[ModelOut])
async def list_models(state: StateDep, _auth: AuthDep) -> list[ModelOut]:
    """Modelos instalados. Devuelve 503 si el motor de IA no está disponible."""
    models = await state.llm.get().list_models()
    default = state.settings.default_model
    return sorted((_to_out(m, default) for m in models), key=lambda m: (not m.is_default, m.name))


@router.get("/{name:path}", response_model=ModelOut)
async def get_model(name: str, state: StateDep, _auth: AuthDep) -> ModelOut:
    info = await state.llm.get().get_model(name)
    return _to_out(info, state.settings.default_model)
