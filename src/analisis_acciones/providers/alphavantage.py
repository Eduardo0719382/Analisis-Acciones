"""Alpha Vantage (free personal key): daily bars of US stocks/ETFs and of cryptocurrencies.

* Stocks: ``TIME_SERIES_DAILY`` (full history; if the free plan only allows the compact
  output, the last 100 sessions). Prices are as traded, NOT adjusted for splits or
  dividends: a split shows as a jump. Every series says so.
* Crypto: ``DIGITAL_CURRENCY_DAILY`` (real daily open/high/low/close and volume).
* Search ``SYMBOL_SEARCH`` (US listings) and quote ``GLOBAL_QUOTE``.

The free plan allows about 25 requests a day; the program keeps what it downloads, so each
symbol costs one request per day at most.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
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

SOURCE_NAME = "Alpha Vantage"
API = "https://www.alphavantage.co/query"
STOCK_NOTE = (
    "Alpha Vantage gratuito: precios sin ajustar por splits ni dividendos (un split aparece "
    "como un salto) y unas 25 consultas al día."
)
COMPACT_NOTE = "Su plan de Alpha Vantage solo permite las últimas 100 sesiones."
_STOCK = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class AlphaVantageProvider(KeyedProvider):
    name = SOURCE_NAME
    service = "alphavantage"

    def get_available_intervals(self) -> list[Interval]:
        return [Interval.D1]

    def _query(self, params: dict[str, str | int]) -> dict[str, Any]:
        data = self.get_json(API, {**params, "apikey": self.api_key()})
        if not isinstance(data, dict):
            raise UserError(
                f"{self.name}: unexpected response",
                user_message="Respuesta inesperada de Alpha Vantage.",
            )
        if "Error Message" in data:
            raise UserError(
                f"{self.name}: {str(data['Error Message'])[:120]}",
                user_message="Alpha Vantage no tiene ese activo.",
            )
        text = str(data.get("Note") or data.get("Information") or "")
        if text and len(data) <= 2:
            lowered = text.lower()
            if "premium" in lowered and "outputsize" in lowered:
                raise _PremiumOutput()
            if (
                "rate limit" in lowered
                or "requests per day" in lowered
                or "call frequency" in lowered
            ):
                raise self.rate_limited()
            if "apikey" in lowered or "api key" in lowered:
                raise UserError(
                    "alpha vantage key rejected", user_message="Alpha Vantage no reconoce la clave."
                )
            raise UserError(
                f"{self.name}: {text[:120]}", user_message=f"Alpha Vantage: {text[:200]}"
            )
        return data

    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        symbol = normalize_symbol(symbol)
        if interval is not Interval.D1:
            raise UserError(
                f"{self.name}: no {interval}",
                user_message="Alpha Vantage (gratuito) solo da datos diarios aquí.",
            )
        notes: list[str] = []
        if is_crypto(symbol):
            base, quote = symbol.rsplit("-", 1)[0], crypto_quote(symbol) or "USD"
            data = self._query(
                {"function": "DIGITAL_CURRENCY_DAILY", "symbol": base, "market": quote}
            )
            table = data.get("Time Series (Digital Currency Daily)")
            notes.append("Alpha Vantage gratuito: unas 25 consultas al día.")
        else:
            if not _STOCK.match(symbol):
                raise UserError(
                    f"{self.name}: unsupported {symbol}",
                    user_message="Alpha Vantage no ofrece ese tipo de símbolo.",
                )
            params: dict[str, str | int] = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "full" if start is None else "compact",
            }
            try:
                data = self._query(params)
            except _PremiumOutput:
                data = self._query({**params, "outputsize": "compact"})
                notes.append(COMPACT_NOTE)
            table = data.get("Time Series (Daily)")
            notes.insert(0, STOCK_NOTE)
        rows = parse_daily(table)
        if start is not None:
            rows = {d: v for d, v in rows.items() if d >= pd.Timestamp(start)}
        if end is not None:
            rows = {d: v for d, v in rows.items() if d <= pd.Timestamp(end)}
        if not rows:
            if start is not None:
                return BarSeries(symbol, interval, empty_bars(), SOURCE_NAME)
            raise UserError(
                f"{self.name}: no data for {symbol}",
                user_message=f"Alpha Vantage no tiene datos de {symbol}.",
            )
        bars, warnings = bars_frame(rows, symbol)
        return BarSeries(symbol, interval, bars, SOURCE_NAME, (*notes, *warnings))

    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]:
        query = query.strip()[:64]
        if not query:
            return []
        data = self._query({"function": "SYMBOL_SEARCH", "keywords": query})
        out = []
        for m in data.get("bestMatches") or []:
            if not isinstance(m, dict) or m.get("4. region") != "United States":
                continue
            symbol = str(m.get("1. symbol", "")).upper()
            if _STOCK.match(symbol):
                out.append(
                    SearchResult(
                        symbol,
                        str(m.get("2. name", symbol))[:120],
                        SOURCE_NAME,
                        str(m.get("3. type", "")).upper(),
                    )
                )
            if len(out) >= limit:
                break
        return out

    def get_quote(self, symbol: str) -> Quote:
        symbol = normalize_symbol(symbol)
        q = self._query({"function": "GLOBAL_QUOTE", "symbol": symbol}).get("Global Quote")
        if not isinstance(q, dict) or number(q.get("05. price")) is None:
            raise UserError(
                f"{self.name}: no quote",
                user_message=f"Alpha Vantage no tiene cotización de {symbol}.",
            )
        return Quote(
            symbol,
            number(q.get("05. price")),
            number(q.get("08. previous close")),
            open=number(q.get("02. open")),
            day_high=number(q.get("03. high")),
            day_low=number(q.get("04. low")),
            volume=number(q.get("06. volume")),
            currency="USD",
            as_of=datetime.now(UTC),
        )

    def get_company_info(self, symbol: str) -> CompanyInfo:
        symbol = normalize_symbol(symbol)
        return CompanyInfo(symbol, None, SOURCE_NAME, "USD")

    def get_currency(self, symbol: str) -> str | None:
        return crypto_quote(symbol) if is_crypto(symbol) else "USD"


class _PremiumOutput(Exception):
    """The free plan refused ``outputsize=full``."""


def parse_daily(table: Any) -> dict[pd.Timestamp, tuple[float | None, ...]]:
    """Alpha Vantage daily table: {"YYYY-MM-DD": {"1. open": "…", …}} (crypto keys may carry a
    currency suffix such as "1a. open (USD)")."""
    rows: dict[pd.Timestamp, tuple[float | None, ...]] = {}
    if not isinstance(table, dict):
        return rows
    for day, values in table.items():
        if not isinstance(values, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)):
            continue

        def pick(field: str, values: dict[str, Any] = values) -> float | None:
            for key, value in values.items():
                if re.match(rf"^\d+[a-z]?\. {field}", str(key)):
                    return number(value)
            return None

        try:
            stamp = pd.Timestamp(str(day))
        except ValueError:
            continue
        rows[stamp] = (pick("open"), pick("high"), pick("low"), pick("close"), pick("volume"))
    return rows
