"""Window comparing the record of exhaustion signs across several assets."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.analysis.exhaustion import (
    DEFAULT_PARAMS,
    DOWN,
    HORIZONS,
    READ_CONTINUE,
    READ_USEFUL,
    UP,
    Outcome,
    Params,
)
from analisis_acciones.models.errors import user_message_for
from analisis_acciones.services.exhaustion_compare import (
    MAX_SYMBOLS,
    READING_LABELS,
    ExhaustionComparison,
    compare_exhaustion,
    comparison_csv,
    comparison_html,
    now_text,
)
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import num
from analisis_acciones.ui import strings
from analisis_acciones.ui.html_pdf import HtmlPdfWriter
from analisis_acciones.ui.workers import Worker, start_worker


class _Item(QTableWidgetItem):
    """Cell sorted by a numeric key when it has one (empty values first)."""

    def __init__(self, text: str, key: float | None = None) -> None:
        super().__init__(text)
        self._key = key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine = self._key
        theirs = other._key if isinstance(other, _Item) else None
        if mine is not None and theirs is not None:
            return mine < theirs
        if (mine is None) != (theirs is None):
            return mine is None
        return self.text() < other.text()


class _ProgressRelay(QObject):
    changed = Signal(int, int, str)


def _pct_item(o: Outcome | None) -> _Item:
    if o is None or o.against_pct is None:
        return _Item("—")
    base = "—" if o.baseline_against_pct is None else f"{num(o.baseline_against_pct, 0)} %"
    return _Item(f"{num(o.against_pct, 0)} % (normal {base})", o.against_pct)


def _p_item(o: Outcome | None) -> _Item:
    p = o.p_value if o else None
    if p is None:
        return _Item("—")
    return _Item("< 0,001" if p < 0.001 else num(p, 3), p)


class ExhaustionCompareDialog(QDialog):
    symbol_activated = Signal(str)

    def __init__(
        self, market: MarketDataService, symbols: list[str], params: Params = DEFAULT_PARAMS,
        parent: QWidget | None = None,
    ) -> None:  # fmt: skip
        super().__init__(parent)
        self._market = market
        self._params = params
        self._workers: set[Worker] = set()
        self._pdf_writer: HtmlPdfWriter | None = None
        self.comparison: ExhaustionComparison | None = None
        self.last_export: Path | None = None
        self.open_after_export = True
        self.setWindowTitle(strings.EXC_TITLE)
        self.resize(1150, 620)

        self.symbols = QLineEdit(", ".join(symbols[:MAX_SYMBOLS]))
        self.symbols.setPlaceholderText(strings.SCAN_PLACEHOLDER.format(max=MAX_SYMBOLS))
        self.symbols.returnPressed.connect(self.run)
        self.horizon = QComboBox()
        for h in reversed(HORIZONS):
            self.horizon.addItem(strings.EXC_HORIZON.format(h=h), h)
        self.horizon.currentIndexChanged.connect(lambda _i: self._fill())
        self.run_button = QPushButton(strings.EXC_RUN)
        self.run_button.clicked.connect(self.run)
        self.cancel_button = QPushButton(strings.SCAN_CANCEL)
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel)
        self.export_button = QPushButton(strings.SCAN_EXPORT)
        self.export_button.setEnabled(False)
        menu = QMenu(self.export_button)
        menu.addAction(strings.SCAN_EXPORT_HTML, lambda: self._ask_and_export("html"))
        menu.addAction(strings.SCAN_EXPORT_PDF, lambda: self._ask_and_export("pdf"))
        menu.addAction(strings.SCAN_EXPORT_CSV, lambda: self._ask_and_export("csv"))
        self.export_button.setMenu(menu)
        top = QHBoxLayout()
        top.addWidget(QLabel(strings.SCAN_SYMBOLS))
        top.addWidget(self.symbols, stretch=1)
        top.addWidget(self.horizon)
        top.addWidget(self.run_button)
        top.addWidget(self.cancel_button)
        top.addWidget(self.export_button)

        self.table = QTableWidget(0, len(strings.EXC_COLUMNS))
        self.table.setHorizontalHeaderLabels(strings.EXC_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._activate)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.hide()
        self._relay = _ProgressRelay(self)
        self._relay.changed.connect(self._on_progress)
        self._cancel_event = threading.Event()
        self.status = QLabel()
        self.status.setWordWrap(True)
        note = QLabel(strings.EXC_NOTE)
        note.setObjectName("detailsSource")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(note)

    def parsed_symbols(self) -> list[str]:
        raw = [s.strip().upper() for s in self.symbols.text().replace(";", ",").split(",")]
        return list(dict.fromkeys(s for s in raw if s))[:MAX_SYMBOLS]

    def run(self) -> None:
        symbols = self.parsed_symbols()
        if not symbols:
            self.status.setText(strings.SCAN_EMPTY)
            return
        self.run_button.setEnabled(False)
        self.status.setText(strings.SCAN_RUNNING.format(count=len(symbols)))
        self._cancel_event = cancel = threading.Event()
        self.progress.setRange(0, len(symbols))
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        relay = self._relay

        def finished() -> None:
            self.run_button.setEnabled(True)
            self.progress.hide()
            self.cancel_button.hide()

        def done(result: ExhaustionComparison) -> None:
            if shiboken6.isValid(self):
                finished()
                self.show_result(result)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                finished()
                self.status.setText(user_message_for(exc))

        def progress(done_count: int, total: int, symbol: str) -> None:
            if shiboken6.isValid(relay):
                relay.changed.emit(done_count, total, symbol)

        market, params = self._market, self._params
        worker = start_worker(
            lambda: compare_exhaustion(market, symbols, params, progress, cancel.is_set),
            done, fail,
        )  # fmt: skip
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def cancel(self) -> None:
        self._cancel_event.set()

    def _on_progress(self, done_count: int, total: int, symbol: str) -> None:
        self.progress.setValue(done_count)
        self.status.setText(strings.SCAN_PROGRESS.format(symbol=symbol, done=done_count + 1,
                                                         total=total))  # fmt: skip

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cancel_event.set()
        super().closeEvent(event)

    def show_result(self, result: ExhaustionComparison) -> None:
        self.comparison = result
        self.export_button.setEnabled(bool(result.rows))
        self._fill()
        text = (strings.SCAN_CANCELLED if result.cancelled
                else strings.SCAN_DONE).format(count=len(result.rows))  # fmt: skip
        if result.problems:
            text += "\n" + "\n".join(result.problems)
        self.status.setText(text)

    def _fill(self) -> None:
        if self.comparison is None:
            return
        result = self.comparison
        h = int(self.horizon.currentData())
        lines = []
        for direction, label in ((UP, strings.EXC_SUMMARY_UP), (DOWN, strings.EXC_SUMMARY_DOWN)):
            groups = result.by_reading(direction)
            lines.append(label.format(
                useful=len(groups[READ_USEFUL]), cont=len(groups[READ_CONTINUE]),
                total=len(result.rows),
                names=", ".join(groups[READ_USEFUL][:10]) or "—",
            ))  # fmt: skip
        self.summary.setText("\n".join(lines))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(result.rows))
        for r, row in enumerate(result.rows):
            cells = [_Item(row.symbol), _Item(now_text(row.now))]
            for direction in (UP, DOWN):
                record = row.record(direction)
                o = record.at(h)
                cells += [
                    _Item(str(o.events if o else 0), o.events if o else 0),
                    _pct_item(o),
                    _p_item(o),
                    _Item(READING_LABELS[record.reading][direction]),
                ]
            for c, item in enumerate(cells):
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)

    def _activate(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self.symbol_activated.emit(item.text())

    # Export ------------------------------------------------------------------
    def _ask_and_export(self, kind: str) -> None:
        filters = {"html": "Página web (*.html)", "pdf": "PDF (*.pdf)", "csv": "CSV (*.csv)"}
        stem = f"agotamiento_{datetime.now():%Y-%m-%d}"
        suggested = str(Path.home() / f"{stem}.{kind}")
        path, _ = QFileDialog.getSaveFileName(self, strings.SCAN_EXPORT, suggested, filters[kind])
        if path:
            self.export(kind, Path(path))

    def export(self, kind: str, path: Path) -> None:
        if self.comparison is None:
            return
        if path.suffix.lower() != f".{kind}":
            path = path.with_name(path.name + f".{kind}")
        try:
            if kind == "csv":
                path.write_text(comparison_csv(self.comparison), encoding="utf-8-sig")
                self._exported(path, open_it=False)
                return
            html = comparison_html(self.comparison, datetime.now())
            if kind == "html":
                path.write_text(html, encoding="utf-8")
                self._exported(path)
                return
        except OSError as exc:
            self.status.setText(strings.SCAN_EXPORT_FAILED.format(error=exc))
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

    def _exported(self, path: Path, open_it: bool = True) -> None:
        self.status.setText(strings.SCAN_EXPORT_SAVED.format(path=path))
        self.last_export = path
        if open_it and self.open_after_export:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
