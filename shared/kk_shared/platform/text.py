"""Normalização de texto para busca/dedup (sem acento, caixa baixa)."""
from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def song_key(title: str, artists: list[str] | None = None) -> str:
    """Chave lógica de dedup: título normalizado + artistas ordenados."""
    t = normalize(title)
    a = " ".join(sorted(normalize(x) for x in (artists or []) if x))
    return f"{t}|{a}".strip("|")
