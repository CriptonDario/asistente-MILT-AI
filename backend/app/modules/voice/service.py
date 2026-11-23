"""Reconocimiento de voz local con faster-whisper (dependencia opcional ``[voice]``).

- El modelo se carga la primera vez que se usa (y se descarga una sola vez desde
  Hugging Face a ``<data_dir>/models/whisper``); después funciona sin conexión.
- Una transcripción a la vez: en CPU, varias en paralelo solo competirían por la RAM.
- La síntesis de voz se hace en el navegador (voces del sistema operativo, locales).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

import anyio.to_thread
import structlog

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError, ValidationAppError

log = structlog.get_logger(__name__)

#: Firmas de los contenedores de audio admitidos (lo que graban los navegadores).
_SIGNATURES: tuple[tuple[str, bytes, int], ...] = (
    ("webm", b"\x1a\x45\xdf\xa3", 0),
    ("ogg", b"OggS", 0),
    ("wav", b"RIFF", 0),
    ("mp4", b"ftyp", 4),
    ("mp3", b"ID3", 0),
)


def detect_audio(head: bytes) -> str:
    for name, magic, offset in _SIGNATURES:
        if head[offset : offset + len(magic)] == magic:
            if name == "wav" and head[8:12] != b"WAVE":
                continue
            return name
    if head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    raise ValidationAppError("Formato de audio no soportado (usa webm, ogg, wav, mp4 o mp3).")


class Transcriber(Protocol):
    def transcribe(self, path: Path, language: str) -> str: ...


class WhisperTranscriber:
    def __init__(self, model: str, download_root: Path) -> None:
        self.model_name = model
        self.download_root = download_root
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            self.download_root.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                download_root=str(self.download_root),
            )
            log.info(
                "whisper_loaded",
                model=self.model_name,
                seconds=round(time.perf_counter() - started, 1),
            )
        return self._model

    def transcribe(self, path: Path, language: str) -> str:
        model = self._load()
        segments, _info = model.transcribe(
            str(path), language=language, beam_size=1, vad_filter=True
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def whisper_installed() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


class VoiceService:
    def __init__(self, settings: Settings, transcriber: Transcriber | None = None) -> None:
        self.settings = settings
        self._transcriber = transcriber
        self._lock = asyncio.Lock()

    @property
    def stt_available(self) -> bool:
        return self._transcriber is not None or whisper_installed()

    def _get_transcriber(self) -> Transcriber:
        if self._transcriber is None:
            if not whisper_installed():
                raise ServiceUnavailableError(
                    "El reconocimiento de voz no está instalado. En backend/: uv sync --extra voice"
                )
            self._transcriber = WhisperTranscriber(
                self.settings.voice_stt_model, self.settings.data_dir / "models" / "whisper"
            )
        return self._transcriber

    async def transcribe(self, data: bytes, *, language: str | None = None) -> tuple[str, int]:
        if not data:
            raise ValidationAppError("El audio está vacío.")
        kind = detect_audio(data[:16])
        transcriber = self._get_transcriber()
        tmp_dir = self.settings.data_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        path = tmp_dir / f"voz-{uuid.uuid4().hex}.{kind}"
        path.write_bytes(data)
        started = time.perf_counter()
        try:
            async with self._lock:
                text = await anyio.to_thread.run_sync(
                    transcriber.transcribe, path, language or self.settings.voice_language
                )
        except (ValidationAppError, ServiceUnavailableError):
            raise
        except Exception as exc:
            log.exception("voice_transcription_failed")
            raise ValidationAppError("No se pudo transcribir el audio.") from exc
        finally:
            with contextlib.suppress(OSError):
                path.unlink()
        return text, round((time.perf_counter() - started) * 1000)
