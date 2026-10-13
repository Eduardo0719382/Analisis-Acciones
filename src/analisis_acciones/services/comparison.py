"""Compare several assets over a common period. Pure calculations (no Qt, no I/O).

* Performance is normalised to 0 % at the first common session, from closes.
* Volatility: annualised standard deviation of daily log returns (× √252).
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
    metrics = []
    for symbol, bars in closes_by_symbol.items():
        series = closes[symbol]
        window = bars.loc[closes.index]
        log_returns = pd.Series(np.log(series / series.shift(1)), index=series.index).dropna()
        volatility = (
            float(log_returns.std(ddof=1) * math.sqrt(TRADING_DAYS) * 100.0)
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
