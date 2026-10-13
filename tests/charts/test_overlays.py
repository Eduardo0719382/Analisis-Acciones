from __future__ import annotations

import json

import numpy as np
import pytest

from analisis_acciones.charts.overlays import elliott_overlay, projection_overlay
from analisis_acciones.forecast.projection import regression_channel, volatility_cone
from analisis_acciones.patterns.elliott import analyze
from tests.synthetic import path


def test_projection_overlay_lines_start_at_last_close() -> None:
    closes = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, 300)))
    projection = volatility_cone(closes, horizon=3, lookback=100)
    dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
    items = projection_overlay(projection, ["2024-12-30", "2024-12-31"], dates, "#888", "#0af")
    assert [item["title"] for item in items] == ["P95", "P75", "P50", "P25", "P5"]
    for item in items:
        assert item["kind"] == "line"
        assert item["points"][0] == {"time": "2024-12-31", "value": projection.base_price}
        assert [p["time"] for p in item["points"][1:]] == dates[:3]
    median = items[2]
    assert median["color"] == "#0af" and median["width"] == 2
    json.dumps(items, allow_nan=False)  # serialisable for the page


def test_regression_overlay_includes_fitted_channel() -> None:
    closes = 50 * np.exp(0.002 * np.arange(200))
    projection = regression_channel(closes, horizon=2, lookback=30)
    past = [f"2024-{m:02d}-{d:02d}" for m in (1, 2) for d in range(1, 29)][:40]
    items = projection_overlay(projection, past, ["2024-03-01", "2024-03-04"], "#888", "#0af")
    median = items[2]["points"]
    assert len(median) == 30 + 2
    assert median[0]["time"] == past[-30]
    assert median[29]["value"] == pytest.approx(closes[-1])


def test_elliott_overlay_labels_and_levels() -> None:
    bars = path(100, 120, 108, 150, 135, 165, 148, 158, 138, 150)
    result = analyze(bars, threshold=0.05)
    dates = bars.index.strftime("%Y-%m-%d").tolist()
    colors = {"up": "#0f0", "down": "#f00", "correction": "#888", "current": "#0af",
              "invalid": "#f0f"}  # fmt: skip
    selected = result.current[0]
    items = elliott_overlay([*result.past, *result.current], dates, selected, colors)
    impulse, correction, current = items[:3]
    assert [lbl["text"] for lbl in impulse["labels"]] == ["0", "1", "2", "3", "4", "5"]
    assert impulse["labels"][1]["position"] == "aboveBar"  # wave 1 ends at a high
    assert impulse["color"] == "#0f0" and correction["color"] == "#888"
    assert [lbl["text"] for lbl in correction["labels"]] == ["A", "B", "C"]
    assert current["style"] == 2 and current["width"] == 2
    levels = [item for item in items if item["kind"] == "level"]
    assert len(levels) == len(selected.targets) + 1
    assert levels[-1]["price"] == 158 and levels[-1]["color"] == "#f0f"
    json.dumps(items, allow_nan=False)
