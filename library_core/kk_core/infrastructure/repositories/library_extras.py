"""Repositórios de playlists, favoritos e histórico."""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from kk_shared.contracts.dtos import (
    HistoryEntryView,
    LyricsView,
    PlaylistItemView,
    PlaylistView,
)

from ..db.models import (
    FavoriteModel,
    HistoryModel,
    LyricsModel,
    PlaylistItemModel,
    PlaylistModel,
    SongModel,
)


class PlaylistRepository:
    def __init__(self, s: Session):
        self.s = s

    def create(self, name: str) -> str:
        m = PlaylistModel(name=name)
        self.s.add(m); self.s.flush()
        return m.id

    def delete(self, playlist_id: str) -> None:
        m = self.s.get(PlaylistModel, playlist_id)
        if m:
            m.deleted_at = func.now()

    def list(self) -> list[PlaylistView]:
        rows = self.s.scalars(
            select(PlaylistModel).where(PlaylistModel.deleted_at.is_(None)).order_by(PlaylistModel.name)
        ).all()
        out = []
        for p in rows:
            n = self.s.scalar(
                select(func.count()).select_from(PlaylistItemModel)
                .where(PlaylistItemModel.playlist_id == p.id)
            )
            out.append(PlaylistView(id=p.id, name=p.name, item_count=int(n or 0)))
        return out

    def next_position(self, playlist_id: str) -> int:
        n = self.s.scalar(
            select(func.max(PlaylistItemModel.position)).where(PlaylistItemModel.playlist_id == playlist_id)
        )
        return (n if n is not None else -1) + 1

    def add_item(self, playlist_id: str, song_id: str) -> str:
        m = PlaylistItemModel(playlist_id=playlist_id, song_id=song_id,
                              position=self.next_position(playlist_id))
        self.s.add(m); self.s.flush()
        return m.id

    def remove_item(self, item_id: str) -> None:
        self.s.execute(delete(PlaylistItemModel).where(PlaylistItemModel.id == item_id))

    def items(self, playlist_id: str) -> list[PlaylistItemView]:
        rows = self.s.execute(
            select(PlaylistItemModel, SongModel)
            .join(SongModel, SongModel.id == PlaylistItemModel.song_id)
            .where(PlaylistItemModel.playlist_id == playlist_id)
            .order_by(PlaylistItemModel.position)
        ).all()
        out = []
        for pi, song in rows:
            artists = ", ".join(sa.artist.name for sa in song.artists)
            out.append(PlaylistItemView(
                id=pi.id, song_id=song.id, title=song.title,
                artists=[a for a in artists.split(", ") if a], position=pi.position,
            ))
        return out


class FavoriteRepository:
    def __init__(self, s: Session):
        self.s = s

    def add(self, song_id: str, user_id: str | None) -> None:
        exists = self.s.scalars(
            select(FavoriteModel).where(FavoriteModel.song_id == song_id, FavoriteModel.user_id.is_(user_id))
        ).first()
        if not exists:
            self.s.add(FavoriteModel(song_id=song_id, user_id=user_id))

    def remove(self, song_id: str, user_id: str | None) -> None:
        self.s.execute(
            delete(FavoriteModel).where(FavoriteModel.song_id == song_id, FavoriteModel.user_id.is_(user_id))
        )

    def is_favorite(self, song_id: str, user_id: str | None) -> bool:
        return self.s.scalars(
            select(FavoriteModel).where(FavoriteModel.song_id == song_id, FavoriteModel.user_id.is_(user_id))
        ).first() is not None

    def song_ids(self, user_id: str | None) -> list[str]:
        rows = self.s.scalars(
            select(FavoriteModel.song_id).where(FavoriteModel.user_id.is_(user_id))
            .order_by(FavoriteModel.created_at.desc())
        ).all()
        return list(rows)


class LyricsRepository:
    def __init__(self, s: Session):
        self.s = s

    def upsert(self, song_id: str, content: str, fmt: str, language: str | None, source: str) -> None:
        m = self.s.scalars(select(LyricsModel).where(LyricsModel.song_id == song_id)).first()
        if m:
            m.content, m.fmt, m.language, m.source = content, fmt, language, source
        else:
            self.s.add(LyricsModel(song_id=song_id, content=content, fmt=fmt,
                                   language=language, source=source))

    def get(self, song_id: str) -> LyricsView | None:
        m = self.s.scalars(select(LyricsModel).where(LyricsModel.song_id == song_id)).first()
        if not m:
            return None
        return LyricsView(song_id=song_id, content=m.content, fmt=m.fmt,
                          language=m.language, source=m.source)


class HistoryRepository:
    def __init__(self, s: Session):
        self.s = s

    def record(self, *, song_id, media_file_id, session_id, singer, song_title, artists_text) -> None:
        self.s.add(HistoryModel(
            song_id=song_id, media_file_id=media_file_id, session_id=session_id,
            singer=singer, song_title=song_title, artists_text=artists_text,
        ))

    def recent(self, limit: int = 100) -> list[HistoryEntryView]:
        rows = self.s.scalars(
            select(HistoryModel).order_by(HistoryModel.created_at.desc()).limit(limit)
        ).all()
        return [
            HistoryEntryView(
                id=h.id, song_id=h.song_id, title=h.song_title,
                artists=[a for a in (h.artists_text or "").split(", ") if a],
                singer=h.singer, played_at=str(h.created_at),
            )
            for h in rows
        ]
