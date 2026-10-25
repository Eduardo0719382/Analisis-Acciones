"""Backtest that exits when the rise shows exhaustion signs, compared with the same trend
strategy without that exit."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pytestqt.qtbot import QtBot

from analisis_acciones.analysis.exhaustion import Params, signal_series
from analisis_acciones.backtesting.engine import BacktestConfig
from analisis_acciones.models.market import BarSeries, Interval
from analisis_acciones.strategies.registry import (
    STRATEGY_REGISTRY,
    trend_exhaustion,
    trend_only,
)
from analisis_acciones.ui.backtest_dialog import BacktestDialog, run_strategy
from analisis_acciones.ui.theme import DARK
from tests.unit.test_exhaustion import bars_from

PARAMS = {"period": 50, "conditions": 3, "rsi_high": 70}


def boom_and_bust(seed: int = 4) -> pd.DataFrame:
    """Calm rise, a fast rally that exhausts, then a slide back below the average."""
    rng = np.random.default_rng(seed)
    steps = np.concatenate([
        rng.normal(0.001, 0.008, 300), rng.normal(0.012, 0.004, 30),
        rng.normal(-0.008, 0.006, 60), rng.normal(0.001, 0.008, 100),
    ])  # fmt: skip
    return bars_from(100 * np.exp(np.cumsum(steps)), np.full(len(steps), 1e6))


def test_exits_include_every_trend_exit_plus_exhaustion() -> None:
    bars = boom_and_bust()
    base = trend_only(bars, PARAMS)
    tested = trend_exhaustion(bars, PARAMS)
    assert (tested["entry"] == base["entry"]).all()
    exhaustion = signal_series(bars, Params(threshold=3)) > 0
    assert (tested["exit"] == (base["exit"] | exhaustion)).all()
    assert exhaustion.any()


def test_signals_do_not_look_ahead() -> None:
    bars = boom_and_bust()
    full = trend_exhaustion(bars, PARAMS)
    cut = trend_exhaustion(bars.iloc[:340], PARAMS)
    assert full.iloc[:340].equals(cut)


def test_outcome_includes_the_strategy_without_the_exit() -> None:
    series = BarSeries("RUN", Interval.D1, boom_and_bust(), "synthetic")
    config = BacktestConfig(10_000, 0.1, 0.0, 0.05)
    outcome = run_strategy(series, "trend_exhaustion", PARAMS, config)
    assert outcome.reference is not None and outcome.reference_stats is not None
    plain = run_strategy(series, "trend_exhaustion", PARAMS, config)
    assert plain.stats == outcome.stats  # deterministic
    # Same entries; exhaustion closes at least one position earlier than the trend exit.
    tested = {t.entry_date: t.exit_date for t in outcome.result.trades}
    reference = {t.entry_date: t.exit_date for t in outcome.reference.trades}
    assert tested.keys() == reference.keys()
    assert all(tested[d] <= reference[d] for d in tested)  # type: ignore[operator]
    assert any(tested[d] < reference[d] for d in tested)  # type: ignore[operator]
    assert STRATEGY_REGISTRY["ema_cross"].reference is None
    assert run_strategy(series, "ema_cross", {"fast": 20, "slow": 50}, config).reference is None


def test_dialog_shows_the_comparison(qtbot: QtBot) -> None:
    series = BarSeries("RUN", Interval.D1, boom_and_bust(), "synthetic")
    dialog = BacktestDialog(series, "RUN · Diario", DARK)
    qtbot.addWidget(dialog)
    dialog.strategy.setCurrentIndex(dialog.strategy.findData("trend_exhaustion"))
    assert "señales de agotamiento" in dialog.rules_label.text()
    dialog.run()
    qtbot.waitUntil(lambda: dialog.outcome is not None, timeout=10000)
    assert "Misma tendencia sin salida por agotamiento: rentabilidad" in dialog.notes.text()


def test_reentry_buys_again_when_the_signs_fade_above_the_average() -> None:
    from analisis_acciones.strategies.registry import trend_exhaustion_reentry

    bars = boom_and_bust()
    plain = trend_exhaustion(bars, PARAMS)
    again = trend_exhaustion_reentry(bars, PARAMS)
    assert (again["exit"] == plain["exit"]).all()
    extra = again["entry"] & ~plain["entry"]
    assert extra.any()
    exhausted = signal_series(bars, Params(threshold=3)) > 0
    average = bars["close"].rolling(50).mean()
    for day in extra[extra].index:
        i = bars.index.get_loc(day)
        assert exhausted.iloc[i - 1] and not exhausted.iloc[i]
        assert bars["close"].iloc[i] > average.iloc[i]
    assert trend_exhaustion_reentry(bars.iloc[:340], PARAMS).equals(again.iloc[:340])


def test_reentry_keeps_more_of_the_trend() -> None:
    series = BarSeries("RUN", Interval.D1, boom_and_bust(), "synthetic")
    config = BacktestConfig(10_000, 0.1, 0.0, 0.05)
    plain = run_strategy(series, "trend_exhaustion", PARAMS, config)
    again = run_strategy(series, "trend_exhaustion_reentry", PARAMS, config)
    assert again.reference_stats == plain.reference_stats
    assert again.stats.trades > plain.stats.trades
    assert again.stats.exposure_pct > plain.stats.exposure_pct
