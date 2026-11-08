"""Base declarativa + mixins transversais (ADR-2/ADR-3).

Toda tabela nasce com id UUIDv7, created_at/updated_at, soft delete e version.
Isso torna sync incremental e resolução de conflito possíveis no futuro sem
reescrever o schema.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from kk_shared.platform.ids import new_id


class Base(DeclarativeBase):
    pass


class UuidPk:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SoftDelete:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


class Versioned:
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
