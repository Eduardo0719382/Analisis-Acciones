"""Persistence of intraday bars (per symbol and interval) and their fetch time."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from analisis_acciones.models.market import BAR_COLUMNS, empty_bars
from analisis_acciones.storage.database import transaction

_COLUMNS = ", ".join(BAR_COLUMNS)


@dataclass(frozen=True)
class IntradayMeta:
    source: str
    fetched_at: datetime


def _sql(value: object) -> object:
    return None if isinstance(value, float) and math.isnan(value) else value


class IntradayRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def load(self, symbol: str, interval: str) -> pd.DataFrame:
        rows = self._conn.execute(
            f"SELECT ts, {_COLUMNS} FROM intraday_bars WHERE symbol = ? AND interval = ? "
            "ORDER BY ts",
            (symbol, interval),
        ).fetchall()
        if not rows:
            return empty_bars()
        frame = pd.DataFrame([tuple(r) for r in rows], columns=["ts", *BAR_COLUMNS])
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("ts")), name="date")
        return frame.astype("float64")

    def meta(self, symbol: str, interval: str) -> IntradayMeta | None:
        row = self._conn.execute(
            "SELECT source, fetched_at FROM intraday_meta WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        ).fetchone()
        if row is None:
            return None
        return IntradayMeta(row["source"], datetime.fromisoformat(row["fetched_at"]))

    def upsert(self, symbol: str, interval: str, source: str, bars: pd.DataFrame,
               fetched_at: datetime, *, replace: bool = False) -> None:  # fmt: skip
        """Insert or overwrite bars; ``replace`` first deletes the stored series."""
        with transaction(self._conn):
            if replace:
                self._conn.execute(
                    "DELETE FROM intraday_bars WHERE symbol = ? AND interval = ?",
                    (symbol, interval),
                )
            self._conn.executemany(
                f"INSERT OR REPLACE INTO intraday_bars (symbol, interval, ts, {_COLUMNS}) "
                f"VALUES (?, ?, ?, {', '.join('?' for _ in BAR_COLUMNS)})",
                [
                    (symbol, interval, ts.strftime("%Y-%m-%dT%H:%M:%S"),
                     *(_sql(float(v)) for v in values))
                    for ts, values in zip(pd.DatetimeIndex(bars.index),
                                          bars[list(BAR_COLUMNS)].itertuples(index=False),
                                          strict=True)
                ],
            )  # fmt: skip
            self.touch(symbol, interval, source, fetched_at)

    def touch(self, symbol: str, interval: str, source: str, fetched_at: datetime) -> None:
        self._conn.execute(
            "INSERT INTO intraday_meta (symbol, interval, source, fetched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(symbol, interval) DO UPDATE SET source = excluded.source, "
            "fetched_at = excluded.fetched_at",
            (symbol, interval, source, fetched_at.isoformat()),
        )
