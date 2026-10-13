from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.indicators import functions as f
from tests.indicators.reference import (
    ref_atr,
    ref_bollinger,
    ref_ema,
    ref_macd,
    ref_rsi,
    ref_sma,
)
from tests.synthetic import synthetic_daily

BARS = synthetic_daily(sessions=400, seed=11)
CLOSE = BARS["close"]
CLOSES = CLOSE.tolist()


def assert_matches(actual: pd.Series, expected: list[float]) -> None:
    got = actual.to_numpy()
    exp = np.array(expected, dtype=float)
    assert len(got) == len(exp)
    assert np.array_equal(np.isnan(got), np.isnan(exp)), "warm-up NaN positions differ"
    mask = ~np.isnan(exp)
    np.testing.assert_allclose(got[mask], exp[mask], rtol=0, atol=1e-8)


# Hand-computed examples ---------------------------------------------------------
def test_sma_by_hand() -> None:
    out = f.sma(pd.Series([1.0, 2, 3, 4, 5]), 3)
    assert out.isna().tolist() == [True, True, False, False, False]
    assert out.tolist()[2:] == [2.0, 3.0, 4.0]


def test_ema_by_hand() -> None:
    # n=3 -> alpha=0.5; seed = mean(2,4,6) = 4; then 0.5*8+0.5*4=6; 0.5*10+0.5*6=8
    out = f.ema(pd.Series([2.0, 4, 6, 8, 10]), 3)
    assert out.tolist()[2:] == [4.0, 6.0, 8.0]
    assert out.iloc[:2].isna().all()


def test_rsi_by_hand() -> None:
    # Changes: +1, +1, -1 (n=2). Seed: gain=(1+1)/2=1, loss=0 -> RSI=100 at index 2.
    # Next: gain=(1*1+0)/2=0.5, loss=(0*1+1)/2=0.5 -> RS=1 -> RSI=50 at index 3.
    out = f.rsi(pd.Series([10.0, 11, 12, 11]), 2)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == 100.0
    assert out.iloc[3] == pytest.approx(50.0)


def test_rsi_flat_series_is_neutral() -> None:
    out = f.rsi(pd.Series([5.0] * 20), 14)
    assert out.iloc[14:].eq(50.0).all()


def test_true_range_by_hand() -> None:
    high = pd.Series([10.0, 12, 11])
    low = pd.Series([8.0, 9, 7])
    close = pd.Series([9.0, 11, 8])
    tr = f.true_range(high, low, close)
    # bar0: 10-8=2; bar1: max(3, |12-9|=3, |9-9|=0)=3; bar2: max(4, |11-11|=0, |7-11|=4)=4
    assert tr.tolist() == [2.0, 3.0, 4.0]


def test_bollinger_by_hand() -> None:
    out = f.bollinger(pd.Series([1.0, 2, 3]), 3, 2.0)
    sd = math.sqrt(2 / 3)  # population sd of 1,2,3
    assert out["middle"].iloc[2] == 2.0
    assert out["upper"].iloc[2] == pytest.approx(2 + 2 * sd)
    assert out["lower"].iloc[2] == pytest.approx(2 - 2 * sd)


# Independent reference implementations -----------------------------------------
@pytest.mark.parametrize("n", [1, 5, 20, 50, 200])
def test_sma_reference(n: int) -> None:
    assert_matches(f.sma(CLOSE, n), ref_sma(CLOSES, n))


@pytest.mark.parametrize("n", [1, 9, 12, 26, 50])
def test_ema_reference(n: int) -> None:
    assert_matches(f.ema(CLOSE, n), ref_ema(CLOSES, n))


@pytest.mark.parametrize("n", [2, 7, 14, 30])
def test_rsi_reference(n: int) -> None:
    out = f.rsi(CLOSE, n)
    assert_matches(out, ref_rsi(CLOSES, n))
    assert out.dropna().between(0, 100).all()


@pytest.mark.parametrize(("fast", "slow", "signal"), [(12, 26, 9), (5, 35, 5), (3, 10, 16)])
def test_macd_reference(fast: int, slow: int, signal: int) -> None:
    out = f.macd(CLOSE, fast, slow, signal)
    line, sig, hist = ref_macd(CLOSES, fast, slow, signal)
    assert_matches(out["macd"], line)
    assert_matches(out["signal"], sig)
    assert_matches(out["histogram"], hist)
    # First signal value appears after slow-1 + signal-1 bars.
    assert out["signal"].first_valid_index() == CLOSE.index[slow - 1 + signal - 1]


@pytest.mark.parametrize(("n", "k"), [(20, 2.0), (10, 1.5), (2, 3.0)])
def test_bollinger_reference(n: int, k: float) -> None:
    out = f.bollinger(CLOSE, n, k)
    upper, middle, lower = ref_bollinger(CLOSES, n, k)
    assert_matches(out["upper"], upper)
    assert_matches(out["middle"], middle)
    assert_matches(out["lower"], lower)


@pytest.mark.parametrize("n", [1, 5, 14, 30])
def test_atr_reference(n: int) -> None:
    out = f.atr(BARS["high"], BARS["low"], BARS["close"], n)
    expected = ref_atr(BARS["high"].tolist(), BARS["low"].tolist(), CLOSES, n)
    assert_matches(out, expected)
    assert (out.dropna() > 0).all()


# Edge cases ---------------------------------------------------------------------
def test_series_shorter_than_period_is_all_nan() -> None:
    short = CLOSE.iloc[:5]
    assert f.sma(short, 10).isna().all()
    assert f.ema(short, 10).isna().all()
    assert f.rsi(short, 10).isna().all()
    assert f.atr(BARS["high"].iloc[:5], BARS["low"].iloc[:5], short, 10).isna().all()


def test_index_is_preserved() -> None:
    for out in (f.sma(CLOSE, 5), f.ema(CLOSE, 5), f.rsi(CLOSE, 5)):
        assert out.index.equals(CLOSE.index)


@pytest.mark.parametrize("bad", [0, -1, 2.5, True])
def test_invalid_periods(bad: object) -> None:
    with pytest.raises(ValueError):
        f.sma(CLOSE, bad)  # type: ignore[arg-type]


def test_macd_requires_fast_below_slow() -> None:
    with pytest.raises(ValueError):
        f.macd(CLOSE, 26, 12, 9)


def test_no_lookahead() -> None:
    """Values up to bar t must not change when later bars are appended."""
    full = f.macd(CLOSE, 12, 26, 9)
    partial = f.macd(CLOSE.iloc[:200], 12, 26, 9)
    pd.testing.assert_frame_equal(full.iloc[:200], partial)
    pd.testing.assert_series_equal(f.rsi(CLOSE, 14).iloc[:200], f.rsi(CLOSE.iloc[:200], 14))
