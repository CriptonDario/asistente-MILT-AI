"""Endpoints de la memoria persistente."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.deps import AuthDep, DbDep, StateDep, client_ip
from app.modules.memory.extractor import extract_suggestions
from app.modules.memory.schemas import (
    DeleteAllRequest,
    ExtractRequest,
    ExtractResult,
    MemoryCreate,
    MemoryKind,
    MemoryOut,
    MemorySearchHit,
    MemorySearchRequest,
    MemoryStats,
    MemoryUpdate,
)
from app.modules.memory.service import MemoryService, to_out

router = APIRouter(prefix="/memories", tags=["memory"])


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    db: DbDep,
    state: StateDep,
    auth: AuthDep,
    kind: MemoryKind | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[MemoryOut]:
    rows = await MemoryService(db, state).list_memories(
        auth.user.id, status="active", kind=kind, q=q
    )
    return [to_out(m) for m in rows]


@router.get("/stats", response_model=MemoryStats)
async def memory_stats(db: DbDep, state: StateDep, auth: AuthDep) -> MemoryStats:
    return await MemoryService(db, state).stats(auth.user.id)


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(body: MemoryCreate, db: DbDep, state: StateDep, auth: AuthDep) -> MemoryOut:
    return to_out(await MemoryService(db, state).create(auth.user.id, body))


@router.post("/search", response_model=list[MemorySearchHit])
async def search_memories(
    body: MemorySearchRequest, db: DbDep, state: StateDep, auth: AuthDep
) -> list[MemorySearchHit]:
    hits = await MemoryService(db, state).search(auth.user.id, body.query, top_k=body.top_k)
    return [MemorySearchHit(memory=to_out(h.memory), score=round(h.score, 4)) for h in hits]


@router.post("/reindex", response_model=MemoryStats)
async def reindex_memories(db: DbDep, state: StateDep, auth: AuthDep) -> MemoryStats:
    """Indexa los recuerdos que quedaron pendientes (p. ej. con Ollama apagado)."""
    service = MemoryService(db, state)
    await service.reindex_pending(auth.user.id)
    return await service.stats(auth.user.id)


@router.get("/suggestions", response_model=list[MemoryOut])
async def list_suggestions(db: DbDep, state: StateDep, auth: AuthDep) -> list[MemoryOut]:
    rows = await MemoryService(db, state).list_memories(
        auth.user.id, status="suggested", kind=None, q=None
    )
    return [to_out(m) for m in rows]


@router.post("/extract", response_model=ExtractResult)
async def extract_from_conversation(
    body: ExtractRequest, state: StateDep, auth: AuthDep
) -> ExtractResult:
    """Pide al modelo que proponga recuerdos de una conversación (quedan como sugerencias)."""
    created, skipped = await extract_suggestions(state, auth.user.id, body.conversation_id)
    return ExtractResult(created=[to_out(m) for m in created], skipped_duplicates=skipped)


@router.post("/suggestions/{memory_id}/accept", response_model=MemoryOut)
async def accept_suggestion(
    memory_id: uuid.UUID, db: DbDep, state: StateDep, auth: AuthDep
) -> MemoryOut:
    return to_out(await MemoryService(db, state).accept(auth.user.id, memory_id))


@router.post("/suggestions/{memory_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_suggestion(
    memory_id: uuid.UUID, db: DbDep, state: StateDep, auth: AuthDep
) -> None:
    await MemoryService(db, state).delete(auth.user.id, memory_id)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: uuid.UUID, body: MemoryUpdate, db: DbDep, state: StateDep, auth: AuthDep
) -> MemoryOut:
    return to_out(await MemoryService(db, state).update(auth.user.id, memory_id, body))


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, request: Request, db: DbDep, state: StateDep, auth: AuthDep
) -> None:
    await MemoryService(db, state).delete(auth.user.id, memory_id)
    await state.audit.record(
        "memory.delete",
        user_id=auth.user.id,
        target_type="memory",
        target_id=memory_id,
        ip=client_ip(request),
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_memories(
    body: DeleteAllRequest, request: Request, db: DbDep, state: StateDep, auth: AuthDep
) -> None:
    """Borra TODA la memoria del usuario. Requiere ``{"confirm": "DELETE"}``."""
    count = await MemoryService(db, state).delete_all(auth.user.id)
    await state.audit.record(
        "memory.delete_all",
        user_id=auth.user.id,
        ip=client_ip(request),
        details={"count": count},
    )


@router.get("/export", response_model=list[MemoryOut])
async def export_memories(db: DbDep, state: StateDep, auth: AuthDep) -> list[MemoryOut]:
    """Portabilidad: todos los recuerdos (activos y sugeridos)."""
    service = MemoryService(db, state)
    active = await service.list_memories(auth.user.id, status="active", kind=None, q=None)
    suggested = await service.list_memories(auth.user.id, status="suggested", kind=None, q=None)
    return [to_out(m) for m in [*active, *suggested]]
