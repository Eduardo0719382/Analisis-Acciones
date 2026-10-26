"""The lab's own SQLite file: orders, decisions, equity snapshots and benchmarks.

It is the source of truth for the virtual books (``lab.book`` derives them from the filled
orders). Rows are only added or updated, never deleted, so an eliminated profile keeps
its full history.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from analisis_acciones.storage.database import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    capital REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    symbol TEXT NOT NULL,             -- app notation: AAPL, BTC-USD
    side TEXT NOT NULL,               -- buy / sell
    notional REAL,                    -- dollars asked for (buys)
    qty_requested REAL,               -- quantity asked for (sells)
    status TEXT NOT NULL,             -- sending, open, filled, partial, dead, not_sent
    alpaca_id TEXT,
    filled_qty REAL NOT NULL DEFAULT 0,
    filled_price REAL,
    filled_at TEXT,
    fee_coin REAL NOT NULL DEFAULT 0, -- crypto buys: coin kept by Alpaca
    fee_usd REAL NOT NULL DEFAULT 0,  -- crypto sells, stock regulatory fees
    bid REAL, ask REAL,               -- quote when decided (to measure slippage)
    forced INTEGER NOT NULL DEFAULT 0, -- sent by the executor (stop), not by the agent
    reason TEXT NOT NULL DEFAULT '',
    decision_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_profile ON orders(profile, created_at);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    profile TEXT NOT NULL,
    kind TEXT NOT NULL,      -- comprar, vender, mantener, nada, sin_accion, no_toca, error
    reason TEXT NOT NULL,    -- the agent's 1-3 lines
    payload TEXT NOT NULL,   -- the agent's decision as sent (JSON)
    outcome TEXT NOT NULL,   -- what the executor did and refused (JSON)
    cash REAL, equity REAL
);
CREATE INDEX IF NOT EXISTS decisions_profile ON decisions(profile, at);
CREATE TABLE IF NOT EXISTS snapshots (
    at TEXT NOT NULL,
    profile TEXT NOT NULL,
    cash REAL NOT NULL,
    equity REAL NOT NULL,
    PRIMARY KEY (at, profile)
);
CREATE TABLE IF NOT EXISTS prices (
    at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    PRIMARY KEY (at, symbol)
);
CREATE TABLE IF NOT EXISTS notes (
    at TEXT NOT NULL,
    kind TEXT NOT NULL,      -- reconcile, fee_check, invariant…
    text TEXT NOT NULL
);
"""

