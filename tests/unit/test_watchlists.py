from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analisis_acciones.models.errors import UserError
from analisis_acciones.services.watchlist_service import DEFAULT_LIST_NAME, WatchlistService
from analisis_acciones.storage.database import open_database


@pytest.fixture
def lists(conn: sqlite3.Connection) -> WatchlistService:
    return WatchlistService(conn)


def test_default_list_created_once(lists: WatchlistService) -> None:
    first = lists.lists()
    assert [w.name for w in first] == [DEFAULT_LIST_NAME]
    assert lists.lists() == first


def test_add_normalises_and_ignores_duplicates(lists: WatchlistService) -> None:
    wid = lists.lists()[0].id
    assert lists.add(wid, " aapl ")
    assert not lists.add(wid, "AAPL")
    assert lists.add(wid, "csv:mio")
    assert lists.symbols(wid) == ["AAPL", "CSV:MIO"]


def test_invalid_symbol_rejected(lists: WatchlistService) -> None:
    with pytest.raises(UserError):
        lists.add(lists.lists()[0].id, "not a ticker!")


def test_remove_and_reorder(lists: WatchlistService) -> None:
    wid = lists.lists()[0].id
    for s in ("AAA", "BBB", "CCC"):
        lists.add(wid, s)
    assert lists.move(wid, "CCC", -1) == ["AAA", "CCC", "BBB"]
    assert lists.move(wid, "AAA", -5) == ["AAA", "CCC", "BBB"]  # clamped at the top
    assert lists.move(wid, "AAA", +10) == ["CCC", "BBB", "AAA"]
    lists.remove(wid, "BBB")
    assert lists.symbols(wid) == ["CCC", "AAA"]


def test_multiple_lists_are_independent(lists: WatchlistService) -> None:
    fav = lists.lists()[0].id
    tech = lists.create("  Tecnología  ").id
    lists.add(fav, "AAPL")
    lists.add(tech, "NVDA")
    assert lists.symbols(fav) == ["AAPL"]
    assert lists.symbols(tech) == ["NVDA"]
    assert [w.name for w in lists.lists()] == [DEFAULT_LIST_NAME, "Tecnología"]


def test_names_validated(lists: WatchlistService) -> None:
    lists.lists()
    with pytest.raises(UserError):
        lists.create("favoritos")  # case-insensitive duplicate
    with pytest.raises(UserError):
        lists.create("   ")
    with pytest.raises(UserError):
        lists.create("x" * 41)
    other = lists.create("Otra")
    lists.rename(other.id, "Renombrada")
    lists.rename(other.id, "renombrada")  # same list, case change allowed
    assert lists.lists()[1].name == "renombrada"


def test_delete_cascades_but_keeps_last_list(lists: WatchlistService) -> None:
    fav = lists.lists()[0].id
    other = lists.create("Otra").id
    lists.add(other, "MSFT")
    lists.delete(other)
    assert [w.id for w in lists.lists()] == [fav]
    with pytest.raises(UserError):
        lists.delete(fav)
    with pytest.raises(UserError):
        lists.add(other, "MSFT")


def test_persistence_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    first = open_database(path)
    service = WatchlistService(first)
    wid = service.create("Persistente").id
    service.add(wid, "TSLA")
    service.add(wid, "META")
    service.move(wid, "META", -1)
    first.close()

    second = open_database(path)
    try:
        again = WatchlistService(second)
        assert [w.name for w in again.lists()] == ["Persistente"]
        assert again.symbols(wid) == ["META", "TSLA"]
    finally:
        second.close()
