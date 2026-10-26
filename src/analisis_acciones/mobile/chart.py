"""Geometry of the phone's candlestick chart (pure numbers; the screen draws them).

Prices take the top 78 % of the area and volume the bottom 18 %. The 20 and 50
session simple moving averages are computed on the whole series before cutting
it, so the first visible values are real averages, not shortened ones.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from analisis_acciones.indicators.functions import sma

PERIODS = {"1M": 22, "3M": 66, "6M": 130, "1A": 260, "5A": 1300}
PRICE_SHARE = 0.78
VOLUME_SHARE = 0.18
MAX_CANDLES = 260  # beyond this, bars are merged (weekly) so each stays visible


@dataclass(frozen=True)
class Candle:
    x: float  # centre
    width: float
    top: float  # body
    bottom: float
    high: float  # wick
    low: float
    up: bool  # close >= open


@dataclass(frozen=True)
class ChartGeometry:
    width: float
    height: float
    candles: list[Candle] = field(default_factory=list)
    sma20: list[tuple[float, float]] = field(default_factory=list)
    sma50: list[tuple[float, float]] = field(default_factory=list)
    volume: list[tuple[float, float, float, bool]] = field(default_factory=list)  # x, w, top, up
    price_high: float = 0.0
    price_low: float = 0.0
    first: str = ""
    last: str = ""


def _visible(bars: pd.DataFrame, period: str) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    close = bars["close"].astype(float)
    s20, s50 = sma(close, 20), sma(close, 50)
    n = PERIODS.get(period, PERIODS["6M"])
    cut = bars.tail(n)
    s20, s50 = s20.loc[cut.index], s50.loc[cut.index]
    if len(cut) > MAX_CANDLES:
        groups = pd.DatetimeIndex(cut.index).to_period("W")
        agg = cut.groupby(groups).agg(open=("open", "first"), high=("high", "max"),
                                      low=("low", "min"), close=("close", "last"),
                                      volume=("volume", "sum"))  # fmt: skip
        last_days = cut.index.to_series().groupby(groups).last()
        agg.index = pd.DatetimeIndex(last_days.to_numpy())
        s20 = s20.groupby(groups).last().set_axis(agg.index)
        s50 = s50.groupby(groups).last().set_axis(agg.index)
        cut = agg
    return cut, s20, s50


def geometry(bars: pd.DataFrame, width: float, height: float, period: str = "6M") -> ChartGeometry:
    """Positions of every element for an area of ``width`` × ``height`` pixels."""
    if bars.empty or width <= 0 or height <= 0:
        return ChartGeometry(width, height)
    cut, s20, s50 = _visible(bars, period)
    n = len(cut)
    values = [float(v) for v in (*cut["high"], *cut["low"], *s20, *s50) if v == v]
    high, low = max(values), min(values)
    span = (high - low) or abs(high) * 0.01 or 1.0
    price_h = height * PRICE_SHARE
    vol_top = height * (1 - VOLUME_SHARE)
    vol_h = height * VOLUME_SHARE
    step = width / n
    body = max(step * 0.7, 1.0)

    def y(v: float) -> float:
        return (high - v) / span * price_h

    def x(i: int) -> float:
        return (i + 0.5) * step

    candles = []
    for i, (o, h, lo, c) in enumerate(zip(cut["open"], cut["high"], cut["low"], cut["close"],
                                          strict=True)):  # fmt: skip
        top, bottom = y(max(o, c)), y(min(o, c))
        candles.append(Candle(x(i), body, top, max(bottom, top + 1), y(h), y(lo), c >= o))
    volumes = cut["volume"].astype(float)
    vmax = float(volumes.max()) if volumes.notna().any() else 0.0
    volume = []
    if vmax > 0 and math.isfinite(vmax):
        for i, (v, candle) in enumerate(zip(volumes, candles, strict=True)):
            if v == v and v > 0:
                volume.append((x(i), body, vol_top + vol_h * (1 - v / vmax), candle.up))
    line20 = [(x(i), y(v)) for i, v in enumerate(s20) if v == v]
    line50 = [(x(i), y(v)) for i, v in enumerate(s50) if v == v]
    index = pd.DatetimeIndex(cut.index)
    return ChartGeometry(width, height, candles, line20, line50, volume, float(high), float(low),
                         f"{index[0]:%d/%m/%Y}", f"{index[-1]:%d/%m/%Y}")  # fmt: skip
