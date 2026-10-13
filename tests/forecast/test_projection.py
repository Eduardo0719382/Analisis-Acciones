from __future__ import annotations

import math

import numpy as np
import pytest

from analisis_acciones.forecast.projection import (
    QUANTILES,
    calibrate,
    regression_channel,
    volatility_cone,
)
from analisis_acciones.models.errors import UserError


def test_cone_by_hand() -> None:
    returns = np.tile([0.01, -0.01], 50)  # 100 log-returns
    closes = 100 * np.exp(np.concatenate([[0], np.cumsum(returns)]))
    proj = volatility_cone(closes, horizon=4, lookback=100)
    sigma = returns.std(ddof=1)
    base = closes[-1]
    assert proj.stats["sigma"] == pytest.approx(sigma)
    assert proj.bands["p50"] == pytest.approx([base] * 4)  # no drift by default
    expected_p95 = base * math.exp(QUANTILES["p95"] * sigma * 2)  # sqrt(4) = 2
    assert proj.bands["p95"][-1] == pytest.approx(expected_p95)
    assert proj.bands["p05"][0] < base < proj.bands["p95"][0]


def test_cone_with_drift() -> None:
    closes = 100 * np.exp(np.linspace(0, 0.5, 101))  # constant log-return 0.005
    proj = volatility_cone(closes, horizon=10, lookback=100, use_drift=True)
    assert proj.bands["p50"][-1] == pytest.approx(closes[-1] * math.exp(0.005 * 10))


def test_regression_on_exact_exponential() -> None:
    closes = 50 * np.exp(0.002 * np.arange(200))
    proj = regression_channel(closes, horizon=5, lookback=120)
    assert proj.stats["r2"] == pytest.approx(1.0)
    expected = 50 * np.exp(0.002 * np.arange(200, 205))
    assert proj.bands["p50"] == pytest.approx(expected.tolist(), rel=1e-9)
    assert proj.bands["p95"] == pytest.approx(proj.bands["p50"], rel=1e-9)  # zero residuals


def test_calibration_matches_theory_on_random_walk() -> None:
    rng = np.random.default_rng(42)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 4000)))
    cal = calibrate(closes, "cone", horizon=10, lookback=252, step=5, max_samples=600)
    assert cal is not None and cal.samples == 600
    assert 0.84 <= cal.inside_90 <= 0.96
    assert 0.42 <= cal.inside_50 <= 0.58


def test_calibration_needs_history() -> None:
    assert calibrate(np.linspace(1, 2, 100), "cone", 10, 252) is None


@pytest.mark.parametrize(
    ("closes", "horizon", "lookback"),
    [(np.linspace(1, 2, 50), 5, 252), (np.linspace(1, 2, 400), 0, 252),
     (np.linspace(1, 2, 400), 5, 5), (np.concatenate([np.linspace(1, 2, 399), [-1]]), 5, 252)],
)  # fmt: skip
def test_invalid_inputs(closes: np.ndarray, horizon: int, lookback: int) -> None:
    with pytest.raises(UserError):
        volatility_cone(closes, horizon, lookback)
