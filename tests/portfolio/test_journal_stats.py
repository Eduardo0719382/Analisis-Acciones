from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from analisis_acciones.portfolio.engine import BUY, SELL, PaperTrade, replay, value
from analisis_acciones.services.journal_stats import journal_stats
from analisis_acciones.services.paper_portfolio import Portfolio, PortfolioReport
from analisis_acciones.services.portfolio_report import portfolio_html


def tr(side: str, qty: float, price: float, day: date, symbol: str = "AAA", note: str = "",
       review: str = "") -> PaperTrade:  # fmt: skip
    return PaperTrade(symbol, side, qty, price, day, 0.0, note, None, review)


TRADES = [
    tr(BUY, 10, 100, date(2024, 1, 2), note="ruptura"),
    tr(BUY, 10, 120, date(2024, 1, 10)),
    tr(SELL, 5, 130, date(2024, 2, 1), review="bien"),  # +100 (avg cost 110)
    tr(SELL, 15, 100, date(2024, 3, 1)),  # -150, position closed
    tr(BUY, 4, 50, date(2024, 4, 1), symbol="BBB", note="dividendo"),
    tr(SELL, 4, 55, date(2024, 4, 11), symbol="BBB"),  # +20
    tr(BUY, 2, 90, date(2024, 5, 1)),  # AAA reopened
    tr(SELL, 2, 99, date(2024, 5, 3)),  # +18
]


def test_holding_period_restarts_when_position_reopens() -> None:
    state = replay(TRADES, 10_000)
    opened = [c.opened_on for c in state.closed]
    assert opened == [date(2024, 1, 2), date(2024, 1, 2), date(2024, 4, 1), date(2024, 5, 1)]


def test_journal_stats() -> None:
    state = replay(TRADES, 10_000)
    st = journal_stats(state.closed, TRADES)
    assert (st.sales, st.winners, st.losers) == (4, 3, 1)
    assert st.win_rate == pytest.approx(75)
    assert st.total_result == pytest.approx(100 - 150 + 20 + 18)
    assert st.profit_factor == pytest.approx(138 / 150)
    assert st.average_gain == pytest.approx(46) and st.average_loss == pytest.approx(-150)
    assert st.payoff_ratio == pytest.approx(46 / 150)
    assert st.best is not None and st.best.result == pytest.approx(100)
    assert st.worst is not None and st.worst.result == pytest.approx(-150)
    assert st.average_days_held == pytest.approx((30 + 59 + 10 + 2) / 4)
    assert [(s.symbol, s.sales, s.winners) for s in st.by_symbol] == [("BBB", 1, 1),
                                                                      ("AAA", 3, 2)]  # fmt: skip
    assert st.with_reason_pct == pytest.approx(25) and st.with_review_pct == pytest.approx(12.5)
    assert st.small_sample


def test_no_sales_and_no_losses() -> None:
    empty = journal_stats([], [])
    assert empty.sales == 0 and empty.win_rate is None and empty.profit_factor is None
    winners = replay([tr(BUY, 1, 10, date(2024, 1, 2)), tr(SELL, 1, 12, date(2024, 1, 3))], 100)
    st = journal_stats(winners.closed, [])
    assert st.profit_factor is None and st.payoff_ratio is None and st.win_rate == 100


def test_stats_panel_in_report() -> None:
    state = replay(TRADES, 10_000)
    p = Portfolio(1, "Diario", 10_000)
    report = PortfolioReport(p, TRADES, value(state, 10_000, {}), pd.Series(dtype=float),
                             pd.Series(dtype=float), "SPY", [], state.closed)  # fmt: skip
    html = portfolio_html(report, datetime(2024, 6, 1))
    assert "Estadísticas del diario" in html and "75 %" in html
    assert "Solo 4 ventas" in html and "Mejor venta" in html
    empty = PortfolioReport(p, [], value(replay([], 1), 1, {}), pd.Series(dtype=float),
                            pd.Series(dtype=float), "SPY", [])  # fmt: skip
    assert "Estadísticas del diario" not in portfolio_html(empty, datetime(2024, 6, 1))
