"""Event Bus in-process (observer pattern) + base dos eventos de domínio.

Transporte local para a arquitetura Event-Driven. Entre processos, o Library
Core Service reemite estes eventos pelo canal IPC (Fase 5) — a interface não muda.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from ..platform.ids import new_id


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base de todos os eventos. `name` identifica o tipo no barramento."""
    name: str
    event_id: str = field(default_factory=new_id)
    occurred_at: float = field(default_factory=lambda: time.time())


Handler = Callable[[DomainEvent], None]


class Subscription:
    def __init__(self, unsubscribe: Callable[[], None]):
        self._unsubscribe = unsubscribe

    def cancel(self) -> None:
        self._unsubscribe()


class EventBus:
    """Publicação/assinatura por nome de evento. Entrega síncrona e isolada:
    um handler que falha não derruba os demais nem o publicador."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._wildcard: list[Handler] = []

    def subscribe(self, event_name: str, handler: Handler) -> Subscription:
        self._handlers[event_name].append(handler)
        return Subscription(lambda: self._handlers[event_name].remove(handler))

    def subscribe_all(self, handler: Handler) -> Subscription:
        self._wildcard.append(handler)
        return Subscription(lambda: self._wildcard.remove(handler))

    def publish(self, event: DomainEvent) -> None:
        for handler in list(self._handlers.get(event.name, ())) + list(self._wildcard):
            try:
                handler(event)
            except Exception:  # noqa: BLE001 — isola falhas de assinantes
                # Fase 0: silencioso; Fase 1+ liga no logging estruturado.
                pass
