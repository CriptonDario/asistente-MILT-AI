"""Configuración de la aplicación (variables de entorno con prefijo ``MILT_``)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    """Directorio de datos del usuario (BD, secretos, logs). Nunca dentro del código."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "MILT"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "milt"


class Settings(BaseSettings):
    """Configuración tipada. Los valores se leen de ``MILT_*`` y de ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="MILT_",
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -------------------------------------------------------------
    profile: Literal["local", "server"] = "local"
    env: Literal["development", "production", "test"] = "development"
    app_name: str = "MILT AI"
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    data_dir: Path = Field(default_factory=default_data_dir)
    database_url: str | None = None
    auto_migrate: bool = True

    # --- HTTP / seguridad de transporte --------------------------------------
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://tauri.localhost",
        "tauri://localhost",
    ]
    max_body_bytes: int = Field(default=1_048_576, ge=1024)
    log_level: str = "INFO"
    log_json: bool = True

    # --- Autenticación --------------------------------------------------------
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "milt-ai"
    jwt_audience: str = "milt-api"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)
    cookie_secure: bool = True
    allow_registration: bool = False
    local_bootstrap_token: SecretStr | None = None
    argon2_time_cost: int = Field(default=3, ge=1)
    argon2_memory_cost_kib: int = Field(default=65_536, ge=8)
    argon2_parallelism: int = Field(default=2, ge=1)
    login_attempts_per_minute: int = Field(default=5, ge=1)
    lockout_threshold: int = Field(default=5, ge=1)

    # --- Motor de IA ----------------------------------------------------------
    llm_provider: Literal["ollama", "fake"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen3:1.7b"
    default_num_ctx: int = Field(default=4096, ge=512)
    default_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_think: bool = False
    llm_connect_timeout: float = Field(default=5.0, gt=0)
    llm_read_timeout: float = Field(default=600.0, gt=0)
    chat_max_input_chars: int = Field(default=32_000, ge=1)
    chat_max_turns_per_user: int = Field(default=2, ge=1)

    # --- Memoria y documentos (RAG) ---------------------------------------------
    #: Qdrant en servidor (perfil server). Si no se define, se usa el modo embebido.
    vector_url: str | None = None
    embedding_model: str = "nomic-embed-text"
    embedding_batch_size: int = Field(default=16, ge=1, le=256)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_document_chunks: int = Field(default=1000, ge=1)
    #: Total de fragmentos por usuario. Qdrant embebido guarda todo en RAM (~3 KB/vector).
    max_chunks_per_user: int = Field(default=20_000, ge=1)
    max_documents_per_user: int = Field(default=200, ge=1)
    # --- Herramientas y automatización ------------------------------------------
    #: Máximo de llamadas a herramientas por turno y presupuesto total de tiempo.
    agent_max_tool_calls: int = Field(default=6, ge=1, le=20)
    agent_time_budget_seconds: float = Field(default=900.0, gt=0)
    tool_timeout_seconds: float = Field(default=60.0, gt=0)
    tool_confirm_timeout_seconds: float = Field(default=120.0, gt=0)
    #: Límite de memoria (MB) y tiempo (s) por defecto para los scripts autorizados.
    script_memory_mb: int = Field(default=512, ge=32)
    script_max_timeout_seconds: int = Field(default=300, ge=1)
    script_python: str = "python"

    # --- Voz -----------------------------------------------------------------------
    #: Modelo de faster-whisper (tiny, base, small...). "base" equilibra calidad y RAM.
    voice_stt_model: str = "base"
    voice_language: str = "es"
    voice_max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    #: Duración máxima del audio decodificado. 10 MB de Opus pueden ser horas de audio:
    #: sin este tope, decodificarlo agotaría la RAM y la CPU.
    voice_max_seconds: int = Field(default=120, ge=5, le=1800)

    #: Parseo en un subproceso con límite de tiempo (aísla archivos maliciosos).
    parse_isolated: bool = True
    parse_timeout_seconds: float = Field(default=120.0, gt=0)
    chunk_chars: int = Field(default=2000, ge=200)
    chunk_overlap_chars: int = Field(default=250, ge=0)
    rag_top_k: int = Field(default=4, ge=1, le=20)
    rag_min_score: float = Field(default=0.4, ge=0.0, le=1.0)
    memory_top_k: int = Field(default=5, ge=1, le=20)
    # Calibrado con nomic-embed-text: relevantes ~0,62-0,67; irrelevantes ~0,48-0,58.
    memory_min_score: float = Field(default=0.6, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_profile(self) -> Settings:
        if self.profile == "server":
            if not self.database_url:
                raise ValueError("MILT_DATABASE_URL es obligatorio en el perfil 'server'")
            secret = self.jwt_secret.get_secret_value() if self.jwt_secret else ""
            if len(secret) < 32:
                raise ValueError(
                    "MILT_JWT_SECRET (>= 32 caracteres) es obligatorio en el perfil 'server'"
                )
        return self

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'milt.db').as_posix()}"

    @property
    def vector_path(self) -> Path:
        return self.data_dir / "vectors"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")
