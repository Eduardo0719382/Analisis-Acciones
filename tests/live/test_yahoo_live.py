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


@pytest.mark.parametrize(("interval", "minutes", "min_days"),
                         [(Interval.H1, 60, 300), (Interval.M15, 15, 30)])  # fmt: skip
def test_intraday_history(provider: YahooFinanceProvider, interval: Interval, minutes: int,
                          min_days: int) -> None:  # fmt: skip
    series = provider.get_historical_data("AAPL", interval)
    bars = series.bars
    index = bars.index
    days = len(set(index.date))
    print(f"AAPL {interval.value}: {len(bars)} bars over {days} days, {index[0]} .. {index[-1]}")
    assert days >= min_days
    assert index.is_monotonic_increasing and not index.has_duplicates
    # Regular session only, New York wall-clock time.
    times = {(t.hour, t.minute) for t in index}
    assert min(times) == (9, 30) and max(times) < (16, 0)
    assert all(m % minutes in (0, 30 % minutes) for _h, m in times)
    assert (bars["high"] >= bars["low"]).all()


def test_fundamentals(provider: YahooFinanceProvider) -> None:
    f = provider.get_fundamentals("AAPL")
    print(f"AAPL fundamentals: cap={f.market_cap} pe={f.trailing_pe} yield={f.dividend_yield} "
          f"margin={f.profit_margin} roe={f.return_on_equity} "
          f"annual={[(a.year, a.revenue, a.net_income, a.eps) for a in f.annual]}")  # fmt: skip
    assert f.market_cap is not None and f.market_cap > 1e11
    assert f.trailing_pe is not None and 1 < f.trailing_pe < 500
    assert f.dividend_yield is not None and 0 < f.dividend_yield < 0.1
    assert f.profit_margin is not None and 0 < f.profit_margin < 1
    assert len(f.annual) >= 3
    assert all(a.revenue is None or a.revenue > 1e10 for a in f.annual)
