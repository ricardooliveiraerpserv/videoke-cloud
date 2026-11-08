"""Ports de serviços de domínio (implementados na infraestrutura)."""
from __future__ import annotations

from typing import Protocol


class IFileOrganizer(Protocol):
    """O Core é dono da organização física da mídia (decisão v0.1).
    Move o arquivo baixado para o acervo gerenciado e devolve o caminho final."""

    def organize(
        self, source_path: str, *, media_id: str, title: str, artists: list[str], ext: str
    ) -> str: ...
