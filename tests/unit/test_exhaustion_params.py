"""Custom exhaustion thresholds and the chart markers built from the signal series."""

from __future__ import annotations

import pytest

from analisis_acciones.analysis.exhaustion import (
    DEFAULT_PARAMS,
    UP,
    Params,
    assess,
    condition_names,
    signal_series,
)
from analisis_acciones.charts.overlays import exhaustion_overlay
from analisis_acciones.services.scanner import scan_bars
from analisis_acciones.services.settings_service import SettingsService
from tests.unit.test_exhaustion import bars_from, rally


def test_defaults_match_the_documented_rules() -> None:
    assert Params(70, 30, 3.0, 0.8, 2.0, 3) == DEFAULT_PARAMS
    assert condition_names(UP)[0] == "RSI en sobrecompra (≥ 70)"
    assert condition_names(UP, Params(rsi_high=80))[0] == "RSI en sobrecompra (≥ 80)"


@pytest.mark.parametrize(
    "bad", [{"rsi_high": 99}, {"rsi_low": 2}, {"atr_multiple": 0}, {"threshold": 7},
            {"volume_ratio": 1.5}, {"z_limit": 9}],
)  # fmt: skip
def test_out_of_range_values_are_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Params(**bad)  # type: ignore[arg-type]


def test_stored_values_are_data_and_fall_back_to_defaults() -> None:
    assert Params.from_dict(None) == DEFAULT_PARAMS
    assert Params.from_dict({"rsi_high": "75; DROP"}) == DEFAULT_PARAMS
    assert Params.from_dict({"rsi_high": 120}) == DEFAULT_PARAMS  # invalid -> all defaults
    assert Params.from_dict({"rsi_high": float("nan")}) == DEFAULT_PARAMS
    assert Params.from_dict({"rsi_high": 75, "threshold": 2.0}) == Params(rsi_high=75, threshold=2)
    p = Params(80, 20, 2.5, 0.7, 1.5, 4)
    assert Params.from_dict(p.to_dict()) == p


def test_settings_keep_the_thresholds(settings: SettingsService) -> None:
    assert settings.exhaustion_params() == DEFAULT_PARAMS
    settings.set_exhaustion_params(Params(rsi_high=80, threshold=4))
    assert settings.exhaustion_params() == Params(rsi_high=80, threshold=4)
    assert not settings.exhaustion_markers()
    settings.set_exhaustion_markers(True)
    assert settings.exhaustion_markers()


def test_looser_thresholds_give_more_signals_and_cases() -> None:
    bars = bars_from(rally(n=900, seed=3))
    strict = signal_series(bars, Params(threshold=5))
    default = signal_series(bars)
    loose = signal_series(bars, Params(rsi_high=60, atr_multiple=1.5, z_limit=1.0, threshold=2))
    count = [int((s != 0).sum()) for s in (strict, default, loose)]
    assert count[0] <= count[1] < count[2]
    a_default, a_loose = assess(bars), assess(bars, Params(threshold=2, rsi_high=60))
    assert a_loose.threshold == 2 and a_default.threshold == 3
    assert a_loose.outcomes[0].events >= a_default.outcomes[0].events
    assert a_loose.met >= a_default.met


def test_scanner_uses_the_thresholds() -> None:
    bars = bars_from(rally())
    assert scan_bars("RUN", bars).exhaustion > 0
    assert scan_bars("RUN", bars, Params(threshold=6, rsi_high=95)).exhaustion == 0


def test_signal_at_a_bar_uses_only_data_up_to_it() -> None:
    bars = bars_from(rally(n=500, seed=5))
    full = signal_series(bars)
    cut = signal_series(bars.iloc[:400])
    assert (full.iloc[:400].to_numpy() == cut.to_numpy()).all()


def test_markers_only_where_a_run_starts() -> None:
    signals = [0, 3, 4, 3, 0, 0, -3, -4, 0, 3, -3]
    dates = [f"2024-01-{d:02d}" for d in range(1, 12)]
    items = exhaustion_overlay(signals, dates, {"up": "#00f", "down": "#f00"})
    markers = items[0]["markers"]
    assert [m["time"] for m in markers] == ["2024-01-02", "2024-01-07", "2024-01-10",
                                            "2024-01-11"]  # fmt: skip
    first, second = markers[0], markers[1]
    assert first["position"] == "aboveBar" and first["shape"] == "arrowDown"
    assert first["color"] == "#f00" and first["text"] == "3"
    assert second["position"] == "belowBar" and second["color"] == "#00f"
    assert exhaustion_overlay([0, 0], dates[:2], {"up": "a", "down": "b"}) == []
