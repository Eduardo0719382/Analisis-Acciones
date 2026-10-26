"""Shared plumbing of the optional sources that need a personal API key.

The key is read at every request (so a key saved in the settings works at once) and is
never part of an error message or a log line. Responses are external data: they are
parsed as JSON and only the fields each adapter names are read.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from analisis_acciones.data.validation import validate_bars
from analisis_acciones.models.errors import NetworkError, ProviderError, UserError
from analisis_acciones.models.market import BAR_COLUMNS
from analisis_acciones.providers.base import MarketDataProvider
from analisis_acciones.providers.yahoo_http import http_get

#: (url, headers) -> body
KeyedFetcher = Callable[..., bytes]


def number(value: Any) -> float | None:
    """A finite number from JSON (numbers or numeric strings); None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


class KeyedProvider(MarketDataProvider):
    """Base for Alpha Vantage, Finnhub and Twelve Data."""

    service = ""  # key in api_keys.SERVICES

    def __init__(self, key: Callable[[], str | None], fetch: KeyedFetcher = http_get) -> None:
        self._key = key
        self._fetch = fetch

    def api_key(self) -> str:
        key = self._key()
        if not key:
            raise UserError(
                f"{self.name}: no api key",
                user_message=f"Falta la clave de {self.name}. Añádala en Fuentes de datos "
                "(PC: menú Ver; celular: Ajustes) o elija otra fuente.",
            )
        return key

    def get_json(
        self, url: str, params: Mapping[str, str | int], headers: Mapping[str, str] | None = None
    ) -> Any:
        full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
        try:
            body = self._fetch(full, headers or {})
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise UserError(
                    f"{self.name} HTTP {exc.code}",
                    user_message=f"{self.name} rechazó la petición: la clave no es válida o su "
                    "plan gratuito no incluye estos datos.",
                ) from None
            if exc.code == 429:
                raise self.rate_limited() from None
            if exc.code == 404:
                raise UserError(
                    f"{self.name} HTTP 404", user_message=f"{self.name} no tiene ese activo."
                ) from None
            raise ProviderError(f"{self.name} HTTP {exc.code}") from None
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise NetworkError(f"{self.name}: {type(exc).__name__}") from None
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as exc:
            raise ProviderError(f"{self.name}: invalid response") from exc

    def rate_limited(self) -> ProviderError:
        return ProviderError(
            f"{self.name} rate limit",
            user_message=f"Se agotaron las consultas gratuitas de {self.name} por ahora. "
            "Espere o elija otra fuente.",
        )


def bars_frame(
    rows: dict[pd.Timestamp, tuple[float | None, ...]],
    symbol: str,
) -> tuple[pd.DataFrame, list[str]]:
    """{day: (open, high, low, close, volume)} -> validated canonical bars."""
    index = pd.DatetimeIndex(sorted(rows), name="date")
    values = [rows[d] for d in index]
    frame = pd.DataFrame(
        {
            "open": [v[0] for v in values],
            "high": [v[1] for v in values],
            "low": [v[2] for v in values],
            "close": [v[3] for v in values],
            "volume": [v[4] for v in values],
        },
        index=index,
        dtype="float64",
    )
    frame["adj_close"] = frame["close"]
    frame["dividends"] = 0.0
    frame["splits"] = 0.0
    frame = frame[list(BAR_COLUMNS)]
    return validate_bars(frame, symbol)
