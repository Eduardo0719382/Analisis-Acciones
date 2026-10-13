from __future__ import annotations

import csv
import io

import numpy as np

from analisis_acciones.backtesting.engine import BacktestConfig, run_backtest
from analisis_acciones.backtesting.statistics import compute_statistics
from analisis_acciones.data.export import (
    backtest_summary_csv,
    backtest_trades_csv,
    bars_to_csv,
    equity_csv,
    safe_cell,
)
from analisis_acciones.indicators.registry import IndicatorConfig
from analisis_acciones.models.market import BarSeries, Interval
from tests.backtesting.test_engine import NO_COSTS, bars_from, signals_at
from tests.synthetic import synthetic_daily


def parse(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_formula_injection_neutralised() -> None:
    assert safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert safe_cell("AAPL") == "AAPL"
    assert safe_cell(-1.5) == -1.5  # numbers are untouched
    assert safe_cell(float("nan")) == ""


def test_bars_csv_with_indicators() -> None:
    bars = synthetic_daily(sessions=30)
    bars.iloc[3, bars.columns.get_loc("volume")] = np.nan
    series = BarSeries("TEST", Interval.D1, bars, "s")
    configs = [IndicatorConfig.create("sma", {"period": 5}), IndicatorConfig.create("macd"),
               IndicatorConfig("ema", {"period": 3}, visible=False)]  # fmt: skip
    rows = parse(bars_to_csv(series, configs))
    header = rows[0]
    assert header[:2] == ["date", "open"]
    assert "SMA (5)" in header and "MACD (12, 26, 9) Señal" in header
    assert not any(h.startswith("EMA") for h in header)  # hidden indicator not exported
    assert len(rows) == 31
    assert rows[1][0] == "2024-01-01"
    assert float(rows[5][header.index("SMA (5)")]) == round(bars["close"].iloc[:5].mean(), 6)
    assert rows[1][header.index("SMA (5)")] == ""  # warm-up: empty, not zero
    assert rows[4][header.index("volume")] == ""


def test_backtest_exports() -> None:
    bars = bars_from([10, 10, 12, 12, 10], [10, 11, 12, 11, 10])
    result = run_backtest(bars, signals_at(bars, [0, 3], [1]), NO_COSTS)
    stats = compute_statistics(result, bars)
    trades = parse(backtest_trades_csv(result, last_close=10.0))
    assert trades[0][0] == "entry_date" and len(trades) == 3
    assert trades[1][-1] == "closed" and trades[2][-1] == "open"
    summary = dict(parse(backtest_summary_csv(stats, {"symbol": "=EVIL()", "strategy": "x"}))[1:])
    assert summary["symbol"] == "'=EVIL()"
    assert summary["trades"] == "1"
    equity = parse(equity_csv(result))
    assert len(equity) == len(bars) + 1
    assert BacktestConfig().initial_capital == 10_000
