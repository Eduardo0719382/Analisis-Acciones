"""Indicator formulas.

Conventions (documented because published implementations differ):

* SMA: arithmetic mean of the last ``n`` values.
* EMA: alpha = 2 / (n + 1), seeded with the SMA of the first ``n`` values;
  the first ``n - 1`` outputs are NaN.
* RSI (Wilder, 1978): the first average gain/loss is the simple mean of the
  first ``n`` changes, then Wilder smoothing avg = (prev * (n - 1) + x) / n.
  RSI = 100 when the average loss is 0 (and 50 when both averages are 0).
* MACD: EMA(fast) - EMA(slow); signal = EMA(signal) of the MACD line, seeded
  with the SMA of its first ``signal`` valid values; histogram = MACD - signal.
* Bollinger Bands: SMA(n) ± k · population standard deviation (ddof=0).
* ATR (Wilder): true range = max(high - low, |high - prev close|,
  |low - prev close|) (first bar: high - low); seeded with the SMA of the first
  ``n`` true ranges, then Wilder smoothing.

All inputs must be NaN-free price columns (guaranteed by data validation).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _check_period(n: int, name: str = "period") -> None:
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError(f"{name} must be a positive integer, got {n!r}")


def sma(values: pd.Series, n: int) -> pd.Series:
    _check_period(n)
    return values.rolling(window=n, min_periods=n).mean()


def _seeded_recursive(values: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """out[t] = alpha*x[t] + (1-alpha)*out[t-1], seeded with the mean of the first n valid x."""
    out = np.full(values.shape, np.nan)
    valid = np.flatnonzero(~np.isnan(values))
    if len(valid) < n:
        return out
    start = valid[0]
    seed_end = start + n - 1
    if np.isnan(values[start : seed_end + 1]).any():
        raise ValueError("gaps inside the seeding window")
    out[seed_end] = values[start : seed_end + 1].mean()
    for t in range(seed_end + 1, len(values)):
        out[t] = alpha * values[t] + (1.0 - alpha) * out[t - 1]
    return out


def ema(values: pd.Series, n: int) -> pd.Series:
    _check_period(n)
    result = _seeded_recursive(values.to_numpy(dtype="float64"), n, 2.0 / (n + 1))
    return pd.Series(result, index=values.index, name=values.name)


def _wilder(values: np.ndarray, n: int) -> np.ndarray:
    return _seeded_recursive(values, n, 1.0 / n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    _check_period(n)
    delta = close.diff().to_numpy(dtype="float64")  # delta[0] is NaN
    gains = np.where(np.isnan(delta), np.nan, np.maximum(delta, 0.0))
    losses = np.where(np.isnan(delta), np.nan, np.maximum(-delta, 0.0))
    avg_gain = _wilder(gains, n)
    avg_loss = _wilder(losses, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        out = 100.0 - 100.0 / (1.0 + rs)
    out = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, out)
    out = np.where((avg_loss == 0) & (avg_gain == 0), 50.0, out)
    out = np.where(np.isnan(avg_gain), np.nan, out)
    return pd.Series(out, index=close.index, name="rsi")


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    _check_period(fast, "fast")
    _check_period(slow, "slow")
    _check_period(signal, "signal")
    if fast >= slow:
        raise ValueError("fast period must be shorter than slow period")
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "histogram": line - sig}, index=close.index)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    _check_period(n)
    if not k > 0:
        raise ValueError("k must be positive")
    middle = sma(close, n)
    std = close.rolling(window=n, min_periods=n).std(ddof=0)
    return pd.DataFrame(
        {"upper": middle + k * std, "middle": middle, "lower": middle - k * std}, index=close.index
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1)
    return ranges.max(axis=1, skipna=True).rename("tr")


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    _check_period(n)
    tr = true_range(high, low, close).to_numpy(dtype="float64")
    return pd.Series(_wilder(tr, n), index=close.index, name="atr")
