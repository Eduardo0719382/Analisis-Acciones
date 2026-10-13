from __future__ import annotations

import json

import numpy as np

from analisis_acciones.charts.chart_widget import FALLBACK_LOCALE, chart_locale
from analisis_acciones.charts.payload import INITIAL_VISIBLE_BARS, build_payload, price_decimals
from analisis_acciones.models.market import BarSeries, Interval
from tests.synthetic import synthetic_daily


def series(bars=None) -> BarSeries:  # type: ignore[no-untyped-def]
    return BarSeries(
        "TEST", Interval.D1, synthetic_daily(sessions=10) if bars is None else bars, "s"
    )


def test_payload_mirrors_bars_exactly() -> None:
    s = series()
    payload = build_payload(s, "TEST · Diario", "#00ff00", "#ff0000")
    assert payload["title"] == "TEST · Diario"
    assert payload["initialBars"] == INITIAL_VISIBLE_BARS
    assert len(payload["candles"]) == 10
    first = payload["candles"][0]
    assert first["time"] == "2024-01-01"
    assert first["close"] == s.bars["close"].iloc[0]
    assert payload["volume"][0]["value"] == s.bars["volume"].iloc[0]
    json.dumps(payload, allow_nan=False)  # must be strict JSON


def test_volume_colour_follows_candle_direction() -> None:
    bars = synthetic_daily(sessions=10)
    payload = build_payload(series(bars), "t", "#00ff00", "#ff0000")
    for candle, vol in zip(payload["candles"], payload["volume"], strict=True):
        expected = "#00ff0080" if candle["close"] >= candle["open"] else "#ff000080"
        assert vol["color"] == expected


def test_missing_volume_is_a_gap_not_zero() -> None:
    bars = synthetic_daily(sessions=5)
    bars.iloc[2, bars.columns.get_loc("volume")] = np.nan
    payload = build_payload(series(bars), "t", "#000000", "#000000")
    assert "value" not in payload["volume"][2]
    assert payload["volumeByIndex"][2] is None
    json.dumps(payload, allow_nan=False)


def test_no_volume_at_all_hides_volume_pane() -> None:
    bars = synthetic_daily(sessions=5)
    bars["volume"] = np.nan
    payload = build_payload(series(bars), "t", "#000000", "#000000")
    assert payload["volume"] is None


def test_price_decimals() -> None:
    bars = synthetic_daily(sessions=5)
    assert price_decimals(bars) == 2
    assert price_decimals(bars / 1000) == 4


def test_chart_locale() -> None:
    assert chart_locale("es-MX") == "es-MX"
    assert chart_locale("en-POSIX") == FALLBACK_LOCALE
    assert chart_locale("C") == FALLBACK_LOCALE
    assert chart_locale("") == FALLBACK_LOCALE
    assert chart_locale("es-MX');alert(1);//") == FALLBACK_LOCALE
