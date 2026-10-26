"""Yahoo over plain HTTPS with SIMULATED responses (no network)."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import date
from typing import Any

import pytest

from analisis_acciones.models.errors import NetworkError, UserError
from analisis_acciones.models.market import BAR_COLUMNS, Interval
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.providers.yahoo_http import YahooHttpClient

# 2024-06-03..06 (Mon-Thu) 13:30 UTC = 09:30 New York, as Yahoo stamps daily bars.
STAMPS = [1717421400, 1717507800, 1717594200, 1717680600]


def chart(symbol: str, tz: str = "America/New_York", stamps: list[int] = STAMPS,
          events: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    n = len(stamps)
    return {"chart": {"result": [{
        "meta": {"symbol": symbol, "currency": "USD", "exchangeTimezoneName": tz,
                 "regularMarketPrice": 104.0, "longName": "Test Inc.",
                 "exchangeName": "NMS", "regularMarketTime": stamps[-1]},
        "timestamp": stamps,
        "indicators": {
            "quote": [{"open": [100.0 + i for i in range(n)],
                       "high": [101.0 + i for i in range(n)],
                       "low": [99.0 + i for i in range(n)],
                       "close": [100.5 + i for i in range(n)],
                       "volume": [1000 + i for i in range(n)]}],
            "adjclose": [{"adjclose": [100.0 + i for i in range(n)]}],
        },
        "events": events or {},
    }], "error": None}}  # fmt: skip


class Fake:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.responses: dict[str, Any] = {}
        self.error: Exception | None = None

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        for key, payload in self.responses.items():
            if key in url:
                return json.dumps(payload).encode()
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]


@pytest.fixture
def fake() -> Fake:
    return Fake()


@pytest.fixture
def provider(fake: Fake) -> YahooFinanceProvider:
    return YahooFinanceProvider(YahooHttpClient(fake))


def test_daily_history_with_dividend_and_split(fake: Fake, provider: YahooFinanceProvider) -> None:
    events = {"dividends": {"1": {"amount": 0.25, "date": STAMPS[1]}},
              "splits": {"2": {"numerator": 4, "denominator": 1, "date": STAMPS[2]}}}  # fmt: skip
    fake.responses["/chart/TEST"] = chart("TEST", events=events)
    series = provider.get_historical_data("TEST", Interval.D1)
    bars = series.bars
    assert list(bars.columns) == list(BAR_COLUMNS)
    assert [d.date() for d in bars.index] == [date(2024, 6, d) for d in (3, 4, 5, 6)]
    assert bars["close"].tolist() == [100.5, 101.5, 102.5, 103.5]
    assert bars["adj_close"].iloc[0] == 100.0
    assert bars["dividends"].tolist() == [0.0, 0.25, 0.0, 0.0]
    assert bars["splits"].tolist() == [0.0, 0.0, 4.0, 0.0]
    assert "period1=-2208994789" in fake.urls[0] and "interval=1d" in fake.urls[0]


def test_bounded_request_and_missing_values(fake: Fake, provider: YahooFinanceProvider) -> None:
    payload = chart("TEST")
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["close"][1] = None  # Yahoo sends null for a missing bar
    fake.responses["/chart/TEST"] = payload
    series = provider.get_historical_data("TEST", Interval.D1, start=date(2024, 6, 1))
    assert len(series.bars) == 3
    assert "period1=1717200000" in fake.urls[0]


def test_crypto_days_are_utc(fake: Fake, provider: YahooFinanceProvider) -> None:
    stamps = [1718409600, 1718496000]  # 2024-06-15 / 16 00:00 UTC (weekend)
    fake.responses["/chart/BTC-USD"] = chart("BTC-USD", "UTC", stamps)
    bars = provider.get_historical_data("BTC-USD", Interval.D1).bars
    assert [d.date() for d in bars.index] == [date(2024, 6, 15), date(2024, 6, 16)]


def test_intraday_keeps_wall_times(fake: Fake, provider: YahooFinanceProvider) -> None:
    fake.responses["/chart/TEST"] = chart("TEST", stamps=[1717421400, 1717425000])
    bars = provider.get_historical_data("TEST", Interval.H1).bars
    assert [t.strftime("%H:%M") for t in bars.index] == ["09:30", "10:30"]
    assert "interval=1h" in fake.urls[0]


def test_quote_search_and_currency(fake: Fake, provider: YahooFinanceProvider) -> None:
    fake.responses["/chart/TEST"] = chart("TEST")
    fake.responses["/search"] = {"quotes": [
        {"symbol": "TEST", "longname": "Test Inc.", "quoteType": "EQUITY", "exchDisp": "NASDAQ"},
        {"symbol": "BTC-USD", "shortname": "Bitcoin USD", "quoteType": "CRYPTOCURRENCY"},
        "garbage",
    ]}  # fmt: skip
    quote = provider.get_quote("TEST")
    assert quote.price == 104.0 and quote.previous_close == 102.5 and quote.currency == "USD"
    assert provider.get_currency("TEST") == "USD"
    assert provider.get_company_info("TEST").name == "Test Inc."
    assert [r.symbol for r in provider.search_symbol("test")] == ["TEST", "BTC-USD"]


def test_unknown_symbol_and_offline(fake: Fake, provider: YahooFinanceProvider) -> None:
    fake.responses["/search"] = {"quotes": []}
    with pytest.raises(UserError):
        provider.get_historical_data("ZZZZ", Interval.D1)
    fake.error = ConnectionError("no route")
    with pytest.raises(NetworkError):
        provider.get_historical_data("TEST", Interval.D1)


def test_garbage_is_rejected_not_invented(fake: Fake, provider: YahooFinanceProvider) -> None:
    payload = chart("TEST")
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["close"] = ["1e999", True, {"x": 1}, 103.5]
    fake.responses["/chart/TEST"] = payload
    bars = provider.get_historical_data("TEST", Interval.D1).bars
    assert bars["close"].tolist() == [103.5]
