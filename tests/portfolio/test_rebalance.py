from __future__ import annotations

from datetime import date

import pytest

from analisis_acciones.portfolio.engine import BUY, SELL, PaperTrade, replay, value
from analisis_acciones.portfolio.rebalance import plan_rebalance

D = date(2024, 1, 2)


def valuation(cash: float = 1000.0):  # type: ignore[no-untyped-def]
    trades = [PaperTrade("AAA", BUY, 60, 10, D), PaperTrade("BBB", BUY, 2, 100, D)]
    # 10 000 initial; AAA 600 + BBB 200 bought; prices now AAA 10, BBB 100.
    state = replay(trades, cash + 800)
    return value(state, cash + 800, {"AAA": 10.0, "BBB": 100.0})


def free(_value: float) -> float:
    return 0.0


def test_plan_moves_to_targets_with_fractions() -> None:
    val = valuation()  # total 1800: AAA 600 (33.3 %), BBB 200 (11.1 %), cash 1000
    plan = plan_rebalance(val, {"AAA": 50, "BBB": 25, "CCC": 20}, free, {"CCC": 40.0})
    orders = {o.symbol: o for o in plan.orders}
    assert orders["AAA"].side == BUY and orders["AAA"].quantity == pytest.approx(30)
    assert orders["BBB"].side == BUY and orders["BBB"].quantity == pytest.approx(2.5)
    assert orders["CCC"].quantity == pytest.approx(9)  # 360 / 40
    assert plan.cash_target_pct == pytest.approx(5)
    assert plan.cash_after == pytest.approx(90)
    assert not plan.scaled and plan.problems == []
    assert plan.weights["AAA"][0] == pytest.approx(600 / 1800 * 100)


def test_sells_first_untargeted_sold_entirely_and_buys_scaled_for_fees() -> None:
    val = valuation(cash=0.0)  # total 800: AAA 600, BBB 200
    plan = plan_rebalance(val, {"BBB": 100}, lambda v: round(v * 0.01, 2))
    sell, buy = plan.orders
    assert (sell.symbol, sell.side, sell.quantity) == ("AAA", SELL, 60)
    assert buy.symbol == "BBB" and buy.side == BUY
    # 600 from the sale minus 6 commission; the purchase plus its 1 % must fit.
    assert buy.value + round(buy.value * 0.01, 2) <= 594 - 0.01 + 1e-9
    assert plan.scaled and plan.cash_after >= 0


def test_small_differences_are_ignored_and_errors_reported() -> None:
    val = valuation()
    near = plan_rebalance(val, {"AAA": 33.5, "BBB": 11.0}, free)
    assert near.orders == []
    assert plan_rebalance(val, {"AAA": 80, "BBB": 30}, free).problems  # > 100 %
    assert "CCC" in plan_rebalance(val, {"CCC": 10}, free).problems[0]  # no price
