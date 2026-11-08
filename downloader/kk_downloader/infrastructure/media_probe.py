"""Probe leve de mídia via ffmpeg (duração/resolução/codecs) + hash."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

MEDIA_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4a", ".mp3", ".opus", ".flac", ".wav"}


def ffmpeg_bin() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        import shutil
        return shutil.which("ffmpeg")


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: str | Path) -> dict:
    ff = ffmpeg_bin()
    if not ff:
        return {}
    proc = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True)
    err = proc.stderr or ""
    out: dict = {"container": Path(path).suffix.lstrip(".")}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)", err)
    if m:
        h, mn, s = map(int, m.groups())
        out["duration_s"] = h * 3600 + mn * 60 + s
    mv = re.search(r"Video:\s*(\w+).*?(\d{2,5})x(\d{2,5})", err)
    if mv:
        out["video_codec"] = mv.group(1)
        out["resolution"] = f"{mv.group(2)}x{mv.group(3)}"
    ma = re.search(r"Audio:\s*(\w+)", err)
    if ma:
        out["audio_codec"] = ma.group(1)
    return out
