"""Organização física do acervo: media/{artista}/{música}/{media_id}.{ext}."""
from __future__ import annotations

import re
import shutil
from pathlib import Path


def _safe(name: str, fallback: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name or "").strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:120] or fallback).strip(". ")


class NullOrganizer:
    """Não move nada — mantém o caminho de origem (usado em testes/consultas)."""

    def organize(self, source_path: str, *, media_id: str, title: str, artists, ext: str) -> str:
        return source_path


class FileOrganizer:
    def __init__(self, media_root: str | Path):
        self.root = Path(media_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def organize(self, source_path: str, *, media_id: str, title: str, artists, ext: str) -> str:
        artist = _safe(artists[0] if artists else "", "Desconhecido")
        song = _safe(title, "Sem título")
        ext = (ext or "").lstrip(".") or "mp4"
        dest_dir = self.root / artist / song
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{media_id}.{ext}"
        src = Path(source_path)
        if src.exists() and src.resolve() != dest.resolve():
            shutil.move(str(src), str(dest))
        return str(dest)
