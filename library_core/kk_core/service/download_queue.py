"""Fila de PEDIDOS de download (só nuvem). O celular enfileira "quero esta música
nova"; o AGENTE no desktop (IP residencial — a nuvem não baixa do YouTube) puxa,
baixa, sobe pro R2 e registra no catálogo.

Tabela isolada criada com CREATE TABLE IF NOT EXISTS no 1º uso (sem Alembic). Usa
psycopg direto (o app já depende dele) no mesmo Postgres/schema da nuvem.
"""
from __future__ import annotations

import os
import time
import uuid

_READY = False


def _schema() -> str:
    return os.environ.get("DB_SCHEMA", "public")


def _connect():
    import psycopg
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(url, options=f"-c search_path={_schema()}")


def _ensure(cur) -> None:
    global _READY
    if _READY:
        return
    cur.execute(
        "CREATE TABLE IF NOT EXISTS download_requests ("
        " id text PRIMARY KEY,"
        " url text, query text, title text, artist text, requested_by text,"
        " status text NOT NULL DEFAULT 'pending',"  # pending|working|done|error
        " song_id text, detail text,"
        " created_at timestamptz DEFAULT now(),"
        " updated_at timestamptz DEFAULT now())"
    )
    _READY = True


def _row(r) -> dict:
    return {"id": r[0], "url": r[1], "query": r[2], "title": r[3], "artist": r[4],
            "requested_by": r[5], "status": r[6], "song_id": r[7], "detail": r[8],
            "created_at": r[9].isoformat() if r[9] else None}


_COLS = "id,url,query,title,artist,requested_by,status,song_id,detail,created_at"


def enqueue(*, url: str = "", query: str = "", title: str = "", artist: str = "",
            requested_by: str = "") -> dict:
    rid = str(uuid.uuid4())
    with _connect() as c, c.cursor() as cur:
        _ensure(cur)
        cur.execute(
            "INSERT INTO download_requests (id,url,query,title,artist,requested_by) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (rid, url or None, query or None, title or None, artist or None, requested_by or None))
        c.commit()
    return {"id": rid}


def list_status(status: str | None = None, limit: int = 50) -> list[dict]:
    with _connect() as c, c.cursor() as cur:
        _ensure(cur)
        if status:
            cur.execute(f"SELECT {_COLS} FROM download_requests WHERE status=%s "
                        "ORDER BY created_at DESC LIMIT %s", (status, limit))
        else:
            cur.execute(f"SELECT {_COLS} FROM download_requests "
                        "ORDER BY created_at DESC LIMIT %s", (limit,))
        return [_row(r) for r in cur.fetchall()]


def claim(limit: int = 5) -> list[dict]:
    """Agente: marca pending→working atomicamente e devolve os reclamados."""
    with _connect() as c, c.cursor() as cur:
        _ensure(cur)
        cur.execute(
            "UPDATE download_requests SET status='working', updated_at=now() "
            "WHERE id IN (SELECT id FROM download_requests WHERE status='pending' "
            "ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED) "
            f"RETURNING {_COLS}", (limit,))
        rows = [_row(r) for r in cur.fetchall()]
        c.commit()
        return rows


def complete(request_id: str, status: str, song_id: str = "", detail: str = "") -> dict:
    with _connect() as c, c.cursor() as cur:
        _ensure(cur)
        cur.execute(
            "UPDATE download_requests SET status=%s, song_id=%s, detail=%s, updated_at=now() "
            "WHERE id=%s", (status, song_id or None, detail or None, request_id))
        c.commit()
    return {"ok": True}
