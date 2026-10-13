from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from analisis_acciones.storage.bar_repository import BarRepository
from analisis_acciones.storage.recent_repository import RecentSymbolRepository
from tests.synthetic import synthetic_daily

T0 = datetime(2024, 5, 1, 21, 0, tzinfo=UTC)


def test_round_trip_preserves_values_and_nan(conn: sqlite3.Connection) -> None:
    repo = BarRepository(conn)
    bars = synthetic_daily(sessions=30)
    bars.iloc[3, bars.columns.get_loc("volume")] = np.nan
    repo.replace("TEST", "src", bars, T0)
    loaded = repo.load("TEST")
    pd.testing.assert_frame_equal(loaded, bars.astype("float64"), check_freq=False)
    meta = repo.meta("TEST")
    assert meta is not None
    assert meta.first_date == date(2024, 1, 1)
    assert meta.last_date == bars.index[-1].date()
    assert meta.fetched_at == T0


def test_unknown_symbol(conn: sqlite3.Connection) -> None:
    repo = BarRepository(conn)
    assert repo.load("NONE").empty
    assert repo.meta("NONE") is None


def test_upsert_overwrites_and_appends(conn: sqlite3.Connection) -> None:
    repo = BarRepository(conn)
    bars = synthetic_daily(sessions=20)
    repo.replace("TEST", "src", bars.iloc[:10], T0)
    update = bars.iloc[8:].copy()
    update.iloc[0, update.columns.get_loc("close")] = 123.0
    repo.upsert("TEST", "src", update, T0)
    loaded = repo.load("TEST")
    assert len(loaded) == 20
    assert loaded.iloc[8]["close"] == 123.0


def test_replace_removes_old_rows(conn: sqlite3.Connection) -> None:
    repo = BarRepository(conn)
    repo.replace("TEST", "src", synthetic_daily(sessions=20), T0)
    repo.replace("TEST", "src", synthetic_daily(sessions=5), T0)
    assert len(repo.load("TEST")) == 5


def test_symbols_are_isolated(conn: sqlite3.Connection) -> None:
    repo = BarRepository(conn)
    repo.replace("A", "src", synthetic_daily(sessions=5), T0)
    repo.replace("B", "src", synthetic_daily(sessions=7), T0)
    repo.delete("A")
    assert repo.load("A").empty
    assert len(repo.load("B")) == 7


def test_recent_symbols_order_and_limit(conn: sqlite3.Connection) -> None:
    repo = RecentSymbolRepository(conn, max_entries=3)
    for i, sym in enumerate(["A", "B", "C", "D"]):
        repo.add(sym, f"Name {sym}", datetime(2024, 1, 1 + i, tzinfo=UTC))
    repo.add("B", None, datetime(2024, 2, 1, tzinfo=UTC))
    recent = repo.list()
    assert [r.symbol for r in recent] == ["B", "D", "C"]
    assert recent[0].name == "Name B"  # name kept when re-added without one
