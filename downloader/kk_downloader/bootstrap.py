"""Composition root do Downloader: monta LibraryClient + backend + use cases."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kk_shared.client.factory import get_library_client
from kk_shared.client.library_client import LibraryClient

from .application.use_cases import DownloadAndRegisterUseCase, SearchYouTubeUseCase
from .infrastructure.ytdlp_adapter import YtDlpBackend


@dataclass
class DownloaderApp:
    library: LibraryClient
    search: SearchYouTubeUseCase
    download: DownloadAndRegisterUseCase
    backend: YtDlpBackend


def build_downloader(library: LibraryClient | None = None) -> DownloaderApp:
    # arquitetura de serviço: fala com o daemon (sobe-o se preciso)
    library = library or get_library_client()
    backend = YtDlpBackend()
    return DownloaderApp(
        library=library,
        search=SearchYouTubeUseCase(backend),
        download=DownloadAndRegisterUseCase(backend, library),
        backend=backend,
    )
