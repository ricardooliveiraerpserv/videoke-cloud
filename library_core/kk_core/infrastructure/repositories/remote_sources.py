"""A4 — repositório da fonte remota (remote_sources).

A nuvem sincroniza isto (catálogo + URLs), sem hospedar o MP4. A fonte 'youtube'
é materializada a partir do source_url que já existe em media_files.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import MediaFileModel, RemoteSourceModel


class SqlRemoteSourceRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, media_file_id: str, uri: str, *, kind: str = "youtube",
               song_id: str | None = None, status: str = "unknown") -> RemoteSourceModel:
        row = self.session.execute(
            select(RemoteSourceModel).where(
                RemoteSourceModel.media_file_id == media_file_id,
                RemoteSourceModel.kind == kind,
            )
        ).scalar_one_or_none()
        if row:
            row.uri = uri
            if song_id:
                row.song_id = song_id
            if status != "unknown":
                row.status = status
            return row
        row = RemoteSourceModel(media_file_id=media_file_id, song_id=song_id,
                                kind=kind, uri=uri, status=status)
        self.session.add(row)
        return row

    def by_media(self, media_file_id: str) -> list[RemoteSourceModel]:
        return list(self.session.execute(
            select(RemoteSourceModel).where(RemoteSourceModel.media_file_id == media_file_id)
        ).scalars())

    def count(self) -> int:
        return int(self.session.execute(select(func.count(RemoteSourceModel.id))).scalar() or 0)

    def backfill_from_media(self) -> int:
        """Cria uma remote_source 'youtube' para cada media_file com source_url
        que ainda não tem. Idempotente. Retorna quantas criou."""
        existing = set(self.session.execute(
            select(RemoteSourceModel.media_file_id).where(RemoteSourceModel.kind == "youtube")
        ).scalars())
        rows = self.session.execute(
            select(MediaFileModel.id, MediaFileModel.song_id, MediaFileModel.source_url)
            .where(MediaFileModel.source_url.is_not(None))
        ).all()
        created = 0
        for mid, sid, url in rows:
            if not url or mid in existing:
                continue
            self.session.add(RemoteSourceModel(
                media_file_id=mid, song_id=sid, kind="youtube", uri=url, status="unknown"))
            created += 1
        return created
