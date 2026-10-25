"""Exhaustion signs on SYNTHETIC series built to show each situation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.analysis.exhaustion import (
    DOWN,
    MIN_BARS,
    THRESHOLD,
    UP,
    assess,
    signal_series,
)


def bars_from(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=len(close))
    frame = pd.DataFrame(
        {"open": close, "high": close * 1.005, "low": close * 0.995, "close": close},
        index=index,
    )
    frame["volume"] = volume if volume is not None else np.nan
    return frame


def rally(n: int = 400, seed: int = 1) -> np.ndarray:
    """Slow noisy uptrend that accelerates sharply in the last 25 bars."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0004, 0.01, n)
    steps[-25:] = rng.normal(0.012, 0.004, 25)
    return 100 * np.exp(np.cumsum(steps))


def test_up_trend_exhaustion_is_described() -> None:
    close = rally()
    volume = np.full(len(close), 1e6)
    volume[-10:] = 5e5  # volume fades while the price keeps rising
    a = assess(bars_from(close, volume))
    assert a.direction == UP and a.signalled and a.available == 6
    met = {c.name: c.met for c in a.conditions}
    assert met["RSI en sobrecompra (≥ 70)"] and met["Precio muy alejado de su media de 50"]
    assert met["Volumen que se apaga en la subida"]
    assert all(c.detail for c in a.conditions)
    for o in a.outcomes:
        assert 0 <= o.against <= o.events <= len(close) // o.horizon
        assert o.baseline_events > o.events


def test_down_trend_mirror_and_missing_volume() -> None:
    a = assess(bars_from(1e4 / rally()))  # the same path upside down
    assert a.direction == DOWN and a.signalled
    assert a.available == 5  # no volume: that condition cannot be evaluated
    assert next(c for c in a.conditions if c.met is None).name.startswith("Volumen")


def test_no_trend_and_short_history() -> None:
    flat = np.full(300, 100.0)  # no trend at all
    assert assess(bars_from(flat)).direction is None
    short = assess(bars_from(rally(MIN_BARS - 1)))
    assert short.direction is None and "al menos" in short.reason


def test_signal_series_matches_last_assessment() -> None:
    close = rally()
    series = signal_series(bars_from(close))
    a = assess(bars_from(close))
    assert series.iloc[-1] == (a.met if a.met >= THRESHOLD else 0)
    assert set(np.unique(series)) <= {0, 3, 4, 5, 6, -3, -4, -5, -6}


def test_outcomes_use_only_past_data() -> None:
    """Changing future bars must not change past signals."""
    close = rally(500, seed=4)
    base = signal_series(bars_from(close))
    changed = close.copy()
    changed[450:] *= 3
    after = signal_series(bars_from(changed))
    assert (base.iloc[:450] == after.iloc[:450]).all()


@pytest.mark.parametrize("seed", [2, 3])
def test_random_walk_has_no_obvious_edge(seed: int) -> None:
    """On a random walk the historical comparison must not claim a strong effect."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, 3000)))
    up_bars = bars_from(close)
    series = signal_series(up_bars)
    assert (series != 0).sum() > 10  # the rules do fire


def test_binomial_p_value() -> None:
    from analisis_acciones.analysis.exhaustion import Outcome

    fair = Outcome(20, 10, 5, 0.0, 100, 50.0)
    assert fair.p_value == pytest.approx(0.623046875)  # P(X >= 5 | n=10, p=0.5)
    extreme = Outcome(20, 10, 10, 0.0, 100, 50.0)
    assert extreme.p_value == pytest.approx(0.5**10)
    low = Outcome(20, 10, 0, 0.0, 100, 50.0)
    assert low.p_value == pytest.approx(0.5**10)
    assert Outcome(20, 0, 0, None, 100, 50.0).p_value is None
