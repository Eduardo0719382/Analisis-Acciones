"""CoinGecko as an alternative price source for cryptocurrencies (free public API, no key).

What the free API gives, and how it is used here (nothing is invented):

* ``/simple/price``: the current price and 24 h change -> quotes.
* ``/coins/{id}/market_chart?interval=daily``: one price per day (taken at 00:00 UTC) and
  the 24 h traded volume, for the last 365 days. A price at 00:00 UTC of day D is the
  closing price of day D-1, so it is stored as that day's close; the last point (the
  current price) is the close so far of the day in progress.
* ``/search``: finding the coin id of a ticker (``BTC-USD`` -> ``bitcoin``).

The free API has no daily open, high or low. Bars therefore carry the close in all four
price columns and every series says so in its notices: candles have no body or wicks
and indicators that use highs and lows (ATR, stochastic, Ichimoku…) work on closes only.
Intraday bars are not offered. Responses are external data: only the fields named here
are read and every number is checked.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from analisis_acciones.data.freshness import crypto_quote, is_crypto
from analisis_acciones.data.validation import validate_bars
from analisis_acciones.models.errors import AppError, NetworkError, ProviderError, UserError
from analisis_acciones.models.market import (
    BarSeries,
    CompanyInfo,
    Interval,
    Quote,
    SearchResult,
    empty_bars,
)
from analisis_acciones.providers.base import MarketDataProvider, normalize_symbol
from analisis_acciones.providers.yahoo_http import Fetcher, http_get

logger = logging.getLogger(__name__)

SOURCE_NAME = "CoinGecko"
API = "https://api.coingecko.com/api/v3"
MAX_DAYS = 365  # history window of the free public API
RETRY_WAIT_S = 20.0
CLOSE_ONLY_NOTE = (
    "CoinGecko (gratuito) da un solo precio por día y 365 días de historia: apertura, máximo "
    "y mínimo no existen en esta fuente, así que las velas no tienen cuerpo ni mechas y los "
    "indicadores que usan máximos y mínimos se calculan con el cierre."
)
#: Quote currencies CoinGecko prices in (``vs_currency``).
VS_CURRENCIES = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CAD",
    "AUD",
    "CHF",
    "CNY",
    "KRW",
    "INR",
    "BRL",
    "MXN",
    "BTC",
    "ETH",
}
#: Ids of frequent coins (saves a search request; checked by the live tests).
KNOWN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "XLM": "stellar",
    "TRX": "tron",
    "ATOM": "cosmos",
    "NEAR": "near",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "HBAR": "hedera-hashgraph",
    "ALGO": "algorand",
    "AAVE": "aave",
    "XMR": "monero",
    "ICP": "internet-computer",
    "UNI": "uniswap",
    "SUI": "sui",
    "APT": "aptos",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
}
_YAHOO_NUMBERED = re.compile(r"^([A-Z]+?)(\d{3,})$")  # UNI7083 -> UNI (Yahoo's disambiguation)
_DAY_MS = 86_400_000


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


class CoinGeckoProvider(MarketDataProvider):
    name = SOURCE_NAME

    def __init__(
        self,
        fetch: Fetcher = http_get,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._fetch = fetch
        self._sleep = sleep
        self._clock = clock
        self._ids: dict[str, tuple[str, str]] = {}  # base -> (coin id, name)
        self._lock = threading.Lock()

    def get_available_intervals(self) -> list[Interval]:
        return [Interval.D1]

    # HTTP -------------------------------------------------------------------------------
    def _get(self, path: str, params: dict[str, str | int]) -> Any:
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
        for attempt in (1, 2):
            try:
                with self._lock:
                    body = self._fetch(url)
                return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt == 1:
                    logger.info("CoinGecko rate limit; retrying once in %s s", RETRY_WAIT_S)
                    self._sleep(RETRY_WAIT_S)
                    continue
                if exc.code == 429:
                    raise ProviderError(
                        "CoinGecko rate limit",
                        user_message="CoinGecko ha limitado las peticiones (su plan gratuito "
                        "admite pocas por minuto). Espere un minuto o use Yahoo Finance.",
                    ) from exc
                if exc.code == 404:
                    raise UserError(
                        f"CoinGecko 404 for {url}", user_message="CoinGecko no tiene esa moneda."
                    ) from exc
                raise ProviderError(f"CoinGecko HTTP {exc.code}") from exc
            except (ConnectionError, TimeoutError, OSError) as exc:
                raise NetworkError(f"CoinGecko: {exc}") from exc
            except ValueError as exc:
                raise ProviderError(f"CoinGecko: invalid response ({exc})") from exc
        raise ProviderError("CoinGecko: no response")  # pragma: no cover

    # Symbols ----------------------------------------------------------------------------
    def _pair(self, symbol: str) -> tuple[str, str]:
        """(base ticker, vs currency) of a Yahoo-style pair such as ``BTC-USD``."""
        symbol = normalize_symbol(symbol)
        quote = crypto_quote(symbol)
        if not is_crypto(symbol) or quote is None:
            raise UserError(
                f"{symbol} is not a crypto pair",
                user_message="CoinGecko solo sirve para criptomonedas (pares como BTC-USD).",
            )
        if quote not in VS_CURRENCIES:
            raise UserError(
                f"CoinGecko has no {quote} prices",
                user_message=f"CoinGecko no da precios en {quote}; use el par en USD "
                "o Yahoo Finance.",
            )
        base = symbol.rsplit("-", 1)[0]
        match = _YAHOO_NUMBERED.match(base)
        return (match[1] if match else base), quote

    def coin(self, symbol: str) -> tuple[str, str, str]:
        """(coin id, name, vs currency) of ``symbol``."""
        base, quote = self._pair(symbol)
        if base not in self._ids:
            if base in KNOWN_IDS:
                self._ids[base] = (KNOWN_IDS[base], base)
            else:
                self._ids[base] = self._search_id(base)
        coin_id, name = self._ids[base]
        return coin_id, name, quote

    def _search_id(self, base: str) -> tuple[str, str]:
        data = self._get("/search", {"query": base})
        coins = data.get("coins") if isinstance(data, dict) else None
        best: tuple[int, str, str] | None = None
        for c in coins if isinstance(coins, list) else []:
            if not isinstance(c, dict) or str(c.get("symbol", "")).upper() != base:
                continue
            coin_id, name = c.get("id"), c.get("name")
            if not isinstance(coin_id, str) or not re.fullmatch(r"[a-z0-9\-]{1,80}", coin_id):
                continue
            rank = c.get("market_cap_rank")
            key = rank if isinstance(rank, int) and rank > 0 else 10**9
            if best is None or key < best[0]:
                best = (key, coin_id, name if isinstance(name, str) else base)
        if best is None:
            raise UserError(
                f"CoinGecko: no coin {base}",
                user_message=f"CoinGecko no tiene ninguna moneda «{base}».",
            )
        return best[1], best[2]

    # Data -------------------------------------------------------------------------------
    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        symbol = normalize_symbol(symbol)
        if interval is not Interval.D1:
            raise UserError(
                f"CoinGecko has no {interval}",
                user_message="CoinGecko (gratuito) solo da datos diarios.",
            )
        coin_id, _name, vs = self.coin(symbol)
        today = self._clock().astimezone(UTC).date()
        days = MAX_DAYS if start is None else max(2, min(MAX_DAYS, (today - start).days + 2))
        data = self._get(
            f"/coins/{coin_id}/market_chart",
            {"vs_currency": vs.lower(), "days": days, "interval": "daily"},
        )
        bars = daily_bars(data)
        if start is not None:
            bars = bars[bars.index >= pd.Timestamp(start)]
        if end is not None:
            bars = bars[bars.index <= pd.Timestamp(end)]
        if bars.empty:
            if start is not None:
                return BarSeries(symbol, interval, empty_bars(), SOURCE_NAME)
            raise UserError(
                f"CoinGecko: no prices for {symbol}",
                user_message=f"CoinGecko no tiene precios de {symbol}.",
            )
        clean, warnings = validate_bars(bars, symbol)
        return BarSeries(symbol, interval, clean, SOURCE_NAME, (CLOSE_ONLY_NOTE, *warnings))

    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        data = self._get("/search", {"query": query[:64]})
        coins = data.get("coins") if isinstance(data, dict) else None
        out = []
        for c in coins if isinstance(coins, list) else []:
            if not isinstance(c, dict):
                continue
            ticker = str(c.get("symbol", "")).upper()
            if not re.fullmatch(r"[A-Z0-9]{2,12}", ticker):
                continue
            name = c.get("name") if isinstance(c.get("name"), str) else ticker
            out.append(
                SearchResult(f"{ticker}-USD", f"{name} (CoinGecko)", SOURCE_NAME, "CRYPTOCURRENCY")
            )
            if len(out) >= limit:
                break
        return out

    def get_quote(self, symbol: str) -> Quote:
        symbol = normalize_symbol(symbol)
        coin_id, _name, vs = self.coin(symbol)
        key = vs.lower()
        data = self._get(
            "/simple/price",
            {
                "ids": coin_id,
                "vs_currencies": key,
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_last_updated_at": "true",
            },
        )
        entry = data.get(coin_id) if isinstance(data, dict) else None
        if not isinstance(entry, dict) or _number(entry.get(key)) is None:
            raise UserError(
                f"CoinGecko: no price for {symbol}",
                user_message=f"CoinGecko no tiene precio de {symbol}.",
            )
        price = _number(entry.get(key))
        change = _number(entry.get(f"{key}_24h_change"))
        previous = (
            price / (1 + change / 100)
            if price is not None and change is not None and change > -100
            else None
        )
        stamp = _number(entry.get("last_updated_at"))
        return Quote(
            symbol,
            price,
            previous,
            volume=_number(entry.get(f"{key}_24h_vol")),
            currency=vs,
            market_state="24 h",
            as_of=datetime.fromtimestamp(stamp, UTC) if stamp else None,
        )

    def get_company_info(self, symbol: str) -> CompanyInfo:
        _coin_id, name, vs = self.coin(symbol)
        return CompanyInfo(normalize_symbol(symbol), name, SOURCE_NAME, vs)

    def get_currency(self, symbol: str) -> str | None:
        try:
            return self._pair(symbol)[1]
        except AppError:
            return None


def daily_bars(data: Any) -> pd.DataFrame:
    """``market_chart`` (interval=daily) as close-only daily bars dated by the day they close."""
    prices = data.get("prices") if isinstance(data, dict) else None
    volumes = data.get("total_volumes") if isinstance(data, dict) else None
    volume_at = {}
    for item in volumes if isinstance(volumes, list) else []:
        if isinstance(item, list) and len(item) == 2:
            ms, v = _number(item[0]), _number(item[1])
            if ms is not None and v is not None and v >= 0:
                volume_at[int(ms)] = v
    rows: dict[pd.Timestamp, tuple[float, float]] = {}
    for item in prices if isinstance(prices, list) else []:
        if not isinstance(item, list) or len(item) != 2:
            continue
        ms, price = _number(item[0]), _number(item[1])
        if ms is None or price is None or price <= 0:
            continue
        stamp = pd.Timestamp(int(ms), unit="ms", tz="UTC")
        day = stamp.normalize()
        # A price at 00:00 UTC closes the previous day; any other time is the day so far.
        if int(ms) % _DAY_MS == 0:
            day -= pd.Timedelta(days=1)
        rows[day.tz_localize(None)] = (price, volume_at.get(int(ms), math.nan))
    if not rows:
        return empty_bars()
    index = pd.DatetimeIndex(sorted(rows), name="date")
    closes = [rows[d][0] for d in index]
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "adj_close": closes,
            "volume": [rows[d][1] for d in index],
            "dividends": 0.0,
            "splits": 0.0,
        },
        index=index,
    )
