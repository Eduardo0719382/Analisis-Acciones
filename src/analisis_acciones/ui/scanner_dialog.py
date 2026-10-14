"""Scanner dialog: the chart's analysis tools applied to a list of symbols."""

from __future__ import annotations

import logging

import shiboken6
from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.models.errors import user_message_for
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scanner import MAX_SYMBOLS, ScanResult, ScanRow, run_scan
from analisis_acciones.ui import strings
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


def matches(row: ScanRow, mode: str) -> bool:
    if mode == "patterns":
        return bool(row.patterns)
    if mode == "bullish":
        return len(row.bullish) > len(row.bearish)
    if mode == "bearish":
        return len(row.bearish) > len(row.bullish)
    if mode == "elliott":
        return bool(row.elliott)
    return True


class ScannerDialog(QDialog):
    #: The user asked to open this symbol on the main chart.
    symbol_activated = Signal(str)

    def __init__(self, market: MarketDataService, symbols: list[str],
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._market = market
        self._workers: set[Worker] = set()
        self.scan: ScanResult | None = None
        self.setWindowTitle(strings.SCAN_TITLE)
        self.resize(1100, 600)

        self.symbols = QLineEdit(", ".join(symbols[:MAX_SYMBOLS]))
        self.symbols.setPlaceholderText(strings.SCAN_PLACEHOLDER)
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
        filters = QHBoxLayout()
        filters.addWidget(QLabel(strings.SCAN_FILTER))
        filters.addWidget(self.filter)
        filters.addStretch(1)

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
        note = QLabel(strings.SCAN_NOTE)
        note.setObjectName("detailsSource")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(filters)
        layout.addWidget(self.table, stretch=1)
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

        def done(result: ScanResult) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.show_result(result)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.status.setText(user_message_for(exc))

        worker = start_worker(lambda: run_scan(self._market, symbols), done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def show_result(self, result: ScanResult) -> None:
        self.scan = result
        self._fill()
        text = strings.SCAN_DONE.format(count=len(result.rows))
        if result.problems:
            text += "\n" + "\n".join(result.problems)
        self.status.setText(text)

    def _fill(self, *_args: object) -> None:
        if self.scan is None:
            return
        loc = QLocale()
        mode = str(self.filter.currentData())
        rows = [r for r in self.scan.rows if matches(r, mode)]

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
                num(row.resistance_pct, 1, sign=True),
            ]  # fmt: skip
            for c, item in enumerate(cells):
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)

    def _activate(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self.symbol_activated.emit(item.text())
