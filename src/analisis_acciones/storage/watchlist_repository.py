"""Persistence of watchlists and their ordered symbols."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from analisis_acciones.storage.database import transaction


@dataclass(frozen=True)
class Watchlist:
    id: int
    name: str


class WatchlistRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def lists(self) -> list[Watchlist]:
        rows = self._conn.execute("SELECT id, name FROM watchlists ORDER BY position, id")
        return [Watchlist(r["id"], r["name"]) for r in rows]

    def get(self, list_id: int) -> Watchlist | None:
        row = self._conn.execute(
            "SELECT id, name FROM watchlists WHERE id = ?", (list_id,)
        ).fetchone()
        return Watchlist(row["id"], row["name"]) if row else None

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM watchlists WHERE name = ? AND id IS NOT ?", (name, exclude_id)
        ).fetchone()
        return row is not None

    def create(self, name: str) -> Watchlist:
        (position,) = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM watchlists"
        ).fetchone()
        cursor = self._conn.execute(
            "INSERT INTO watchlists (name, position) VALUES (?, ?)", (name, position)
        )
        return Watchlist(int(cursor.lastrowid or 0), name)

    def rename(self, list_id: int, name: str) -> None:
        self._conn.execute("UPDATE watchlists SET name = ? WHERE id = ?", (name, list_id))

    def delete(self, list_id: int) -> None:
        self._conn.execute("DELETE FROM watchlists WHERE id = ?", (list_id,))

    def symbols(self, list_id: int) -> list[str]:
        rows = self._conn.execute(
            "SELECT symbol FROM watchlist_items WHERE watchlist_id = ? ORDER BY position",
            (list_id,),
        )
        return [r["symbol"] for r in rows]

    def add(self, list_id: int, symbol: str, added_at: datetime) -> bool:
        """Append ``symbol``; returns False when it was already in the list."""
        (position,) = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM watchlist_items WHERE watchlist_id = ?",
            (list_id,),
        ).fetchone()
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO watchlist_items (watchlist_id, symbol, position, added_at) "
            "VALUES (?, ?, ?, ?)",
            (list_id, symbol, position, added_at.isoformat()),
        )
        return cursor.rowcount == 1

    def remove(self, list_id: int, symbol: str) -> None:
        self._conn.execute(
            "DELETE FROM watchlist_items WHERE watchlist_id = ? AND symbol = ?", (list_id, symbol)
        )

    def set_order(self, list_id: int, symbols: list[str]) -> None:
        with transaction(self._conn):
            for position, symbol in enumerate(symbols):
                self._conn.execute(
                    "UPDATE watchlist_items SET position = ? WHERE watchlist_id = ? AND symbol = ?",
                    (position, list_id, symbol),
                )
