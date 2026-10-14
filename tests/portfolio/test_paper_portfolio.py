from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from analisis_acciones.models.errors import UserError
from analisis_acciones.portfolio.engine import (
    BUY,
    SELL,
    PaperTrade,
    equity_curve,
    replay,
    value,
)
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, synthetic_daily

D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def t(side: str, qty: float, price: float, day: date = D1, fee: float = 0.0,
      symbol: str = "AAA") -> PaperTrade:  # fmt: skip
    return PaperTrade(symbol, side, qty, price, day, fee)


def test_average_cost_realised_and_cash() -> None:
    trades = [t(BUY, 10, 100, D1, 1), t(BUY, 10, 120, D2), t(SELL, 5, 130, D3, 2)]
    state = replay(trades, 10_000)
    pos = state.positions["AAA"]
    assert pos.quantity == 15
    assert pos.average_cost == pytest.approx((1001 + 1200) / 20)
    assert pos.realized == pytest.approx(5 * 130 - 2 - 5 * (2201 / 20))
    assert state.cash == pytest.approx(10_000 - 1001 - 1200 + 648)
    assert state.commissions == 3


def test_impossible_trades_are_refused() -> None:
    with pytest.raises(UserError) as cash:
        replay([t(BUY, 100, 200)], 10_000)
    assert "Efectivo insuficiente" in cash.value.user_message
    with pytest.raises(UserError) as short:
        replay([t(BUY, 1, 10, D2), t(SELL, 1, 10, D1)], 1000)  # sale dated before the purchase
    assert "no se pueden vender" in short.value.user_message


def test_valuation_and_weights() -> None:
    state = replay([t(BUY, 10, 100), t(BUY, 5, 20, symbol="BBB")], 2000)
    val = value(state, 2000, {"AAA": 110, "BBB": 18})
    assert val.total_value == pytest.approx(900 + 1100 + 90)
    aaa = val.holdings[0]
    assert aaa.unrealized == pytest.approx(100) and aaa.unrealized_pct == pytest.approx(10)
    assert aaa.weight_pct == pytest.approx(1100 / 2090 * 100)
    assert val.total_return_pct == pytest.approx(4.5)
    unknown = value(state, 2000, {"AAA": 110})
    assert unknown.total_value is None and unknown.unrealized is None


def test_equity_curve_values_each_day() -> None:
    closes = {"AAA": pd.Series([100.0, 110.0, 90.0], index=pd.bdate_range(D1, periods=3))}
    curve = equity_curve([t(BUY, 10, 100, D1)], 1000, closes, D3)
    assert list(curve) == pytest.approx([1000, 1100, 900])


@pytest.fixture
def service() -> Iterator[PaperPortfolioService]:
    client = FakeYahooClient(synthetic_daily(sessions=60))
    client.known = {"TEST", "SPY"}
    now = datetime(2024, 3, 30, 12, tzinfo=UTC)
    market = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                               clock=lambda: now)  # fmt: skip
    yield PaperPortfolioService(open_database(":memory:"), market, clock=lambda: now)
    market.close()


def test_service_flow(service: PaperPortfolioService) -> None:
    (default,) = service.portfolios()
    assert default.name == "Mi cartera" and default.initial_cash == 10_000
    buy = service.add_trade(default.id, "test", BUY, 10, trade_date=date(2024, 1, 15))
    expected, _ = service.close_on("TEST", date(2024, 1, 15))
    assert buy.price == pytest.approx(expected) and buy.id
    service.add_trade(default.id, "TEST", SELL, 4, price=150.0, trade_date=date(2024, 2, 1))
    with pytest.raises(UserError):
        service.add_trade(default.id, "TEST", SELL, 10, price=100)  # only 6 left
    with pytest.raises(UserError):
        service.delete_trade(default.id, buy.id)  # the later sale would become impossible
    with pytest.raises(UserError):
        service.add_trade(default.id, "TEST", BUY, 1, trade_date=date(2030, 1, 1))

    report = service.report(default.id)
    assert report.problems == []
    assert report.valuation.holdings[0].quantity == 6
    assert report.equity.index[0] == pd.Timestamp("2024-01-15")
    assert report.benchmark.iloc[0] == pytest.approx(10_000)
    assert len(report.benchmark) == len(report.equity)

    second = service.create("  Prueba  ", 500)
    assert second.name == "Prueba" and len(service.portfolios()) == 2
    with pytest.raises(UserError):
        service.create("Prueba", 100)
    service.delete(second.id)
    assert [p.name for p in service.portfolios()] == ["Mi cartera"]
