"""Build chart overlay items (plain dicts for chart.js). No Qt imports."""

from __future__ import annotations

from typing import Any

from analisis_acciones.forecast.projection import Projection
from analisis_acciones.patterns.elliott import CORRECTION, WaveCount
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


def projection_overlay(projection: Projection, past_dates: list[str], future_dates: list[str],
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


def elliott_overlay(counts: list[WaveCount], dates: list[str], selected: WaveCount | None,
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
