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
from analisis_acciones.services.watchlist_service import ALTCOIN_EXAMPLE, CRYPTO_EXAMPLE

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
    print(f"AAPL calendar: earnings={f.earnings_date}..{f.earnings_date_end} "
          f"estimate={f.earnings_estimated} ex_div={f.ex_dividend_date} "
          f"paid={f.dividend_payment_date}")  # fmt: skip
    # AAPL reports every quarter and pays a quarterly dividend: the dates should be within a
    # few months of today (past or future).
    for day in (f.earnings_date, f.ex_dividend_date):
        assert day is not None and abs((day - date.today()).days) < 200


def test_currencies_and_exchange_rates(provider: YahooFinanceProvider) -> None:
    found = {s: provider.get_currency(s) for s in ("AAPL", "SAP.DE", "VOD.L")}
    print(f"currencies: {found}")
    assert found == {"AAPL": "USD", "SAP.DE": "EUR", "VOD.L": "GBp"}
    rates = provider.get_historical_data("EURUSD=X", Interval.D1, date.today() - timedelta(30))
    last = float(rates.bars["close"].iloc[-1])
    print(f"EURUSD=X: {len(rates)} bars, last {last}")
    assert len(rates) > 10 and 0.7 < last < 1.6


def test_crypto_daily_history_includes_weekends(provider: YahooFinanceProvider) -> None:
    series = provider.get_historical_data("BTC-USD", Interval.D1)
    bars = series.bars
    print(f"BTC-USD: {len(bars)} bars {series.first_date} .. {series.last_date}")
    assert len(bars) > 1000
    assert (bars.index[-60:].day_of_week >= 5).sum() >= 10  # quoted every day
    assert series.last_date is not None and series.last_date > date.today() - timedelta(days=5)


def test_crypto_search(provider: YahooFinanceProvider) -> None:
    results = provider.search_symbol("bitcoin")
    assert any(r.asset_type == "CRYPTOCURRENCY" for r in results)


@pytest.mark.parametrize("symbol", sorted(set(CRYPTO_EXAMPLE) | set(ALTCOIN_EXAMPLE)))
def test_example_crypto_tickers_exist(provider: YahooFinanceProvider, symbol: str) -> None:
    start = date.today() - timedelta(days=20)
    series = provider.get_historical_data(symbol, Interval.D1, start=start)
    assert len(series) >= 10, f"{symbol}: {len(series)} bars"


@pytest.fixture(scope="module")
def http_provider() -> YahooFinanceProvider:
    from analisis_acciones.providers.yahoo_http import YahooHttpClient

    return YahooFinanceProvider(YahooHttpClient())


@pytest.mark.parametrize("symbol", ["AAPL", "BTC-USD"])
def test_http_client_matches_yfinance(
    provider: YahooFinanceProvider, http_provider: YahooFinanceProvider, symbol: str
) -> None:
    """The mobile client returns the same daily closes as yfinance for the same dates."""
    start = date.today() - timedelta(days=60)
    ours = http_provider.get_historical_data(symbol, Interval.D1, start=start).bars
    theirs = provider.get_historical_data(symbol, Interval.D1, start=start).bars
    common = ours.index.intersection(theirs.index)[:-1]  # the last bar may still be forming
    assert len(common) >= 20
    rel = (ours.loc[common, "close"] - theirs.loc[common, "close"]).abs() / theirs.loc[
        common, "close"
    ]
    assert float(rel.max()) < 1e-6


def test_http_client_full_history_quote_and_search(http_provider: YahooFinanceProvider) -> None:
    bars = http_provider.get_historical_data("AAPL", Interval.D1).bars
    assert len(bars) > 2000 and (bars["splits"] > 0).any() and (bars["dividends"] > 0).any()
    assert http_provider.get_quote("AAPL").price > 0
    assert any(r.symbol == "AAPL" for r in http_provider.search_symbol("apple"))
    hourly = http_provider.get_historical_data("MSFT", Interval.H1).bars
    assert len(hourly) > 100
    with pytest.raises(UserError):
        http_provider.get_historical_data("ZZZZQQQX", Interval.D1)


def test_coingecko_daily_history_and_known_ids() -> None:
    """CoinGecko (free public API): BTC history and every id the program knows exist."""
    import json as _json

    from analisis_acciones.providers.coingecko import API, KNOWN_IDS, CoinGeckoProvider
    from analisis_acciones.providers.yahoo_http import http_get

    gecko = CoinGeckoProvider()
    series = gecko.get_historical_data("BTC-USD", Interval.D1)
    bars = series.bars
    assert 300 <= len(bars) <= 370
    assert series.last_date is not None and series.last_date >= date.today() - timedelta(days=2)
    assert (bars["close"] > 0).all()
    quote = gecko.get_quote("BTC-USD")
    assert quote.price is not None and quote.price > 0
    ids = ",".join(sorted(set(KNOWN_IDS.values())))
    found = _json.loads(http_get(f"{API}/simple/price?ids={ids}&vs_currencies=usd"))
    missing = sorted(set(KNOWN_IDS.values()) - set(found))
    assert not missing, missing


@pytest.mark.parametrize("service", ["alphavantage", "finnhub", "twelvedata"])
def test_keyed_source_with_a_real_key(service: str) -> None:
    """Runs only when ANALISIS_ACCIONES_<SERVICE>_KEY is set (never with keys in the code)."""
    import os

    from analisis_acciones.services.api_keys import env_name
    from analisis_acciones.services.data_sources import SOURCE_BY_KEY

    key = os.environ.get(env_name(service))
    if not key:
        pytest.skip(f"no {SOURCE_BY_KEY[service].name} key in the environment")
    from analisis_acciones.providers.alphavantage import AlphaVantageProvider
    from analisis_acciones.providers.finnhub import FinnhubProvider
    from analisis_acciones.providers.twelvedata import TwelveDataProvider

    cls = {"alphavantage": AlphaVantageProvider, "finnhub": FinnhubProvider,
           "twelvedata": TwelveDataProvider}[service]  # fmt: skip
    provider = cls(lambda: key)
    assert (provider.get_quote("AAPL").price or 0) > 0
