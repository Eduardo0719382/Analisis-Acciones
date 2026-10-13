"""Compare several assets: normalised performance chart and metrics table."""

from __future__ import annotations

import logging

import pandas as pd
import shiboken6
from PySide6.QtCore import QLocale
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

from analisis_acciones.models.errors import AppError, UserError, user_message_for
from analisis_acciones.models.market import Interval
from analisis_acciones.services.comparison import PERIODS, ComparisonResult, compare
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.ui import strings
from analisis_acciones.ui.equity_chart import EquityChart
from analisis_acciones.ui.theme import ThemeTokens
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

MAX_SYMBOLS = 6
SERIES_COLOURS = ("#4c8dff", "#f5a623", "#26a69a", "#ec407a", "#ab47bc", "#26c6da")


def run_comparison(market: MarketDataService, symbols: list[str],
                   period_days: int | None) -> tuple[ComparisonResult, list[str]]:  # fmt: skip
    """Load each symbol (cache-first) and compare; failures are reported per symbol."""
    loaded: dict[str, pd.DataFrame] = {}
    problems: list[str] = []
    for symbol in symbols:
        try:
            result = market.load(symbol, Interval.D1)
        except AppError as exc:
            problems.append(f"{symbol}: {exc.user_message}")
            continue
        loaded[result.series.symbol] = result.series.bars
    if not loaded:
        raise UserError("no symbol loaded", user_message="; ".join(problems) or strings.CMP_EMPTY)
    return compare(loaded, period_days), problems


class ComparisonDialog(QDialog):
    def __init__(self, market: MarketDataService, tokens: ThemeTokens, symbols: list[str],
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._market = market
        self._workers: set[Worker] = set()
        self.comparison: ComparisonResult | None = None
        self.setWindowTitle(strings.CMP_TITLE)
        self.resize(960, 640)

        self.symbols = QLineEdit(", ".join(symbols[:MAX_SYMBOLS]))
        self.symbols.setPlaceholderText(strings.CMP_PLACEHOLDER)
        self.period = QComboBox()
        for label, days in PERIODS.items():
            self.period.addItem(label, days)
        self.period.setCurrentIndex(self.period.findText("1A"))
        self.run_button = QPushButton(strings.CMP_RUN)
        self.run_button.clicked.connect(self.run)
        self.symbols.returnPressed.connect(self.run)
        top = QHBoxLayout()
        top.addWidget(QLabel(strings.CMP_SYMBOLS))
        top.addWidget(self.symbols, stretch=1)
        top.addWidget(QLabel(strings.CMP_PERIOD))
        top.addWidget(self.period)
        top.addWidget(self.run_button)

        loc = QLocale()
        self.chart = EquityChart(tokens, value_format=lambda v: f"{loc.toString(v, 'f', 0)} %")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(strings.CMP_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.status = QLabel()
        self.status.setObjectName("detailsSource")
        self.status.setWordWrap(True)
        note = QLabel(strings.CMP_NOTE)
        note.setObjectName("detailsSource")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.chart, stretch=3)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.status)
        layout.addWidget(note)

    def parsed_symbols(self) -> list[str]:
        raw = [s.strip().upper() for s in self.symbols.text().replace(";", ",").split(",")]
        unique = list(dict.fromkeys(s for s in raw if s))
        return unique[:MAX_SYMBOLS]

    def run(self) -> None:
        symbols = self.parsed_symbols()
        if not symbols:
            self.status.setText(strings.CMP_EMPTY)
            return
        period = self.period.currentData()
        self.run_button.setEnabled(False)
        self.status.setText(strings.CMP_LOADING)

        def done(payload: tuple[ComparisonResult, list[str]]) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.show_result(*payload)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.status.setText(user_message_for(exc))

        worker = start_worker(lambda: run_comparison(self._market, symbols, period), done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def show_result(self, result: ComparisonResult, problems: list[str]) -> None:
        self.comparison = result
        loc = QLocale()
        self.chart.set_series([
            (symbol, result.performance[symbol], SERIES_COLOURS[i % len(SERIES_COLOURS)])
            for i, symbol in enumerate(result.performance.columns)
        ])  # fmt: skip

        def pct(v: float | None) -> str:
            return "—" if v is None else f"{'+' if v > 0 else ''}{loc.toString(v, 'f', 2)} %"

        self.table.setRowCount(len(result.metrics))
        for row, m in enumerate(result.metrics):
            cells = [
                m.symbol, pct(m.total_return_pct), pct(m.volatility_pct).replace("+", ""),
                pct(m.max_drawdown_pct),
                "—" if m.avg_volume is None else loc.toString(int(m.avg_volume)),
                "—" if m.rsi14 is None else loc.toString(m.rsi14, "f", 1),
            ]  # fmt: skip
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))
        text = strings.CMP_RANGE.format(
            start=f"{result.start:%d/%m/%Y}",
            end=f"{result.end:%d/%m/%Y}",
            sessions=len(result.performance),
        )
        if problems:
            text += "\n" + "\n".join(problems)
        self.status.setText(text)
