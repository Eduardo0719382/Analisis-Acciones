"""Build chart overlay items (plain dicts for chart.js). No Qt imports."""

from __future__ import annotations

from typing import Any

from analisis_acciones.charts.payload import ChartTime
from analisis_acciones.forecast.projection import Projection
from analisis_acciones.patterns.chart_patterns import ChartPattern
from analisis_acciones.patterns.elliott import CORRECTION, WaveCount
from analisis_acciones.patterns.levels import Level
from analisis_acciones.patterns.zigzag import HIGH

# Lightweight Charts LineStyle values.
SOLID, DOTTED, DASHED, LARGE_DASHED = 0, 1, 2, 3

_BAND_STYLE = {
    "p95": (DOTTED, "P95"),
    "p75": (DASHED, "P75"),
    "p50": (LARGE_DASHED, "P50"),
    "p25": (DASHED, "P25"),
    "p05": (DOTTED, "P5"),
}


def projection_overlay(projection: Projection, past_dates: list[ChartTime],
                       future_dates: list[ChartTime],
                       color: str, median_color: str) -> list[dict[str, Any]]:  # fmt: skip
    """One line per band.

    A fan (volatility cone) opens from the last close; a regression channel is
    also drawn over the bars it was fitted on, then continues into the future.
    ``past_dates`` are the dates of the bars on the chart (at least the last one).
    """
    items = []
    dates = future_dates[: projection.horizon]
    for band, (style, title) in _BAND_STYLE.items():
        values = projection.bands[band][: len(dates)]
        fitted = projection.fitted.get(band, [])
        if fitted and len(past_dates) >= len(fitted):
            points = [{"time": d, "value": v}
                      for d, v in zip(past_dates[-len(fitted):], fitted, strict=True)]  # fmt: skip
        else:
            points = [{"time": past_dates[-1], "value": projection.base_price}]
        points += [{"time": d, "value": v} for d, v in zip(dates, values, strict=True)]
        items.append({
            "kind": "line", "points": points, "style": style, "title": title,
            "color": median_color if band == "p50" else color,
            "width": 2 if band == "p50" else 1, "lastValue": True,
        })  # fmt: skip
    return items


def elliott_overlay(counts: list[WaveCount], dates: list[ChartTime], selected: WaveCount | None,
                    colors: dict[str, str]) -> list[dict[str, Any]]:  # fmt: skip
    """Lines through each count's pivots with wave labels; levels for the selected count.

    ``colors`` keys: ``up``, ``down`` (completed impulses by direction),
    ``correction``, ``current`` and ``invalid``.
    """
    items: list[dict[str, Any]] = []
    for count in counts:
        if count.current:
            color = colors["current"]
        elif count.kind == CORRECTION:
            color = colors["correction"]
        else:
            color = colors["up"] if count.direction > 0 else colors["down"]
        points = [{"time": dates[p.index], "value": p.price} for p in count.pivots]
        labels = [
            {"time": dates[p.index], "text": text,
             "position": "aboveBar" if p.kind == HIGH else "belowBar"}
            for p, text in zip(count.pivots, count.labels, strict=True) if text
        ]  # fmt: skip
        items.append({
            "kind": "line", "points": points, "labels": labels, "color": color,
            "style": DASHED if count.current else SOLID,
            "width": 2 if count is selected else 1,
        })  # fmt: skip
    if selected is not None:
        for target in selected.targets:
            items.append({"kind": "level", "price": target.price, "color": colors["current"],
                          "style": DASHED, "title": target.label})  # fmt: skip
        if selected.invalidation is not None:
            items.append({"kind": "level", "price": selected.invalidation,
                          "color": colors["invalid"], "style": DOTTED,
                          "title": "Invalidación"})  # fmt: skip
    return items


def levels_overlay(levels: list[Level], close: float, support_color: str,
                   resistance_color: str) -> list[dict[str, Any]]:  # fmt: skip
    return [
        {"kind": "level", "price": lv.price, "style": DASHED,
         "color": support_color if lv.role(close) == "support" else resistance_color,
         "title": f"{'S' if lv.role(close) == 'support' else 'R'} ×{lv.touches}"}
        for lv in levels
    ]  # fmt: skip


