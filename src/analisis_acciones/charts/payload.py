"""Convert a BarSeries into the JSON payload drawn by chart.js. No Qt imports.

The payload carries only values present in the data: bars without volume get
no volume point (a gap), never a zero.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from analisis_acciones.models.market import BarSeries

INITIAL_VISIBLE_BARS = 180


def price_decimals(bars: pd.DataFrame) -> int:
    """2 decimals for normal prices, 4 for sub-dollar instruments."""
    if bars.empty:
        return 2
    low = float(bars["low"].min())
    return 4 if low < 1.0 else 2


def _finite(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def build_payload(series: BarSeries, title: str, up_color: str, down_color: str) -> dict[str, Any]:
    bars = series.bars
    candles: list[dict[str, Any]] = []
    volume: list[dict[str, Any]] = []
    volume_by_index: list[float | None] = []
    for ts, o, h, low, c, v in zip(
        pd.DatetimeIndex(bars.index),
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
        strict=True,
    ):
        day = ts.strftime("%Y-%m-%d")
        candles.append({"time": day, "open": float(o), "high": float(h), "low": float(low),
                        "close": float(c)})  # fmt: skip
        vol = _finite(v)
        volume_by_index.append(vol)
        if vol is None:
            volume.append({"time": day})  # whitespace point: no data, not zero
        else:
            colour = up_color if c >= o else down_color
            volume.append({"time": day, "value": vol, "color": colour + "80"})

    has_volume = any(v is not None for v in volume_by_index)
    return {
        "symbol": series.symbol,
        "title": title,
        "decimals": price_decimals(bars),
        "initialBars": INITIAL_VISIBLE_BARS,
        "candles": candles,
        "volume": volume if has_volume else None,
        "volumeByIndex": volume_by_index if has_volume else None,
    }
