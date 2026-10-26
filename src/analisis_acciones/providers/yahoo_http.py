"""Yahoo Finance over plain HTTPS (standard library only), for platforms without yfinance.

yfinance needs native packages (curl_cffi) that do not exist for Android, so the
mobile app uses this client instead. It implements the same ``YahooClient``
protocol as ``YFinanceClient``, returning frames shaped like yfinance's, so
``YahooFinanceProvider`` and everything above it work unchanged.

Endpoints: ``/v8/finance/chart`` (prices, dividends, splits and the quote
fields of its ``meta``) and ``/v1/finance/search``. Company fundamentals need
an authenticated endpoint and are not available here (an empty statement and
quote-only info are returned; nothing is invented).

Every response is external data: it is parsed as JSON and only the fields
listed here are read, with numbers checked by the provider.
"""

from __future__ import annotations

import json
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Mobile Safari/537.36"
)
TIMEOUT_S = 20
MAX_BYTES = 30 * 1024 * 1024
EARLIEST = -2208994789  # 1900-01-02, as yfinance uses for the whole history

#: url -> response body. Injected so tests never touch the network.
Fetcher = Callable[[str], bytes]


def _ssl_context() -> ssl.SSLContext:
    """Default context; with certifi's bundle when available (Android has no system file)."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S, context=_ssl_context()) as resp:
            body: bytes = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError:
        raise  # carries the status code ("HTTP Error 404: ...")
    except (urllib.error.URLError, OSError) as exc:
        raise ConnectionError(f"{url.split('?')[0]}: {exc}") from exc
    if len(body) > MAX_BYTES:
        raise ValueError("response too large")
    return body


def _epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def _floats(values: Any, n: int) -> list[float]:
    """``n`` numbers from a JSON list; anything that is not a finite number becomes NaN."""
    out = []
    items = values if isinstance(values, list) else []
    for i in range(n):
        v = items[i] if i < len(items) else None
        ok = isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
        out.append(float(v) if ok else math.nan)
    return out


class YahooHttpClient:
    """``YahooClient`` over HTTPS with the standard library."""

    def __init__(self, fetch: Fetcher = http_get) -> None:
        self._fetch = fetch

    def _json(self, url: str) -> dict[str, Any]:
        data = json.loads(self._fetch(url).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("unexpected response")
        return data

    def _chart(self, symbol: str, params: dict[str, str | int]) -> dict[str, Any]:
        url = CHART_URL + urllib.parse.quote(symbol, safe="") + "?" + urllib.parse.urlencode(params)
        chart = self._json(url).get("chart")
        if not isinstance(chart, dict):
            raise ValueError("unexpected chart response")
        results = chart.get("result")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            return {}
        result: dict[str, Any] = results[0]
        return result

    def history(self, symbol: str, start: date | None, end: date | None,
                interval: str = "1d") -> pd.DataFrame:  # fmt: skip
        params: dict[str, str | int] = {
            "interval": interval, "events": "div|split", "includeAdjustedClose": "true",
            "includePrePost": "false",
            "period1": _epoch(start) if start is not None else EARLIEST,
            "period2": _epoch((end or date.today()) + timedelta(days=1))
            if end is not None else int(time.time()) + 86_400,
        }  # fmt: skip
        result = self._chart(symbol, params)
        return chart_frame(result, intraday=interval != "1d")

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        params = {"q": query, "quotesCount": limit, "newsCount": 0, "listsCount": 0,
                  "enableFuzzyQuery": "false"}  # fmt: skip
        quotes = self._json(SEARCH_URL + "?" + urllib.parse.urlencode(params)).get("quotes")
        return [q for q in quotes if isinstance(q, dict)] if isinstance(quotes, list) else []

    def info(self, symbol: str) -> dict[str, Any]:
        """Quote fields from the chart's ``meta`` (no fundamentals over this endpoint)."""
        result = self._chart(symbol, {"range": "5d", "interval": "1d"})
        meta = result.get("meta") if result else None
        if not isinstance(meta, dict):
            return {}
        keys = ("currency", "regularMarketPrice", "regularMarketTime", "longName", "shortName",
                "fullExchangeName", "exchangeName", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
                "regularMarketDayHigh", "regularMarketDayLow", "regularMarketVolume",
                "instrumentType")  # fmt: skip
        info = {k: meta[k] for k in keys if k in meta}
        if "exchangeName" in info:
            info["exchange"] = info.pop("exchangeName")
        frame = chart_frame(result, intraday=False)
        closes = frame["Close"].dropna() if not frame.empty else pd.Series(dtype=float)
        if len(closes) >= 2:
            info["regularMarketPreviousClose"] = float(closes.iloc[-2])
        return info

    def income_statement(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame()  # needs an authenticated endpoint: not available


def chart_frame(result: dict[str, Any], intraday: bool) -> pd.DataFrame:
    """A chart ``result`` as a yfinance-shaped frame (exchange-local, tz-aware index)."""
    stamps = result.get("timestamp") if result else None
    if not isinstance(stamps, list) or not stamps:
        return pd.DataFrame()
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    tz = meta.get("exchangeTimezoneName") if isinstance(meta, dict) else None
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    quote = quotes[0] if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict) \
        else {}  # fmt: skip
    adjs = indicators.get("adjclose") if isinstance(indicators, dict) else None
    adj = adjs[0].get("adjclose") if isinstance(adjs, list) and adjs and isinstance(adjs[0], dict) \
        else None  # fmt: skip
    n = len(stamps)
    seconds = [int(s) if isinstance(s, int | float) and not isinstance(s, bool) else 0
               for s in stamps]  # fmt: skip
    try:
        index = pd.to_datetime(seconds, unit="s", utc=True).tz_convert(str(tz or "UTC"))
    except (ValueError, TypeError, KeyError):
        index = pd.to_datetime(seconds, unit="s", utc=True)
    close = _floats(quote.get("close"), n)
    frame = pd.DataFrame(
        {
            "Open": _floats(quote.get("open"), n),
            "High": _floats(quote.get("high"), n),
            "Low": _floats(quote.get("low"), n),
            "Close": close,
            "Adj Close": _floats(adj, n) if adj is not None else close,
            "Volume": _floats(quote.get("volume"), n),
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=index,
    )
    frame = frame[[s > 0 for s in seconds]]
    frame = frame[frame["Close"].notna()]
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    if not intraday and not frame.empty:
        _add_events(frame, result.get("events"))
    return frame


def _add_events(frame: pd.DataFrame, events: Any) -> None:
    """Dividends and split ratios on the row of their (exchange-local) date."""
    if not isinstance(events, dict):
        return
    days = pd.DatetimeIndex(frame.index).normalize()
    tz = pd.DatetimeIndex(frame.index).tz

    def row_of(stamp: Any) -> int | None:
        if not isinstance(stamp, int | float) or isinstance(stamp, bool):
            return None
        day = pd.Timestamp(int(stamp), unit="s", tz="UTC").tz_convert(tz).normalize()
        pos = days.get_indexer([day])[0]
        return int(pos) if pos >= 0 else None

    dividends = events.get("dividends")
    for item in dividends.values() if isinstance(dividends, dict) else []:
        if not isinstance(item, dict):
            continue
        amount, pos = item.get("amount"), row_of(item.get("date"))
        if pos is not None and isinstance(amount, int | float) and math.isfinite(amount) \
                and amount > 0:  # fmt: skip
            frame.iloc[pos, frame.columns.get_loc("Dividends")] += float(amount)
    splits = events.get("splits")
    for item in splits.values() if isinstance(splits, dict) else []:
        if not isinstance(item, dict):
            continue
        num, den, pos = item.get("numerator"), item.get("denominator"), row_of(item.get("date"))
        if pos is None or not all(isinstance(v, int | float) and math.isfinite(v) and v > 0
                                  for v in (num, den)):  # fmt: skip
            continue
        frame.iloc[pos, frame.columns.get_loc("Stock Splits")] = float(num) / float(den)
