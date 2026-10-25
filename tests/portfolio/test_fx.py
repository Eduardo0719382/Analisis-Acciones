"""Multi-currency paper portfolio: SYNTHETIC prices and exchange rates."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from analisis_acciones.models.market import Interval
from analisis_acciones.portfolio.engine import BUY
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.fx import pair_for
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
from analisis_acciones.services.portfolio_report import portfolio_html, portfolio_trades_csv
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, synthetic_daily

NOW = datetime(2024, 3, 30, 12, tzinfo=UTC)


class MultiClient(FakeYahooClient):
    """Different bars and currency per symbol."""

    def __init__(self) -> None:
        super().__init__(synthetic_daily(sessions=60))
        rate = synthetic_daily(sessions=60)
        rate[["open", "high", "low", "close", "adj_close"]] = 1.1
        rate.loc[rate.index >= pd.Timestamp("2024-03-01"), ["open", "high", "low", "close"]] = 1.2
        pence = synthetic_daily(sessions=60, seed=3)
        gbp = synthetic_daily(sessions=60)
        gbp[["open", "high", "low", "close", "adj_close"]] = 1.25
        self.frames = {"SAP": synthetic_daily(sessions=60, seed=2), "EURUSD=X": rate,
                       "VOD.L": pence, "GBPUSD=X": gbp,
                       "SPY": synthetic_daily(sessions=60)}  # fmt: skip
        self.currencies = {"SAP": "EUR", "VOD.L": "GBp", "SPY": "USD", "EURUSD=X": "USD",
                           "GBPUSD=X": "USD"}  # fmt: skip
        btc = synthetic_daily(sessions=60, seed=5)
        btc[["open", "high", "low", "close", "adj_close"]] = 50_000.0
        self.frames["BTC-USD"] = btc
        self.frames["ETH-BTC"] = synthetic_daily(sessions=60, seed=6) / 2000  # about 0.05 BTC
        self.frames["ETH-EUR"] = synthetic_daily(sessions=60, seed=7) * 25
        self.known = set(self.frames) | {"NOCUR"}
        self.frames["NOCUR"] = synthetic_daily(sessions=60, seed=4)

    def history(self, symbol: str, start: date | None, end: date | None,
                interval: str = "1d") -> pd.DataFrame:  # fmt: skip
        self.bars = self.frames.get(symbol, self.bars)
        return super().history(symbol, start, end, interval)

    def info(self, symbol: str) -> dict[str, object]:
        currency = self.currencies.get(symbol)
        return {"currency": currency} if currency else {}


@pytest.fixture
def service() -> Iterator[PaperPortfolioService]:
    market = MarketDataService(YahooFinanceProvider(MultiClient()), open_database(":memory:"),
                               clock=lambda: NOW)  # fmt: skip
    yield PaperPortfolioService(open_database(":memory:"), market, clock=lambda: NOW)
    market.close()


def test_pairs() -> None:
    assert pair_for("USD") == (None, 1.0)
    assert pair_for("EUR") == ("EURUSD=X", 1.0)
    assert pair_for("eur") == ("EURUSD=X", 1.0)
    assert pair_for("GBp") == ("GBPUSD=X", 0.01) and pair_for("GBP") == ("GBPUSD=X", 1.0)
    assert pair_for("ZAc") == ("ZARUSD=X", 0.01) and pair_for("ILA") == ("ILSUSD=X", 0.01)


def test_trades_in_other_currencies(service: PaperPortfolioService) -> None:
    (p,) = service.portfolios()
    sap = service.add_trade(p.id, "SAP", BUY, 10, trade_date=date(2024, 2, 1))
    local, _ = service.close_on("SAP", date(2024, 2, 1))
    assert sap.currency == "EUR" and sap.fx_rate == pytest.approx(1.1)
    assert sap.price == pytest.approx(local)  # recorded in euros
    by_amount = service.add_trade(p.id, "SAP", BUY, amount=1320.0, price=100.0,
                                  trade_date=date(2024, 3, 4))  # fmt: skip
    assert by_amount.fx_rate == pytest.approx(1.2)
    assert by_amount.quantity == pytest.approx(1320 / 120)  # $ amount at 1.2 $/€
    vod = service.add_trade(p.id, "VOD.L", BUY, 100, price=80.0, trade_date=date(2024, 2, 1))
    assert vod.currency == "GBp" and vod.fx_rate == pytest.approx(0.0125)  # pence

    report = service.report(p.id)
    v = report.valuation
    spent = 10 * local * 1.1 + 1320.0 + 100 * 80 * 0.0125
    assert v.cash == pytest.approx(10_000 - spent)
    bars = service._market.load("SAP", Interval.D1).series.bars["close"]
    sap_holding = next(h for h in v.holdings if h.symbol == "SAP")
    assert sap_holding.price == pytest.approx(float(bars.iloc[-1]) * 1.2)  # today's rate
    assert any("EURUSD=X" in n for n in report.fx_notes)
    html = portfolio_html(report, NOW)
    assert "EUR</td>" in html and "GBp</td>" in html and "EURUSD=X" in html
    assert portfolio_trades_csv(report).splitlines()[1].endswith(",EUR,1.1")
    # The rebalance plan works in dollars and records local prices.
    service.set_targets(p.id, {"SAP": 50, "VOD.L": 10})
    plan = service.rebalance_plan(report)
    assert plan.problems == [] and plan.orders
    service.apply_rebalance(p.id, plan)
    after = service.report(p.id).valuation
    weights = {h.symbol: h.weight_pct for h in after.holdings}
    assert weights["SAP"] == pytest.approx(50, abs=0.05)
    assert weights["VOD.L"] == pytest.approx(10, abs=0.05)


def test_crypto_pairs_in_other_currencies(service: PaperPortfolioService) -> None:
    assert pair_for("BTC") == ("BTC-USD", 1.0) and pair_for("USDT") == ("USDT-USD", 1.0)
    (p,) = service.portfolios()
    eth_btc = service.add_trade(p.id, "ETH-BTC", BUY, 1, trade_date=date(2024, 2, 1))
    assert eth_btc.currency == "BTC" and eth_btc.fx_rate == pytest.approx(50_000)
    eth_eur = service.add_trade(p.id, "ETH-EUR", BUY, 0.5, trade_date=date(2024, 3, 4))
    assert eth_eur.currency == "EUR" and eth_eur.fx_rate == pytest.approx(1.2)
    report = service.report(p.id)
    assert any("BTC-USD" in n for n in report.fx_notes)
    holding = next(h for h in report.valuation.holdings if h.symbol == "ETH-BTC")
    last = float(service._market.load("ETH-BTC", Interval.D1).series.bars["close"].iloc[-1])
    assert holding.price == pytest.approx(last * 50_000)  # in dollars


def test_unknown_currency_is_noted(service: PaperPortfolioService) -> None:
    (p,) = service.portfolios()
    trade = service.add_trade(p.id, "NOCUR", BUY, 1, trade_date=date(2024, 2, 1))
    assert trade.currency == "USD" and trade.fx_rate == 1.0
    assert any("divisa desconocida" in n for n in service.report(p.id).fx_notes)
