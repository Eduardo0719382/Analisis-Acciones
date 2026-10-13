"""Persistence of daily bars and their fetch metadata."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from analisis_acciones.models.market import BAR_COLUMNS, empty_bars
from analisis_acciones.storage.database import transaction

_COLUMNS = ", ".join(BAR_COLUMNS)
_PLACEHOLDERS = ", ".join("?" for _ in range(len(BAR_COLUMNS) + 2))


@dataclass(frozen=True)
class SeriesMeta:
    symbol: str
    source: str
    fetched_at: datetime
    first_date: date | None
    last_date: date | None


def _sql_value(value: float) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


class BarRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def load(self, symbol: str) -> pd.DataFrame:
        rows = self._conn.execute(
            f"SELECT date, {_COLUMNS} FROM daily_bars WHERE symbol = ? ORDER BY date",
            (symbol,),
        ).fetchall()
        if not rows:
            return empty_bars()
        frame = pd.DataFrame([tuple(r) for r in rows], columns=["date", *BAR_COLUMNS])
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")), name="date")
        return frame.astype("float64")

    def meta(self, symbol: str) -> SeriesMeta | None:
        row = self._conn.execute(
            "SELECT symbol, source, fetched_at, first_date, last_date "
            "FROM series_meta WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        if row is None:
            return None
        return SeriesMeta(
            symbol=row["symbol"],
            source=row["source"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            first_date=date.fromisoformat(row["first_date"]) if row["first_date"] else None,
            last_date=date.fromisoformat(row["last_date"]) if row["last_date"] else None,
        )

    def replace(self, symbol: str, source: str, bars: pd.DataFrame, fetched_at: datetime) -> None:
        """Replace the whole stored series."""
        with transaction(self._conn):
            self._conn.execute("DELETE FROM daily_bars WHERE symbol = ?", (symbol,))
            self._insert(symbol, bars)
            self._update_meta(symbol, source, fetched_at)

    def upsert(self, symbol: str, source: str, bars: pd.DataFrame, fetched_at: datetime) -> None:
        """Insert new bars and overwrite existing ones on the same dates."""
        with transaction(self._conn):
            self._insert(symbol, bars)
            self._update_meta(symbol, source, fetched_at)

    def touch(self, symbol: str, fetched_at: datetime) -> None:
        self._conn.execute(
            "UPDATE series_meta SET fetched_at = ? WHERE symbol = ?",
            (fetched_at.isoformat(), symbol),
        )

    def delete(self, symbol: str) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM daily_bars WHERE symbol = ?", (symbol,))
            self._conn.execute("DELETE FROM series_meta WHERE symbol = ?", (symbol,))

    def _insert(self, symbol: str, bars: pd.DataFrame) -> None:
        records = [
            (symbol, ts.date().isoformat(), *(_sql_value(v) for v in values))
            for ts, values in zip(
                pd.DatetimeIndex(bars.index),
                bars.loc[:, list(BAR_COLUMNS)].itertuples(index=False, name=None),
                strict=True,
            )
        ]
        self._conn.executemany(
            f"INSERT OR REPLACE INTO daily_bars (symbol, date, {_COLUMNS}) "
            f"VALUES ({_PLACEHOLDERS})",
            records,
        )

    def _update_meta(self, symbol: str, source: str, fetched_at: datetime) -> None:
        first, last = self._conn.execute(
            "SELECT MIN(date), MAX(date) FROM daily_bars WHERE symbol = ?", (symbol,)
        ).fetchone()
        self._conn.execute(
            "INSERT INTO series_meta (symbol, source, fetched_at, first_date, last_date) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET source = excluded.source, "
            "fetched_at = excluded.fetched_at, first_date = excluded.first_date, "
            "last_date = excluded.last_date",
            (symbol, source, fetched_at.isoformat(), first, last),
        )
