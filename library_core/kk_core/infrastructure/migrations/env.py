"""Ambiente Alembic. Fonte da verdade do schema = Base.metadata (models)."""
from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from kk_core.infrastructure.db.base import Base
from kk_core.infrastructure.db import models  # noqa: F401 — registra tabelas
from kk_shared.platform.paths import default_db_path

config = context.config

db_url = os.environ.get("KK_DB_URL") or f"sqlite:///{default_db_path()}"
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to):
    # o índice FTS5 é gerenciado por DDL manual; Alembic deve ignorá-lo
    if type_ == "table" and name.startswith("songs_fts"):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=db_url, target_metadata=target_metadata,
        literal_binds=True, render_as_batch=True, include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            render_as_batch=True,  # necessário p/ ALTER em SQLite
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
