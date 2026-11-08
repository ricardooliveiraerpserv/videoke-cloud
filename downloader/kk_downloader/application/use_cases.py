"""Casos de uso do Downloader. O download termina chamando o Library Core
(register_media) — é isso que faz a música aparecer no Karaokê (Fase 1)."""
from __future__ import annotations

import os
import tempfile

from kk_shared.client.library_client import LibraryClient
from kk_shared.contracts.dtos import RegisterMediaDTO, SongView

from ..infrastructure.metadata_parser import parse as parse_meta
from ..infrastructure.ports import IDownloaderBackend, ProgressCb, SearchHit

# duração mínima aceita ao catalogar: abaixo disso é clipe/amostra/incompleta.
# Vale p/ TODOS os caminhos de download (uma música, lote, arsenal, manifesto).
MIN_DURATION_S = 60


class SearchYouTubeUseCase:
    def __init__(self, backend: IDownloaderBackend):
        self._backend = backend

    def execute(self, query: str, *, deep: bool = True, limit: int = 25, cookies: str = "") -> list[SearchHit]:
        return self._backend.search(query, limit, deep, cookies)


class DownloadAndRegisterUseCase:
    """Baixa → parseia metadados → registra no Library Core."""

    def __init__(self, backend: IDownloaderBackend, library: LibraryClient):
        self._backend = backend
        self._library = library

    def execute(
        self, url: str, *, audio_only: bool = False, max_height: int = 720,
        artist_hint: str | None = None, title_hint: str | None = None,
        cookies: str = "", staging_dir: str | None = None,
        progress: ProgressCb | None = None, ignore_blacklist: bool = False,
    ) -> SongView | None:
        staging = staging_dir or tempfile.mkdtemp(prefix="kk_dl_")
        media = self._backend.download(
            url, staging, audio_only=audio_only, max_height=max_height,
            cookies=cookies, progress=progress,
        )
        # piso de duração: não cataloga música muito curta (clipe/amostra/incompleta).
        # duration_s==0 = desconhecida → deixa passar (não dá p/ julgar).
        if media.duration_s and media.duration_s < MIN_DURATION_S:
            try:
                os.remove(media.path)
            except OSError:
                pass
            return None
        song_title, artists = parse_meta(
            media.title, artist_hint=artist_hint, title_hint=title_hint
        )
        dto = RegisterMediaDTO(
            title=song_title, artists=artists,
            source_path=media.path, channel_name=media.channel,
            channel_external_id=media.channel_id, container=media.container,
            video_codec=media.video_codec, audio_codec=media.audio_codec,
            duration_s=media.duration_s, resolution=media.resolution,
            sha256=media.sha256, source_url=media.source_url,
            source_title=media.title,   # título cru do YouTube, como veio
            trust_artist=bool(artist_hint and title_hint),  # manifesto curado → sem quarentena
            ignore_blacklist=ignore_blacklist,  # baixado por URL explícita → destrava banimento
        )
        # O Core cataloga, organiza o arquivo e publica MediaFileAdded.
        return self._library.register_media(dto)
