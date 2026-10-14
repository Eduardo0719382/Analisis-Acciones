from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.models.errors import UserError
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.fundamentals_report import bar_chart, big, fundamentals_html
from analisis_acciones.services.market_data_service import MarketDataService, annual_dividends
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, synthetic_daily

INFO = {
    "regularMarketPrice": 200.0, "currency": "USD", "marketCap": 3.1e12, "trailingPE": 31.5,
    "forwardPE": 28.0, "trailingEps": 6.35, "priceToBook": 45.2, "dividendRate": 1.0,
    "payoutRatio": 0.15, "profitMargins": 0.25, "operatingMargins": 0.31,
    "returnOnEquity": 1.47, "revenueGrowth": 0.06, "earningsGrowth": 999.0, "beta": 1.2,
    "longName": "Test Corp",
}  # fmt: skip


def statement() -> pd.DataFrame:
    cols = [pd.Timestamp("2024-09-30"), pd.Timestamp("2023-09-30"), pd.Timestamp("2022-09-30")]
    return pd.DataFrame(
        {cols[0]: [391e9, 93.7e9, 6.08], cols[1]: [383e9, 97e9, 6.13],
         cols[2]: [394e9, np.nan, 6.11]},
        index=["TotalRevenue", "NetIncome", "DilutedEPS"],
    )  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2025, 3, 7, 22, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def client() -> FakeYahooClient:
    fake = FakeYahooClient()
    fake.info_payload = dict(INFO)
    fake.statement = statement()
    return fake


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def market(client: FakeYahooClient, clock: Clock) -> Iterator[MarketDataService]:
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"), clock)
    yield service
    service.close()


def test_provider_parses_ratios_and_statement(client: FakeYahooClient) -> None:
    f = YahooFinanceProvider(client).get_fundamentals("test")
    assert f.trailing_pe == 31.5 and f.dividend_yield == pytest.approx(1.0 / 200)
    assert f.return_on_equity == 1.47  # 147 % is plausible for buyback-heavy companies
    assert f.earnings_growth is None  # 99 900 %: wrong unit, dropped rather than shown
    assert [a.year for a in f.annual] == [2022, 2023, 2024]
    assert f.annual[0].net_income is None and f.annual[-1].revenue == 391e9
    client.statement = pd.DataFrame()
    assert YahooFinanceProvider(client).get_fundamentals("TEST").annual == ()


def test_service_caches_and_serves_stale(market: MarketDataService, client: FakeYahooClient,
                                         clock: Clock) -> None:  # fmt: skip
    first = market.fundamentals("TEST")
    assert not first.stale and first.data.market_cap == 3.1e12
    client.info_payload = {**INFO, "trailingPE": 10.0}
    assert market.fundamentals("TEST").data.trailing_pe == 31.5  # within a day: cache
    clock.now += timedelta(days=2)
    market._provider._info_cache.clear()  # type: ignore[attr-defined]
    client.error = ConnectionError("offline")
    stale = market.fundamentals("TEST")
    assert stale.stale and stale.notice and stale.data.trailing_pe == 31.5
    client.error = None
    assert market.fundamentals("TEST").data.trailing_pe == 10.0
    with pytest.raises(UserError):
        market.fundamentals("CSV:MINE")


def test_annual_dividends_from_bars() -> None:
    bars = synthetic_daily(sessions=600)
    bars.loc[bars.index[[10, 70, 300]], "dividends"] = [0.2, 0.25, 0.3]
    years = pd.DatetimeIndex(bars.index[[10, 70, 300]]).year
    out = annual_dividends(bars)
    assert out[0] == (years[0], pytest.approx(0.45)) and out[-1] == (years[2], pytest.approx(0.3))
    assert annual_dividends(synthetic_daily(sessions=10)) == ()


def test_report_formatting_and_escaping(market: MarketDataService) -> None:
    assert big(3.1e12) == "3,10 billones" and big(93.7e9) == "93,7 mil millones"
    assert big(-2.5e6) == "−2,5 millones" and big(None) == "—"
    svg = bar_chart([(2022, 1e9), (2023, None), (2024, -5e8)])
    assert svg.count('class="pos"') == 1 and svg.count('class="neg"') == 1
    html = fundamentals_html(market.fundamentals("TEST"), name="<Test & Co>")
    assert "&lt;Test &amp; Co&gt;" in html and "<Test" not in html
    assert "31,5" in html and "3,10 billones USD" in html and "Ingresos por año" in html
    assert "<script" not in html
