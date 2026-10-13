"""Backtest engine and statistics checked against hand-computed results."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.backtesting.engine import BacktestConfig, run_backtest
from analisis_acciones.backtesting.statistics import compute_statistics, max_drawdown_pct
from analisis_acciones.models.errors import UserError
from analisis_acciones.strategies.registry import (
    STRATEGY_REGISTRY,
    crosses_above,
    validate_strategy_params,
)
from tests.analysis.test_rules import make_bars

NO_COSTS = BacktestConfig(initial_capital=1000.0, commission_pct=0.0, slippage_pct=0.0)


def bars_from(opens: list[float], closes: list[float]) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-01", periods=len(opens), name="date")
    o, c = np.array(opens, float), np.array(closes, float)
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 1, "low": np.minimum(o, c) - 1,
                         "close": c, "adj_close": c, "volume": 1.0, "dividends": 0.0,
                         "splits": 0.0}, index=index)  # fmt: skip


def signals_at(bars: pd.DataFrame, entries: list[int], exits: list[int]) -> pd.DataFrame:
    s = pd.DataFrame({"entry": False, "exit": False}, index=bars.index)
    s.iloc[entries, 0] = True
    s.iloc[exits, 1] = True
    return s


def test_no_signals_no_trades() -> None:
    bars = bars_from([10] * 5, [10, 11, 12, 11, 10])
    result = run_backtest(bars, signals_at(bars, [], []), NO_COSTS)
    stats = compute_statistics(result, bars)
    assert result.trades == () and result.open_trade is None
    assert (result.equity == 1000.0).all()
    assert stats.total_return_pct == 0.0
    assert stats.trades == 0 and stats.win_rate_pct is None and stats.profit_factor is None
    assert stats.max_drawdown_pct == 0.0 and stats.exposure_pct == 0.0


def test_fills_at_next_open_without_costs() -> None:
    #            0    1    2    3    4    5
    opens = [10, 20, 22, 25, 30, 28]
    closes = [19, 21, 24, 29, 27, 26]
    bars = bars_from(opens, closes)
    result = run_backtest(bars, signals_at(bars, entries=[0], exits=[3]), NO_COSTS)
    (trade,) = result.trades
    # Signal at close of bar 0 -> buy at open of bar 1 (20): floor(1000/20) = 50 shares.
    assert trade.entry_date == date(2024, 1, 2) and trade.entry_price == 20 and trade.shares == 50
    # Exit signal at close of bar 3 -> sell at open of bar 4 (30).
    assert trade.exit_date == date(2024, 1, 5) and trade.exit_price == 30
    assert trade.pnl() == 500.0
    assert trade.return_pct == pytest.approx(50.0)
    # Equity: bar0 1000; bar1 0 + 50*21=1050; bar2 1200; bar3 1450; bar4 1500 cash; bar5 1500.
    assert result.equity.tolist() == [1000, 1050, 1200, 1450, 1500, 1500]


def test_costs_by_hand() -> None:
    bars = bars_from([100, 100, 110, 110], [100, 105, 110, 110])
    config = BacktestConfig(initial_capital=10_000, commission_pct=1.0, commission_fixed=5.0,
                            slippage_pct=1.0)  # fmt: skip
    result = run_backtest(bars, signals_at(bars, [0], [1]), config)
    (trade,) = result.trades
    buy = 100 * 1.01  # 101.0
    shares = int((10_000 - 5) // (buy * 1.01))  # 97
    assert trade.entry_price == pytest.approx(buy) and trade.shares == shares
    entry_comm = buy * shares * 0.01 + 5
    sell = 110 * 0.99
    exit_comm = sell * shares * 0.01 + 5
    assert trade.entry_commission == pytest.approx(entry_comm)
    assert trade.exit_commission == pytest.approx(exit_comm)
    expected_pnl = (sell - buy) * shares - entry_comm - exit_comm
    assert trade.pnl() == pytest.approx(expected_pnl)
    assert result.equity.iloc[-1] == pytest.approx(10_000 + expected_pnl)
    stats = compute_statistics(result, bars)
    assert stats.commissions == pytest.approx(entry_comm + exit_comm)


def test_signal_on_last_bar_is_not_executed() -> None:
    bars = bars_from([10, 10, 10], [10, 10, 10])
    result = run_backtest(bars, signals_at(bars, [2], []), NO_COSTS)
    assert result.open_trade is None and result.pending_signal == "buy"
    assert any("última barra" in n for n in result.notes)


def test_open_position_marked_to_market() -> None:
    bars = bars_from([10, 10, 12], [10, 11, 15])
    result = run_backtest(bars, signals_at(bars, [0], []), NO_COSTS)
    stats = compute_statistics(result, bars)
    assert result.trades == () and result.open_trade is not None
    assert result.equity.iloc[-1] == 100 * 15
    assert stats.open_trade_pnl == 500.0
    assert stats.trades == 0  # only closed trades are counted


def test_multiple_trades_stats() -> None:
    #       0   1   2   3   4   5   6   7
    opens = [10, 10, 12, 12, 10, 10, 8, 8]
    closes = [10, 11, 12, 11, 10, 9, 8, 8]
    bars = bars_from(opens, closes)
    # Trade A: buy open1=10, sell open3=12 (+200). Trade B: buy open4=10 (120 shares of 1200),
    # sell open6=8 (-240).
    result = run_backtest(bars, signals_at(bars, [0, 3], [2, 5]), NO_COSTS)
    stats = compute_statistics(result, bars)
    assert [t.pnl() for t in result.trades] == [200.0, -240.0]
    assert stats.trades == 2 and stats.winning == 1 and stats.losing == 1
    assert stats.win_rate_pct == 50.0
    assert stats.profit_factor == pytest.approx(200 / 240)
    assert stats.final_equity == 960.0
    assert stats.total_return_pct == pytest.approx(-4.0)
    assert stats.buy_and_hold_pct == pytest.approx(-20.0)  # open 10 -> close 8


def test_max_drawdown_by_hand() -> None:
    equity = pd.Series([100, 120, 90, 130, 104, 140])
    # Declines: 120 -> 90 = -25 % and 130 -> 104 = -20 %; the larger one is reported.
    assert max_drawdown_pct(equity) == pytest.approx(-25.0)


def test_no_lookahead_in_execution() -> None:
    """Trades decided before bar t do not change when bars after t change."""
    bars = make_bars(np.concatenate([np.linspace(100, 60, 80), np.linspace(60, 130, 80),
                                     np.linspace(130, 90, 60)]))  # fmt: skip
    spec = STRATEGY_REGISTRY["ema_cross"]
    params = spec.defaults()
    full = run_backtest(bars, spec.signals(bars, params), NO_COSTS)
    cut = 170
    altered = bars.copy()
    altered.iloc[cut:, :4] *= 3  # wildly different future
    other = run_backtest(altered, spec.signals(altered, params), NO_COSTS)
    before = [t for t in full.trades if t.exit_date and t.exit_date < bars.index[cut].date()]
    before_other = [t for t in other.trades if t.exit_date and t.exit_date < bars.index[cut].date()]
    assert before == before_other
    pd.testing.assert_series_equal(full.equity.iloc[:cut], other.equity.iloc[:cut])


def test_ema_strategy_trades_match_crossovers() -> None:
    bars = make_bars(np.concatenate([np.linspace(100, 60, 80), np.linspace(60, 130, 80),
                                     np.linspace(130, 70, 80)]))  # fmt: skip
    spec = STRATEGY_REGISTRY["ema_cross"]
    signals = spec.signals(bars, {"fast": 20, "slow": 50})
    result = run_backtest(bars, signals, NO_COSTS)
    entry_bars = list(np.flatnonzero(signals["entry"].to_numpy()))
    assert len(result.trades) >= 1
    first = result.trades[0]
    assert first.entry_date == bars.index[entry_bars[0] + 1].date()  # next bar's open


def test_crosses_above_definition() -> None:
    a = pd.Series([1.0, 2, 3, 2, 4])
    assert crosses_above(a, 2.5).tolist() == [False, False, True, False, True]


def test_validation() -> None:
    with pytest.raises(UserError):
        BacktestConfig(initial_capital=0).validate()
    with pytest.raises(UserError):
        validate_strategy_params(STRATEGY_REGISTRY["rsi_reversion"], {"low": 80, "high": 70})
    with pytest.raises(UserError):
        run_backtest(bars_from([1], [1]), signals_at(bars_from([1], [1]), [], []), NO_COSTS)


def test_insufficient_cash_is_noted() -> None:
    bars = bars_from([10, 5000, 5000], [10, 5000, 5000])
    result = run_backtest(bars, signals_at(bars, [0], []), NO_COSTS)
    assert result.open_trade is None
    assert any("capital insuficiente" in n for n in result.notes)
