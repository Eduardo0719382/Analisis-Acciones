"""Conversion of prices to US dollars with Yahoo's daily exchange-rate series.

The rate of a day is the last daily close of the pair on or before that day
(the same "last close" rule as prices). Sub-unit quotes are handled: London
prices in pence (GBp/GBX), Johannesburg in cents (ZAc) and Tel Aviv in agorot
(ILA). Rates are data from the source, never estimated: a missing rate is an
error reported to the user.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from analisis_acciones.models.errors import AppError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

BASE = "USD"
# Case matters: "GBP" is pounds, "GBp" pence.
SUBUNITS = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ILA": "ILS"}
PRICE_COLUMNS = ("open", "high", "low", "close", "adj_close", "dividends")


def pair_for(currency: str) -> tuple[str | None, float]:
    """Yahoo symbol of the currency→USD pair and the sub-unit factor (None for USD)."""
    if currency in SUBUNITS:
        return f"{SUBUNITS[currency]}{BASE}=X", 0.01
    code = currency.upper()
    if code == BASE:
        return None, 1.0
    return f"{code}{BASE}=X", 1.0


@dataclass
class FxConverter:
    """Loads (cache-first) and remembers the rate series used by one calculation."""

    market: MarketDataService
    notes: list[str] = field(default_factory=list)
    _series: dict[str, pd.Series] = field(default_factory=dict)

    def currency_of(self, symbol: str) -> str:
        currency = self.market.currency(symbol)
        if currency is None:
            note = f"{symbol}: divisa desconocida, se toma en dólares."
            if note not in self.notes:
                self.notes.append(note)
            return BASE
        return currency

    def series(self, currency: str) -> pd.Series | None:
        """Dollars per unit of ``currency`` by day (None for USD)."""
        pair, factor = pair_for(currency)
        if pair is None:
            return None
        if pair not in self._series:
            try:
                closes = self.market.load(pair, Interval.D1).series.bars["close"]
            except AppError as exc:
                raise UserError(
                    f"no fx {pair}: {exc}",
                    user_message=f"No hay tipo de cambio {pair} ({exc.user_message}).",
                ) from exc
            self._series[pair] = closes.sort_index() * factor
            note = f"Importes en {currency} convertidos a $ con {pair} de cada día."
            if note not in self.notes:
                self.notes.append(note)
        return self._series[pair]

    def rate_on(self, currency: str, day: date) -> float:
        series = self.series(currency)
        if series is None:
            return 1.0
        known = series[series.index <= pd.Timestamp(day)]
        if known.empty:
            raise UserError(
                f"no fx rate for {currency} on {day}",
                user_message=f"No hay tipo de cambio de {currency} para esa fecha.",
            )
        return float(known.iloc[-1])

    def to_usd(self, bars: pd.DataFrame, currency: str) -> pd.DataFrame:
        """Prices and dividends of ``bars`` in dollars (rate of each day, carried forward)."""
        series = self.series(currency)
        if series is None:
            return bars
        rates = series.reindex(series.index.union(bars.index)).ffill().reindex(bars.index)
        if rates.isna().any():
            # Days before the first available rate: use the first rate and say so.
            first = float(series.iloc[0])
            start = pd.Timestamp(series.index[0])
            note = f"Antes del {start:%d/%m/%Y} se usa el primer tipo de cambio de {currency}."
            if note not in self.notes:
                self.notes.append(note)
            rates = rates.fillna(first)
        out = bars.copy()
        for column in PRICE_COLUMNS:
            if column in out:
                out[column] = out[column] * rates
        return out
