"""Window of the weekly exhaustion summary, exportable as a visual HTML or PDF report."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.analysis.exhaustion import DEFAULT_PARAMS, UP, Params
from analisis_acciones.models.errors import user_message_for
from analisis_acciones.services.exhaustion_compare import READING_LABELS
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import num
from analisis_acciones.services.weekly_summary import (
    WeeklySummary,
    record_sentence,
    weekly_html,
    weekly_summary,
)
from analisis_acciones.ui import strings
from analisis_acciones.ui.html_pdf import HtmlPdfWriter
from analisis_acciones.ui.workers import Worker, start_worker


class _ProgressRelay(QObject):
    changed = Signal(int, int, str)


class WeeklySummaryDialog(QDialog):
    symbol_activated = Signal(str)

    def __init__(
        self, market: MarketDataService, symbols: list[str], today: Callable[[], date],
        params: Params = DEFAULT_PARAMS, parent: QWidget | None = None,
    ) -> None:  # fmt: skip
        super().__init__(parent)
        self._market = market
        self._symbols = symbols
        self._today = today
        self._params = params
        self._workers: set[Worker] = set()
        self._pdf_writer: HtmlPdfWriter | None = None
        self._cancel_event = threading.Event()
        self.summary: WeeklySummary | None = None
        self.last_export: Path | None = None
        self.open_after_export = True
        self.setWindowTitle(strings.WEEK_TITLE)
        self.resize(1000, 560)

        self.intro = QLabel(strings.WEEK_INTRO.format(count=len(symbols)))
        self.intro.setWordWrap(True)
        self.export_button = QPushButton(strings.SCAN_EXPORT)
        self.export_button.setEnabled(False)
        menu = QMenu(self.export_button)
        menu.addAction(strings.SCAN_EXPORT_PDF, lambda: self._ask_and_export("pdf"))
        menu.addAction(strings.SCAN_EXPORT_HTML, lambda: self._ask_and_export("html"))
        self.export_button.setMenu(menu)
        self.cancel_button = QPushButton(strings.SCAN_CANCEL)
        self.cancel_button.clicked.connect(self._cancel_event.set)
        top = QHBoxLayout()
        top.addWidget(self.intro, stretch=1)
        top.addWidget(self.cancel_button)
        top.addWidget(self.export_button)

        self.table = QTableWidget(0, len(strings.WEEK_COLUMNS))
        self.table.setHorizontalHeaderLabels(strings.WEEK_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._activate)
        self.progress = QProgressBar()
        self._relay = _ProgressRelay(self)
        self._relay.changed.connect(self._on_progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        note = QLabel(strings.WEEK_NOTE)
        note.setObjectName("detailsSource")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(note)

    def run(self) -> None:
        if not self._symbols:
            self.status.setText(strings.SCAN_EMPTY)
            self.progress.hide()
            self.cancel_button.hide()
            return
        self.progress.setRange(0, len(self._symbols))
        relay, cancel = self._relay, self._cancel_event
        market, symbols, params, today = self._market, self._symbols, self._params, self._today()

        def finished() -> None:
            self.progress.hide()
            self.cancel_button.hide()

        def done(summary: WeeklySummary) -> None:
            if shiboken6.isValid(self):
                finished()
                self.show_summary(summary)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                finished()
                self.status.setText(user_message_for(exc))

        def progress(done_count: int, total: int, symbol: str) -> None:
            if shiboken6.isValid(relay):
                relay.changed.emit(done_count, total, symbol)

        worker = start_worker(
            lambda: weekly_summary(market, symbols, today, params, progress, cancel.is_set),
            done, fail,
        )  # fmt: skip
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def _on_progress(self, done_count: int, total: int, symbol: str) -> None:
        self.progress.setValue(done_count)
        self.status.setText(strings.SCAN_PROGRESS.format(symbol=symbol, done=done_count + 1,
                                                         total=total))  # fmt: skip

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cancel_event.set()
        super().closeEvent(event)

    def show_summary(self, summary: WeeklySummary) -> None:
        self.summary = summary
        self.export_button.setEnabled(True)
        self.table.setRowCount(len(summary.signals))
        for r, s in enumerate(summary.signals):
            change = (
                "—" if s.week_change_pct is None else f"{num(s.week_change_pct, 1, sign=True)} %"
            )
            cells = [
                s.symbol,
                strings.WEEK_RISE if s.direction == UP else strings.WEEK_FALL,
                f"{s.started:%d/%m/%Y}",
                strings.WEEK_ACTIVE if s.active else strings.WEEK_ENDED,
                change,
                READING_LABELS[s.reading][s.direction],
                record_sentence(s),
            ]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        text = strings.WEEK_DONE.format(
            signals=len(summary.signals), analysed=summary.analysed,
            start=f"{summary.start:%d/%m}", end=f"{summary.end:%d/%m/%Y}",
        )  # fmt: skip
        if summary.cancelled:
            text = strings.SCAN_CANCELLED.format(count=summary.analysed) + " " + text
        if summary.problems:
            text += "\n" + "\n".join(summary.problems)
        self.status.setText(text)

    def _activate(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self.symbol_activated.emit(item.text())

    # Export ------------------------------------------------------------------
    def _ask_and_export(self, kind: str) -> None:
        filters = {"html": "Página web (*.html)", "pdf": "PDF (*.pdf)"}
        suggested = str(Path.home() / f"resumen_semanal_{datetime.now():%Y-%m-%d}.{kind}")
        path, _ = QFileDialog.getSaveFileName(self, strings.SCAN_EXPORT, suggested, filters[kind])
        if path:
            self.export(kind, Path(path))

    def export(self, kind: str, path: Path) -> None:
        if self.summary is None:
            return
        if path.suffix.lower() != f".{kind}":
            path = path.with_name(path.name + f".{kind}")
        html = weekly_html(self.summary, datetime.now())
        if kind == "html":
            try:
                path.write_text(html, encoding="utf-8")
            except OSError as exc:
                self.status.setText(strings.SCAN_EXPORT_FAILED.format(error=exc))
                return
            self._exported(path)
            return
        self.status.setText(strings.SCAN_EXPORT_WORKING)
        self.export_button.setEnabled(False)

        def written(ok: bool) -> None:
            self._pdf_writer = None
            if not shiboken6.isValid(self):
                return
            self.export_button.setEnabled(True)
            if ok and path.exists():
                self._exported(path)
            else:
                self.status.setText(strings.SCAN_EXPORT_FAILED.format(error="PDF"))

        self._pdf_writer = HtmlPdfWriter(html, path, written, self)

    def _exported(self, path: Path) -> None:
        self.status.setText(strings.SCAN_EXPORT_SAVED.format(path=path))
        self.last_export = path
        if self.open_after_export:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
