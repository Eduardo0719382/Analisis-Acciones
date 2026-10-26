"""CoinGecko as a crypto source, with SIMULATED responses (no network)."""

from __future__ import annotations

import io
import json
import sqlite3
import urllib.error
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest

from analisis_acciones.models.errors import NetworkError, ProviderError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.coingecko import (
    CLOSE_ONLY_NOTE,
    SOURCE_NAME,
    CoinGeckoProvider,
    daily_bars,
)
from analisis_acciones.providers.routing import CryptoSourceRouter
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from tests.synthetic import FakeYahooClient, synthetic_daily

DAY = 86_400_000
D0 = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)  # 00:00 UTC
NOW = datetime(2026, 1, 4, 15, 30, tzinfo=UTC)


def chart(n: int = 3, start: int = D0) -> dict[str, Any]:
    prices = [[start + i * DAY, 100.0 + i] for i in range(n)]
    prices.append([start + (n - 1) * DAY + 15 * 3_600_000, 200.0])  # now: day in progress
    volumes = [[p[0], 1e9 + i] for i, p in enumerate(prices)]
    return {"prices": prices, "market_caps": [], "total_volumes": volumes}


class Fake:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.routes: dict[str, Any] = {}
        self.errors: list[Exception] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if self.errors:
            raise self.errors.pop(0)
        for key, payload in self.routes.items():
            if key in url:
                return json.dumps(payload).encode()
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]


@pytest.fixture
def fake() -> Fake:
    return Fake()


@pytest.fixture
def gecko(fake: Fake) -> CoinGeckoProvider:
    return CoinGeckoProvider(fake, sleep=lambda s: None, clock=lambda: NOW)


def test_daily_points_close_the_previous_day() -> None:
    bars = daily_bars(chart(3))
    # 00:00 UTC of Jan 1, 2, 3 close Dec 31, Jan 1, Jan 2; the 15:00 point is Jan 3 so far.
    assert [d.date() for d in bars.index] == [date(2025, 12, 31), date(2026, 1, 1),
                                              date(2026, 1, 2), date(2026, 1, 3)]  # fmt: skip
    assert bars["close"].tolist() == [100.0, 101.0, 102.0, 200.0]
    assert (bars["open"] == bars["close"]).all() and (bars["high"] == bars["low"]).all()
    assert bars["volume"].iloc[0] == 1e9
    assert daily_bars({"prices": [[D0, "x"], [D0, -5], "junk"]}).empty


def test_history_quote_and_info(fake: Fake, gecko: CoinGeckoProvider) -> None:
    fake.routes["/coins/bitcoin/market_chart"] = chart(5)
    series = gecko.get_historical_data("BTC-USD", Interval.D1)
    assert series.source == SOURCE_NAME and CLOSE_ONLY_NOTE in series.warnings
    assert "vs_currency=usd" in fake.urls[0] and "days=365" in fake.urls[0]
    assert series.bars["close"].iloc[-1] == 200.0
    fake.routes["/simple/price"] = {"bitcoin": {"usd": 67000.0, "usd_24h_change": 5.0,
                                                "usd_24h_vol": 3e10,
                                                "last_updated_at": 1767540000}}  # fmt: skip
    quote = gecko.get_quote("btc-usd")
    assert quote.price == 67000.0 and quote.previous_close == pytest.approx(67000 / 1.05)
    assert quote.currency == "USD" and quote.as_of is not None
    assert gecko.get_company_info("BTC-USD").exchange == SOURCE_NAME
    assert gecko.get_currency("ETH-EUR") == "EUR"
    gecko.get_historical_data("BTC-EUR", Interval.D1, start=date(2026, 1, 1))
    assert "vs_currency=eur" in fake.urls[-1] and "days=5" in fake.urls[-1]


def test_unknown_coins_are_found_by_search(fake: Fake, gecko: CoinGeckoProvider) -> None:
    fake.routes["/search"] = {"coins": [
        {"id": "wif-fake", "symbol": "WIF", "name": "Imitación", "market_cap_rank": 900},
        {"id": "dogwifcoin", "symbol": "WIF", "name": "dogwifhat", "market_cap_rank": 60},
        {"id": "Bad Id!", "symbol": "WIF", "name": "x", "market_cap_rank": 1},
    ]}  # fmt: skip
    assert gecko.coin("WIF-USD") == ("dogwifcoin", "dogwifhat", "USD")
    assert gecko.coin("UNI7083-USD")[0] == "uniswap"  # Yahoo's numbered ticker
    calls = len(fake.urls)
    gecko.coin("WIF-USD")
    assert len(fake.urls) == calls  # remembered


def test_refusals_and_errors(fake: Fake, gecko: CoinGeckoProvider) -> None:
    with pytest.raises(UserError):
        gecko.get_historical_data("AAPL", Interval.D1)
    with pytest.raises(UserError, match="USDT"):
        gecko.coin("SOL-USDT")
    with pytest.raises(UserError):
        gecko.get_historical_data("BTC-USD", Interval.H1)
    fake.routes["/coins/bitcoin/market_chart"] = chart(3)
    fake.errors = [http_error(429)]
    assert not gecko.get_historical_data("BTC-USD", Interval.D1).bars.empty  # retried once
    fake.errors = [http_error(429), http_error(429)]
    with pytest.raises(ProviderError):
        gecko.get_historical_data("BTC-USD", Interval.D1)
    fake.errors = [ConnectionError("down")]
    with pytest.raises(NetworkError):
        gecko.get_historical_data("BTC-USD", Interval.D1)
    fake.routes["/search"] = {"coins": []}
    with pytest.raises(UserError):
        gecko.coin("ZZZQ-USD")


def test_router_and_cache_follow_the_setting(fake: Fake, gecko: CoinGeckoProvider,
                                             conn: sqlite3.Connection) -> None:  # fmt: skip
    yahoo_bars = synthetic_daily(sessions=300)
    yahoo_bars.index = pd.date_range("2025-03-10", periods=300, freq="D", name="date")
    client = FakeYahooClient(yahoo_bars)
    client.known = {"BTC-USD", "AAPL"}
    use = {"gecko": False}
    router = CryptoSourceRouter(YahooFinanceProvider(client), gecko, lambda: use["gecko"])
    market = MarketDataService(router, conn, lambda: NOW)
    fake.routes["/coins/bitcoin/market_chart"] = chart(3)

    first = market.load("BTC-USD", Interval.D1)
    assert first.series.source == "Yahoo Finance" and len(first.series.bars) == 300
    use["gecko"] = True
    switched = market.load("BTC-USD", Interval.D1)  # cached Yahoo data is not reused
    assert switched.series.source == SOURCE_NAME and len(switched.series.bars) == 4
    assert CLOSE_ONLY_NOTE in switched.notices
    again = market.load("BTC-USD", Interval.D1)  # from cache: the note is still shown
    assert again.from_cache and CLOSE_ONLY_NOTE in again.notices
    assert market.load("AAPL", Interval.D1).series.source == "Yahoo Finance"  # stocks: Yahoo
    assert router.source_for("BTC-USD", Interval.H1) == "Yahoo Finance"  # no intraday at CG
    use["gecko"] = False
    assert market.load("BTC-USD", Interval.D1).series.source == "Yahoo Finance"