def patterns_overlay(patterns: list[ChartPattern], dates: list[ChartTime],
                     selected: ChartPattern | None,
                     colors: dict[str, str]) -> list[dict[str, Any]]:  # fmt: skip
    """Pivots, labels and pattern lines; targets/invalidation for the selected one.

    ``colors`` keys: ``up``, ``down``, ``neutral``, ``target`` and ``invalid``.
    """
    items: list[dict[str, Any]] = []
    for pattern in patterns:
        color = colors["up"] if pattern.bias > 0 else colors["down"] if pattern.bias < 0 \
            else colors["neutral"]  # fmt: skip
        width = 2 if pattern is selected else 1
        labels = [
            {"time": dates[p.index], "text": text,
             "position": "aboveBar" if p.kind == HIGH else "belowBar"}
            for p, text in zip(pattern.points, pattern.labels, strict=True) if text
        ]  # fmt: skip
        items.append({
            "kind": "line", "color": color, "style": SOLID, "width": width, "labels": labels,
            "points": [{"time": dates[p.index], "value": p.price} for p in pattern.points],
        })  # fmt: skip
        for seg in pattern.lines:
            if seg.end <= seg.start:
                continue
            items.append({
                "kind": "line", "color": color, "style": DASHED, "width": width,
                "points": [{"time": dates[seg.start], "value": seg.start_price},
                           {"time": dates[seg.end], "value": seg.end_price}],
            })  # fmt: skip
    if selected is not None:
        for target in selected.targets:
            items.append({"kind": "level", "price": target.price, "color": colors["target"],
                          "style": DASHED, "title": target.label})  # fmt: skip
        if selected.invalidation is not None:
            items.append({"kind": "level", "price": selected.invalidation,
                          "color": colors["invalid"], "style": DOTTED,
                          "title": "Invalidación"})  # fmt: skip
    return items


def volume_profile_overlay(profile: dict[str, Any], color: str, value_color: str,
                           poc_color: str, line_color: str) -> list[dict[str, Any]]:  # fmt: skip
    """Bars of the profile plus POC / value-area lines (see ``indicators.functions``)."""
    bands = profile.get("bands") or []
    if not bands:
        return []
    poc, val, vah = profile["poc"], profile["val"], profile["vah"]
    items: list[dict[str, Any]] = [{
        "kind": "profile", "color": color, "valueColor": value_color, "pocColor": poc_color,
        "bands": [
            {"low": low, "high": high, "volume": volume, "poc": bool(low <= poc <= high),
             "inValue": bool(low >= val - 1e-9 and high <= vah + 1e-9)}
            for low, high, volume in bands
        ],
    }]  # fmt: skip
    for price, title in ((poc, "POC"), (vah, "VA alto"), (val, "VA bajo")):
        items.append({"kind": "level", "price": price, "color": line_color,
                      "style": SOLID if title == "POC" else DOTTED, "title": title})  # fmt: skip
    return items


def exhaustion_overlay(signals: list[int], dates: list[ChartTime],
                       colors: dict[str, str]) -> list[dict[str, Any]]:  # fmt: skip
    """One marker where each run of exhaustion signals starts (``signal_series`` values).

    Up-trend exhaustion (positive score) is drawn above the bar pointing down, down-trend
    exhaustion below the bar pointing up; the text is the number of conditions met.
    ``colors`` keys: ``up`` and ``down``.
    """
    markers = []
    previous = 0
    for value, time in zip(signals, dates, strict=True):
        if value and (previous == 0 or (value > 0) != (previous > 0)):
            rising = value > 0
            markers.append({
                "time": time, "text": str(abs(value)),
                "position": "aboveBar" if rising else "belowBar",
                "shape": "arrowDown" if rising else "arrowUp",
                "color": colors["down"] if rising else colors["up"],
            })  # fmt: skip
        previous = value
    return [{"kind": "markers", "markers": markers}] if markers else []
