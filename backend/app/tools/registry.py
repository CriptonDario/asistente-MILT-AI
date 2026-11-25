"""Catálogo de herramientas disponibles y selección por perfil de agente."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.tools.base import Tool
from app.tools.builtin.automation import ScriptRunTool
from app.tools.builtin.files import (
    CodeSearchTool,
    FileListTool,
    FileReadTool,
    FileWriteTool,
    ProjectTreeTool,
)
from app.tools.builtin.knowledge import DocSearchTool
from app.tools.builtin.security import (
    IocMatchTool,
    LogsAnalyzeTool,
    NetDiagnoseTool,
    SecurityReportTool,
)


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool[Any]]) -> None:
        self._tools: dict[str, Tool[Any]] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Herramienta duplicada: {tool.name}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool[Any] | None:
        return self._tools.get(name)

    def all(self) -> list[Tool[Any]]:
        return list(self._tools.values())

    def for_profile(self, profile: str) -> list[Tool[Any]]:
        return [t for t in self._tools.values() if profile in t.profiles]


def default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            FileListTool(),
            FileReadTool(),
            ProjectTreeTool(),
            CodeSearchTool(),
            FileWriteTool(),
            DocSearchTool(),
            ScriptRunTool(),
            LogsAnalyzeTool(),
            IocMatchTool(),
            NetDiagnoseTool(),
            SecurityReportTool(),
        ]
    )
