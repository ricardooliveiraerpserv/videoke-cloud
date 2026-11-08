"""Geração de IDs globais (UUIDv7, time-ordered) — ADR-2.

UUIDv7 embute o timestamp em ms nos bits altos, então os IDs são
monotonicamente crescentes (bons para índice/ordenação) e geráveis offline
sem colisão entre dispositivos/bibliotecas — base para sync futuro.
"""
from __future__ import annotations

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """Retorna um UUID versão 7 (RFC 9562)."""
    unix_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)          # 12 bits
    rand_b = secrets.randbits(62)          # 62 bits
    value = (
        (unix_ms << 80)
        | (0x7 << 76)                      # versão 7
        | (rand_a << 64)
        | (0b10 << 62)                     # variante RFC 4122
        | rand_b
    )
    return uuid.UUID(int=value)


def new_id() -> str:
    """ID como string (forma canônica usada nos DTOs/contratos)."""
    return str(uuid7())
