"""Scanner dialog: the chart's analysis tools applied to a list of symbols."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

import shiboken6
from PySide6.QtCore import QLocale, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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

from analisis_acciones.models.errors import user_message_for
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import default_file_stem, scan_csv, scan_report_html
from analisis_acciones.services.scanner import (
    MAX_SYMBOLS,
    FundamentalLimits,
    ScanResult,
    ScanRow,
    passes_fundamentals,
    run_scan,
)
from analisis_acciones.ui import strings
from analisis_acciones.ui.html_pdf import HtmlPdfWriter
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

PATTERNS_COLUMN = 6


class _Item(QTableWidgetItem):
    """Table cell that sorts by a numeric key when it has one."""

    def __init__(self, text: str, key: float | None = None) -> None:
        super().__init__(text)
        self._key = key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        # Not delegating to QTableWidgetItem.__lt__: PySide calls this override again.
        mine = self._key
        theirs = other._key if isinstance(other, _Item) else None
        if mine is not None and theirs is not None:
            return mine < theirs
        if (mine is None) != (theirs is None):
            return mine is None  # empty values first
        return self.text().casefold() < other.text().casefold()


def pct(fraction: float | None) -> float | None:
    return None if fraction is None else fraction * 100


def exhaustion_item(row: ScanRow) -> _Item:
    if not row.exhaustion:
        return _Item("—", 0)
    text = strings.SCAN_EXH_UP if row.exhaustion > 0 else strings.SCAN_EXH_DOWN
    item = _Item(text.format(met=abs(row.exhaustion), total=row.exhaustion_total),
                 abs(row.exhaustion))  # fmt: skip
    item.setToolTip(strings.SCAN_EXH_TIP)
    return item


def matches(row: ScanRow, mode: str) -> bool:
    if mode == "patterns":
        return bool(row.patterns)
    if mode == "bullish":
        return len(row.bullish) > len(row.bearish)
    if mode == "bearish":
        return len(row.bearish) > len(row.bullish)
    if mode == "elliott":
        return bool(row.elliott)
    if mode == "exhaustion":
        return row.exhaustion != 0
    return True


class _ProgressRelay(QObject):
    """Carries progress from the scan thread to the GUI thread (queued signal)."""

    changed = Signal(int, int, str)


class ScannerDialog(QDialog):
    #: The user asked to open this symbol on the main chart.
    symbol_activated = Signal(str)

    def __init__(self, market: MarketDataService, symbols: list[str],
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._market = market
        self._workers: set[Worker] = set()
        self.scan: ScanResult | None = None
        self.last_export: Path | None = None
        self.setWindowTitle(strings.SCAN_TITLE)
        self.resize(1250, 640)

        self.symbols = QLineEdit(", ".join(symbols[:MAX_SYMBOLS]))
        self.symbols.setPlaceholderText(strings.SCAN_PLACEHOLDER.format(max=MAX_SYMBOLS))
        self.symbols.returnPressed.connect(self.run)
        self.run_button = QPushButton(strings.SCAN_RUN)
        self.run_button.clicked.connect(self.run)
        self.filter = QComboBox()
        for key, label in strings.SCAN_FILTERS.items():
            self.filter.addItem(label, key)
        self.filter.currentIndexChanged.connect(self._fill)
        top = QHBoxLayout()
        top.addWidget(QLabel(strings.SCAN_SYMBOLS))
        top.addWidget(self.symbols, stretch=1)
        top.addWidget(self.run_button)
        self.cancel_button = QPushButton(strings.SCAN_CANCEL)
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel)
        top.addWidget(self.cancel_button)
        self.progress = QProgressBar()
        self.progress.hide()
        self._progress_relay = _ProgressRelay(self)
        self._progress_relay.changed.connect(self._on_progress)
        self._cancel_event = threading.Event()
        filters = QHBoxLayout()
        filters.addWidget(QLabel(strings.SCAN_FILTER))
        filters.addWidget(self.filter)
        self.with_fundamentals = QCheckBox(strings.SCAN_FUNDAMENTALS)
        self.with_fundamentals.setToolTip(strings.SCAN_FUNDAMENTALS_TIP)
        self.max_pe = QDoubleSpinBox()
        self.max_pe.setRange(0, 1000)
        self.max_pe.setDecimals(1)
        self.max_pe.setSpecialValueText(strings.SCAN_NO_LIMIT)
        self.min_yield = QDoubleSpinBox()
        self.min_yield.setRange(0, 30)
        self.min_yield.setDecimals(1)
        self.min_yield.setSingleStep(0.5)
        self.min_yield.setSuffix(" %")
        self.min_yield.setSpecialValueText(strings.SCAN_NO_LIMIT)
        self.min_cap = QDoubleSpinBox()
        self.min_cap.setRange(0, 10_000)
        self.min_cap.setDecimals(1)
        self.min_cap.setSuffix(strings.SCAN_CAP_SUFFIX)
        self.min_cap.setSpecialValueText(strings.SCAN_NO_LIMIT)
        # Growth and margin may be negative limits; the minimum of the range means "no limit".
        self.min_growth = QDoubleSpinBox()
        self.min_growth.setRange(-101, 1000)
        self.min_growth.setDecimals(1)
        self.min_growth.setSuffix(" %")
        self.min_growth.setSpecialValueText(strings.SCAN_NO_LIMIT)
        self.min_growth.setValue(-101)
        self.min_margin = QDoubleSpinBox()
        self.min_margin.setRange(-101, 100)
        self.min_margin.setDecimals(1)
        self.min_margin.setSuffix(" %")
        self.min_margin.setSpecialValueText(strings.SCAN_NO_LIMIT)
        self.min_margin.setValue(-101)
        for spin in (self.max_pe, self.min_yield, self.min_cap, self.min_growth, self.min_margin):
            spin.valueChanged.connect(self._fill)
        filters.addStretch(1)
        fundamentals_row = QHBoxLayout()
        fundamentals_row.addWidget(self.with_fundamentals)
        for label, spin in ((strings.SCAN_MAX_PE, self.max_pe),
                            (strings.SCAN_MIN_YIELD, self.min_yield),
                            (strings.SCAN_MIN_CAP, self.min_cap),
                            (strings.SCAN_MIN_GROWTH, self.min_growth),
                            (strings.SCAN_MIN_MARGIN, self.min_margin)):  # fmt: skip
            fundamentals_row.addWidget(QLabel(label))
            fundamentals_row.addWidget(spin)
        fundamentals_row.addStretch(1)
        self.export_button = QPushButton(strings.SCAN_EXPORT)
        export_menu = QMenu(self.export_button)
        export_menu.addAction(strings.SCAN_EXPORT_HTML, lambda: self._ask_and_export("html"))
        export_menu.addAction(strings.SCAN_EXPORT_PDF, lambda: self._ask_and_export("pdf"))
        export_menu.addAction(strings.SCAN_EXPORT_CSV, lambda: self._ask_and_export("csv"))
        self.export_button.setMenu(export_menu)
        self.export_button.setEnabled(False)
        filters.addWidget(self.export_button)
        #: Open exported reports with the system's default program (off in tests).
        self.open_after_export = True
        self._pdf_writer: HtmlPdfWriter | None = None

        self.table = QTableWidget(0, len(strings.SCAN_COLUMNS))
        self.table.setHorizontalHeaderLabels(strings.SCAN_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            PATTERNS_COLUMN, QHeaderView.ResizeMode.Interactive
        )
        self.table.setColumnWidth(PATTERNS_COLUMN, 280)
        self.table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.table.cellDoubleClicked.connect(self._activate)
        self.status = QLabel()
        self.status.setObjectName("detailsSource")
        self.status.setWordWrap(True)
        note = QLabel(strings.SCAN_NOTE + " " + strings.SCAN_FUNDAMENTALS_NOTE)
        note.setObjectName("detailsSource")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(filters)
        layout.addLayout(fundamentals_row)
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
        relay = self._progress_relay

        def finished() -> None:
            self.run_button.setEnabled(True)
            self.progress.hide()
            self.cancel_button.hide()

        def done(result: ScanResult) -> None:
            if shiboken6.isValid(self):
                finished()
                self.show_result(result)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                finished()
                self.status.setText(user_message_for(exc))

        def progress(done_count: int, total: int, symbol: str) -> None:
            # Called on the worker thread: the relay's signal is delivered on the GUI thread.
            if shiboken6.isValid(relay):
                relay.changed.emit(done_count, total, symbol)

        fundamentals = self.with_fundamentals.isChecked()
        market = self._market
        worker = start_worker(
            lambda: run_scan(market, symbols, progress, fundamentals, cancel.is_set), done, fail
        )
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
        self._cancel_event.set()  # stop a running scan: nobody will see its result
        super().closeEvent(event)

    def show_result(self, result: ScanResult) -> None:
        self.scan = result
        self.export_button.setEnabled(True)
        self._fill()
        text = (strings.SCAN_CANCELLED if result.cancelled
                else strings.SCAN_DONE).format(count=len(result.rows))  # fmt: skip
        if result.problems:
            text += "\n" + "\n".join(result.problems)
        self.status.setText(text)

    def limits(self) -> FundamentalLimits:
        """Active fundamental limits (a spin box at its minimum means no limit)."""

        def limit(spin: QDoubleSpinBox) -> float | None:
            return None if spin.value() <= spin.minimum() else spin.value()

        return FundamentalLimits(limit(self.max_pe), limit(self.min_yield), limit(self.min_cap),
                                 limit(self.min_growth), limit(self.min_margin))  # fmt: skip

    def _visible_rows(self) -> list[ScanRow]:
        assert self.scan is not None
        mode = str(self.filter.currentData())
        limits = self.limits()
        checked = any(r.fundamentals_checked for r in self.scan.rows)
        return [
            r
            for r in self.scan.rows
            if matches(r, mode) and (not checked or passes_fundamentals(r, limits))
        ]

    def _fill(self, *_args: object) -> None:
        if self.scan is None:
            return
        loc = QLocale()
        rows = self._visible_rows()
        if self.limits().active and not any(r.fundamentals_checked for r in self.scan.rows):
            self.status.setText(strings.SCAN_FUNDAMENTALS_HINT)

        def num(value: float | None, decimals: int = 2, sign: bool = False) -> _Item:
            if value is None:
                return _Item("—")
            text = loc.toString(value, "f", decimals)
            return _Item(f"+{text}" if sign and value > 0 else text, value)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            bull = _Item(str(len(row.bullish)), len(row.bullish))
            bull.setToolTip("\n".join(row.bullish))
            bear = _Item(str(len(row.bearish)), len(row.bearish))
            bear.setToolTip("\n".join(row.bearish))
            patterns = _Item("; ".join(row.patterns))
            patterns.setToolTip("\n".join(row.patterns))
            cells = [
                _Item(row.symbol), num(row.close), num(row.change_pct, sign=True),
                num(row.rsi14, 1), bull, bear, patterns, _Item(row.elliott),
                num(None if row.support_pct is None else -row.support_pct, 1),
                num(row.resistance_pct, 1, sign=True), num(row.pe, 1),
                num(pct(row.dividend_yield), 2),
                num(None if row.market_cap is None else row.market_cap / 1e9, 1),
                num(pct(row.revenue_growth), 1, sign=True), num(pct(row.profit_margin), 1),
                exhaustion_item(row),
            ]  # fmt: skip
            for c, item in enumerate(cells):
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)

    # Export ------------------------------------------------------------------
    def visible_result(self) -> ScanResult:
        """The rows the current filter shows (and the scan's problems)."""
        assert self.scan is not None
        return ScanResult(self._visible_rows(), self.scan.problems)

    def _ask_and_export(self, kind: str) -> None:
        filters = {"html": "Página web (*.html)", "pdf": "PDF (*.pdf)", "csv": "CSV (*.csv)"}
        suggested = str(Path.home() / f"{default_file_stem(datetime.now())}.{kind}")
        path, _ = QFileDialog.getSaveFileName(self, strings.SCAN_EXPORT, suggested, filters[kind])
        if path:
            self.export(kind, Path(path))

    def export(self, kind: str, path: Path) -> None:
        if self.scan is None:
            return
        if path.suffix.lower() != f".{kind}":
            path = path.with_name(path.name + f".{kind}")
        result = self.visible_result()
        mode = str(self.filter.currentData())
        note = "" if mode == "all" else strings.SCAN_EXPORT_FILTER_NOTE.format(
            name=strings.SCAN_FILTERS[mode])  # fmt: skip
        limits = self.limits()
        if any(r.fundamentals_checked for r in self.scan.rows) and limits.active:
            note = (note + " " if note else "") + strings.SCAN_EXPORT_FILTER_NOTE.format(
                name=limits.describe()
            )
        try:
            if kind == "csv":
                path.write_text(scan_csv(result), encoding="utf-8-sig")  # BOM: Excel reads UTF-8
                self._exported(path, open_it=False)
                return
            html = scan_report_html(result, datetime.now(), note=note)
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

    def _activate(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self.symbol_activated.emit(item.text())
