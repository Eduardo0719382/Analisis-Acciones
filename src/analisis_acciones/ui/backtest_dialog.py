"""Backtesting window: choose a strategy and costs, run it on the series on the chart."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import shiboken6
from PySide6.QtCore import QLocale
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.backtesting.engine import BacktestConfig, BacktestResult, run_backtest
from analisis_acciones.backtesting.statistics import Statistics, compute_statistics
from analisis_acciones.data.export import backtest_summary_csv, backtest_trades_csv, equity_csv
from analisis_acciones.data.freshness import is_crypto
from analisis_acciones.models.errors import AppError, user_message_for
from analisis_acciones.models.market import BarSeries
from analisis_acciones.services.portfolio_report import qty
from analisis_acciones.strategies.registry import (
    STRATEGIES,
    STRATEGY_REGISTRY,
    validate_strategy_params,
)
from analisis_acciones.ui import strings
from analisis_acciones.ui.equity_chart import EquityChart
from analisis_acciones.ui.theme import ThemeTokens
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestOutcome:
    result: BacktestResult
    stats: Statistics
    buy_and_hold: pd.Series
    #: The same strategy without the rule under test (e.g. the exhaustion exit), if any.
    reference: BacktestResult | None = None
    reference_stats: Statistics | None = None


def run_strategy(series: BarSeries, strategy_id: str, params: dict[str, float],
                 config: BacktestConfig) -> BacktestOutcome:  # fmt: skip
    spec = STRATEGY_REGISTRY[strategy_id]
    clean = validate_strategy_params(spec, params)
    bars = series.bars
    result = run_backtest(bars, spec.signals(bars, clean), config)
    stats = compute_statistics(result, bars)
    # Reference: invested at the first open, no costs.
    buy_and_hold = bars["close"] / float(bars["open"].iloc[0]) * config.initial_capital
    if spec.reference is None:
        return BacktestOutcome(result, stats, buy_and_hold)
    reference = run_backtest(bars, spec.reference(bars, clean), config)
    return BacktestOutcome(result, stats, buy_and_hold, reference,
                           compute_statistics(reference, bars))  # fmt: skip


def reference_color(tokens: ThemeTokens) -> str:
    """First colour of the validated reference palette, light or dark step."""
    return "#d95926" if QColor(tokens.background).lightness() < 128 else "#eb6834"


class BacktestDialog(QDialog):
    def __init__(self, series: BarSeries, title: str, tokens: ThemeTokens,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._series = series
        self._tokens = tokens
        self._workers: set[Worker] = set()
        self.outcome: BacktestOutcome | None = None
        self.setWindowTitle(strings.BT_TITLE.format(title=title))
        self.resize(980, 720)

        # Settings
        self.strategy = QComboBox()
        for spec in STRATEGIES:
            self.strategy.addItem(spec.name, spec.id)
        self.strategy.currentIndexChanged.connect(self._rebuild_params)
        self.params_form = QFormLayout()
        self.rules_label = QLabel()
        self.rules_label.setObjectName("detailsSource")
        self.rules_label.setWordWrap(True)
        self.capital = QDoubleSpinBox()
        self.capital.setRange(1, 1e9)
        self.capital.setDecimals(0)
        self.capital.setValue(10_000)
        self.commission = QDoubleSpinBox()
        self.commission.setRange(0, 5)
        self.commission.setDecimals(3)
        self.commission.setValue(0.1)
        self.commission.setSuffix(" %")
        self.fixed = QDoubleSpinBox()
        self.fixed.setRange(0, 1000)
        self.fixed.setDecimals(2)
        self.slippage = QDoubleSpinBox()
        self.slippage.setRange(0, 5)
        self.slippage.setDecimals(3)
        self.slippage.setValue(0.05)
        self.slippage.setSuffix(" %")
        costs = QFormLayout()
        costs.addRow(strings.BT_CAPITAL, self.capital)
        costs.addRow(strings.BT_COMMISSION, self.commission)
        costs.addRow(strings.BT_FIXED, self.fixed)
        costs.addRow(strings.BT_SLIPPAGE, self.slippage)
        self.run_button = QPushButton(strings.BT_RUN)
        self.run_button.clicked.connect(self.run)
        self.export_button = QPushButton(strings.BT_EXPORT)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(lambda: self.export())
        self.error = QLabel()
        self.error.setObjectName("panelEmpty")
        self.error.setProperty("error", True)
        self.error.setWordWrap(True)

        strategy_box = QGroupBox(strings.BT_STRATEGY)
        strategy_layout = QVBoxLayout(strategy_box)
        strategy_layout.addWidget(self.strategy)
        strategy_layout.addLayout(self.params_form)
        strategy_layout.addWidget(self.rules_label)
        costs_box = QGroupBox(strings.BT_COSTS)
        costs_box.setLayout(costs)
        settings = QVBoxLayout()
        settings.addWidget(strategy_box)
        settings.addWidget(costs_box)
        settings.addWidget(self.run_button)
        settings.addWidget(self.export_button)
        settings.addWidget(self.error)
        timing = QLabel(strings.BT_TIMING)
        timing.setObjectName("detailsSource")
        timing.setWordWrap(True)
        settings.addWidget(timing)
        settings.addStretch(1)

        # Results
        self.stats_grid = QGridLayout()
        self.stat_labels: dict[str, QLabel] = {}
        for i, (key, label) in enumerate(strings.BT_STATS):
            caption = QLabel(label)
            caption.setObjectName("detailsCaption")
            value = QLabel("—")
            value.setObjectName("detailsValue")
            self.stats_grid.addWidget(caption, i // 3, (i % 3) * 2)
            self.stats_grid.addWidget(value, i // 3, (i % 3) * 2 + 1)
            self.stat_labels[key] = value
        self.chart = EquityChart(tokens)
        self.trades = QTableWidget(0, 6)
        self.trades.setHorizontalHeaderLabels(strings.BT_TRADE_COLUMNS)
        self.trades.verticalHeader().setVisible(False)
        self.trades.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trades.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.notes = QLabel()
        self.notes.setObjectName("detailsSource")
        self.notes.setWordWrap(True)
        disclaimer = QLabel(strings.BT_DISCLAIMER)
        disclaimer.setObjectName("detailsSource")
        disclaimer.setWordWrap(True)

        results = QVBoxLayout()
        results.addLayout(self.stats_grid)
        results.addWidget(self.chart, stretch=2)
        results.addWidget(self.trades, stretch=1)
        results.addWidget(self.notes)
        results.addWidget(disclaimer)

        body = QHBoxLayout(self)
        left = QWidget()
        left.setLayout(settings)
        left.setMaximumWidth(330)
        body.addWidget(left)
        body.addLayout(results, stretch=1)
        self._rebuild_params()

    # Parameters --------------------------------------------------------------
    def _rebuild_params(self, _index: int = 0) -> None:
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self.editors: dict[str, QSpinBox | QDoubleSpinBox] = {}
        spec = STRATEGY_REGISTRY[str(self.strategy.currentData())]
        for p in spec.params:
            editor: QSpinBox | QDoubleSpinBox
            if p.kind == "int":
                editor = QSpinBox()
                editor.setRange(int(p.minimum), int(p.maximum))
                editor.setValue(int(p.default))
            else:
                editor = QDoubleSpinBox()
                editor.setRange(float(p.minimum), float(p.maximum))
                editor.setValue(float(p.default))
            editor.valueChanged.connect(self._update_rules)
            self.editors[p.key] = editor
            self.params_form.addRow(p.label, editor)
        self._update_rules()

    def _params(self) -> dict[str, float]:
        return {k: float(e.value()) for k, e in self.editors.items()}

    def _update_rules(self) -> None:
        spec = STRATEGY_REGISTRY[str(self.strategy.currentData())]
        entry, exit_ = spec.describe(self._params())
        self.rules_label.setText(f"{entry}\n{exit_}")

    # Running -----------------------------------------------------------------
    def run(self) -> None:
        self.error.setText("")
        config = BacktestConfig(self.capital.value(), self.commission.value(),
                                self.fixed.value(), self.slippage.value(),
                                fractional=is_crypto(self._series.symbol))  # fmt: skip
        strategy_id, params, series = str(self.strategy.currentData()), self._params(), self._series
        self.run_button.setEnabled(False)

        def done(outcome: BacktestOutcome) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.show_outcome(outcome)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.error.setText(user_message_for(exc) if isinstance(exc, AppError)
                                   else strings.BT_FAILED)  # fmt: skip

        worker = start_worker(lambda: run_strategy(series, strategy_id, params, config), done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def export(self, base: Path | None = None) -> list[Path]:
        """Write trades, summary and equity CSV files next to ``base``."""
        if self.outcome is None:
            return []
        if base is None:
            chosen, _ = QFileDialog.getSaveFileName(
                self, strings.BT_EXPORT, f"backtest_{self._series.symbol.replace(':', '_')}.csv",
                strings.EXPORT_CSV_FILTER,
            )  # fmt: skip
            if not chosen:
                return []
            base = Path(chosen)
        stem = base.with_suffix("")
        outcome = self.outcome
        spec = STRATEGY_REGISTRY[str(self.strategy.currentData())]
        entry, exit_ = spec.describe(self._params())
        cfg = outcome.result.config
        context = {
            "symbol": self._series.symbol, "interval": self._series.interval.value,
            "from": str(self._series.first_date), "to": str(self._series.last_date),
            "strategy": spec.name, "entry_rule": entry, "exit_rule": exit_,
            "commission_pct": cfg.commission_pct, "commission_fixed": cfg.commission_fixed,
            "slippage_pct": cfg.slippage_pct,
        }  # fmt: skip
        if outcome.reference_stats is not None:
            context["reference"] = spec.reference_name
            context["reference_return_pct"] = round(outcome.reference_stats.total_return_pct, 4)
            context["reference_max_drawdown_pct"] = round(
                outcome.reference_stats.max_drawdown_pct, 4
            )
        last_close = float(self._series.bars["close"].iloc[-1])
        files = {
            Path(f"{stem}_operaciones.csv"): backtest_trades_csv(outcome.result, last_close),
            Path(f"{stem}_resumen.csv"): backtest_summary_csv(outcome.stats, context),
            Path(f"{stem}_capital.csv"): equity_csv(outcome.result),
        }
        try:
            for path, text in files.items():
                path.write_text(text, encoding="utf-8")
        except OSError as exc:
            self.error.setText(strings.EXPORT_FAILED.format(error=exc))
            return []
        self.notes.setText(strings.BT_EXPORT_DONE.format(files=", ".join(p.name for p in files)))
        return list(files)

    def show_outcome(self, outcome: BacktestOutcome) -> None:
        self.outcome = outcome
        self.export_button.setEnabled(True)
        loc = QLocale()
        s = outcome.stats

        def money(v: float) -> str:
            return loc.toString(v, "f", 2)

        def pct(v: float | None) -> str:
            return "—" if v is None else f"{'+' if v > 0 else ''}{loc.toString(v, 'f', 2)} %"

        values = {
            "initial": money(s.initial_capital),
            "final": money(s.final_equity),
            "return": pct(s.total_return_pct),
            "trades": str(s.trades),
            "winning": str(s.winning),
            "losing": str(s.losing),
            "win_rate": pct(s.win_rate_pct).replace("+", ""),
            "drawdown": pct(s.max_drawdown_pct),
            "profit_factor": "—"
            if s.profit_factor is None
            else loc.toString(s.profit_factor, "f", 2),
            "buy_hold": pct(s.buy_and_hold_pct),
            "exposure": pct(s.exposure_pct).replace("+", ""),
            "commissions": money(s.commissions),
        }
        for key, text in values.items():
            self.stat_labels[key].setText(text)

        t = self._tokens
        lines = [
            (strings.BT_EQUITY, outcome.result.equity, t.accent),
            (strings.BT_BUY_HOLD, outcome.buy_and_hold, t.text_muted),
        ]
        spec = STRATEGY_REGISTRY[str(self.strategy.currentData())]
        if outcome.reference is not None:
            lines.append((spec.reference_name, outcome.reference.equity, reference_color(t)))
        self.chart.set_series(lines)

        trades = list(outcome.result.trades)
        rows = trades + ([outcome.result.open_trade] if outcome.result.open_trade else [])
        self.trades.setRowCount(len(rows))
        last_close = float(self._series.bars["close"].iloc[-1])
        for r, trade in enumerate(rows):
            pnl = trade.pnl(last_close)
            cells = [
                f"{trade.entry_date:%d/%m/%Y}", money(trade.entry_price),
                f"{trade.exit_date:%d/%m/%Y}" if trade.exit_date else strings.BT_OPEN,
                money(trade.exit_price) if trade.exit_price is not None else money(last_close),
                qty(trade.shares), money(pnl),
            ]  # fmt: skip
            for c, text in enumerate(cells):
                self.trades.setItem(r, c, QTableWidgetItem(text))
        notes = list(outcome.result.notes)
        if outcome.result.open_trade:
            notes.append(strings.BT_OPEN_NOTE)
        if s.profit_factor is None and s.trades:
            notes.append(strings.BT_PF_UNDEFINED)
        ref = outcome.reference_stats
        if ref is not None:
            diff = s.total_return_pct - ref.total_return_pct
            notes.append(strings.BT_REFERENCE.format(
                name=spec.reference_name, ret=pct(ref.total_return_pct), trades=ref.trades,
                drawdown=pct(ref.max_drawdown_pct), diff=pct(diff),
                dd_diff=pct(s.max_drawdown_pct - ref.max_drawdown_pct),
            ))  # fmt: skip
        self.notes.setText("\n".join(notes))
