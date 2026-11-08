"""Caminhos padrão do ecossistema, cross-platform."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "KaraokePlatform"


def data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_db_path() -> Path:
    return data_dir() / "library.db"


def default_media_dir() -> Path:
    p = data_dir() / "media"
    p.mkdir(parents=True, exist_ok=True)
    return p
