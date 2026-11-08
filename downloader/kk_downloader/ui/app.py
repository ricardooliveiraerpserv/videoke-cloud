"""Entry da GUI do Video Downloader."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ..bootstrap import build_downloader
from .main_window import DownloaderWindow


def main(argv: list[str] | None = None) -> int:
    qapp = QApplication(argv if argv is not None else sys.argv)
    qapp.setApplicationName("Video Downloader")
    app = build_downloader()          # fala com o daemon (sobe-o se preciso)
    win = DownloaderWindow(app)
    win.show()
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
