"""Monitoramento de diretórios: cataloga automaticamente arquivos que caem
numa pasta observada (responsabilidade do Library Core).

Roda dentro do daemon. Referencia os arquivos no lugar (organize=False) e
deduplica por hash — reprocessar a mesma pasta não duplica.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from kk_shared.contracts.dtos import RegisterMediaDTO

from ..infrastructure.media_engine.probe import MEDIA_EXTS, clean_title, probe, sha256


class _Handler(FileSystemEventHandler):
    def __init__(self, on_file):
        self._on_file = on_file

    def on_created(self, event):
        if not event.is_directory:
            self._on_file(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._on_file(event.dest_path)


class WatchService:
    def __init__(self, library, on_added=None):
        self._lib = library
        self._on_added = on_added
        self._observer: Observer | None = None
        self._pending: set[str] = set()
        self._lock = threading.Lock()

    def start(self, dirs: list[str]) -> list[str]:
        dirs = [d for d in dirs if d and Path(d).expanduser().is_dir()]
        if not dirs:
            return []
        self._observer = Observer()
        handler = _Handler(self._schedule)
        for d in dirs:
            self._observer.schedule(handler, str(Path(d).expanduser()), recursive=True)
        self._observer.daemon = True
        self._observer.start()
        # varredura inicial: cataloga o que já está na pasta
        for d in dirs:
            for p in Path(d).expanduser().rglob("*"):
                if p.is_file() and p.suffix.lower() in MEDIA_EXTS:
                    self._schedule(str(p))
        return dirs

    def _schedule(self, path: str) -> None:
        if Path(path).suffix.lower() not in MEDIA_EXTS:
            return
        with self._lock:
            if path in self._pending:
                return
            self._pending.add(path)
        threading.Thread(target=self._ingest_when_stable, args=(path,), daemon=True).start()

    def _ingest_when_stable(self, path: str) -> None:
        try:
            self._wait_stable(path)
            self._ingest(path)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with self._lock:
                self._pending.discard(path)

    @staticmethod
    def _wait_stable(path: str, tries: int = 40) -> None:
        last = -1
        for _ in range(tries):
            try:
                size = Path(path).stat().st_size
            except OSError:
                size = -1
            if size >= 0 and size == last:
                return
            last = size
            time.sleep(0.5)

    def _ingest(self, path: str) -> None:
        if not Path(path).exists():
            return
        info = probe(path)
        view = self._lib.register_media(RegisterMediaDTO(
            title=clean_title(Path(path).name), artists=[], source_path=str(path),
            container=info.get("container"), video_codec=info.get("video_codec"),
            audio_codec=info.get("audio_codec"), duration_s=info.get("duration_s", 0),
            resolution=info.get("resolution"), sha256=sha256(path), organize=False,
        ))
        if view is not None and self._on_added:   # None = arquivo na lista negra
            self._on_added(view.title)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
