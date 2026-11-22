"""Las migraciones crean exactamente el esquema de los modelos y son reversibles."""

from __future__ import annotations

from pathlib import Path

from alembic import command

from app.db.migrate import alembic_config, run_migrations


def test_upgrade_matches_models_and_downgrade(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url)
    cfg = alembic_config(url)
    # Falla si los modelos tienen cambios que no están en ninguna migración.
    command.check(cfg)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
