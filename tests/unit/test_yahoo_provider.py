"""Yahoo adapter with a fake client (synthetic data; no network)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from analisis_acciones.models.errors import NetworkError, ProviderError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.base import normalize_symbol
from analisis_acciones.providers.yahoo import YahooFinanceProvider, map_yahoo_error
from tests.synthetic import FakeYahooClient, synthetic_daily


class YFRateLimitError(Exception):
    """Same class name as yfinance's, which is what the mapper inspects."""


class YFPricesMissingError(Exception):
    pass


class ConnectTimeout(Exception):
    pass


class HTTPError(Exception):
    """Mimics curl_cffi/requests HTTPError: message and optional response."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.response = type("R", (), {"status_code": status})() if status else None


@pytest.fixture
def client() -> FakeYahooClient:
    return FakeYahooClient()


@pytest.fixture
def provider(client: FakeYahooClient) -> YahooFinanceProvider:
    return YahooFinanceProvider(client)


def test_history_is_mapped_to_canonical_schema(
    provider: YahooFinanceProvider, client: FakeYahooClient
) -> None:
    series = provider.get_historical_data("test", Interval.D1)
    assert series.symbol == "TEST"
    assert series.source == "Yahoo Finance"
    assert series.bars.index.tz is None  # session dates, tz-naive
    assert series.bars.index[0] == pd.Timestamp("2024-01-01")
    pd.testing.assert_frame_equal(
        series.bars, client.bars.astype("float64"), check_freq=False, check_names=False
    )
    assert client.history_calls == [("TEST", None, None)]


def test_bounded_request_passes_dates(
    provider: YahooFinanceProvider, client: FakeYahooClient
) -> None:
    series = provider.get_historical_data(
        "TEST", Interval.D1, start=date(2024, 2, 1), end=date(2024, 2, 9)
    )
    assert series.first_date == date(2024, 2, 1)
    assert series.last_date == date(2024, 2, 9)
    assert client.history_calls[-1] == ("TEST", date(2024, 2, 1), date(2024, 2, 9))


def test_unknown_ticker(provider: YahooFinanceProvider) -> None:
    with pytest.raises(UserError) as info:
        provider.get_historical_data("ZZZZ", Interval.D1)
    assert "ZZZZ" in info.value.user_message


def test_bounded_request_without_rows_is_empty_not_error(
    provider: YahooFinanceProvider, client: FakeYahooClient
) -> None:
    client.error = YFPricesMissingError("no prices in range")
    series = provider.get_historical_data("TEST", Interval.D1, start=date(2030, 1, 1))
    assert series.bars.empty


@pytest.mark.parametrize("bad", ["", "   ", "AAPL; DROP", "a" * 20, "$$$"])
def test_invalid_symbols_rejected_before_any_request(
    provider: YahooFinanceProvider, client: FakeYahooClient, bad: str
) -> None:
    with pytest.raises(UserError):
        provider.get_historical_data(bad, Interval.D1)
    assert client.history_calls == []


def test_symbol_normalization() -> None:
    assert normalize_symbol(" brk-b ") == "BRK-B"
    assert normalize_symbol("^GSPC") == "^GSPC"


def test_unsupported_interval(provider: YahooFinanceProvider) -> None:
    with pytest.raises(UserError):
        provider.get_historical_data("TEST", Interval.M5)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (YFRateLimitError(), ProviderError),
        (YFPricesMissingError(), UserError),
        (ConnectTimeout(), NetworkError),
        (ConnectionError("down"), NetworkError),
        (TimeoutError(), NetworkError),
        (KeyError("chart"), ProviderError),
        (HTTPError("HTTP Error 404: "), UserError),
        (HTTPError("Not Found", status=404), UserError),
        (HTTPError("HTTP Error 429: Too Many Requests"), ProviderError),
        (HTTPError("HTTP Error 500: "), ProviderError),
    ],
)
def test_error_mapping(exc: Exception, expected: type) -> None:
    assert isinstance(map_yahoo_error(exc, "TEST"), expected)


def test_network_error_propagates(provider: YahooFinanceProvider, client: FakeYahooClient) -> None:
    client.error = ConnectionError("no internet")
    with pytest.raises(NetworkError):
        provider.get_historical_data("TEST", Interval.D1)


def test_invalid_rows_from_source_are_dropped(client: FakeYahooClient) -> None:
    bars = synthetic_daily(sessions=100)
    bars.iloc[50, bars.columns.get_loc("low")] = bars.iloc[50]["high"] * 2
    client.bars = bars
    series = YahooFinanceProvider(client).get_historical_data("TEST", Interval.D1)
    assert len(series) == 99
    assert series.warnings


def test_search_filters_to_us_equities_and_etfs(
    provider: YahooFinanceProvider, client: FakeYahooClient
) -> None:
    client.search_payload = [
        {"symbol": "AAPL", "longname": "Apple Inc.", "quoteType": "EQUITY", "exchDisp": "NASDAQ"},
        {"symbol": "AAPL.MX", "shortname": "Apple MX", "quoteType": "EQUITY"},
        {"symbol": "SPY", "shortname": "SPDR S&P 500", "quoteType": "ETF", "exchange": "PCX"},
        {"symbol": "AAPL250117C00150000", "quoteType": "OPTION"},
        {"symbol": None, "quoteType": "EQUITY"},
        "garbage",
    ]
    results = provider.search_symbol("apple")
    assert [r.symbol for r in results] == ["AAPL", "SPY"]
    assert results[0].name == "Apple Inc."
    assert results[1].exchange == "PCX"


def test_empty_search(provider: YahooFinanceProvider) -> None:
    assert provider.search_symbol("   ") == []


def test_quote_uses_only_numeric_fields(
    provider: YahooFinanceProvider, client: FakeYahooClient
) -> None:
    client.info_payload = {
        "regularMarketPrice": 110.0,
        "regularMarketPreviousClose": 100.0,
        "regularMarketVolume": 0,
        "regularMarketDayHigh": "not a number",
        "currency": "USD",
        "regularMarketTime": 1_700_000_000,
    }
    quote = provider.get_quote("TEST")
    assert quote.price == 110.0
    assert quote.change == pytest.approx(10.0)
    assert quote.change_pct == pytest.approx(10.0)
    assert quote.volume == 0.0  # zero is a value, not "missing"
    assert quote.day_high is None
    assert quote.currency == "USD"
    assert quote.as_of is not None


def test_quote_without_price_is_not_found(
    provider: YahooFinanceProvider, client: FakeYahooClient
) -> None:
    client.info_payload = {"trailingPegRatio": None}
    with pytest.raises(UserError):
        provider.get_quote("TEST")


def test_company_info(provider: YahooFinanceProvider, client: FakeYahooClient) -> None:
    client.info_payload = {
        "longName": "Test Corp",
        "fiftyTwoWeekHigh": 150.0,
        "fiftyTwoWeekLow": 90.5,
        "sector": "Technology",
    }
    info = provider.get_company_info("TEST")
    assert info.name == "Test Corp"
    assert info.fifty_two_week_low == 90.5
    assert info.industry is None


def test_offline_misreported_as_missing_ticker_becomes_network_error(
    provider: YahooFinanceProvider, client: FakeYahooClient
) -> None:
    # Observed with yfinance when offline: "possibly delisted; no timezone found".
    client.known = set()
    client.search_error = ConnectionError("CONNECT tunnel failed")
    with pytest.raises(NetworkError):
        provider.get_historical_data("TSLA", Interval.D1)


def test_quote_offline_misreported_becomes_network_error(
    provider: YahooFinanceProvider, client: FakeYahooClient
) -> None:
    client.info_payload = {}
    client.search_error = ConnectionError("down")
    with pytest.raises(NetworkError):
        provider.get_quote("TEST")
