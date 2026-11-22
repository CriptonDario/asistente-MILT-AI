"""Ejecución programática de migraciones Alembic."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # ConfigParser interpreta '%': se escapa para URLs con contraseñas codificadas.
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


def run_migrations(database_url: str) -> None:
    """Aplica todas las migraciones pendientes (síncrono: ejecutar en un hilo)."""
    command.upgrade(alembic_config(database_url), "head")
