"""Endpoints de documentos (RAG)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Request, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.core.deps import AuthDep, DbDep, StateDep, client_ip
from app.core.errors import NotFoundError
from app.modules.documents.schemas import (
    DocumentOut,
    DocumentSearchHit,
    DocumentSearchRequest,
    UploadResult,
)
from app.modules.documents.service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    response: Response,
    db: DbDep,
    state: StateDep,
    auth: AuthDep,
    file: UploadFile = File(...),
) -> UploadResult:
    """Sube un documento (PDF, DOCX, XLSX, CSV, TXT). Se procesa en segundo plano."""
    doc, duplicate = await DocumentService(db, state).upload(auth.user.id, file)
    if duplicate:
        response.status_code = status.HTTP_200_OK
    else:
        await state.audit.record(
            "document.upload",
            user_id=auth.user.id,
            target_type="document",
            target_id=doc.id,
            ip=client_ip(request),
            details={"kind": doc.kind, "size": doc.size_bytes},
        )
    return UploadResult(document=DocumentOut.model_validate(doc), duplicate=duplicate)


@router.get("", response_model=list[DocumentOut])
async def list_documents(db: DbDep, state: StateDep, auth: AuthDep) -> list[DocumentOut]:
    docs = await DocumentService(db, state).list_documents(auth.user.id)
    return [DocumentOut.model_validate(d) for d in docs]


@router.post("/search", response_model=list[DocumentSearchHit])
async def search_documents(
    body: DocumentSearchRequest, db: DbDep, state: StateDep, auth: AuthDep
) -> list[DocumentSearchHit]:
    return await DocumentService(db, state).search(
        auth.user.id, body.query, document_ids=body.document_ids, top_k=body.top_k
    )


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID, db: DbDep, state: StateDep, auth: AuthDep
) -> DocumentOut:
    return DocumentOut.model_validate(
        await DocumentService(db, state).get(auth.user.id, document_id)
    )


@router.get("/{document_id}/file")
async def download_document(
    document_id: uuid.UUID, db: DbDep, state: StateDep, auth: AuthDep
) -> FileResponse:
    """Descarga el original (siempre como adjunto: nunca se renderiza en el navegador)."""
    service = DocumentService(db, state)
    doc = await service.get(auth.user.id, document_id)
    path = service.file_path(doc)
    if not path.exists():
        raise NotFoundError("El archivo original ya no está disponible.")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=doc.filename,
        content_disposition_type="attachment",
    )


@router.post("/{document_id}/reindex", response_model=DocumentOut)
async def reindex_document(
    document_id: uuid.UUID, db: DbDep, state: StateDep, auth: AuthDep
) -> DocumentOut:
    doc = await DocumentService(db, state).reindex(auth.user.id, document_id)
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, request: Request, db: DbDep, state: StateDep, auth: AuthDep
) -> None:
    await DocumentService(db, state).delete(auth.user.id, document_id)
    await state.audit.record(
        "document.delete",
        user_id=auth.user.id,
        target_type="document",
        target_id=document_id,
        ip=client_ip(request),
    )
