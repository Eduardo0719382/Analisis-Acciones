"""Alpha Vantage, Finnhub and Twelve Data with SIMULATED responses; keys stay private."""

from __future__ import annotations

import io
import json
import sqlite3
import urllib.error
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from analisis_acciones.models.errors import AppError, ProviderError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.alphavantage import (
    COMPACT_NOTE,
    STOCK_NOTE,
    AlphaVantageProvider,
    parse_daily,
)
from analisis_acciones.providers.finnhub import FinnhubProvider
from analisis_acciones.providers.routing import SourceRouter, plain_stock
from analisis_acciones.providers.twelvedata import TwelveDataProvider
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.api_keys import (
    FileKeyStore,
    KeyringStore,
    MemoryKeyStore,
    clean_key,
    env_name,
    masked,
)
from analisis_acciones.services.data_sources import SOURCE_BY_KEY, SOURCES, build_router
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from tests.synthetic import FakeYahooClient

KEY = "TESTKEY1234567890"


class Fake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.routes: dict[str, Any] = {}
        self.error: Exception | None = None

    def __call__(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        self.calls.append((url, dict(headers or {})))
        if self.error is not None:
            raise self.error
        for key, payload in self.routes.items():
            if key in url:
                return json.dumps(payload).encode()
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x/y?apikey=" + KEY, code, "x", {}, io.BytesIO(b""))  # type: ignore[arg-type]


def av_daily(n: int = 3, crypto: bool = False) -> dict[str, Any]:
    days = {f"2026-01-0{i + 2}": (
        {"1. open": str(10 + i), "2. high": str(12 + i), "3. low": str(9 + i),
         "4. close": str(11 + i), "5. volume": "1000"}) for i in range(n)}  # fmt: skip
    key = "Time Series (Digital Currency Daily)" if crypto else "Time Series (Daily)"
    return {"Meta Data": {}, key: days}


# Alpha Vantage ---------------------------------------------------------------------------
def test_alpha_vantage_stock_and_crypto() -> None:
    fake = Fake()
    av = AlphaVantageProvider(lambda: KEY, fake)
    fake.routes["function=TIME_SERIES_DAILY"] = av_daily()
    series = av.get_historical_data("AAPL", Interval.D1)
    assert series.bars["close"].tolist() == [11.0, 12.0, 13.0]
    assert series.bars["high"].iloc[0] == 12.0 and STOCK_NOTE in series.warnings
    assert "outputsize=full" in fake.calls[0][0]
    fake.routes["DIGITAL_CURRENCY_DAILY"] = av_daily(2, crypto=True)
    btc = av.get_historical_data("BTC-EUR", Interval.D1)
    assert "symbol=BTC" in fake.calls[-1][0] and "market=EUR" in fake.calls[-1][0]
    assert len(btc.bars) == 2
    old_style = {"2026-01-02": {"1a. open (USD)": "1", "2a. high (USD)": "2",
                                "3a. low (USD)": "0.5", "4a. close (USD)": "1.5",
                                "5. volume": "7"}}  # fmt: skip
    assert parse_daily(old_style)[next(iter(parse_daily(old_style)))] == (1.0, 2.0, 0.5, 1.5, 7.0)


def test_alpha_vantage_compact_fallback_and_limits() -> None:
    fake = Fake()
    av = AlphaVantageProvider(lambda: KEY, fake)
    premium = {"Information": "The outputsize=full parameter value is a premium feature."}
    answers = [premium, av_daily()]

    def fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
        fake.calls.append((url, {}))
        return json.dumps(answers.pop(0)).encode()

    av2 = AlphaVantageProvider(lambda: KEY, fetch)
    series = av2.get_historical_data("AAPL", Interval.D1)
    assert COMPACT_NOTE in series.warnings and "outputsize=compact" in fake.calls[-1][0]
    fake.routes["TIME_SERIES_DAILY"] = {
        "Information": "We have detected your API key as ... 25 requests per day."
    }
    with pytest.raises(ProviderError):
        av.get_historical_data("AAPL", Interval.D1)
    fake.routes["TIME_SERIES_DAILY"] = {"Error Message": "Invalid API call."}
    with pytest.raises(UserError):
        AlphaVantageProvider(lambda: KEY, fake).get_historical_data("AAPL", Interval.D1)
    with pytest.raises(UserError, match="key"):
        AlphaVantageProvider(lambda: None, fake).get_historical_data("AAPL", Interval.D1)


# Finnhub ---------------------------------------------------------------------------------
def test_finnhub_candles_quote_and_refusal() -> None:
    fake = Fake()
    fh = FinnhubProvider(lambda: KEY, fake)
    t0 = int(datetime(2026, 1, 5, tzinfo=UTC).timestamp())
    fake.routes["/stock/candle"] = {"s": "ok", "t": [t0, t0 + 86400], "o": [1, 2], "h": [3, 4],
                                    "l": [0.5, 1], "c": [2, 3], "v": [10, 20]}  # fmt: skip
    bars = fh.get_historical_data("AAPL", Interval.D1).bars
    assert bars["close"].tolist() == [2.0, 3.0]
    url, headers = fake.calls[-1]
    assert KEY not in url and headers == {"X-Finnhub-Token": KEY}  # key in a header only
    fake.routes["/crypto/candle"] = {"error": "You don't have access to this resource."}
    with pytest.raises(UserError) as info:
        fh.get_historical_data("BTC-USD", Interval.D1)
    assert "no incluye el historial" in info.value.user_message
    assert "BINANCE%3ABTCUSDT" in fake.calls[-1][0]
    fake.routes["/quote"] = {"c": 190.5, "pc": 188.0, "o": 189, "h": 191, "l": 187,
                             "t": t0}  # fmt: skip
    assert fh.get_quote("AAPL").price == 190.5
    fake.routes["/quote"] = {"c": 0, "pc": 0}
    with pytest.raises(UserError):
        fh.get_quote("ZZZZ")


# Twelve Data -----------------------------------------------------------------------------
def test_twelve_data_series_and_errors() -> None:
    fake = Fake()
    td = TwelveDataProvider(lambda: KEY, fake)
    fake.routes["/time_series"] = {"status": "ok", "values": [
        {"datetime": "2026-01-05", "open": "1", "high": "2", "low": "0.5", "close": "1.5",
         "volume": "100"},
        {"datetime": "2026-01-06", "open": "1.5", "high": "2.5", "low": "1", "close": "2",
         "volume": "200"},
        {"datetime": "nonsense", "open": "9"},
    ]}  # fmt: skip
    bars = td.get_historical_data("ETH-EUR", Interval.D1).bars
    assert bars["close"].tolist() == [1.5, 2.0]
    url, headers = fake.calls[-1]
    assert "symbol=ETH%2FEUR" in url and KEY not in url
    assert headers == {"Authorization": f"apikey {KEY}"}
    fake.routes["/time_series"] = {"status": "error", "code": 429, "message": "limit"}
    with pytest.raises(ProviderError):
        td.get_historical_data("AAPL", Interval.D1)
    fake.routes["/time_series"] = {"status": "error", "code": 401, "message": "bad key"}
    with pytest.raises(UserError):
        td.get_historical_data("AAPL", Interval.D1)


def test_keys_never_appear_in_errors() -> None:
    for provider_cls in (AlphaVantageProvider, FinnhubProvider, TwelveDataProvider):
        for error in (http_error(401), http_error(429), http_error(500),
                      ConnectionError("https://x?apikey=" + KEY)):  # fmt: skip
            fake = Fake()
            fake.error = error
            with pytest.raises(AppError) as info:
                provider_cls(lambda: KEY, fake).get_historical_data("AAPL", Interval.D1)
            text = f"{info.value} {info.value.user_message} {info.value!r}"
            assert KEY not in text, (provider_cls.name, text)


# Router, settings and keys ---------------------------------------------------------------
def test_router_picks_a_source_per_asset_kind(conn: sqlite3.Connection) -> None:
    from analisis_acciones.storage.settings_repository import SettingsRepository

    settings = SettingsService(SettingsRepository(conn))
    keys = MemoryKeyStore()
    router = build_router(YahooFinanceProvider(FakeYahooClient()), settings, keys)
    assert router.source_for("AAPL") == router.source_for("BTC-USD") == "Yahoo Finance"
    settings.set_stock_source("twelvedata")
    settings.set_crypto_source("coingecko")
    assert router.source_for("AAPL") == "Twelve Data"
    assert router.source_for("BTC-USD") == "CoinGecko"
    assert router.source_for("^GSPC") == router.source_for("EURUSD=X") == "Yahoo Finance"
    assert router.source_for("AAPL", Interval.H1) == "Yahoo Finance"  # intraday: Yahoo
    with pytest.raises(UserError):
        settings.set_stock_source("coingecko")  # CoinGecko has no stocks
    assert plain_stock("BRK-B") and not plain_stock("BTC-USD") and not plain_stock("CSV:X")
    assert {s.key for s in SOURCES if s.stocks} == {"yahoo", "twelvedata", "alphavantage",
                                                     "finnhub"}  # fmt: skip
    assert SOURCE_BY_KEY["coingecko"].needs_key is False


def test_key_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FileKeyStore(tmp_path / "private" / "claves.json")
    assert store.get("finnhub") is None
    store.set("finnhub", f"  {KEY} ")
    assert store.get("finnhub") == KEY
    store.delete("finnhub")
    assert store.get("finnhub") is None
    with pytest.raises(UserError):
        store.set("finnhub", "bad key; rm -rf")
    with pytest.raises(UserError):
        clean_key("otro", KEY)
    assert masked(KEY) == "TES…890" and KEY not in masked(KEY)
    monkeypatch.setenv(env_name("twelvedata"), KEY)
    assert KeyringStore().get("twelvedata") == KEY  # environment variable wins


def test_market_service_uses_the_chosen_stock_source(conn: sqlite3.Connection) -> None:
    from analisis_acciones.storage.settings_repository import SettingsRepository

    settings = SettingsService(SettingsRepository(conn))
    settings.set_stock_source("alphavantage")
    fake = Fake()
    fake.routes["TIME_SERIES_DAILY"] = av_daily()
    yahoo = YahooFinanceProvider(FakeYahooClient())
    router = SourceRouter(yahoo, {"alphavantage": AlphaVantageProvider(lambda: KEY, fake)},
                          settings.stock_source, settings.crypto_source)  # fmt: skip
    market = MarketDataService(router, conn, lambda: datetime(2026, 1, 8, 22, tzinfo=UTC))
    result = market.load("AAPL", Interval.D1)
    assert result.series.source == "Alpha Vantage" and len(result.series.bars) == 3
    assert result.series.last_date == date(2026, 1, 4)


# Automatic fallback, Alpha Vantage savings, real-time quotes --------------------------------
def _settings(conn: sqlite3.Connection) -> SettingsService:
    from analisis_acciones.storage.settings_repository import SettingsRepository

    return SettingsService(SettingsRepository(conn))


def test_failed_source_falls_back_and_is_retried_hourly(conn: sqlite3.Connection) -> None:
    settings = _settings(conn)
    settings.set_stock_source("twelvedata")
    fake = Fake()
    fake.error = http_error(429)
    keys = MemoryKeyStore()
    keys.set("twelvedata", KEY)
    yahoo_client = FakeYahooClient()
    router = build_router(YahooFinanceProvider(yahoo_client), settings, keys)
    router._sources["twelvedata"] = TwelveDataProvider(lambda: KEY, fake)
    now = [datetime(2026, 1, 8, 22, tzinfo=UTC)]
    market = MarketDataService(router, conn, lambda: now[0])

    first = market.load("TEST", Interval.D1)
    assert first.series.source == "Yahoo Finance" and len(fake.calls) == 1
    assert any("Twelve Data no pudo" in n and "Yahoo Finance" in n for n in first.notices)
    held = market.load("TEST", Interval.D1)  # within the hour: no new request to Twelve Data
    assert held.from_cache and len(fake.calls) == 1
    assert any("se volverá a probar" in n for n in held.notices)
    now[0] += timedelta(hours=2)
    market.load("TEST", Interval.D1)
    assert len(fake.calls) == 2  # retried, still failing, Yahoo again

    settings.set_auto_fallback(False)
    with pytest.raises(ProviderError):
        router.get_historical_data("TEST", Interval.D1)
    settings.set_auto_fallback(True)
    with pytest.raises(ProviderError):  # partial refreshes never mix sources
        router.get_historical_data("TEST", Interval.D1, start=date(2026, 1, 1))


def test_yahoo_falls_back_only_on_transient_failures(conn: sqlite3.Connection) -> None:
    settings = _settings(conn)
    fake = Fake()
    fake.routes["TIME_SERIES_DAILY"] = av_daily()
    yahoo_client = FakeYahooClient()
    router = SourceRouter(
        YahooFinanceProvider(yahoo_client),
        {"alphavantage": AlphaVantageProvider(lambda: KEY, fake)},
        settings.stock_source, settings.crypto_source,
        fallback=settings.auto_fallback, stock_fallbacks=("alphavantage",),
    )  # fmt: skip
    yahoo_client.error = ConnectionError("offline")
    series = router.get_historical_data("TEST", Interval.D1)
    assert series.source == "Alpha Vantage" and "Yahoo Finance no pudo" in series.warnings[0]
    yahoo_client.error = None
    calls = len(fake.calls)
    with pytest.raises(UserError):  # unknown at Yahoo: no quota spent elsewhere
        router.get_historical_data("NOPE", Interval.D1)
    assert len(fake.calls) == calls
    assert router.alternatives("^GSPC", Interval.D1, router._primary) == []


def test_alpha_vantage_daily_budget_and_slow_refresh(conn: sqlite3.Connection) -> None:
    now = [datetime(2026, 1, 8, 12, tzinfo=UTC)]
    fake = Fake()
    fake.routes["TIME_SERIES_DAILY"] = av_daily()
    av = AlphaVantageProvider(lambda: KEY, fake, clock=lambda: now[0], budget=2)
    av.get_historical_data("AAPL", Interval.D1)
    av.get_historical_data("MSFT", Interval.D1)
    assert av.requests_left() == 0
    with pytest.raises(ProviderError, match="rate limit"):
        av.get_historical_data("IBM", Interval.D1)
    assert len(fake.calls) == 2  # the third request was never sent
    now[0] += timedelta(days=1)
    assert av.requests_left() == 2
    fake.routes = {"function": {"Information": "We have detected your API key ... 25 requests "
                                "per day."}}  # fmt: skip
    with pytest.raises(ProviderError):
        av.get_historical_data("IBM", Interval.D1)
    assert av.requests_left() == 0  # Alpha Vantage said so: nothing more today

    settings = _settings(conn)
    settings.set_crypto_source("alphavantage")
    fake2 = Fake()
    fake2.routes["DIGITAL_CURRENCY_DAILY"] = av_daily(3, crypto=True)
    router = SourceRouter(YahooFinanceProvider(FakeYahooClient()),
                          {"alphavantage": AlphaVantageProvider(lambda: KEY, fake2)},
                          settings.stock_source, settings.crypto_source)  # fmt: skip
    market = MarketDataService(router, conn, lambda: now[0])
    market.load("BTC-USD", Interval.D1)
    now[0] += timedelta(hours=2)  # crypto is normally refreshed every hour
    assert market.load("BTC-USD", Interval.D1).from_cache and len(fake2.calls) == 1
    now[0] += timedelta(hours=5)
    market.load("BTC-USD", Interval.D1)
    assert len(fake2.calls) == 2


def test_real_time_quote_from_finnhub(conn: sqlite3.Connection) -> None:
    settings = _settings(conn)
    keys = MemoryKeyStore()
    yahoo_client = FakeYahooClient()
    yahoo_client.info_payload = {"regularMarketPrice": 5.0, "currency": "USD"}
    router = build_router(YahooFinanceProvider(yahoo_client), settings, keys)
    fake = Fake()
    fake.routes["/quote"] = {"c": 101.5, "pc": 100.0, "o": 100.2, "h": 102, "l": 99,
                             "t": 1767900000}  # fmt: skip
    router._sources["finnhub"] = FinnhubProvider(lambda: KEY, fake)
    assert router.get_quote("TEST").source == "Yahoo Finance"  # no key yet
    keys.set("finnhub", KEY)
    quote = router.get_quote("TEST")
    assert quote.source == "Finnhub" and quote.price == 101.5
    assert router.get_quote("BTC-USD").source == "Yahoo Finance"  # stocks only
    settings.set_realtime_quotes(False)
    assert router.get_quote("TEST").source == "Yahoo Finance"
    settings.set_realtime_quotes(True)
    fake.error = http_error(429)
    assert router.get_quote("TEST").source == "Yahoo Finance"  # Finnhub failing: regular quote
    from analisis_acciones.data.details import build_details

    fake.error = None
    details = build_details("TEST", FakeYahooClient().bars.iloc[:0], router.get_quote("TEST"))
    assert details.quote_source == "Finnhub" and details.price == 101.5
