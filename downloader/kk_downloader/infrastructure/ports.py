"""Portas e DTOs internos do Downloader (abstrai a fonte: yt-dlp hoje)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class SearchHit:
    url: str
    title: str
    channel: str = ""
    channel_id: str | None = None
    duration_s: int = 0


@dataclass
class DownloadedMedia:
    path: str
    title: str
    channel: str | None = None
    channel_id: str | None = None
    duration_s: int = 0
    resolution: str | None = None
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    sha256: str = ""
    source_url: str = ""


ProgressCb = Callable[[float, str], None]  # (percent, texto)


class IDownloaderBackend(Protocol):
    def search(self, query: str, limit: int, deep: bool, cookies: str) -> list[SearchHit]: ...
    def video_info(self, url_or_id: str, *, cookies: str) -> SearchHit | None: ...
    def stream_url(self, url: str, *, max_height: int, cookies: str) -> str: ...
    def youtube_title(self, url_or_id: str, *, cookies: str) -> str | None: ...
    def download(
        self, url: str, staging_dir: str, *, audio_only: bool, max_height: int,
        cookies: str, progress: ProgressCb | None,
    ) -> DownloadedMedia: ...
