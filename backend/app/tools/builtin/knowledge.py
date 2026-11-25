"""Herramientas sobre el conocimiento del usuario: búsqueda en sus documentos."""

from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import Field

from app.modules.documents.service import DocumentService
from app.tools.base import RiskLevel, Tool, ToolArgs, ToolContext, ToolResult, truncate


class DocSearchArgs(ToolArgs):
    query: Annotated[str, Field(min_length=2, max_length=500, description="Qué buscar")]
    top_k: int = Field(default=4, ge=1, le=8)


class DocSearchTool(Tool[DocSearchArgs]):
    name = "doc_search"
    description = (
        "Busca en los documentos que el usuario ha subido a MILT y devuelve los fragmentos "
        "más relevantes con su fuente."
    )
    risk = RiskLevel.READ
    Args = DocSearchArgs
    profiles: ClassVar[frozenset[str]] = frozenset({"general", "coder", "security", "documents"})

    def describe(self, args: DocSearchArgs) -> str:
        return f"Buscar «{args.query}» en tus documentos"

    async def run(self, args: DocSearchArgs, ctx: ToolContext) -> ToolResult:
        async with ctx.state.sessionmaker() as db:
            hits = await DocumentService(db, ctx.state).search(
                ctx.user_id, args.query, document_ids=None, top_k=args.top_k
            )
        if not hits:
            return ToolResult(
                content="No hay fragmentos relevantes en tus documentos.", summary="Sin resultados"
            )
        parts = [
            f"[{i}] {h.filename}" + (f" ({h.location})" if h.location else "") + f":\n{h.content}"
            for i, h in enumerate(hits, start=1)
        ]
        return ToolResult(
            content=truncate("\n\n".join(parts)),
            summary=f"{len(hits)} fragmentos de {len({h.filename for h in hits})} documentos",
        )
