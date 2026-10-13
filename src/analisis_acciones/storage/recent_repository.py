"""Recently opened symbols."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from analisis_acciones.models.market import SearchResult


class RecentSymbolRepository:
    def __init__(self, conn: sqlite3.Connection, max_entries: int = 20) -> None:
        self._conn = conn
        self._max = max_entries

    def add(self, symbol: str, name: str | None, opened_at: datetime) -> None:
        self._conn.execute(
            "INSERT INTO recent_symbols (symbol, name, opened_at) VALUES (?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET opened_at = excluded.opened_at, "
            "name = COALESCE(excluded.name, recent_symbols.name)",
            (symbol, name, opened_at.isoformat()),
        )
        self._conn.execute(
            "DELETE FROM recent_symbols WHERE symbol NOT IN ("
            " SELECT symbol FROM recent_symbols ORDER BY opened_at DESC LIMIT ?)",
            (self._max,),
        )

    def list(self, limit: int = 10) -> list[SearchResult]:
        rows = self._conn.execute(
            "SELECT symbol, name FROM recent_symbols ORDER BY opened_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [SearchResult(r["symbol"], r["name"] or r["symbol"]) for r in rows]
