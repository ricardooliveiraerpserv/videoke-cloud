"""Guarda o token de licença no diretório de dados do app (offline-first)."""
from __future__ import annotations

from pathlib import Path

from kk_shared.platform.paths import data_dir


def _token_path() -> Path:
    return data_dir() / "license.token"


def load_token() -> str | None:
    try:
        t = _token_path().read_text(encoding="utf-8").strip()
        return t or None
    except OSError:
        return None


def save_token(token: str) -> None:
    p = _token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token.strip(), encoding="utf-8")


def clear_token() -> None:
    try:
        _token_path().unlink()
    except OSError:
        pass
