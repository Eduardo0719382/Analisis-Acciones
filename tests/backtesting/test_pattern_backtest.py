from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.backtesting.patterns import (
    STOP,
    TARGET,
    TIME,
    PatternBacktestConfig,
    PatternTrade,
    _stats,
    honest_breakouts,
    run_pattern_backtest,
    simulate,
)
from analisis_acciones.models.errors import UserError
from analisis_acciones.patterns.chart_patterns import CONFIRMED, ChartPattern, detect
from analisis_acciones.patterns.elliott import Target
from analisis_acciones.patterns.zigzag import HIGH, Pivot
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, path, synthetic_daily

NO_COSTS = PatternBacktestConfig(commission_pct=0, slippage_pct=0, max_bars=5)


def bars_from(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-01", periods=len(rows), name="date")
    o, h, lo, c = zip(*rows, strict=True)
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": 1.0},
                        index=index)  # fmt: skip


def pattern(bias: int, target: float, stop: float, breakout: int = 0) -> ChartPattern:
    return ChartPattern("double", "Doble suelo" if bias > 0 else "Doble techo", bias,
                        (Pivot(0, 100, HIGH),), ("",), (), (), CONFIRMED, breakout,
                        (Target("Objetivo", target),), stop)  # fmt: skip


FLAT = (100.0, 101.0, 99.0, 100.0)


def test_long_hits_target_at_level() -> None:
    bars = bars_from([FLAT, (100, 101, 99, 100.5), (101, 106, 100, 105), FLAT])
    trade = simulate("A", bars, pattern(1, target=105, stop=95), NO_COSTS)
    assert trade is not None
    assert (trade.entry_price, trade.exit_price, trade.exit_reason) == (100, 105, TARGET)
    assert trade.return_pct == pytest.approx(5.0) and trade.bars_held == 2
    assert trade.signal_date.isoformat() == "2024-01-01"


def test_stop_first_when_both_touched_same_bar() -> None:
    bars = bars_from([FLAT, (100, 111, 89, 100), FLAT])
    trade = simulate("A", bars, pattern(1, target=110, stop=90), NO_COSTS)
    assert trade is not None and trade.exit_reason == STOP and trade.exit_price == 90


def test_gap_through_stop_fills_at_open_and_short_side() -> None:
    bars = bars_from([FLAT, FLAT, (112, 113, 111, 112), FLAT])
    trade = simulate("A", bars, pattern(-1, target=90, stop=105), NO_COSTS)
    assert trade is not None and trade.direction == -1
    assert (trade.exit_reason, trade.exit_price) == (STOP, 112)
    assert trade.return_pct == pytest.approx(-12.0)


def test_time_exit_and_costs() -> None:
    bars = bars_from([FLAT] * 10)
    config = PatternBacktestConfig(commission_pct=0.1, slippage_pct=0.5, max_bars=3)
    trade = simulate("A", bars, pattern(1, target=150, stop=50), config)
    assert trade is not None and trade.exit_reason == TIME and trade.bars_held == 3
    expected = (100 * 0.995) / (100 * 1.005) - 1 - 0.002
    assert trade.return_pct == pytest.approx(expected * 100)
    assert trade.baseline_pct == pytest.approx(0.0)


def test_breakout_on_last_bar_cannot_trade() -> None:
    bars = bars_from([FLAT, FLAT])
    assert simulate("A", bars, pattern(1, 110, 90, breakout=1), NO_COSTS) is None


def lead_in() -> list[float]:
    return [100.0 + (i % 2) * 0.5 for i in range(14)]  # 130 bars of near-flat prices


def test_honest_breakouts_are_visible_on_their_day() -> None:
    bars = path(*lead_in(), 130, 115, 129.5, 98, 104)
    confirmed, _discarded = honest_breakouts(bars)
    top = next(p for p in confirmed if p.name == "Doble techo")
    assert top.breakout is not None
    visible = {(p.name, p.breakout) for p in detect(bars.iloc[: top.breakout + 1])}
    assert ("Doble techo", top.breakout) in visible


def test_stats() -> None:
    def t(ret: float, reason: str, base: float | None = 0.5) -> PatternTrade:
        d = pd.Timestamp("2024-01-02").date()
        return PatternTrade("A", "X", 1, d, d, 1, d, 1, reason, 4, ret, base)

    s = _stats("X", [t(10, TARGET), t(-5, STOP), t(-5, STOP), t(2, TIME, None)])
    assert s.trades == 4 and s.win_rate_pct == 50
    assert s.avg_return_pct == pytest.approx(0.5) and s.median_return_pct == pytest.approx(-1.5)
    assert s.profit_factor == pytest.approx(12 / 10)
    assert (s.target_pct, s.stop_pct, s.time_pct) == (25, 50, 25)
    assert s.edge_pct == pytest.approx(0.0)


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    client = FakeYahooClient(synthetic_daily(sessions=900, seed=3))
    client.known = {"AAA"}
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: datetime(2027, 6, 1, tzinfo=UTC))  # fmt: skip
    yield service
    service.close()


def test_run_over_symbols(market: MarketDataService) -> None:
    both = run_pattern_backtest(market, ["aaa", "ZZZ"], PatternBacktestConfig())
    assert both.symbols == ["AAA"] and both.problems[0].startswith("ZZZ")
    longs = run_pattern_backtest(market, ["AAA"], PatternBacktestConfig(long_only=True))
    assert all(t.direction == 1 for t in longs.trades)
    assert longs.skipped_short == sum(t.direction < 0 for t in both.trades)
    if both.trades:
        overall = both.overall()
        assert overall is not None and overall.trades == len(both.trades)
        assert sum(g.trades for g in both.by_pattern()) == len(both.trades)
    assert np.isfinite([t.return_pct for t in both.trades]).all()
    with pytest.raises(UserError):
        run_pattern_backtest(market, [" "], PatternBacktestConfig())
    with pytest.raises(UserError):
        run_pattern_backtest(market, ["AAA"], PatternBacktestConfig(patterns=()))
