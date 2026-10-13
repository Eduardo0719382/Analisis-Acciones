"""Validation and cleaning of OHLCV bars.

Rules (rows that break them are dropped and reported, never repaired):

* the index must be dates; duplicates keep the last occurrence; sorted ascending;
* open/high/low/close must all be present, finite and > 0;
* high >= max(open, close, low) and low <= min(open, close), with a small
  relative tolerance for rounding in the source;
* volume, when present, must be >= 0 (missing volume stays NaN).

If too large a share of rows is invalid the whole series is rejected with a
DataError, because silently plotting a heavily filtered series would mislead.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from analisis_acciones.models.errors import DataError
from analisis_acciones.models.market import BAR_COLUMNS, PRICE_COLUMNS

logger = logging.getLogger(__name__)

TOLERANCE = 1e-6  # relative, absorbs float rounding in source data
MAX_INVALID_SHARE = 0.05


def validate_bars(frame: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, list[str]]:
    """Return a cleaned copy in the canonical schema plus Spanish warning messages."""
    missing = [c for c in PRICE_COLUMNS if c not in frame.columns]
    if missing:
        raise DataError(f"{symbol}: missing columns {missing}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise DataError(f"{symbol}: index is not a DatetimeIndex")

    df = frame.copy()
    for column in BAR_COLUMNS:
        if column not in df.columns:
            df[column] = 0.0 if column in ("dividends", "splits") else np.nan
    df = df.loc[:, list(BAR_COLUMNS)].apply(pd.to_numeric, errors="coerce").astype("float64")
    df.index = pd.DatetimeIndex(df.index, name="date")

    warnings: list[str] = []
    total = len(df)
    if total == 0:
        raise DataError(
            f"{symbol}: no bars",
            user_message=f"No hay datos de precios para {symbol}.",
        )

    duplicated = df.index.duplicated(keep="last")
    if duplicated.any():
        warnings.append(f"Se eliminaron {int(duplicated.sum())} fecha(s) duplicada(s).")
        df = df[~duplicated]
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()

    prices = df[list(PRICE_COLUMNS)]
    all_missing = prices.isna().all(axis=1)
    if all_missing.any():
        # Sources (e.g. Yahoo) emit empty rows for holidays/halts; not an error.
        logger.debug("%s: dropping %d empty rows", symbol, int(all_missing.sum()))
        df = df[~all_missing]
        prices = df[list(PRICE_COLUMNS)]

    hi_ref = prices[["open", "close", "low"]].max(axis=1)
    lo_ref = prices[["open", "close"]].min(axis=1)
    invalid = (
        prices.isna().any(axis=1)
        | ~np.isfinite(prices).all(axis=1)
        | (prices <= 0).any(axis=1)
        | (prices["high"] < hi_ref * (1 - TOLERANCE))
        | (prices["low"] > lo_ref * (1 + TOLERANCE))
        | (df["volume"] < 0)
    )
    n_invalid = int(invalid.sum())
    if n_invalid:
        share = n_invalid / max(len(df), 1)
        logger.warning(
            "%s: %d invalid bar(s) dropped, e.g. %s",
            symbol,
            n_invalid,
            list(df.index[invalid][:3].date),
        )
        if share > MAX_INVALID_SHARE:
            raise DataError(
                f"{symbol}: {n_invalid}/{len(df)} invalid bars",
                user_message=(
                    f"Los datos de {symbol} contienen demasiadas barras inválidas "
                    f"({n_invalid} de {len(df)}). No se mostrarán."
                ),
            )
        warnings.append(f"Se descartaron {n_invalid} barra(s) con valores inválidos.")
        df = df[~invalid]

    if df.empty:
        raise DataError(
            f"{symbol}: no valid bars", user_message=f"No hay datos válidos para {symbol}."
        )
    df[["dividends", "splits"]] = df[["dividends", "splits"]].fillna(0.0)
    return df, warnings
