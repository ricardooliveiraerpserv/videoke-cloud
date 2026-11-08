"""Eventos do contexto de Catálogo (ver seção 10 da arquitetura)."""
from __future__ import annotations

from dataclasses import dataclass

from .bus import DomainEvent


@dataclass(frozen=True, kw_only=True)
class MediaFileAdded(DomainEvent):
    name: str = "MediaFileAdded"
    song_id: str = ""
    media_file_id: str = ""
    title: str = ""


@dataclass(frozen=True, kw_only=True)
class MediaFileMissing(DomainEvent):
    name: str = "MediaFileMissing"
    media_file_id: str = ""


@dataclass(frozen=True, kw_only=True)
class LibraryReindexed(DomainEvent):
    name: str = "LibraryReindexed"
    total_songs: int = 0
