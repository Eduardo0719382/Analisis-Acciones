"""Ichimoku, stochastics, ADX, OBV and Supertrend vs plain-Python references."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.charts.payload import build_indicator_payload, future_times
from analisis_acciones.indicators import functions as f
from analisis_acciones.indicators.registry import IndicatorConfig
from tests.indicators.reference import ref_atr, ref_rsi, ref_sma
from tests.indicators.test_functions import assert_matches
from tests.synthetic import synthetic_daily

BARS = synthetic_daily(sessions=300, seed=5)
H, L, C, V = (BARS[c].tolist() for c in ("high", "low", "close", "volume"))
NaN = float("nan")


def ref_mid(n: int) -> list[float]:
    return [NaN if i < n - 1 else (max(H[i - n + 1 : i + 1]) + min(L[i - n + 1 : i + 1])) / 2
            for i in range(len(C))]  # fmt: skip


def test_ichimoku_reference() -> None:
    out = f.ichimoku(BARS["high"], BARS["low"], BARS["close"])
    tenkan, kijun = ref_mid(9), ref_mid(26)
    assert_matches(out["tenkan"], tenkan)
    assert_matches(out["kijun"], kijun)
    assert_matches(out["senkou_a"], [(a + b) / 2 for a, b in zip(tenkan, kijun, strict=True)])
    assert_matches(out["senkou_b"], ref_mid(52))
    assert_matches(out["chikou"], C)


def ref_position(values: list[float], n: int) -> list[float]:
    out = []
    for i in range(len(values)):
        window = values[i - n + 1 : i + 1] if i >= n - 1 else []
        if len(window) < n or any(math.isnan(x) for x in window):
            out.append(NaN)
            continue
        lo, hi = min(window), max(window)
        out.append(50.0 if hi == lo else 100 * (values[i] - lo) / (hi - lo))
    return out


def test_stochastic_reference() -> None:
    out = f.stochastic(BARS["high"], BARS["low"], BARS["close"], 14, 3, 3)
    raw = []
    for i in range(len(C)):
        if i < 13:
            raw.append(NaN)
            continue
        lo, hi = min(L[i - 13 : i + 1]), max(H[i - 13 : i + 1])
        raw.append(50.0 if hi == lo else 100 * (C[i] - lo) / (hi - lo))
    k = ref_sma(raw, 3)
    assert_matches(out["k"], [x if not math.isnan(x) else NaN for x in k])
    assert_matches(out["d"], ref_sma(k, 3))


def test_stoch_rsi_reference() -> None:
    out = f.stoch_rsi(BARS["close"], 14, 14, 3, 3)
    k = ref_sma(ref_position(ref_rsi(C, 14), 14), 3)
    assert_matches(out["k"], k)
    assert out["k"].dropna().between(0, 100).all()


def ref_adx(n: int) -> tuple[list[float], list[float], list[float]]:
    size = len(C)
    tr, pdm, mdm = [NaN] * size, [NaN] * size, [NaN] * size
    for i in range(1, size):
        up, down = H[i] - H[i - 1], L[i - 1] - L[i]
        pdm[i] = up if up > down and up > 0 else 0.0
        mdm[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))

    def wilder(xs: list[float]) -> list[float]:
        out = [NaN] * size
        first = next(i for i, x in enumerate(xs) if not math.isnan(x))
        out[first + n - 1] = sum(xs[first : first + n]) / n
        for i in range(first + n, size):
            out[i] = (out[i - 1] * (n - 1) + xs[i]) / n
        return out

    s_tr, s_p, s_m = wilder(tr), wilder(pdm), wilder(mdm)
    pdi = [NaN if math.isnan(t) else 100 * p / t for p, t in zip(s_p, s_tr, strict=True)]
    mdi = [NaN if math.isnan(t) else 100 * m / t for m, t in zip(s_m, s_tr, strict=True)]
    dx = [NaN if math.isnan(p) else (100 * abs(p - m) / (p + m) if p + m > 0 else 0.0)
          for p, m in zip(pdi, mdi, strict=True)]  # fmt: skip
    return wilder(dx), pdi, mdi


def test_adx_reference() -> None:
    out = f.adx(BARS["high"], BARS["low"], BARS["close"], 14)
    adx, pdi, mdi = ref_adx(14)
    assert_matches(out["plus_di"], pdi)
    assert_matches(out["minus_di"], mdi)
    assert_matches(out["adx"], adx)


def test_obv_reference_and_missing_volume() -> None:
    expected = [0.0]
    for i in range(1, len(C)):
        sign = 1 if C[i] > C[i - 1] else -1 if C[i] < C[i - 1] else 0
        expected.append(expected[-1] + sign * V[i])
    assert_matches(f.obv(BARS["close"], BARS["volume"]), expected)
    gap = BARS["volume"].copy()
    gap.iloc[10] = np.nan
    out = f.obv(BARS["close"], gap)
    assert out.iloc[:10].notna().all() and out.iloc[10:].isna().all()  # unknown stays unknown


def test_supertrend_reference() -> None:
    out = f.supertrend(BARS["high"], BARS["low"], BARS["close"], 10, 3.0)
    atr = ref_atr(H, L, C, 10)
    upper = lower = None
    trend = 1
    exp_line, exp_dir = [], []
    for i in range(len(C)):
        if math.isnan(atr[i]):
            exp_line.append(NaN)
            exp_dir.append(NaN)
            continue
        mid = (H[i] + L[i]) / 2
        bu, bl = mid + 3 * atr[i], mid - 3 * atr[i]
        if upper is None:
            upper, lower, trend = bu, bl, 1
        else:
            upper = bu if bu < upper or C[i - 1] > upper else upper
            lower = bl if bl > lower or C[i - 1] < lower else lower
            trend = (-1 if C[i] < lower else 1) if trend == 1 else (1 if C[i] > upper else -1)
        exp_line.append(lower if trend == 1 else upper)
        exp_dir.append(float(trend))
    assert_matches(out["value"], exp_line)
    assert_matches(out["direction"], exp_dir)


def test_flat_range_stochastic_is_neutral() -> None:
    flat = pd.Series([10.0] * 30)
    out = f.stochastic(flat, flat, flat, 14, 1, 1)
    assert out["k"].iloc[13:].eq(50.0).all()


def test_ichimoku_cloud_is_drawn_ahead_and_chikou_behind() -> None:
    bars = synthetic_daily(sessions=120)
    payload, failed = build_indicator_payload([IndicatorConfig.create("ichimoku")], bars,
                                              "#00ff00", "#ff0000", "#888888")  # fmt: skip
    assert not failed
    outputs = {o["key"]: o for o in payload[0]["outputs"]}
    last_bar = bars.index[-1].strftime("%Y-%m-%d")
    senkou_times = [p["time"] for p in outputs["senkou_a"]["points"]]
    future = future_times(bars, 26)
    assert senkou_times[-1] == future[-1] > last_bar  # cloud extends 26 bars ahead
    assert len(future) == 26 and all(pd.Timestamp(d).weekday() < 5 for d in future)
    chikou = [p for p in outputs["chikou"]["points"] if "value" in p]
    assert chikou[-1]["time"] == bars.index[-27].strftime("%Y-%m-%d")
    assert chikou[-1]["value"] == pytest.approx(bars["close"].iloc[-1])


@pytest.mark.parametrize("weeks", [True, False])
def test_future_times_follow_interval(weeks: bool) -> None:
    index = pd.date_range("2024-01-01", periods=30, freq="7D" if weeks else "MS")
    bars = synthetic_daily(sessions=30).set_axis(index)
    future = future_times(bars, 3)
    gaps = pd.DatetimeIndex(future).to_series().diff().dropna().dt.days
    assert (gaps == 7).all() if weeks else (gaps >= 28).all()


def test_supertrend_points_coloured_by_direction() -> None:
    bars = synthetic_daily(sessions=150)
    payload, _ = build_indicator_payload([IndicatorConfig.create("supertrend")], bars,
                                         "#00ff00", "#ff0000", "#888888")  # fmt: skip
    (output,) = payload[0]["outputs"]
    colours = {p["color"] for p in output["points"] if "value" in p}
    assert colours <= {"#00ff00", "#ff0000"} and colours
