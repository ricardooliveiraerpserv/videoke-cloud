"""DTOs (Pydantic v2) — a fronteira tipada entre as aplicações e o Library Core.

Estes objetos são o "idioma" trafegado pelo LibraryClient. São imutáveis do
ponto de vista de contrato: mudanças incompatíveis exigem nova versão.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from .enums import MediaStatus, QueueStatus, RequestStatus

T = TypeVar("T")


# ---- Entrada ----
class RegisterMediaDTO(BaseModel):
    """O Downloader entrega isto ao Core ao concluir um download."""
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    year: int | None = None
    language: str | None = None
    genres: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)

    # arquivo físico (uma versão)
    source_path: str
    channel_name: str | None = None
    channel_external_id: str | None = None
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    duration_s: int = 0
    resolution: str | None = None
    sha256: str | None = None
    thumbnail_path: str | None = None
    source_url: str | None = None
    source_title: str | None = None   # título original do vídeo (web), como veio
    organize: bool = True   # False = referencia o arquivo no lugar (import de pasta)
    trust_artist: bool = False  # artista CURADO (manifesto/hint) → NÃO passa pelo guard de quarentena
    ignore_blacklist: bool = False  # download EXPLÍCITO por URL → destrava a lista negra (traz de volta o que foi excluído)


class SearchFilters(BaseModel):
    language: str | None = None
    genre: str | None = None
    artist_id: str | None = None    # escopa a busca a UM cantor (filtro por cantor)
    category_ids: list[str] | None = None   # escopa a busca a categorias (filtro de estilo)
    only_playable: bool = True


class PageReq(BaseModel):
    limit: int = 50
    # keyset pagination (ADR de performance): cursor em vez de OFFSET
    after: str | None = None


class PresetDTO(BaseModel):
    pitch: int = 0     # -6..+6
    tempo: int = 100   # 75..125


# ---- Saída (views de leitura — CQRS leve) ----
class MediaFileView(BaseModel):
    id: str
    channel: str | None = None
    duration_s: int = 0
    resolution: str | None = None
    container: str | None = None
    status: MediaStatus = MediaStatus.OK
    path: str | None = None
    source_url: str | None = None
    source_title: str | None = None


class SongView(BaseModel):
    id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    language: str | None = None
    versions: list[MediaFileView] = Field(default_factory=list)

    @property
    def version_count(self) -> int:
        return len(self.versions)


class SongRowView(BaseModel):
    """Projeção LEVE de uma linha da lista (browse) — CQRS de leitura.

    Ao contrário de SongView, NÃO carrega o grafo de versões/artistas (que no ORM
    é `lazy="selectin"` e faz o payload explodir). Só o necessário para pintar a
    linha: título, artistas (nomes), categoria, rótulo de formato e duração da 1ª
    versão viva e a contagem de versões."""
    id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    language: str | None = None
    category: str | None = None
    format_label: str | None = None   # ex.: "MP4 · 1080p" (container + altura da 1ª versão)
    duration_s: int = 0
    version_count: int = 0


class ArtistView(BaseModel):
    id: str
    name: str
    song_count: int = 0
    category_id: str | None = None
    category: str | None = None


class ArtistCategoryView(BaseModel):
    """Estilo/categoria de artista (Sertanejo, Samba, Rock…). Vira botão no Painel."""
    id: str
    name: str
    artist_count: int = 0
    song_count: int = 0


class EnqueueDTO(BaseModel):
    """Pedido de entrada na fila de cantores (≠ playlist)."""
    song_id: str
    singer: str
    pitch: int | None = None    # None → usa o preset da música
    tempo: int | None = None
    note: str = ""


class QueueItemView(BaseModel):
    id: str
    session_id: str
    song_id: str
    media_file_id: str
    song_title: str
    artists: list[str] = Field(default_factory=list)
    singer: str = ""
    pitch: int = 0
    tempo: int = 100
    note: str = ""
    status: QueueStatus = QueueStatus.WAITING
    position: int = 0
    estimated_duration_s: int = 0


class SongRequestView(BaseModel):
    """Fase D — pedido de convidado visível ao operador."""
    id: str
    session_id: str
    song_id: str
    song_title: str = ""
    artists: list[str] = Field(default_factory=list)
    singer: str = ""
    note: str = ""
    device: str = ""
    status: RequestStatus = RequestStatus.PENDING
    queue_item_id: str | None = None


class PlaylistItemView(BaseModel):
    id: str
    song_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    position: int = 0


class PlaylistView(BaseModel):
    id: str
    name: str
    item_count: int = 0


class LyricsView(BaseModel):
    song_id: str
    content: str = ""
    fmt: str = "text"          # text | lrc | srt
    language: str | None = None
    source: str = ""


class HistoryEntryView(BaseModel):
    id: str
    song_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    singer: str = ""
    played_at: str = ""


class MediaSourceDTO(BaseModel):
    """Fonte de reprodução resolvida pelo Core. A app NÃO acessa o disco
    diretamente — pede a fonte ao Core (hoje caminho local; futuro: URL de
    streaming servida pelo Library Core Service)."""
    media_file_id: str
    uri: str
    is_local: bool = True


class Page(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    next_cursor: str | None = None
    total_estimate: int | None = None
