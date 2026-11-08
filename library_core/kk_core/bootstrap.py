"""Composition root do Library Core (modo in-process).

Monta engine + schema + client. As aplicações chamam isto para obter um
LibraryClient pronto sem conhecer a infraestrutura por dentro.
"""
from __future__ import annotations

from pathlib import Path

from kk_shared.events.bus import EventBus

from .application.in_process_client import InProcessLibraryClient
from .infrastructure.db.engine import create_db_engine, init_schema, make_session_factory
from .infrastructure.fs.organizer import FileOrganizer, NullOrganizer


def build_in_process_client(
    db_path: str | Path | None = None,
    bus: EventBus | None = None,
    media_root: str | Path | None = None,
    echo: bool = False,
) -> InProcessLibraryClient:
    engine = create_db_engine(db_path, echo=echo)
    init_schema(engine)  # produção real usa Alembic; aqui garante o schema
    session_factory = make_session_factory(engine)
    organizer = FileOrganizer(media_root) if media_root else NullOrganizer()
    return InProcessLibraryClient(session_factory, bus, organizer)
