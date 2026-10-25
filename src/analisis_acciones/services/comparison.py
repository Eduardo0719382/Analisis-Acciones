"""Compare several assets over a common period. Pure calculations (no Qt, no I/O).

* Performance is normalised to 0 % at the first common session, from closes.
* Volatility: annualised standard deviation of daily log returns (× √252, or × √365
  when the common sessions include weekends: assets quoted every day such as crypto).
* Max drawdown: largest peak-to-trough fall of the close over the period.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from analisis_acciones.backtesting.statistics import max_drawdown_pct
from analisis_acciones.indicators import functions as f
from analisis_acciones.models.errors import DataError

TRADING_DAYS = 252
CALENDAR_DAYS = 365
PERIODS: dict[str, int | None] = {"6M": 182, "1A": 365, "3A": 3 * 365, "5A": 5 * 365, "Máx": None}


@dataclass(frozen=True)
class AssetMetrics:
    symbol: str
    total_return_pct: float
    volatility_pct: float | None
    max_drawdown_pct: float
    avg_volume: float | None
    rsi14: float | None


@dataclass(frozen=True)
class ComparisonResult:
    start: date
    end: date
    performance: pd.DataFrame  # columns = symbols, values = % since start
    metrics: tuple[AssetMetrics, ...]


def compare(closes_by_symbol: dict[str, pd.DataFrame], period_days: int | None) -> ComparisonResult:
    if len(closes_by_symbol) < 1:
        raise DataError("nothing to compare", user_message="Indique al menos un activo.")
    closes = pd.concat(
        {symbol: bars["close"] for symbol, bars in closes_by_symbol.items()}, axis=1, join="inner"
    ).dropna()
    if period_days is not None and not closes.empty:
        cutoff = closes.index[-1] - pd.Timedelta(days=period_days)
        closes = closes[closes.index >= cutoff]
    if len(closes) < 2:
        raise DataError(
            "no common history",
            user_message="Los activos no tienen suficientes sesiones en común en ese periodo.",
        )
    performance = (closes / closes.iloc[0] - 1.0) * 100.0
    every_day = (pd.DatetimeIndex(closes.index[-60:]).weekday >= 5).sum() >= 2
    per_year = CALENDAR_DAYS if every_day else TRADING_DAYS
    metrics = []
    for symbol, bars in closes_by_symbol.items():
        series = closes[symbol]
        window = bars.loc[closes.index]
        log_returns = pd.Series(np.log(series / series.shift(1)), index=series.index).dropna()
        volatility = (
            float(log_returns.std(ddof=1) * math.sqrt(per_year) * 100.0)
            if len(log_returns) >= 2 else None
        )  # fmt: skip
        volume = window["volume"].dropna()
        rsi = f.rsi(bars["close"].loc[: closes.index[-1]], 14).iloc[-1]
        metrics.append(
            AssetMetrics(
                symbol=symbol,
                total_return_pct=float(performance[symbol].iloc[-1]),
                volatility_pct=volatility,
                max_drawdown_pct=max_drawdown_pct(series),
                avg_volume=float(volume.mean()) if not volume.empty else None,
                rsi14=None if pd.isna(rsi) else float(rsi),
            )
        )
    return ComparisonResult(
        start=pd.Timestamp(closes.index[0]).date(),
        end=pd.Timestamp(closes.index[-1]).date(),
        performance=performance,
        metrics=tuple(metrics),
    )


@dataclass(frozen=True)
class BenchmarkLine:
    """Benchmark closes rebased to the asset's close at the start of the window."""

    values: pd.Series  # aligned to the asset's bars from the window start (NaN where missing)
    asset_return_pct: float
    benchmark_return_pct: float
    start: pd.Timestamp

    @property
    def relative_pct(self) -> float:
        """Asset return minus benchmark return over the window (percentage points)."""
        return self.asset_return_pct - self.benchmark_return_pct


def benchmark_line(asset: pd.DataFrame, benchmark: pd.DataFrame,
                   window: int = 250) -> BenchmarkLine | None:  # fmt: skip
    """Rebase ``benchmark`` onto ``asset`` over the last ``window`` bars of the asset.

    Only bars present in both series are used; None when they share fewer than 2.
    """
    tail = asset["close"].tail(window)
    common = tail.index.intersection(benchmark.index)
    if len(common) < 2:
        return None
    start = common[0]
    bench = benchmark["close"].reindex(tail.index).loc[start:]
    base_asset = float(tail.loc[start])
    base_bench = float(benchmark.loc[start, "close"])
    rebased = bench / base_bench * base_asset
    last = common[-1]
    return BenchmarkLine(
        values=rebased,
        asset_return_pct=(float(tail.loc[last]) / base_asset - 1) * 100,
        benchmark_return_pct=(float(benchmark.loc[last, "close"]) / base_bench - 1) * 100,
        start=pd.Timestamp(start),
    )
