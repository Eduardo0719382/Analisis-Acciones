from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.indicators import functions as f
from analisis_acciones.indicators.registry import IndicatorConfig, compute
from tests.synthetic import path, synthetic_daily, synthetic_intraday


def test_vwap_daily_is_rolling_volume_weighted_typical_price() -> None:
    idx = pd.bdate_range("2024-01-01", periods=3)
    high = pd.Series([11.0, 12, 13], idx)
    low = pd.Series([9.0, 10, 11], idx)
    close = pd.Series([10.0, 11, 12], idx)
    vol = pd.Series([100.0, 300, 100], idx)
    out = f.vwap(high, low, close, vol, 2)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx((10 * 100 + 11 * 300) / 400)
    assert out.iloc[2] == pytest.approx((11 * 300 + 12 * 100) / 400)
    vol.iloc[1] = np.nan
    assert np.isnan(f.vwap(high, low, close, vol, 2).iloc[2])


def test_vwap_intraday_resets_each_session() -> None:
    bars = synthetic_intraday(start="2025-03-06", days=2)  # 7 hourly bars per day
    out = f.vwap(bars["high"], bars["low"], bars["close"], bars["volume"])
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    assert out.iloc[0] == pytest.approx(typical.iloc[0])
    assert out.iloc[7] == pytest.approx(typical.iloc[7])  # first bar of the second day
    day1 = slice(0, 7)
    expected = (typical.iloc[day1] * bars["volume"].iloc[day1]).sum() / bars["volume"].iloc[
        day1
    ].sum()
    assert out.iloc[6] == pytest.approx(expected)


def test_auto_fibonacci_levels_of_last_swing() -> None:
    bars = path(100, 120, 110, 160)  # last swing: 110 (index 20) -> 160 (index 30)
    out = f.auto_fibonacci(bars["high"], bars["low"], 5.0)
    assert list(out.columns) == ["f0000", "f0236", "f0382", "f0500", "f0618", "f0786", "f1000"]
    assert out.iloc[:20].isna().all().all()
    last = out.iloc[-1]
    assert last["f0000"] == pytest.approx(160) and last["f1000"] == pytest.approx(110)
    assert last["f0618"] == pytest.approx(160 - 0.618 * 50)
    flat = f.auto_fibonacci(bars["high"].iloc[:3], bars["low"].iloc[:3], 5.0)
    assert flat.isna().all().all()


def test_auto_fibonacci_registry_labels() -> None:
    config = IndicatorConfig.create("auto_fib")
    labels = [o.label for o in config.spec.outputs]
    assert labels == ["0 %", "23,6 %", "38,2 %", "50 %", "61,8 %", "78,6 %", "100 %"]
    values = compute(config, synthetic_daily(sessions=300))
    assert values.iloc[-1].notna().all()


def test_volume_profile_spreads_volume_over_ranges() -> None:
    idx = pd.bdate_range("2024-01-01", periods=2)
    high = pd.Series([12.0, 10.0], idx)
    low = pd.Series([10.0, 10.0], idx)  # second bar has no range: all at 10
    vol = pd.Series([100.0, 50.0], idx)
    profile = f.volume_profile(high, low, vol, bins=2)
    bands = profile["bands"]
    assert bands == [(10.0, 11.0, pytest.approx(100.0)), (11.0, 12.0, pytest.approx(50.0))]
    assert profile["poc"] == pytest.approx(10.5)
    assert sum(b[2] for b in bands) == pytest.approx(150)  # volume is conserved


def test_volume_profile_value_area() -> None:
    bars = synthetic_daily(sessions=250)
    profile = f.volume_profile(bars["high"], bars["low"], bars["volume"], bins=30)
    bands = profile["bands"]
    total = sum(b[2] for b in bands)
    inside = sum(
        b[2] for b in bands if b[0] >= profile["val"] - 1e-9 and b[1] <= profile["vah"] + 1e-9
    )
    assert inside >= 0.7 * total
    assert profile["val"] <= profile["poc"] <= profile["vah"]
    empty = f.volume_profile(bars["high"], bars["low"], bars["volume"] * np.nan)
    assert empty["bands"] == [] and empty["poc"] is None
