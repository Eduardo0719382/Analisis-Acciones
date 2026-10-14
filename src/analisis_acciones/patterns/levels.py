"""Automatic support and resistance levels from swing pivots.

Swing highs and lows (ZigZag) lying in a zone no wider than 2 × ``tolerance``
are grouped; a group touched at least ``min_touches`` times becomes a
level. Highs and lows are grouped together because a broken resistance often
acts as support later (and vice versa). A level below the last close is
reported as support, one above it as resistance.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analisis_acciones.indicators.functions import atr
from analisis_acciones.patterns.zigzag import Pivot


@dataclass(frozen=True)
class Level:
    price: float
    touches: int
    first: int  # bar index of the first touch
    last: int  # bar index of the latest touch
    low: float  # zone bounds (lowest and highest touching pivot)
    high: float

    def role(self, close: float) -> str:
        return "support" if self.price < close else "resistance"


def price_tolerance(bars: pd.DataFrame, window: int = 100) -> float:
    """Median ATR(14)/close of the last ``window`` bars, clamped to 0.5–5 %."""
    ratio = (atr(bars["high"], bars["low"], bars["close"], 14) / bars["close"]).tail(window)
    median = float(ratio.median()) if ratio.notna().any() else 0.01
    return float(min(max(median, 0.005), 0.05))


def support_resistance(pivots: list[Pivot], close: float, tolerance: float,
                       min_touches: int = 2, per_side: int = 4) -> list[Level]:  # fmt: skip
    """Nearest ``per_side`` levels below and above ``close``, ordered by price."""
    if not pivots:
        return []
    ordered = sorted(pivots, key=lambda p: p.price)
    groups: list[list[Pivot]] = [[ordered[0]]]
    for pivot in ordered[1:]:
        group = groups[-1]
        # Measured from the group's lowest price so zones cannot chain wider
        # than 2 × tolerance.
        if pivot.price - group[0].price <= 2 * tolerance * group[0].price:
            group.append(pivot)
        else:
            groups.append([pivot])
    levels = [
        Level(
            price=sum(p.price for p in g) / len(g),
            touches=len(g),
            first=min(p.index for p in g),
            last=max(p.index for p in g),
            low=min(p.price for p in g),
            high=max(p.price for p in g),
        )
        for g in groups
        if len(g) >= min_touches
    ]
    below = sorted((lv for lv in levels if lv.price < close), key=lambda lv: -lv.price)
    above = sorted((lv for lv in levels if lv.price >= close), key=lambda lv: lv.price)
    return sorted(below[:per_side] + above[:per_side], key=lambda lv: lv.price)
