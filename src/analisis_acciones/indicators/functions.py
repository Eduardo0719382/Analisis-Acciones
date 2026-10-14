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


# ---------------------------------------------------------------------------
# Additional indicators (Phase 10)
# ---------------------------------------------------------------------------
def _midpoint(high: pd.Series, low: pd.Series, n: int) -> pd.Series:
    return (high.rolling(n, min_periods=n).max() + low.rolling(n, min_periods=n).min()) / 2.0


def ichimoku(
    high: pd.Series, low: pd.Series, close: pd.Series,
    tenkan: int = 9, kijun: int = 26, senkou_b: int = 52,
) -> pd.DataFrame:  # fmt: skip
    """Ichimoku lines computed **at each bar** (no displacement applied here).

    Conventionally Senkou A/B are drawn ``displacement`` bars ahead and Chikou
    (the close) ``displacement`` bars behind; the chart applies that shift.
    """
    for value, name in ((tenkan, "tenkan"), (kijun, "kijun"), (senkou_b, "senkou_b")):
        _check_period(value, name)
    tenkan_sen = _midpoint(high, low, tenkan)
    kijun_sen = _midpoint(high, low, kijun)
    return pd.DataFrame(
        {
            "tenkan": tenkan_sen,
            "kijun": kijun_sen,
            "senkou_a": (tenkan_sen + kijun_sen) / 2.0,
            "senkou_b": _midpoint(high, low, senkou_b),
            "chikou": close,
        },
        index=close.index,
    )


def _range_position(values: pd.Series, n: int) -> pd.Series:
    """100·(x − min) / (max − min) over ``n`` bars; 50 when the range is zero."""
    lowest = values.rolling(n, min_periods=n).min()
    highest = values.rolling(n, min_periods=n).max()
    span = highest - lowest
    out = 100.0 * (values - lowest) / span.where(span != 0)
    return out.where(~((span == 0) & highest.notna()), 50.0)


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, smooth: int = 3, d: int = 3
) -> pd.DataFrame:
    """Slow stochastic: %K = SMA(raw %K, smooth), %D = SMA(%K, d). Flat range -> 50."""
    for value, name in ((k, "k"), (smooth, "smooth"), (d, "d")):
        _check_period(value, name)
    lowest = low.rolling(k, min_periods=k).min()
    highest = high.rolling(k, min_periods=k).max()
    span = highest - lowest
    raw = (100.0 * (close - lowest) / span.where(span != 0)).where(
        ~((span == 0) & highest.notna()), 50.0
    )
    k_line = sma(raw, smooth)
    return pd.DataFrame({"k": k_line, "d": sma(k_line, d)}, index=close.index)


def stoch_rsi(close: pd.Series, rsi_period: int = 14, stoch_period: int = 14,
              smooth: int = 3, d: int = 3) -> pd.DataFrame:  # fmt: skip
    """Stochastic of the RSI, 0–100. Flat RSI range -> 50."""
    for value, name in ((stoch_period, "stoch"), (smooth, "smooth"), (d, "d")):
        _check_period(value, name)
    position = _range_position(rsi(close, rsi_period), stoch_period)
    k_line = sma(position, smooth)
    return pd.DataFrame({"k": k_line, "d": sma(k_line, d)}, index=close.index)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.DataFrame:
    """Wilder's ADX with +DI/−DI. Directional movement starts at the second bar."""
    _check_period(n)
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0).astype(float)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0).astype(float)
    plus_dm[0] = minus_dm[0] = np.nan  # no previous bar
    tr = true_range(high, low, close).to_numpy(dtype="float64", copy=True)
    tr[0] = np.nan
    sm_tr = _wilder(tr, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * _wilder(plus_dm.astype(float), n) / sm_tr
        minus_di = 100.0 * _wilder(minus_dm.astype(float), n) / sm_tr
        total = plus_di + minus_di
        dx = np.where(total > 0, 100.0 * np.abs(plus_di - minus_di) / total, 0.0)
    dx = np.where(np.isnan(plus_di) | np.isnan(minus_di), np.nan, dx)
    return pd.DataFrame(
        {"adx": _wilder(dx, n), "plus_di": plus_di, "minus_di": minus_di}, index=close.index
    )


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-balance volume starting at 0. Unknown volume makes the running total unknown."""
    direction = np.sign(close.diff().to_numpy(dtype=float))
    flow = direction * volume.to_numpy(dtype=float)
    flow[0] = 0.0 if pd.notna(volume.iloc[0]) else np.nan
    return pd.Series(np.cumsum(flow), index=close.index, name="obv")


def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 10,
               multiplier: float = 3.0) -> pd.DataFrame:  # fmt: skip
    """Supertrend on Wilder's ATR: the line and its direction (+1 up, −1 down)."""
    _check_period(n)
    if not multiplier > 0:
        raise ValueError("multiplier must be positive")
    atr_values = atr(high, low, close, n).to_numpy()
    mid = ((high + low) / 2.0).to_numpy()
    c = close.to_numpy(dtype=float)
    size = len(c)
    upper = np.full(size, np.nan)
    lower = np.full(size, np.nan)
    trend = np.zeros(size)
    line = np.full(size, np.nan)
    for t in range(size):
        if np.isnan(atr_values[t]):
            continue
        basic_upper = mid[t] + multiplier * atr_values[t]
        basic_lower = mid[t] - multiplier * atr_values[t]
        if t == 0 or np.isnan(upper[t - 1]):
            upper[t], lower[t], trend[t] = basic_upper, basic_lower, 1
        else:
            upper[t] = basic_upper if (basic_upper < upper[t - 1] or c[t - 1] > upper[t - 1]) \
                else upper[t - 1]  # fmt: skip
            lower[t] = basic_lower if (basic_lower > lower[t - 1] or c[t - 1] < lower[t - 1]) \
                else lower[t - 1]  # fmt: skip
            if trend[t - 1] == 1:
                trend[t] = -1 if c[t] < lower[t] else 1
            else:
                trend[t] = 1 if c[t] > upper[t] else -1
        line[t] = lower[t] if trend[t] == 1 else upper[t]
    direction = np.where(np.isnan(line), np.nan, trend)
    return pd.DataFrame({"value": line, "direction": direction}, index=close.index)


# ---------------------------------------------------------------------------
# VWAP, automatic Fibonacci, volume profile
# ---------------------------------------------------------------------------
def _has_time_of_day(index: pd.Index) -> bool:
    idx = pd.DatetimeIndex(index)
    return len(idx) > 0 and bool((idx != idx.normalize()).any())


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
         n: int = 20) -> pd.Series:  # fmt: skip
    """Volume-weighted average of the typical price (H+L+C)/3.

    Intraday bars: cumulative from each session's first bar (resets daily).
    Daily and longer bars: rolling over the last ``n`` bars. Bars without
    volume make the value unknown rather than being treated as zero volume.
    """
    _check_period(n)
    typical = (high + low + close) / 3.0
    weighted = typical * volume
    if _has_time_of_day(close.index):
        day = pd.DatetimeIndex(close.index).normalize()
        num = weighted.groupby(day).cumsum()
        den = volume.groupby(day).cumsum()
    else:
        num = weighted.rolling(n, min_periods=n).sum()
        den = volume.rolling(n, min_periods=n).sum()
    out = num / den.where(den > 0)
    return out.rename("vwap")


FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)


def auto_fibonacci(high: pd.Series, low: pd.Series, threshold_pct: float = 0.0) -> pd.DataFrame:
    """Retracement levels of the latest swing (ZigZag), drawn from the swing's start.

    The swing runs from the second-to-last pivot (100 %) to the last one (0 %),
    which may still be extending. A threshold of 0 picks it from volatility.
    This is a display aid built from the whole series, not a signal.
    """
    from analisis_acciones.patterns.zigzag import auto_threshold, zigzag  # avoid import cycle

    bars = pd.DataFrame({"high": high, "low": low, "close": (high + low) / 2})
    threshold = threshold_pct / 100 if threshold_pct > 0 else auto_threshold(bars)
    pivots = zigzag(high, low, threshold)
    columns = {f"f{round(r * 1000):04d}": pd.Series(np.nan, index=high.index) for r in FIB_RATIOS}
    if len(pivots) < 2:
        return pd.DataFrame(columns)
    start, end = pivots[-2], pivots[-1]
    for ratio, key in zip(FIB_RATIOS, columns, strict=True):
        level = end.price - ratio * (end.price - start.price)
        columns[key].iloc[start.index :] = level
    return pd.DataFrame(columns)


def volume_profile(high: pd.Series, low: pd.Series, volume: pd.Series, bins: int = 24,
                   value_area: float = 0.7) -> dict[str, object]:  # fmt: skip
    """Volume traded per price band. Each bar's volume is spread evenly over its range.

    Returns the bands (low, high, volume), the point of control (band with
    most volume) and the value area: the bands around it holding ``value_area``
    of the volume. Bars without volume are ignored.
    """
    if bins < 2:
        raise ValueError("bins must be at least 2")
    hi = high.to_numpy(dtype=float)
    lo = low.to_numpy(dtype=float)
    vol = volume.to_numpy(dtype=float)
    ok = np.isfinite(hi) & np.isfinite(lo) & np.isfinite(vol) & (vol > 0)
    hi, lo, vol = hi[ok], lo[ok], vol[ok]
    if len(vol) == 0:
        return {"bands": [], "poc": None, "val": None, "vah": None}
    top, bottom = float(hi.max()), float(lo.min())
    if top <= bottom:
        top = bottom * 1.001 + 1e-9
    edges = np.linspace(bottom, top, bins + 1)
    totals = np.zeros(bins)
    for h, low_, v in zip(hi, lo, vol, strict=True):
        if h <= low_:
            idx = min(int(np.searchsorted(edges, h, side="right")) - 1, bins - 1)
            totals[max(idx, 0)] += v
            continue
        overlap = np.clip(np.minimum(edges[1:], h) - np.maximum(edges[:-1], low_), 0, None)
        totals += v * overlap / (h - low_)
    poc = int(np.argmax(totals))
    target = value_area * totals.sum()
    lo_i = hi_i = poc
    covered = totals[poc]
    while covered < target and (lo_i > 0 or hi_i < bins - 1):
        below = totals[lo_i - 1] if lo_i > 0 else -1.0
        above = totals[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += totals[hi_i]
        else:
            lo_i -= 1
            covered += totals[lo_i]
    bands = [(float(edges[i]), float(edges[i + 1]), float(totals[i])) for i in range(bins)]
    return {"bands": bands, "poc": float((edges[poc] + edges[poc + 1]) / 2),
            "val": float(edges[lo_i]), "vah": float(edges[hi_i + 1])}  # fmt: skip
