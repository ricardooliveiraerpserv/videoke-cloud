"""Janela do Video Downloader — busca no YouTube, baixa (catalogando no Core
via daemon) e importa pastas. Espelha o CLI, com telinha."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..bootstrap import DownloaderApp
from .workers import DownloadWorker, ImportWorker, SearchWorker


def _dur(s: int) -> str:
    m, sec = divmod(int(s or 0), 60)
    return f"{m}:{sec:02d}"


class DownloaderWindow(QMainWindow):
    def __init__(self, app: DownloaderApp):
        super().__init__()
        self.app = app
        self.pool = QThreadPool.globalInstance()
        self._workers = set()
        self._hits = {}          # row -> SearchHit
        self._dl_rows = {}       # download row -> table row index

        self.setWindowTitle("Video Downloader")
        self.resize(940, 660)
        self.setCentralWidget(self._build())

    def _build(self) -> QWidget:
        self.query = QLineEdit(); self.query.setPlaceholderText("Artista ou música…")
        self.query.returnPressed.connect(self._search)
        self.deep = QCheckBox("Busca profunda"); self.deep.setChecked(True)
        self.kind = QComboBox(); self.kind.addItem("Vídeo (MP4)", False); self.kind.addItem("Áudio", True)
        self.quality = QComboBox()
        for lbl, h in [("Melhor", 1080), ("720p", 720), ("480p", 480), ("360p", 360)]:
            self.quality.addItem(lbl, h)
        search_btn = QPushButton("Buscar"); search_btn.clicked.connect(self._search)
        top = QHBoxLayout()
        top.addWidget(self.query, 1); top.addWidget(self.deep)
        top.addWidget(self.kind); top.addWidget(self.quality); top.addWidget(search_btn)

        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["", "Título", "Canal", "Duração"])
        self.results.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)

        selall = QPushButton("Selecionar todos"); selall.clicked.connect(self._select_all)
        dl_btn = QPushButton("Baixar selecionados"); dl_btn.clicked.connect(self._download_selected)
        imp_btn = QPushButton("Importar pasta…"); imp_btn.clicked.connect(self._import)
        actions = QHBoxLayout()
        actions.addWidget(selall); actions.addStretch(1); actions.addWidget(imp_btn); actions.addWidget(dl_btn)

        self.downloads = QTableWidget(0, 3)
        self.downloads.setHorizontalHeaderLabels(["Título", "Progresso", "Status"])
        self.downloads.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.downloads.setEditTriggers(QTableWidget.NoEditTriggers)

        self.status = QLabel("Pronto."); self.status.setStyleSheet("color:#888;")

        root = QVBoxLayout()
        root.addLayout(top)
        root.addWidget(QLabel("<b>Resultados</b>")); root.addWidget(self.results, 2)
        root.addLayout(actions)
        root.addWidget(QLabel("<b>Downloads</b>")); root.addWidget(self.downloads, 1)
        root.addWidget(self.status)
        w = QWidget(); w.setLayout(root); return w

    def _keep(self, worker):
        self._workers.add(worker)
        for sig in (getattr(worker.signals, n, None) for n in ("done", "error", "failed")):
            if sig:
                sig.connect(lambda *a, w=worker: self._workers.discard(w))
        return worker

    # ---- busca ----
    def _search(self) -> None:
        q = self.query.text().strip()
        if not q:
            return
        self.status.setText("Buscando no YouTube…")
        w = self._keep(SearchWorker(self.app.search, q, self.deep.isChecked(), 25))
        w.signals.done.connect(self._on_results)
        w.signals.error.connect(lambda e: self.status.setText(f"Erro: {e[:120]}"))
        self.pool.start(w)

    def _on_results(self, hits) -> None:
        self.results.setRowCount(0); self._hits.clear()
        for h in hits:
            r = self.results.rowCount(); self.results.insertRow(r)
            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked); self.results.setItem(r, 0, chk)
            self.results.setItem(r, 1, QTableWidgetItem(h.title))
            self.results.setItem(r, 2, QTableWidgetItem(h.channel))
            self.results.setItem(r, 3, QTableWidgetItem(_dur(h.duration_s)))
            self._hits[r] = h
        self.status.setText(f"{len(hits)} resultado(s). Marque e baixe.")

    def _select_all(self) -> None:
        for r in range(self.results.rowCount()):
            self.results.item(r, 0).setCheckState(Qt.Checked)

    # ---- download ----
    def _download_selected(self) -> None:
        audio = self.kind.currentData(); height = self.quality.currentData()
        n = 0
        for r in range(self.results.rowCount()):
            if self.results.item(r, 0).checkState() == Qt.Checked and r in self._hits:
                self._start_download(self._hits[r], audio, height); n += 1
        self.status.setText(f"{n} download(s) iniciado(s)." if n else "Marque ao menos um.")

    def _start_download(self, hit, audio: bool, height: int) -> None:
        row = self.downloads.rowCount(); self.downloads.insertRow(row)
        self.downloads.setItem(row, 0, QTableWidgetItem(hit.title))
        bar = QProgressBar(); bar.setRange(0, 100); self.downloads.setCellWidget(row, 1, bar)
        self.downloads.setItem(row, 2, QTableWidgetItem("Baixando"))
        w = self._keep(DownloadWorker(self.app.download, row, hit.url,
                                      audio_only=audio, max_height=height))
        w.signals.progress.connect(self._dl_progress)
        w.signals.done.connect(self._dl_done)
        w.signals.failed.connect(self._dl_failed)
        self.pool.start(w)

    def _dl_progress(self, row: int, pct: float, _spd: str) -> None:
        bar = self.downloads.cellWidget(row, 1)
        if bar:
            bar.setValue(int(pct))

    def _dl_done(self, row: int, title: str) -> None:
        bar = self.downloads.cellWidget(row, 1)
        if bar:
            bar.setValue(100)
        self.downloads.item(row, 2).setText("Catalogado ✓")
        self.status.setText(f"Catalogado: {title}")

    def _dl_failed(self, row: int, err: str) -> None:
        self.downloads.item(row, 2).setText("Falhou")
        self.status.setText(f"Falha: {err[:120]}")

    # ---- import ----
    def _import(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pasta com mídia já baixada")
        if not folder:
            return
        self.status.setText("Importando pasta…")
        w = self._keep(ImportWorker(self.app.library, folder))
        w.signals.progress.connect(lambda i, t, title: self.status.setText(f"Importando {i}/{t}: {title[:40]}"))
        w.signals.done.connect(lambda res: self.status.setText(
            f"Importadas {res['added']} de {res['total']} (falhas: {res['failed']})."))
        w.signals.error.connect(lambda e: self.status.setText(f"Erro no import: {e[:120]}"))
        self.pool.start(w)
