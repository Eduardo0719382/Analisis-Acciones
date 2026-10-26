"""Finnhub (free personal key, about 60 requests a minute).

The free plan reliably includes real-time quotes of US stocks, symbol search and company
profiles. Historical candles (``/stock/candle``, ``/crypto/candle``) are paid on most
current free keys: when Finnhub refuses them the user is told so plainly. Crypto pairs
are read from Binance against USDT (``BTC-USD`` -> ``BINANCE:BTCUSDT``), which is said in
every crypto series. The key travels in a header, never in the URL.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from analisis_acciones.data.freshness import crypto_quote, is_crypto
from analisis_acciones.models.errors import UserError
from analisis_acciones.models.market import (
    BarSeries,
    CompanyInfo,
    Interval,
    Quote,
    SearchResult,
    empty_bars,
)
from analisis_acciones.providers.base import normalize_symbol
from analisis_acciones.providers.keyed import KeyedProvider, bars_frame, number

SOURCE_NAME = "Finnhub"
API = "https://finnhub.io/api/v1"
CRYPTO_NOTE = "Finnhub: criptomonedas de Binance en USDT (moneda estable cercana al dólar)."
_STOCK = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
EARLIEST = date(1990, 1, 1)


class FinnhubProvider(KeyedProvider):
    name = SOURCE_NAME
    service = "finnhub"

    def get_available_intervals(self) -> list[Interval]:
        return [Interval.D1]

    def _get(self, path: str, params: dict[str, str | int]) -> Any:
        data = self.get_json(f"{API}{path}", params, {"X-Finnhub-Token": self.api_key()})
        if isinstance(data, dict) and isinstance(data.get("error"), str):
            text = data["error"]
            if "access" in text.lower():
                raise UserError(
                    "finnhub: no access",
                    user_message=(
                        "Su plan gratuito de Finnhub no incluye el historial de precios (velas). "
                        "Finnhub sirve para la cotización actual; para gráficos elija otra fuente."
                    ),
                )
            raise UserError(f"finnhub: {text[:120]}", user_message=f"Finnhub: {text[:200]}")
        return data

    @staticmethod
    def _crypto_symbol(symbol: str) -> str:
        base = symbol.rsplit("-", 1)[0]
        quote = crypto_quote(symbol) or "USD"
        return f"BINANCE:{base}{'USDT' if quote in ('USD', 'USDT') else quote}"

    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        symbol = normalize_symbol(symbol)
        if interval is not Interval.D1:
            raise UserError(
                f"{self.name}: no {interval}",
                user_message="Finnhub: aquí solo se usan datos diarios.",
            )
        crypto = is_crypto(symbol)
        if not crypto and not _STOCK.match(symbol):
            raise UserError(
                f"{self.name}: unsupported {symbol}",
                user_message="Finnhub no ofrece ese tipo de símbolo.",
            )
        first = start or EARLIEST
        last = (end or datetime.now(UTC).date()) + timedelta(days=1)
        params: dict[str, str | int] = {
            "symbol": self._crypto_symbol(symbol) if crypto else symbol,
            "resolution": "D",
            "from": int(datetime(first.year, first.month, first.day, tzinfo=UTC).timestamp()),
            "to": int(datetime(last.year, last.month, last.day, tzinfo=UTC).timestamp()),
        }
        data = self._get("/crypto/candle" if crypto else "/stock/candle", params)
        rows = parse_candles(data)
        if not rows:
            if start is not None:
                return BarSeries(symbol, interval, empty_bars(), SOURCE_NAME)
            raise UserError(
                f"{self.name}: no data", user_message=f"Finnhub no tiene datos de {symbol}."
            )
        bars, warnings = bars_frame(rows, symbol)
        notes = (CRYPTO_NOTE,) if crypto else ()
        return BarSeries(symbol, interval, bars, SOURCE_NAME, (*notes, *warnings))

    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]:
        query = query.strip()[:64]
        if not query:
            return []
        data = self._get("/search", {"q": query})
        out = []
        for r in data.get("result") or [] if isinstance(data, dict) else []:
            if not isinstance(r, dict):
                continue
            symbol = str(r.get("symbol", "")).upper()
            if _STOCK.match(symbol) and "." not in symbol:
                out.append(
                    SearchResult(
                        symbol,
                        str(r.get("description", symbol))[:120],
                        SOURCE_NAME,
                        str(r.get("type", "")).upper(),
                    )
                )
            if len(out) >= limit:
                break
        return out

    def get_quote(self, symbol: str) -> Quote:
        symbol = normalize_symbol(symbol)
        target = self._crypto_symbol(symbol) if is_crypto(symbol) else symbol
        q = self._get("/quote", {"symbol": target})
        price = number(q.get("c")) if isinstance(q, dict) else None
        if not price:  # Finnhub answers 0 for unknown symbols
            raise UserError(
                f"{self.name}: no quote", user_message=f"Finnhub no tiene cotización de {symbol}."
            )
        stamp = number(q.get("t"))
        return Quote(
            symbol,
            price,
            number(q.get("pc")),
            open=number(q.get("o")),
            day_high=number(q.get("h")),
            day_low=number(q.get("l")),
            currency="USD",
            as_of=datetime.fromtimestamp(stamp, UTC) if stamp else None,
        )

    def get_company_info(self, symbol: str) -> CompanyInfo:
        symbol = normalize_symbol(symbol)
        if is_crypto(symbol):
            return CompanyInfo(symbol, None, SOURCE_NAME, "USD")
        p = self._get("/stock/profile2", {"symbol": symbol})
        p = p if isinstance(p, dict) else {}
        text = {
            k: str(p[k])[:120]
            for k in ("name", "exchange", "currency", "finnhubIndustry")
            if isinstance(p.get(k), str)
        }
        return CompanyInfo(
            symbol,
            text.get("name"),
            text.get("exchange"),
            text.get("currency"),
            industry=text.get("finnhubIndustry"),
        )

    def get_currency(self, symbol: str) -> str | None:
        return "USD"


def parse_candles(data: Any) -> dict[pd.Timestamp, tuple[float | None, ...]]:
    """Finnhub candles: {"s": "ok", "t": [...], "o": [...], ...} -> {day: ohlcv}."""
    if not isinstance(data, dict) or data.get("s") != "ok":
        return {}
    cols = [data.get(k) for k in ("t", "o", "h", "l", "c", "v")]
    if not all(isinstance(c, list) for c in cols):
        return {}
    n = min(len(c) for c in cols)  # type: ignore[arg-type]
    rows: dict[pd.Timestamp, tuple[float | None, ...]] = {}
    for i in range(n):
        stamp = number(cols[0][i])  # type: ignore[index]
        if stamp is None:
            continue
        day = pd.Timestamp(int(stamp), unit="s", tz="UTC").tz_localize(None).normalize()
        rows[day] = tuple(number(c[i]) for c in cols[1:])  # type: ignore[index]
    return rows
