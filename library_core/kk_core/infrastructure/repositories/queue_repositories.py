"""Repositório da fila de cantores e sessões."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from kk_shared.contracts.dtos import QueueItemView, SongRequestView
from kk_shared.contracts.enums import QueueStatus, RequestStatus

from ..db.models import QueueItemModel, SessionModel, SongRequestModel

ACTIVE = (QueueStatus.WAITING.value, QueueStatus.SINGING.value)


def _to_view(m: QueueItemModel) -> QueueItemView:
    return QueueItemView(
        id=m.id, session_id=m.session_id, song_id=m.song_id,
        media_file_id=m.media_file_id or "", song_title=m.song_title,
        artists=[a for a in (m.artists_text or "").split(", ") if a],
        singer=m.singer, pitch=m.pitch, tempo=m.tempo, note=m.note,
        status=QueueStatus(m.status), position=m.position,
        estimated_duration_s=m.estimated_duration_s,
    )


class QueueRepository:
    def __init__(self, session: Session):
        self.s = session

    # sessões
    def create_session(self, name: str) -> str:
        m = SessionModel(name=name, status="active")
        self.s.add(m)
        self.s.flush()
        return m.id

    def active_session(self) -> str | None:
        m = self.s.scalars(
            select(SessionModel).where(SessionModel.status == "active")
            .order_by(SessionModel.created_at.desc())
        ).first()
        return m.id if m else None

    # código de convidado (Fase D)
    def get_session(self, session_id: str) -> SessionModel | None:
        return self.s.get(SessionModel, session_id)

    def session_by_code(self, code: str) -> str | None:
        m = self.s.scalars(
            select(SessionModel).where(
                SessionModel.code == code, SessionModel.status == "active"
            )
        ).first()
        return m.id if m else None

    def set_code(self, session_id: str, code: str) -> None:
        m = self.s.get(SessionModel, session_id)
        if m:
            m.code = code

    # itens
    def add(self, **fields) -> QueueItemView:
        m = QueueItemModel(**fields)
        self.s.add(m)
        self.s.flush()
        return _to_view(m)

    def get(self, item_id: str) -> QueueItemModel | None:
        return self.s.get(QueueItemModel, item_id)

    def list_active(self, session_id: str) -> list[QueueItemView]:
        rows = self.s.scalars(
            select(QueueItemModel)
            .where(QueueItemModel.session_id == session_id, QueueItemModel.status.in_(ACTIVE))
            .order_by(QueueItemModel.position)
        ).all()
        return [_to_view(m) for m in rows]

    def active_models(self, session_id: str) -> list[QueueItemModel]:
        return list(self.s.scalars(
            select(QueueItemModel)
            .where(QueueItemModel.session_id == session_id, QueueItemModel.status.in_(ACTIVE))
            .order_by(QueueItemModel.position)
        ).all())

    def current(self, session_id: str) -> QueueItemView | None:
        m = self.s.scalars(
            select(QueueItemModel).where(
                QueueItemModel.session_id == session_id,
                QueueItemModel.status == QueueStatus.SINGING.value,
            )
        ).first()
        return _to_view(m) if m else None

    def next_position(self, session_id: str) -> int:
        rows = self.active_models(session_id)
        return (max((m.position for m in rows), default=-1)) + 1


def _to_request_view(m: SongRequestModel) -> SongRequestView:
    return SongRequestView(
        id=m.id, session_id=m.session_id, song_id=m.song_id,
        song_title=m.song_title,
        artists=[a for a in (m.artists_text or "").split(", ") if a],
        singer=m.singer, note=m.note, device=m.device,
        status=RequestStatus(m.status), queue_item_id=m.queue_item_id,
    )


class SongRequestRepository:
    """Pedidos de convidado aguardando o operador (Fase D)."""

    def __init__(self, session: Session):
        self.s = session

    def create(self, **fields) -> SongRequestView:
        m = SongRequestModel(**fields)
        self.s.add(m)
        self.s.flush()
        return _to_request_view(m)

    def get(self, request_id: str) -> SongRequestModel | None:
        return self.s.get(SongRequestModel, request_id)

    def list_by_session(self, session_id: str,
                        status: str | None = None) -> list[SongRequestView]:
        q = select(SongRequestModel).where(SongRequestModel.session_id == session_id)
        if status:
            q = q.where(SongRequestModel.status == status)
        q = q.order_by(SongRequestModel.created_at)
        return [_to_request_view(m) for m in self.s.scalars(q).all()]