OPEN_STATES = ("sending", "open", "partial")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Store:
    conn: sqlite3.Connection

    @classmethod
    def open(cls, path: Path | str) -> Store:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = connect(path)
        conn.executescript(SCHEMA)
        return cls(conn)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # -- profiles -------------------------------------------------------------------------

    def ensure_profile(self, profile_id: str, capital: float, at: str | None = None) -> str:
        """Start date of the profile's book (created on first sight)."""
        row = self.conn.execute("SELECT started_at FROM profiles WHERE id = ?",
                                (profile_id,)).fetchone()  # fmt: skip
        if row:
            return str(row["started_at"])
        started = at or now_iso()
        self.conn.execute("INSERT INTO profiles (id, started_at, capital) VALUES (?, ?, ?)",
                          (profile_id, started, capital))  # fmt: skip
        return started

    def profile_start(self, profile_id: str) -> tuple[str, float] | None:
        row = self.conn.execute("SELECT started_at, capital FROM profiles WHERE id = ?",
                                (profile_id,)).fetchone()  # fmt: skip
        return (str(row["started_at"]), float(row["capital"])) if row else None

    # -- orders ---------------------------------------------------------------------------

    def add_order(self, *, client_order_id: str, profile: str, symbol: str, side: str,
                  notional: float | None, qty: float | None, bid: float | None,
                  ask: float | None, forced: bool, reason: str,
                  decision_id: int | None) -> None:  # fmt: skip
        at = now_iso()
        self.conn.execute(
            "INSERT INTO orders (client_order_id, profile, symbol, side, notional, qty_requested,"
            " status, bid, ask, forced, reason, decision_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'sending', ?, ?, ?, ?, ?, ?, ?)",
            (client_order_id, profile, symbol, side, notional, qty, bid, ask, int(forced),
             reason, decision_id, at, at),
        )  # fmt: skip

    def update_order(self, client_order_id: str, **fields: Any) -> None:
        allowed = {"status", "alpaca_id", "filled_qty", "filled_price", "filled_at", "fee_coin",
                   "fee_usd", "decision_id"}  # fmt: skip
        if not fields or set(fields) - allowed:
            raise ValueError(f"bad order fields {set(fields) - allowed}")
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE orders SET {cols}, updated_at = ? WHERE client_order_id = ?",
                          (*fields.values(), now_iso(), client_order_id))  # fmt: skip

    def orders(self, profile: str | None = None, states: tuple[str, ...] | None = None,
               since: str | None = None) -> list[sqlite3.Row]:  # fmt: skip
        sql, args = "SELECT * FROM orders WHERE 1 = 1", []
        if profile:
            sql += " AND profile = ?"
            args.append(profile)
        if states:
            sql += f" AND status IN ({', '.join('?' * len(states))})"
            args.extend(states)
        if since:
            sql += " AND created_at >= ?"
            args.append(since)
        return list(self.conn.execute(sql + " ORDER BY COALESCE(filled_at, created_at), created_at",
                                      args))  # fmt: skip

    # -- decisions, snapshots, prices, notes ----------------------------------------------

    def add_decision(self, profile: str, kind: str, reason: str, payload: Any,
                     at: str | None = None) -> int:  # fmt: skip
        cur = self.conn.execute(
            "INSERT INTO decisions (at, profile, kind, reason, payload, outcome)"
            " VALUES (?, ?, ?, ?, ?, '{}')",
            (at or now_iso(), profile, kind, reason, json.dumps(payload, ensure_ascii=False)),
        )
        return int(cur.lastrowid or 0)

    def finish_decision(self, decision_id: int, outcome: Any, cash: float, equity: float) -> None:
        self.conn.execute(
            "UPDATE decisions SET outcome = ?, cash = ?, equity = ? WHERE id = ?",
            (json.dumps(outcome, ensure_ascii=False), cash, equity, decision_id),
        )

    def decisions(self, profile: str | None = None, since: str | None = None,
                  limit: int | None = None) -> list[sqlite3.Row]:  # fmt: skip
        sql, args = "SELECT * FROM decisions WHERE 1 = 1", []
        if profile:
            sql += " AND profile = ?"
            args.append(profile)
        if since:
            sql += " AND at >= ?"
            args.append(since)
        sql += " ORDER BY id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(self.conn.execute(sql, args))

    def add_snapshot(self, profile: str, cash: float, equity: float, at: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO snapshots (at, profile, cash, equity) VALUES (?, ?, ?, ?)",
            (at or now_iso(), profile, cash, equity),
        )

    def snapshots(self, profile: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM snapshots WHERE profile = ? ORDER BY at",
                                      (profile,)))  # fmt: skip

    def add_prices(self, prices: dict[str, float], at: str | None = None) -> None:
        stamp = at or now_iso()
        self.conn.executemany("INSERT OR REPLACE INTO prices (at, symbol, price) VALUES (?, ?, ?)",
                              [(stamp, s, p) for s, p in prices.items()])  # fmt: skip

    def price_at_or_after(self, symbol: str, at: str) -> float | None:
        row = self.conn.execute(
            "SELECT price FROM prices WHERE symbol = ? AND at >= ? ORDER BY at LIMIT 1",
            (symbol, at),
        ).fetchone()
        return float(row["price"]) if row else None

    def price_series(self, symbol: str, since: str) -> list[tuple[str, float]]:
        return [(str(r["at"]), float(r["price"])) for r in self.conn.execute(
            "SELECT at, price FROM prices WHERE symbol = ? AND at >= ? ORDER BY at",
            (symbol, since))]  # fmt: skip

    def add_note(self, kind: str, text: str) -> None:
        self.conn.execute(
            "INSERT INTO notes (at, kind, text) VALUES (?, ?, ?)", (now_iso(), kind, text)
        )

    def notes(self, since: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM notes WHERE at >= ? ORDER BY at", (since,)))
