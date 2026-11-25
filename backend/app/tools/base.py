"""Contrato de las herramientas que el modelo puede pedir usar.

Principio (docs/fase-1/06-seguridad.md §4): el LLM *propone*, la política *decide* y el
usuario *confirma*. Ninguna herramienta ejecuta comandos arbitrarios.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from app.core.errors import AppError

if TYPE_CHECKING:
    from app.core.state import AppState

#: Máximo de caracteres del resultado que se devuelve al modelo (cabe en el contexto).
MAX_RESULT_CHARS = 6000


class RiskLevel(StrEnum):
    READ = "read"  # lee archivos dentro de las carpetas permitidas
    INTERNAL = "internal"  # escribe solo en el almacenamiento de MILT (reportes)
    WRITE = "write"  # modifica archivos del usuario
    EXECUTE = "execute"  # ejecuta un script autorizado
    NETWORK = "network"  # consulta la red (solo la propia)


class Decision(StrEnum):
    AUTO = "auto"
    CONFIRM = "confirm"
    DENY = "deny"


class ToolError(AppError):
    status_code = 422
    code = "tool_error"
    title = "La herramienta no pudo completarse"


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


A = TypeVar("A", bound=ToolArgs)


@dataclass
class ToolContext:
    state: AppState
    user_id: uuid.UUID
    user_role: str
    conversation_id: uuid.UUID | None
    allowed_roots: list[Path] = field(default_factory=list)
    #: Sesión remota (relay, Fase 7): las herramientas sensibles quedan denegadas.
    remote: bool = False


@dataclass(frozen=True)
class ToolResult:
    #: Texto que recibe el modelo (se recorta a MAX_RESULT_CHARS).
    content: str
    #: Resumen corto para la interfaz y el historial.
    summary: str
    data: dict[str, Any] | None = None


def truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [recortado: {len(text) - limit} caracteres más]"


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Esquema JSON compacto para el modelo: sin títulos (ahorra tokens)."""
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if isinstance(value, dict):
            cleaned[key] = _clean_schema(value)
        elif isinstance(value, list):
            cleaned[key] = [_clean_schema(v) if isinstance(v, dict) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


class Tool(ABC, Generic[A]):
    name: ClassVar[str]
    description: ClassVar[str]
    risk: ClassVar[RiskLevel]
    Args: ClassVar[type[ToolArgs]]
    #: Perfiles de agente en los que se ofrece (limita los tokens del prompt).
    profiles: ClassVar[frozenset[str]]
    #: Necesita carpetas permitidas configuradas.
    needs_roots: ClassVar[bool] = False

    def spec(self) -> dict[str, Any]:
        """Definición en formato de función para Ollama."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _clean_schema(self.Args.model_json_schema()),
            },
        }

    def describe(self, args: A) -> str:
        """Resumen legible de lo que se va a hacer (se muestra al pedir confirmación)."""
        return f"{self.name}({args.model_dump_json()})"

    @abstractmethod
    async def run(self, args: A, ctx: ToolContext) -> ToolResult: ...
