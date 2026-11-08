"""Workers (QThreadPool) do Downloader — mantêm a UI responsiva."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal

from ..application.import_service import ImportFolderUseCase
from ..application.use_cases import DownloadAndRegisterUseCase, SearchYouTubeUseCase


class SearchSignals(QObject):
    done = Signal(list)
    error = Signal(str)


class SearchWorker(QRunnable):
    def __init__(self, uc: SearchYouTubeUseCase, query: str, deep: bool, limit: int):
        super().__init__()
        self.uc, self.query, self.deep, self.limit = uc, query, deep, limit
        self.signals = SearchSignals()

    def run(self) -> None:
        try:
            self.signals.done.emit(self.uc.execute(self.query, deep=self.deep, limit=self.limit))
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))


class DownloadSignals(QObject):
    progress = Signal(int, float, str)   # row, pct, speed
    done = Signal(int, str)              # row, título catalogado
    failed = Signal(int, str)           # row, erro


class DownloadWorker(QRunnable):
    def __init__(self, uc: DownloadAndRegisterUseCase, row: int, url: str, *,
                 audio_only: bool, max_height: int):
        super().__init__()
        self.uc, self.row, self.url = uc, row, url
        self.audio_only, self.max_height = audio_only, max_height
        self.signals = DownloadSignals()

    def run(self) -> None:
        try:
            view = self.uc.execute(
                self.url, audio_only=self.audio_only, max_height=self.max_height,
                progress=lambda pct, spd: self.signals.progress.emit(self.row, pct, spd),
            )
            self.signals.done.emit(self.row, view.title)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self.row, str(exc))


class ImportSignals(QObject):
    progress = Signal(int, int, str)    # i, total, título
    done = Signal(dict)
    error = Signal(str)


class ImportWorker(QRunnable):
    def __init__(self, library, folder: str):
        super().__init__()
        self.library, self.folder = library, folder
        self.signals = ImportSignals()

    def run(self) -> None:
        try:
            res = ImportFolderUseCase(self.library).execute(
                self.folder, progress=lambda i, t, title: self.signals.progress.emit(i, t, title)
            )
            self.signals.done.emit(res)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))
