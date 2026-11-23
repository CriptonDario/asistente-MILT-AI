"""Endpoints de voz (reconocimiento local; la síntesis la hace el navegador)."""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from app.core.deps import AuthDep, StateDep
from app.core.errors import PayloadTooLargeError

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceStatusOut(BaseModel):
    stt_available: bool
    stt_model: str
    language: str
    #: La síntesis usa las voces del sistema operativo desde el navegador (local).
    tts: str = "browser"


class TranscriptionOut(BaseModel):
    text: str
    duration_ms: int


@router.get("/status", response_model=VoiceStatusOut)
async def voice_status(state: StateDep, _auth: AuthDep) -> VoiceStatusOut:
    return VoiceStatusOut(
        stt_available=state.voice.stt_available,
        stt_model=state.settings.voice_stt_model,
        language=state.settings.voice_language,
    )


@router.post("/transcribe", response_model=TranscriptionOut)
async def transcribe(
    state: StateDep, auth: AuthDep, audio: UploadFile = File(...)
) -> TranscriptionOut:
    await state.rate_limiter.hit(f"voice:{auth.user.id}", limit=20, window_seconds=60)
    limit = state.settings.voice_max_upload_bytes
    data = await audio.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLargeError(f"El audio supera {limit // (1024 * 1024)} MB.")
    text, duration_ms = await state.voice.transcribe(data)
    return TranscriptionOut(text=text, duration_ms=duration_ms)
