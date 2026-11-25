"""Política de permisos: qué herramientas se ejecutan solas, cuáles se confirman y cuáles no."""

from __future__ import annotations

from typing import Any

from app.core.errors import ValidationAppError
from app.tools.base import Decision, RiskLevel, Tool

DEFAULT_DECISION: dict[RiskLevel, Decision] = {
    RiskLevel.READ: Decision.AUTO,
    RiskLevel.INTERNAL: Decision.AUTO,
    RiskLevel.WRITE: Decision.CONFIRM,
    RiskLevel.EXECUTE: Decision.CONFIRM,
    RiskLevel.NETWORK: Decision.CONFIRM,
}

#: Riesgos que nunca pueden ejecutarse sin confirmación (ni aunque el usuario lo pida).
ALWAYS_CONFIRM = frozenset({RiskLevel.EXECUTE, RiskLevel.NETWORK})
#: Riesgos denegados en sesiones remotas (acceso desde fuera del equipo).
DENIED_REMOTE = frozenset({RiskLevel.WRITE, RiskLevel.EXECUTE, RiskLevel.NETWORK})


def validate_override(tool: Tool[Any], decision: Decision) -> None:
    if decision == Decision.AUTO and tool.risk in ALWAYS_CONFIRM:
        raise ValidationAppError(
            f"La herramienta {tool.name} ({tool.risk.value}) siempre requiere confirmación."
        )


def decide(tool: Tool[Any], overrides: dict[str, str] | None, *, remote: bool) -> Decision:
    if remote and tool.risk in DENIED_REMOTE:
        return Decision.DENY
    raw = (overrides or {}).get(tool.name)
    if raw is not None:
        try:
            override = Decision(raw)
        except ValueError:
            override = None
        if override is not None:
            # Una preferencia guardada nunca puede saltarse la confirmación obligatoria.
            if override == Decision.AUTO and tool.risk in ALWAYS_CONFIRM:
                return Decision.CONFIRM
            return override
    return DEFAULT_DECISION[tool.risk]
