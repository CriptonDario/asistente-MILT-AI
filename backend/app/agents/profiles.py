"""Perfiles de agente y construcción del prompt de sistema."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

AgentProfileName = Literal["general", "coder", "security", "documents"]

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_PROFILE_ADDENDA: dict[str, str] = {
    "general": "",
    "coder": (
        "Perfil activo: asistente de programación. Analiza, genera y depura código en "
        "Python, PHP, Java, Kotlin, JavaScript/TypeScript, C# y SQL. Explica la causa de los "
        "errores antes de proponer la solución y entrega código completo y funcional."
    ),
    "security": (
        "Perfil activo: ciberseguridad defensiva. Ayudas a analizar logs, configuraciones e "
        "indicadores de compromiso de sistemas propios del usuario. No ayudas a atacar "
        "sistemas de terceros."
    ),
    "documents": (
        "Perfil activo: análisis de documentos. Resume y extrae información con precisión, "
        "citando la parte del documento en la que te basas."
    ),
}


@lru_cache(maxsize=8)
def _load_template(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def build_system_prompt(profile: str, *, user_name: str, today: date | None = None) -> str:
    base = _load_template("general").format(
        user_name=user_name or "el usuario",
        today=(today or date.today()).isoformat(),
    )
    addendum = _PROFILE_ADDENDA.get(profile, "")
    return f"{base}\n{addendum}".strip()
