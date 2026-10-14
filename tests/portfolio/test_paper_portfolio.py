from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from analisis_acciones.models.errors import UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.portfolio.engine import (
    BUY,
    DIVIDEND,
    SELL,
    SPLIT,
    CorporateEvent,
    PaperTrade,
    adjust_for_splits,
    equity_curve,
    replay,
    split_factor_after,
    value,
)
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.paper_portfolio import PaperPortfolioService, Portfolio
from analisis_acciones.services.portfolio_report import portfolio_html
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


def test_dividend_paid_on_ex_date_to_shares_held_before() -> None:
    events = [CorporateEvent("AAA", D2, DIVIDEND, 0.5)]
    # Bought on D1; a purchase on the ex-date itself does not collect the dividend.
    state = replay([t(BUY, 10, 100, D1), t(BUY, 4, 100, D2)], 10_000, events=events)
    assert state.cash == pytest.approx(10_000 - 1400 + 5)
    assert state.dividends == pytest.approx(5)
    (applied,) = state.applied
    assert applied.shares == 10 and applied.cash == pytest.approx(5)
    val = value(state, 10_000, {"AAA": 100})
    assert val.dividends == pytest.approx(5) and val.total_value == pytest.approx(10_005)


def test_split_converts_trades_to_todays_units() -> None:
    splits = {"AAA": pd.Series([0.0, 2.0, 0.0], index=pd.bdate_range(D1, periods=3))}
    adjusted = adjust_for_splits([t(BUY, 3, 100, D1), t(SELL, 2, 60, D3)], splits)
    assert (adjusted[0].quantity, adjusted[0].price) == (6, 50)  # before the 2:1 split
    assert (adjusted[1].quantity, adjusted[1].price) == (2, 60)  # after it: unchanged
    state = replay(adjusted, 1000)
    assert state.positions["AAA"].quantity == 4
    assert state.positions["AAA"].realized == pytest.approx(2 * 60 - 2 * 50)
    assert split_factor_after(splits["AAA"], D1) == 2 and split_factor_after(splits["AAA"], D2) == 1


def test_fractional_quantities_and_rounding() -> None:
    state = replay([t(BUY, 0.333333, 30), t(SELL, 0.3333334, 31, D2)], 100)  # rounding absorbed
    assert state.positions["AAA"].quantity == 0
    with pytest.raises(UserError):
        replay([t(BUY, 0.5, 30), t(SELL, 0.6, 31, D2)], 100)


def test_commission_schedule() -> None:
    p = Portfolio(1, "x", 1000, commission_fixed=1.5, commission_pct=0.1, commission_min=2)
    assert p.commission_for(100) == 2  # 1.5 + 0.1 → minimum 2
    assert p.commission_for(5000) == pytest.approx(6.5)
    assert Portfolio(1, "x", 1000).commission_for(5000) == 0
    assert Portfolio(1, "x", 1000, commission_fixed=1).commission_for(10) == 1


def test_buy_by_amount_and_automatic_commission(service: PaperPortfolioService) -> None:
    (p,) = service.portfolios()
    with pytest.raises(UserError):
        service.set_costs(p.id, -1, 0, 0)
    p = service.set_costs(p.id, 1.0, 0.0, 0.0)
    trade = service.add_trade(p.id, "TEST", BUY, amount=250, price=99.0,
                              trade_date=date(2024, 1, 15))  # fmt: skip
    assert trade.quantity == pytest.approx(round(250 / 99, 6)) and trade.commission == 1.0
    manual = service.add_trade(p.id, "TEST", BUY, 0.5, price=99.0, commission=0.0,
                               trade_date=date(2024, 1, 16))  # fmt: skip
    assert manual.commission == 0.0
    with pytest.raises(UserError):
        service.add_trade(p.id, "TEST", BUY, 1, amount=100)  # both given
    with pytest.raises(UserError):
        service.add_trade(p.id, "TEST", BUY)  # neither given
    service.set_review(p.id, trade.id or 0, "  Entré pronto.  ")
    assert service.trades(p.id)[0].review == "Entré pronto."
    report = service.report(p.id)
    assert report.valuation.commissions == 1.0
    assert report.valuation.holdings[0].quantity == pytest.approx(trade.quantity + 0.5)


@pytest.fixture
def events_service() -> Iterator[PaperPortfolioService]:
    """SYNTHETIC history with a 2:1 split on 2024-02-01 and a dividend on 2024-02-15."""
    bars = synthetic_daily(sessions=60)
    split_day, div_day = pd.Timestamp("2024-02-01"), pd.Timestamp("2024-02-15")
    bars.loc[bars.index < split_day, ["open", "high", "low", "close"]] /= 2  # split-adjusted
    bars.loc[split_day, "splits"] = 2.0
    bars.loc[div_day, "dividends"] = 0.25
    client = FakeYahooClient(bars)
    client.known = {"TEST", "SPY"}
    now = datetime(2024, 3, 30, 12, tzinfo=UTC)
    market = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                               clock=lambda: now)  # fmt: skip
    yield PaperPortfolioService(open_database(":memory:"), market, clock=lambda: now)
    market.close()


def test_split_and_dividend_in_service(events_service: PaperPortfolioService) -> None:
    service = events_service
    (p,) = service.portfolios()
    price, _ = service.close_on("TEST", date(2024, 1, 15))
    adjusted = service._market.load("TEST", Interval.D1).series.bars["close"]
    assert price == pytest.approx(float(adjusted.loc["2024-01-15"]) * 2)  # real quoted price
    service.add_trade(p.id, "TEST", BUY, 10, trade_date=date(2024, 1, 15))
    # 20 shares after the split: selling 15 is possible only thanks to it.
    service.add_trade(p.id, "TEST", SELL, 15, trade_date=date(2024, 3, 1))
    report = service.report(p.id)
    assert report.valuation.holdings[0].quantity == pytest.approx(5)
    split, dividend = report.events
    assert (split.event.kind, split.shares) == (SPLIT, 20)
    assert (dividend.event.kind, dividend.shares) == (DIVIDEND, 20)
    assert dividend.cash == pytest.approx(5) and report.valuation.dividends == pytest.approx(5)
    html = portfolio_html(report, datetime(2024, 3, 30))
    assert "Eventos corporativos" in html and "de 10 a 20 acciones" in html
    assert "+5,00 $ en efectivo" in html

    service.set_costs(p.id, 0, 0, 0, apply_dividends=False)
    assert service.report(p.id).valuation.dividends == 0


def test_split_display_before_later_split() -> None:
    """A dividend paid before a later split is shown in the units of its day."""
    trades = [PaperTrade("AAA", BUY, 10, 100, D1, id=1)]
    splits = {"AAA": pd.Series([0.0, 0.0, 2.0], index=pd.bdate_range(D1, periods=3))}
    events = [CorporateEvent("AAA", D2, DIVIDEND, 0.5), CorporateEvent("AAA", D3, SPLIT, 2.0)]
    state = replay(adjust_for_splits(trades, splits), 10_000, events=events)
    dividend = PaperPortfolioService._as_quoted(state.applied[0], splits)
    assert dividend.shares == 10 and dividend.event.value == 1.0
    assert dividend.cash == pytest.approx(10)


def test_messages_use_the_units_of_the_trade_day() -> None:
    splits = {"AAA": pd.Series([0.0, 0.0, 4.0], index=pd.bdate_range(D1, periods=3))}
    with pytest.raises(UserError) as exc:
        replay(adjust_for_splits([t(BUY, 30, 400, D1)], splits), 10_000)
    assert "comprar 30 AAA" in exc.value.user_message
