"""Modelos ORM (SQLAlchemy 2.0) — fatia de Catálogo da Fase 0.

Escopo Fase 0: artists, songs, song_artists, channels, media_files, presets,
outbox_events, settings + índice FTS5 (via DDL em search/ddl.py). Álbuns como
tabela, gêneros/categorias/letras/thumbnails N:N entram nas fases seguintes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDelete, Timestamped, UuidPk, Versioned


class ArtistModel(UuidPk, Timestamped, Base):
    __tablename__ = "artists"
    name: Mapped[str] = mapped_column(String(300))
    # único por normalização (bancos novos): evita cadastro poluído com variantes.
    # get_or_create/resolve_or_create já garantem isso por consulta em bancos antigos.
    name_norm: Mapped[str] = mapped_column(String(300), unique=True, index=True)


class ArtistCategoryModel(UuidPk, Timestamped, Base):
    """Estilo/categoria musical do artista (Sertanejo, Samba, Rock, MPB…).
    Registro com nomes ÚNICOS — vira botão de filtro no Painel."""
    __tablename__ = "artist_categories"
    name: Mapped[str] = mapped_column(String(120))
    name_norm: Mapped[str] = mapped_column(String(120), unique=True, index=True)


class ArtistCategoryLinkModel(Base):
    """Vínculo artista → categoria. PK no artista = UMA categoria por artista."""
    __tablename__ = "artist_category_links"
    artist_id: Mapped[str] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    category_id: Mapped[str] = mapped_column(
        ForeignKey("artist_categories.id", ondelete="CASCADE"), index=True)


class ChannelModel(UuidPk, Timestamped, Base):
    __tablename__ = "channels"
    name: Mapped[str] = mapped_column(String(300))
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)


class SongModel(UuidPk, Timestamped, SoftDelete, Versioned, Base):
    __tablename__ = "songs"
    title: Mapped[str] = mapped_column(String(500))
    title_norm: Mapped[str] = mapped_column(String(500), index=True)
    song_key: Mapped[str] = mapped_column(String(700), index=True)
    album: Mapped[str | None] = mapped_column(String(500), nullable=True)
    album_id: Mapped[str | None] = mapped_column(
        ForeignKey("albums.id", ondelete="SET NULL"), nullable=True, index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    karaoke_confirmed: Mapped[int] = mapped_column(Integer, default=0, index=True)

    media_files: Mapped[list["MediaFileModel"]] = relationship(
        back_populates="song", cascade="all, delete-orphan", lazy="selectin"
    )
    artists: Mapped[list["SongArtistModel"]] = relationship(
        back_populates="song", cascade="all, delete-orphan", lazy="selectin"
    )


class BlacklistModel(UuidPk, Timestamped, Base):
    """Arquivos banidos: excluídos do acervo e NUNCA reimportados (chave = sha256)."""
    __tablename__ = "blacklist"
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artist: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class SongArtistModel(Base):
    __tablename__ = "song_artists"
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="main")

    song: Mapped["SongModel"] = relationship(back_populates="artists")
    artist: Mapped["ArtistModel"] = relationship(lazy="joined")


class MediaFileModel(UuidPk, Timestamped, SoftDelete, Versioned, Base):
    __tablename__ = "media_files"
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[str | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(Text)
    container: Mapped[str | None] = mapped_column(String(20), nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(40), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="ok", index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)

    song: Mapped["SongModel"] = relationship(back_populates="media_files")
    channel: Mapped["ChannelModel | None"] = relationship(lazy="joined")


class PresetModel(UuidPk, Timestamped, Base):
    __tablename__ = "presets"
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pitch: Mapped[int] = mapped_column(Integer, default=0)
    tempo: Mapped[int] = mapped_column(Integer, default=100)
    __table_args__ = (UniqueConstraint("song_id", "user_id", name="uq_preset_song_user"),)


class OutboxEventModel(UuidPk, Timestamped, Base):
    __tablename__ = "outbox_events"
    name: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    processed: Mapped[int] = mapped_column(Integer, default=0, index=True)


class SettingModel(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class AlbumModel(UuidPk, Timestamped, Base):
    __tablename__ = "albums"
    name: Mapped[str] = mapped_column(String(300))
    name_norm: Mapped[str] = mapped_column(String(300), index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GenreModel(UuidPk, Timestamped, Base):
    __tablename__ = "genres"
    name: Mapped[str] = mapped_column(String(120))
    name_norm: Mapped[str] = mapped_column(String(120), unique=True, index=True)


class SongGenreModel(Base):
    __tablename__ = "song_genres"
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True)


class CategoryModel(UuidPk, Timestamped, Base):
    __tablename__ = "categories"
    name: Mapped[str] = mapped_column(String(120))
    name_norm: Mapped[str] = mapped_column(String(120), unique=True, index=True)


class SongCategoryModel(Base):
    __tablename__ = "song_categories"
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True)


class DownloadModel(UuidPk, Timestamped, Base):
    __tablename__ = "downloads"
    url: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(500), default="")
    kind: Mapped[str] = mapped_column(String(10), default="video")
    status: Mapped[str] = mapped_column(String(20), default="done", index=True)
    media_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class ThumbnailModel(UuidPk, Timestamped, Base):
    __tablename__ = "thumbnails"
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)


class UserModel(UuidPk, Timestamped, Base):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="singer")   # singer|operator|admin


class DeviceModel(UuidPk, Timestamped, Base):
    __tablename__ = "devices"
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="monitor")
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class SessionModel(UuidPk, Timestamped, Base):
    __tablename__ = "sessions"
    name: Mapped[str] = mapped_column(String(200), default="Sessão")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    # Fase D: código numérico curto que o convidado digita (ou lê no QR) para
    # entrar na sessão. Atribuído sob demanda; NULL enquanto a sessão não for
    # aberta a convidados.
    code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)


class SongRequestModel(UuidPk, Timestamped, Base):
    """Fase D: pedido de um CONVIDADO, aguardando o operador aceitar/recusar.
    Aprovar cria um item de fila (queue_item_id); recusar apenas marca."""
    __tablename__ = "song_requests"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"))
    song_title: Mapped[str] = mapped_column(String(500), default="")   # snapshot p/ exibir sem join
    artists_text: Mapped[str] = mapped_column(String(500), default="")
    singer: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    device: Mapped[str] = mapped_column(String(80), default="")        # quem pediu (diagnóstico)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    queue_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class QueueItemModel(UuidPk, Timestamped, Base):
    __tablename__ = "queue"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"))
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True)
    song_title: Mapped[str] = mapped_column(String(500), default="")   # snapshot p/ exibição rápida
    artists_text: Mapped[str] = mapped_column(String(500), default="")
    singer: Mapped[str] = mapped_column(String(200), default="")
    pitch: Mapped[int] = mapped_column(Integer, default=0)
    tempo: Mapped[int] = mapped_column(Integer, default=100)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    estimated_duration_s: Mapped[int] = mapped_column(Integer, default=0)


class PlaylistModel(UuidPk, Timestamped, SoftDelete, Base):
    __tablename__ = "playlists"
    name: Mapped[str] = mapped_column(String(200))


class PlaylistItemModel(UuidPk, Timestamped, Base):
    __tablename__ = "playlist_items"
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), index=True)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)


class LyricsModel(UuidPk, Timestamped, Base):
    __tablename__ = "lyrics"
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    fmt: Mapped[str] = mapped_column(String(10), default="text")   # text | lrc | srt
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="")     # sidecar | manual | subtitle
    __table_args__ = (UniqueConstraint("song_id", name="uq_lyrics_song"),)


class FavoriteModel(UuidPk, Timestamped, Base):
    __tablename__ = "favorites"
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (UniqueConstraint("song_id", "user_id", name="uq_fav_song_user"),)


class HistoryModel(UuidPk, Timestamped, Base):
    __tablename__ = "history"
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    media_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    singer: Mapped[str] = mapped_column(String(200), default="")
    song_title: Mapped[str] = mapped_column(String(500), default="")
    artists_text: Mapped[str] = mapped_column(String(500), default="")


class RemoteSourceModel(UuidPk, Timestamped, Base):
    """A4 — fonte remota de reprodução, DESACOPLADA do arquivo físico.

    É o que a nuvem sincroniza (catálogo + URLs), sem hospedar o MP4:
    kind=youtube (a source_url), cloud_cache (hot-cache no Storage) ou local.
    """
    __tablename__ = "remote_sources"
    media_file_id: Mapped[str] = mapped_column(
        ForeignKey("media_files.id", ondelete="CASCADE"), index=True
    )
    song_id: Mapped[str | None] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="youtube")   # youtube|cloud_cache|local
    uri: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="unknown")  # ok|unavailable|unknown
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("media_file_id", "kind", name="uq_remote_media_kind"),)


Index("ix_media_song_status", MediaFileModel.song_id, MediaFileModel.status)
Index("ix_outbox_pending", OutboxEventModel.processed, OutboxEventModel.created_at)
Index("ix_queue_session_pos", QueueItemModel.session_id, QueueItemModel.position)
Index("ix_queue_session_status", QueueItemModel.session_id, QueueItemModel.status)
