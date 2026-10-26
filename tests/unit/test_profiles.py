"""Breakout / pullback strategies and the horizon x style profiles (long-only)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.backtesting.engine import BacktestConfig, run_backtest
from analisis_acciones.models.errors import UserError
from analisis_acciones.strategies.profiles import (
    HORIZON_NAMES,
    PROFILES,
    STYLE_NAMES,
    profile,
)
from analisis_acciones.strategies.registry import STRATEGY_REGISTRY


def bars(close: list[float]) -> pd.DataFrame:
    c = pd.Series(close, dtype=float)
    idx = pd.date_range("2020-01-01", periods=len(c), freq="D")
    return pd.DataFrame(
        {"open": c.shift(1).fillna(c.iloc[0]).to_numpy(), "high": (c + 1).to_numpy(),
         "low": (c - 1).to_numpy(), "close": c.to_numpy(), "adj_close": c.to_numpy(),
         "volume": 1.0, "dividends": 0.0, "splits": 0.0},
        index=idx,
    )  # fmt: skip


def test_breakout_buys_new_highs_and_sells_new_lows() -> None:
    data = bars([10] * 10 + [20] + [20] * 5 + [5])
    sig = STRATEGY_REGISTRY["breakout"].signals(data, {"entry_n": 5, "exit_n": 3})
    assert sig["entry"].tolist().index(True) == 10
    assert sig["exit"].iloc[-1] and not sig["exit"].iloc[:10].any()


def test_pullback_needs_the_trend() -> None:
    rng = np.random.default_rng(1)
    down = bars(list(200 - np.arange(300) * 0.3 + rng.normal(0, 1, 300)))
    params = {"trend": 100, "period": 14, "low": 40, "high": 65}
    sig = STRATEGY_REGISTRY["pullback"].signals(down, params)
    assert not (sig["entry"] & (down["close"] <= down["close"].rolling(100).mean())).any()


def test_profiles_cover_every_horizon_and_style() -> None:
    assert {(p.horizon, p.style) for p in PROFILES} == {
        (h, s) for h in HORIZON_NAMES for s in STYLE_NAMES
    }
    assert len({p.id for p in PROFILES}) == len(PROFILES)


@pytest.mark.parametrize("p", PROFILES, ids=lambda p: p.id)
def test_every_profile_is_valid_and_long_only(p) -> None:  # type: ignore[no-untyped-def]
    assert p.strategy_id in STRATEGY_REGISTRY
    params = p.validated_params()
    rng = np.random.default_rng(7)
    data = bars(list(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, 600)))))
    sig = STRATEGY_REGISTRY[p.strategy_id].signals(data, params)
    result = run_backtest(data, sig, BacktestConfig(fractional=True))
    assert all(t.shares > 0 for t in result.trades)
    assert (result.equity > 0).all()


def test_unknown_profile() -> None:
    with pytest.raises(UserError):
        profile("nope")
