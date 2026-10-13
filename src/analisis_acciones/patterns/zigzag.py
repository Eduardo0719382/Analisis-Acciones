"""ZigZag swing pivots.

A swing high is confirmed once price falls ``threshold`` (a fraction, e.g.
0.05) below it, and a swing low once price rises that much above it. Highs
use the bar's high and lows the bar's low. The extreme of the leg still in
progress is returned as the last pivot with ``confirmed=False``: it may still
move as new bars arrive.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from analisis_acciones.indicators.functions import atr

HIGH, LOW = "H", "L"


@dataclass(frozen=True)
class Pivot:
    index: int  # position in the bar frame
    price: float
    kind: str  # HIGH or LOW
    confirmed: bool = True


def zigzag(high: pd.Series | np.ndarray, low: pd.Series | np.ndarray,
           threshold: float) -> list[Pivot]:  # fmt: skip
    if not 0 < threshold < 1:
        raise ValueError("threshold must be a fraction between 0 and 1")
    hi = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    size = len(hi)
    pivots: list[Pivot] = []
    if size == 0:
        return pivots
    trend = 0  # 0 = undecided, 1 = rising leg, -1 = falling leg
    hi_i = lo_i = ext = 0
    for t in range(1, size):
        if trend == 0:
            if hi[t] > hi[hi_i]:
                hi_i = t
            if lo[t] < lo[lo_i]:
                lo_i = t
            if hi[hi_i] >= lo[lo_i] * (1 + threshold):
                if lo_i < hi_i:
                    pivots.append(Pivot(lo_i, float(lo[lo_i]), LOW))
                    trend, ext = 1, hi_i
                else:
                    pivots.append(Pivot(hi_i, float(hi[hi_i]), HIGH))
                    trend, ext = -1, lo_i
        elif trend == 1:
            if hi[t] > hi[ext]:
                ext = t
            elif lo[t] <= hi[ext] * (1 - threshold):
                pivots.append(Pivot(ext, float(hi[ext]), HIGH))
                trend, ext = -1, t
        else:
            if lo[t] < lo[ext]:
                ext = t
            elif hi[t] >= lo[ext] * (1 + threshold):
                pivots.append(Pivot(ext, float(lo[ext]), LOW))
                trend, ext = 1, t
    if trend == 1:
        pivots.append(Pivot(ext, float(hi[ext]), HIGH, confirmed=False))
    elif trend == -1:
        pivots.append(Pivot(ext, float(lo[ext]), LOW, confirmed=False))
    return pivots


def auto_threshold(bars: pd.DataFrame, multiple: float = 3.0, window: int = 100) -> float:
    """``multiple`` × the median ATR(14) as a fraction of the close, clamped to 2–30 %."""
    ratio = (atr(bars["high"], bars["low"], bars["close"], 14) / bars["close"]).tail(window)
    median = float(ratio.median()) if ratio.notna().any() else 0.02
    return float(min(max(multiple * median, 0.02), 0.30))
