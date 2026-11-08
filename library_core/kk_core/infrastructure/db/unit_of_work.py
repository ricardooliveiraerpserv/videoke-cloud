"""Unit of Work — fronteira transacional única. Agrega os repositórios sobre
uma mesma Session, coleta eventos de domínio e os grava no outbox no commit.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session, sessionmaker

from kk_shared.events.bus import DomainEvent

from ..repositories.catalog_repositories import (
    SqlArtistRepository,
    SqlBlacklistRepository,
    SqlChannelRepository,
    SqlMediaRepository,
    SqlPresetRepository,
    SqlSongRepository,
)
from ..repositories.library_extras import (
    FavoriteRepository,
    HistoryRepository,
    LyricsRepository,
    PlaylistRepository,
)
from ..repositories.queue_repositories import QueueRepository, SongRequestRepository
from ..repositories.remote_sources import SqlRemoteSourceRepository
from ..repositories.taxonomy import (
    AlbumRepository,
    ArtistCategoryRepository,
    DownloadRecordRepository,
    TagRepository,
    ThumbnailRepository,
)
from ..search.fts import FtsSearchIndex
from .models import OutboxEventModel


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory
        self.events: list[DomainEvent] = []

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.session: Session = self._session_factory()
        self.songs = SqlSongRepository(self.session)
        self.media = SqlMediaRepository(self.session)
        self.artists = SqlArtistRepository(self.session)
        self.channels = SqlChannelRepository(self.session)
        self.presets = SqlPresetRepository(self.session)
        self.blacklist = SqlBlacklistRepository(self.session)
        if self.session.bind.dialect.name == "postgresql":   # F1: busca no Postgres
            from ..search.pg import PgSearchIndex
            self.search = PgSearchIndex(self.session)
        else:
            self.search = FtsSearchIndex(self.session)
        self.queue = QueueRepository(self.session)
        self.requests = SongRequestRepository(self.session)   # Fase D
        self.playlists = PlaylistRepository(self.session)
        self.favorites = FavoriteRepository(self.session)
        self.history = HistoryRepository(self.session)
        self.lyrics = LyricsRepository(self.session)
        self.albums = AlbumRepository(self.session)
        self.artist_categories = ArtistCategoryRepository(self.session)
        self.tags = TagRepository(self.session)
        self.downloads = DownloadRecordRepository(self.session)
        self.thumbnails = ThumbnailRepository(self.session)
        self.remote_sources = SqlRemoteSourceRepository(self.session)  # A4
        self.events = []
        return self

    def __exit__(self, exc_type, *_exc) -> None:
        if exc_type:
            self.rollback()
        self.session.close()

    def add_event(self, event: DomainEvent) -> None:
        self.events.append(event)

    def commit(self) -> None:
        # persiste os eventos no outbox junto com a mesma transação (garantia)
        for ev in self.events:
            payload = {k: v for k, v in ev.__dict__.items() if k not in ("name",)}
            self.session.add(OutboxEventModel(name=ev.name, payload=json.dumps(payload, default=str)))
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
