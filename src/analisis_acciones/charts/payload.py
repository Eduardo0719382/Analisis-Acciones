"""Convert a BarSeries into the JSON payload drawn by chart.js. No Qt imports.

The payload carries only values present in the data: bars without volume get
no volume point (a gap), never a zero.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from analisis_acciones.indicators.registry import IndicatorConfig, compute
from analisis_acciones.models.market import BarSeries

logger = logging.getLogger(__name__)

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


def future_times(bars: pd.DataFrame, count: int) -> list[str]:
    """Approximate dates of the next ``count`` bars (used to draw shifted lines ahead).

    Daily series step over weekends (holidays are not modelled); weekly and
    monthly series step by the typical gap between their last bars.
    """
    if count <= 0 or bars.empty:
        return []
    index = pd.DatetimeIndex(bars.index)
    last = index[-1]
    gaps = index.to_series().diff().dropna().dt.days.tail(20)
    typical = float(gaps.median()) if not gaps.empty else 1.0
    if typical <= 4:
        dates = pd.bdate_range(last + pd.Timedelta(days=1), periods=count)
    elif typical <= 10:
        dates = pd.date_range(last + pd.Timedelta(days=7), periods=count, freq="7D")
    else:
        dates = pd.date_range(last, periods=count + 1, freq="MS")[1:]
    return [d.strftime("%Y-%m-%d") for d in dates]


def _points(times: list[str], values: list[float | None], style: str, up_color: str,
            down_color: str) -> list[dict[str, Any]]:  # fmt: skip
    if style == "histogram":
        up, down = up_color + "99", down_color + "99"
        return [
            {"time": t, "value": v, "color": up if v >= 0 else down} if v is not None
            else {"time": t}  # warm-up: no point, not zero
            for t, v in zip(times, values, strict=True)
        ]  # fmt: skip
    return [
        {"time": t, "value": v} if v is not None else {"time": t}
        for t, v in zip(times, values, strict=True)
    ]


def _shifted_points(raw: list[float | None], times: list[str], future: list[str],
                    shift: int) -> list[dict[str, Any]]:  # fmt: skip
    """Value computed at bar i drawn at bar i + shift (beyond the last bar: future dates)."""
    all_times = times + future
    points: list[dict[str, Any]] = []
    for i, value in enumerate(raw):
        j = i + shift
        if j < 0 or j >= len(all_times):
            continue
        points.append(
            {"time": all_times[j]} if value is None else {"time": all_times[j], "value": value}
        )
    return points


def build_indicator_payload(
    configs: list[IndicatorConfig],
    bars: pd.DataFrame,
    up_color: str,
    down_color: str,
    level_color: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Chart payload for the visible indicators, plus labels of any that failed.

    A failing indicator is skipped (and reported) instead of breaking the chart.
    """
    times = pd.DatetimeIndex(bars.index).strftime("%Y-%m-%d").tolist()
    decimals = price_decimals(bars)
    payload: list[dict[str, Any]] = []
    failed: list[str] = []
    for config in configs:
        if not config.visible:
            continue
        spec = config.spec
        try:
            values = compute(config, bars)
        except (ValueError, ArithmeticError):
            logger.exception("Indicator %s failed", config.label)
            failed.append(config.label)
            continue
        outputs = []
        for output in spec.outputs:
            column = values[output.key].to_numpy(dtype="float64")
            finite = np.isfinite(column)
            raw: list[float | None] = [
                v if ok else None for v, ok in zip(column.tolist(), finite.tolist(), strict=True)
            ]
            shift = output.shift(config.params)
            if shift:
                points = _shifted_points(raw, times, future_times(bars, abs(shift)), shift)
                # Legend shows, at each bar, the value drawn at that bar's time.
                by_index = [
                    raw[i - shift] if 0 <= i - shift < len(raw) else None for i in range(len(raw))
                ]
            else:
                by_index = raw
                points = _points(times, by_index, output.style, up_color, down_color)
                if output.color_sign is not None:
                    signs = values[output.color_sign].to_numpy(dtype="float64")
                    for point, sign in zip(points, signs, strict=True):
                        if "value" in point:
                            point["color"] = up_color if sign > 0 else down_color
            outputs.append(
                {
                    "key": output.key,
                    "label": output.label,
                    "style": output.style,
                    "color": output.color,
                    "points": points,
                    "byIndex": by_index,
                }
            )
        payload.append({
            "uid": config.uid,
            "label": config.label,
            "placement": spec.placement,
            "decimals": spec.decimals if spec.decimals is not None
            else (2 if spec.id == "rsi" else decimals),
            "levels": list(spec.levels),
            "levelColor": level_color,
            "outputs": outputs,
            "fills": [
                {"a": a, "b": b, "upColor": up_color + "33", "downColor": down_color + "33"}
                for a, b in spec.fills
            ],
        })  # fmt: skip
    return payload, failed
