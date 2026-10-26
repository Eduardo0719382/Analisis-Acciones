"""Twelve Data (free personal key: about 800 requests a day, 8 a minute).

``/time_series`` gives real daily open/high/low/close and volume for US stocks, ETFs and
cryptocurrencies (``BTC/USD``), up to 5000 sessions per request; ``/quote`` and
``/symbol_search`` complete it. The key travels in a header, never in the URL.
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

SOURCE_NAME = "Twelve Data"
API = "https://api.twelvedata.com"
NOTE = "Twelve Data gratuito: unas 800 consultas al día y 8 por minuto."
_STOCK = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class TwelveDataProvider(KeyedProvider):
    name = SOURCE_NAME
    service = "twelvedata"

    def get_available_intervals(self) -> list[Interval]:
        return [Interval.D1]

    def _get(self, path: str, params: dict[str, str | int]) -> Any:
        data = self.get_json(f"{API}{path}", params, {"Authorization": f"apikey {self.api_key()}"})
        if isinstance(data, dict) and data.get("status") == "error":
            code = data.get("code")
            message = str(data.get("message", ""))[:200]
            if code == 429:
                raise self.rate_limited()
            if code in (401, 403):
                raise UserError(
                    "twelve data key rejected",
                    user_message=f"Twelve Data rechazó la petición: {message}",
                )
            raise UserError(f"twelve data {code}", user_message=f"Twelve Data: {message}")
        return data

    @staticmethod
    def _symbol(symbol: str) -> str:
        if is_crypto(symbol):
            return f"{symbol.rsplit('-', 1)[0]}/{crypto_quote(symbol)}"
        if not _STOCK.match(symbol):
            raise UserError(
                f"twelve data: unsupported {symbol}",
                user_message="Twelve Data no ofrece ese tipo de símbolo aquí.",
            )
        return symbol

    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        symbol = normalize_symbol(symbol)
        if interval is not Interval.D1:
            raise UserError(
                f"{self.name}: no {interval}",
                user_message="Twelve Data: aquí solo se usan datos diarios.",
            )
        params: dict[str, str | int] = {
            "symbol": self._symbol(symbol),
            "interval": "1day",
            "outputsize": 5000,
            "order": "asc",
            "timezone": "UTC" if is_crypto(symbol) else "Exchange",
        }
        if start is not None:
            params["start_date"] = start.isoformat()
        if end is not None:
            params["end_date"] = end.isoformat()
        rows = parse_values(self._get("/time_series", params))
        if not rows:
            if start is not None:
                return BarSeries(symbol, interval, empty_bars(), SOURCE_NAME)
            raise UserError(
                f"{self.name}: no data", user_message=f"Twelve Data no tiene datos de {symbol}."
            )
        bars, warnings = bars_frame(rows, symbol)
        return BarSeries(symbol, interval, bars, SOURCE_NAME, (NOTE, *warnings))

    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]:
        query = query.strip()[:64]
        if not query:
            return []
        data = self._get("/symbol_search", {"symbol": query, "outputsize": 30})
        out = []
        for r in data.get("data") or [] if isinstance(data, dict) else []:
            if not isinstance(r, dict) or r.get("country") not in ("United States", None, ""):
                continue
            symbol = str(r.get("symbol", "")).upper()
            if _STOCK.match(symbol):
                out.append(
                    SearchResult(
                        symbol,
                        str(r.get("instrument_name", symbol))[:120],
                        str(r.get("exchange", SOURCE_NAME))[:30],
                        str(r.get("instrument_type", "")).upper(),
                    )
                )
            if len(out) >= limit:
                break
        return out

    def get_quote(self, symbol: str) -> Quote:
        symbol = normalize_symbol(symbol)
        q = self._get("/quote", {"symbol": self._symbol(symbol)})
        price = number(q.get("close")) if isinstance(q, dict) else None
        if price is None:
            raise UserError(
                f"{self.name}: no quote",
                user_message=f"Twelve Data no tiene cotización de {symbol}.",
            )
        stamp = number(q.get("timestamp"))
        return Quote(
            symbol,
            price,
            number(q.get("previous_close")),
            open=number(q.get("open")),
            day_high=number(q.get("high")),
            day_low=number(q.get("low")),
            volume=number(q.get("volume")),
            currency=str(q.get("currency") or "USD")[:5],
            as_of=datetime.fromtimestamp(stamp, UTC) if stamp else None,
        )

    def get_company_info(self, symbol: str) -> CompanyInfo:
        symbol = normalize_symbol(symbol)
        return CompanyInfo(symbol, None, SOURCE_NAME, self.get_currency(symbol))

    def get_currency(self, symbol: str) -> str | None:
        return crypto_quote(symbol) if is_crypto(symbol) else "USD"


def parse_values(data: Any) -> dict[pd.Timestamp, tuple[float | None, ...]]:
    values = data.get("values") if isinstance(data, dict) else None
    rows: dict[pd.Timestamp, tuple[float | None, ...]] = {}
    for v in values if isinstance(values, list) else []:
        if not isinstance(v, dict) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", str(v.get("datetime"))
        ):
            continue
        rows[pd.Timestamp(str(v["datetime"]))] = tuple(
            number(v.get(k)) for k in ("open", "high", "low", "close", "volume")
        )
    return rows
