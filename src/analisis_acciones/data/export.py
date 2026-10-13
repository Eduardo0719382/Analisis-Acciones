"""Export data to CSV text. Pure functions (no Qt, no file I/O).

Text cells that start with ``= + - @`` (or tab/CR) are prefixed with an
apostrophe so spreadsheet programs never interpret exported data as a formula
(CSV injection).
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from analisis_acciones.backtesting.engine import BacktestResult
from analisis_acciones.backtesting.statistics import Statistics
from analisis_acciones.indicators.registry import IndicatorConfig, compute
from analisis_acciones.models.market import BAR_COLUMNS, BarSeries

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    """Neutralise spreadsheet formulas in text cells; numbers pass through."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def _write(rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return buffer.getvalue()


def bars_to_csv(series: BarSeries, indicators: Sequence[IndicatorConfig] = ()) -> str:
    """Bars plus the values of the given (visible) indicators, one row per bar."""
    bars = series.bars
    columns: dict[str, pd.Series] = {c: bars[c] for c in BAR_COLUMNS}
    for config in indicators:
        if not config.visible:
            continue
        values = compute(config, bars)
        for output in config.spec.outputs:
            name = (
                config.label if len(config.spec.outputs) == 1 else f"{config.label} {output.label}"
            )
            columns[name] = values[output.key]
    header = ["date", *columns]
    rows: list[list[Any]] = [header]
    table = pd.DataFrame(columns)
    index = pd.DatetimeIndex(bars.index)
    for ts, row in zip(index, table.itertuples(index=False, name=None), strict=True):
        rows.append([ts.strftime("%Y-%m-%d"), *(_num(v) for v in row)])
    return _write(rows)


def _num(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, int) and not isinstance(value, bool):
        return value  # counts stay integers
    return round(float(value), 6)


def backtest_trades_csv(result: BacktestResult, last_close: float) -> str:
    rows: list[list[Any]] = [
        ["entry_date", "entry_price", "exit_date", "exit_price", "shares", "entry_commission",
         "exit_commission", "pnl", "return_pct", "status"],
    ]  # fmt: skip
    trades = list(result.trades) + ([result.open_trade] if result.open_trade else [])
    for t in trades:
        rows.append([
            t.entry_date.isoformat(), _num(t.entry_price),
            t.exit_date.isoformat() if t.exit_date else "",
            _num(t.exit_price) if t.exit_price is not None else "",
            t.shares, _num(t.entry_commission), _num(t.exit_commission),
            _num(t.pnl(last_close)),
            _num(t.return_pct) if t.return_pct is not None else "",
            "open" if t.is_open else "closed",
        ])  # fmt: skip
    return _write(rows)


def backtest_summary_csv(stats: Statistics, context: dict[str, Any]) -> str:
    """Key/value summary: run context (symbol, strategy, costs) and statistics."""
    rows: list[list[Any]] = [["field", "value"]]
    rows.extend([key, value] for key, value in context.items())
    for key, value in vars(stats).items():
        rows.append([key, "" if value is None else _num(value)])
    return _write(rows)


def equity_csv(result: BacktestResult) -> str:
    rows: list[list[Any]] = [["date", "equity"]]
    index = pd.DatetimeIndex(result.equity.index)
    for ts, value in zip(index, result.equity.to_numpy(), strict=True):
        rows.append([ts.strftime("%Y-%m-%d"), _num(value)])
    return _write(rows)
