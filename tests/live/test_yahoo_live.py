"""Real Yahoo Finance calls. Excluded by default; run with ``pytest -m live``.

These checks only assert structural properties (non-empty, valid schema,
plausible ranges). They never compare against hard-coded prices.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from analisis_acciones.models.errors import UserError
from analisis_acciones.models.market import BAR_COLUMNS, Interval
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def provider() -> YahooFinanceProvider:
    return YahooFinanceProvider()


def test_full_daily_history(provider: YahooFinanceProvider) -> None:
    series = provider.get_historical_data("AAPL", Interval.D1)
    bars = series.bars
    print(f"AAPL: {len(bars)} bars {series.first_date} .. {series.last_date}")
    assert len(bars) > 2000
    assert list(bars.columns) == list(BAR_COLUMNS)
    assert bars.index.is_monotonic_increasing and not bars.index.has_duplicates
    assert (bars["high"] >= bars["low"]).all()
    assert series.last_date is not None and series.last_date > date.today() - timedelta(days=10)
    assert (bars["splits"] > 0).any()  # AAPL has had splits


def test_bounded_history(provider: YahooFinanceProvider) -> None:
    start = date.today() - timedelta(days=40)
    series = provider.get_historical_data("MSFT", Interval.D1, start=start)
    assert 15 <= len(series) <= 35
    assert series.first_date is not None and series.first_date >= start


def test_invalid_ticker(provider: YahooFinanceProvider) -> None:
    with pytest.raises(UserError):
        provider.get_historical_data("ZZZZQQQX", Interval.D1)


def test_search(provider: YahooFinanceProvider) -> None:
    results = provider.search_symbol("microsoft")
    print("search:", results[:3])
    assert any(r.symbol == "MSFT" for r in results)


def test_quote_and_info(provider: YahooFinanceProvider) -> None:
    quote = provider.get_quote("NVDA")
    info = provider.get_company_info("NVDA")
    print("quote:", quote, "info:", info)
    assert quote.price is not None and quote.price > 0
    assert info.name


def test_service_end_to_end(provider: YahooFinanceProvider) -> None:
    from analisis_acciones.storage.database import open_database

    conn: sqlite3.Connection = open_database(":memory:")
    service = MarketDataService(provider, conn)
    first = service.load("TSLA", Interval.W1)
    second = service.load("TSLA", Interval.D1)
    assert not first.from_cache and second.from_cache
    assert len(second.series) > len(first.series)
