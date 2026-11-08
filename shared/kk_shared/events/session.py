"""Eventos do contexto de Sessão/Fila (alimentam o Segundo Monitor)."""
from __future__ import annotations

from dataclasses import dataclass

from .bus import DomainEvent


@dataclass(frozen=True, kw_only=True)
class QueueItemAdded(DomainEvent):
    name: str = "QueueItemAdded"
    session_id: str = ""
    item_id: str = ""
    singer: str = ""
    song_title: str = ""


@dataclass(frozen=True, kw_only=True)
class QueueReordered(DomainEvent):
    name: str = "QueueReordered"
    session_id: str = ""


@dataclass(frozen=True, kw_only=True)
class NowSinging(DomainEvent):
    name: str = "NowSinging"
    session_id: str = ""
    item_id: str = ""
    singer: str = ""
    song_title: str = ""
    next_singer: str = ""


@dataclass(frozen=True, kw_only=True)
class QueueItemDone(DomainEvent):
    name: str = "QueueItemDone"
    session_id: str = ""
    item_id: str = ""


# --- Fase D: convidado pede, operador aprova/recusa ---
@dataclass(frozen=True, kw_only=True)
class SongRequested(DomainEvent):
    name: str = "SongRequested"
    session_id: str = ""
    request_id: str = ""
    singer: str = ""
    song_title: str = ""


@dataclass(frozen=True, kw_only=True)
class RequestApproved(DomainEvent):
    name: str = "RequestApproved"
    session_id: str = ""
    request_id: str = ""
    item_id: str = ""          # item de fila criado


@dataclass(frozen=True, kw_only=True)
class RequestRejected(DomainEvent):
    name: str = "RequestRejected"
    session_id: str = ""
    request_id: str = ""
