"""Forward test with virtual money: completed bars only, replay from the start date."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from analisis_acciones.models.market import Interval
from analisis_acciones.services.forward_test import (
    BUDGET,
    SLEEVES,
    completed,
    load_start,
    render_report,
    run_all,
    save_start,
)
from analisis_acciones.strategies.profiles import PROFILES

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def daily(days: int, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, days)))
    idx = pd.date_range(end="2026-10-26", periods=days, freq="D")
    c = pd.Series(close, index=idx)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c * 1.01, "low": c * 0.99,
                         "close": c, "adj_close": c, "volume": 1.0, "dividends": 0.0,
                         "splits": 0.0})  # fmt: skip


def test_incomplete_bars_are_dropped() -> None:
    d = daily(30)  # last bar is today (2026-10-26)
    assert len(completed(d, Interval.D1, NOW)) == 29
    assert len(completed(d.iloc[:-1], Interval.D1, NOW)) == 29
    assert len(completed(d, Interval.H1, NOW)) == 29
    weekly = d.iloc[[-9, -8]]  # Oct 18 and Oct 19: both in weeks that are over
    assert len(completed(weekly, Interval.W1, NOW)) == 2
    this_week = d.iloc[[-9, -1]]  # 2026-10-26 is a Monday: its week is not over
    assert len(completed(this_week, Interval.W1, NOW)) == 1
    monthly = d.iloc[[-30, -1]]
    assert len(completed(monthly, Interval.MN1, NOW)) == 1


def fetch(symbol: str, interval: Interval) -> pd.DataFrame:
    base = daily(900, seed=len(symbol))
    if interval.is_intraday:
        idx = pd.date_range(end="2026-10-26 11:00", periods=2000, freq="h", tz="UTC")
        c = pd.Series(
            100 * np.exp(np.cumsum(np.random.default_rng(5).normal(0, 0.004, 2000))), index=idx
        )
        return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c * 1.002,
                             "low": c * 0.998, "close": c, "adj_close": c, "volume": 1.0,
                             "dividends": 0.0, "splits": 0.0})  # fmt: skip
    return base


def test_replay_gives_every_profile_its_budget() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    results = run_all(fetch, start, NOW)
    assert [r.profile for r in results] == list(PROFILES)
    for r in results:
        assert r.start_value == BUDGET and len(r.sleeves) == len(SLEEVES)
        assert all(s.value > 0 for s in r.sleeves)
    assert run_all(fetch, start, NOW)[0].value == results[0].value  # deterministic


def test_nothing_happens_before_the_data_exists() -> None:
    results = run_all(fetch, datetime(2026, 10, 26, 13, 0, tzinfo=UTC), NOW)
    assert all(r.value == BUDGET and r.return_pct == 0 for r in results)
    text = render_report(results, NOW, NOW)
    assert "Prueba hacia adelante" in text and "asesoramiento" in text


def test_start_state_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "forward_test" / "state.json"
    assert load_start(path) is None
    save_start(path, NOW)
    assert load_start(path) == NOW
