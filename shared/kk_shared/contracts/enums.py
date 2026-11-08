"""Enumerações compartilhadas pelo ecossistema (linguagem ubíqua)."""
from __future__ import annotations

from enum import Enum


class MediaStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    CORRUPT = "corrupt"
    ARCHIVED = "archived"


class OutputKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    REGISTERING = "registering"
    DONE = "done"
    FAILED = "failed"


class QueueStatus(str, Enum):
    WAITING = "waiting"
    SINGING = "singing"
    DONE = "done"
    SKIPPED = "skipped"


class RequestStatus(str, Enum):
    """Fase D — ciclo de vida de um pedido de convidado."""
    PENDING = "pending"
    APPROVED = "approved"   # virou item de fila (queue_item_id preenchido)
    REJECTED = "rejected"


class ArtistRole(str, Enum):
    MAIN = "main"
    FEAT = "feat"
