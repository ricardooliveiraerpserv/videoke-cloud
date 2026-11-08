"""Criação do engine SQLite afinado para performance (seção 13) + bootstrap
do schema, incluindo o índice FTS5."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from kk_shared.platform.paths import default_db_path

from .base import Base
from . import models  # noqa: F401 — registra os modelos no metadata

FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS songs_fts USING fts5(
    song_id UNINDEXED,
    title_norm,
    artist_norm,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


# F1 — busca no Postgres: tabela comum (sem FTS5) consultada por ILIKE/_scope.
PG_SEARCH_DDL = """
CREATE TABLE IF NOT EXISTS songs_search (
    song_id     text PRIMARY KEY,
    title_norm  text,
    artist_norm text
);
"""


def _apply_pragmas(dbapi_conn, _rec) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA foreign_keys=ON;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA temp_store=MEMORY;")
    cur.execute("PRAGMA cache_size=-16000;")   # ~16 MB
    cur.execute("PRAGMA busy_timeout=5000;")   # espera locks (daemon + import juntos)
    cur.close()


def create_db_engine(db_path: str | Path | None = None, echo: bool = False) -> Engine:
    """SQLite (local) ou Postgres (nuvem). Usa DATABASE_URL se definido, ou um
    db_path que já seja uma URL postgres://; senão trata como caminho SQLite."""
    import os
    if db_path is not None:                      # caminho explícito tem prioridade
        path = str(db_path)
        if path.startswith(("postgresql", "postgres://")):
            url = path
        else:
            url = "sqlite://" if path == ":memory:" else f"sqlite:///{path}"
    else:                                        # sem caminho → DATABASE_URL (nuvem) ou default
        url = os.environ.get("DATABASE_URL") or f"sqlite:///{default_db_path()}"
    # normaliza p/ o driver psycopg3 (Render/Supabase dão 'postgresql://...')
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    # Isolamento num schema próprio (ex.: compartilhar o Supabase do Mês Redondo).
    # Via libpq `options` → vale p/ TODA conexão/consulta (ORM e SQL cru), sem
    # depender de timing de listener.
    connect_args: dict = {}
    schema = os.environ.get("DB_SCHEMA")
    if "postgresql" in url and schema:
        # SÓ o schema próprio no search_path: isolamento total e o create_all não
        # confunde com tabelas de mesmo nome em 'public' (ex.: ambiente de teste).
        connect_args["options"] = f"-c search_path={schema}"
    engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _apply_pragmas)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_schema(engine: Engine) -> None:
    """Cria tabelas + índice de busca do dialeto (FTS5 no SQLite, songs_search no PG).
    No Postgres, respeita DB_SCHEMA (schema próprio p/ compartilhar a instância)."""
    import os
    schema = os.environ.get("DB_SCHEMA")
    if engine.dialect.name == "postgresql" and schema:
        try:   # role escopada não cria schema (nem precisa — o admin já criou)
            with engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        except Exception:  # noqa: BLE001
            pass
    Base.metadata.create_all(engine)   # vai pro schema do search_path
    with engine.begin() as conn:
        conn.execute(text(FTS_DDL if engine.dialect.name == "sqlite" else PG_SEARCH_DDL))
