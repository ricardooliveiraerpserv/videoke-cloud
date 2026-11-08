"""Entidades do contexto Catálogo. Song é o agregado raiz (ADR-4)."""
from __future__ import annotations

from dataclasses import dataclass, field

from kk_shared.contracts.enums import MediaStatus
from kk_shared.platform.ids import new_id
from kk_shared.platform.text import song_key as _song_key

from ..value_objects import Duration, Resolution


@dataclass
class Artist:
    id: str = field(default_factory=new_id)
    name: str = ""


@dataclass
class Channel:
    """Fonte/canal de origem de um arquivo (ex.: 'Karaokê Club')."""
    id: str = field(default_factory=new_id)
    name: str = ""
    external_id: str | None = None   # id do canal na fonte (ex.: YouTube UC...)


@dataclass
class MediaFile:
    """Arquivo físico — uma versão concreta de uma música."""
    id: str = field(default_factory=new_id)
    song_id: str = ""
    channel: Channel | None = None
    path: str = ""
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    duration: Duration = field(default_factory=Duration)
    resolution: Resolution = field(default_factory=Resolution)
    sha256: str | None = None
    status: MediaStatus = MediaStatus.OK
    source_url: str | None = None
    source_title: str | None = None      # título original do vídeo (web), como veio

    def is_playable(self) -> bool:
        return self.status == MediaStatus.OK and bool(self.path)


@dataclass(frozen=True)
class SongRow:
    """Projeção de leitura de UMA linha da lista (browse). Não é o agregado —
    é o mínimo para pintar a linha sem carregar o grafo completo de versões."""
    id: str
    title: str
    language: str | None = None
    artists: list[str] = field(default_factory=list)   # nomes já ordenados
    category: str | None = None
    container: str | None = None      # da 1ª versão viva com formato
    resolution: str | None = None     # idem ("1920x1080")
    duration_s: int = 0               # 1ª versão viva com duração
    version_count: int = 0


@dataclass
class Song:
    """Obra lógica. Uma música tem N arquivos (versões de canais diferentes)."""
    id: str = field(default_factory=new_id)
    title: str = ""
    artists: list[Artist] = field(default_factory=list)
    album: str | None = None
    year: int | None = None
    language: str | None = None
    genres: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    media_files: list[MediaFile] = field(default_factory=list)

    def song_key(self) -> str:
        return _song_key(self.title, [a.name for a in self.artists])

    def add_version(self, media: MediaFile) -> None:
        media.song_id = self.id
        self.media_files.append(media)

    def best_version(self) -> MediaFile | None:
        """Regra: versão tocável de maior duração (música completa)."""
        playable = [m for m in self.media_files if m.is_playable()]
        if not playable:
            return None
        return max(playable, key=lambda m: m.duration.seconds)
