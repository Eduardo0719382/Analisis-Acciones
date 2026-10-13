"""Build chart overlay items (plain dicts for chart.js). No Qt imports."""

from __future__ import annotations

from typing import Any

from analisis_acciones.forecast.projection import Projection

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
