from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analisis_acciones.models.errors import InternalError
from analisis_acciones.storage.database import (
    Migration,
    apply_migrations,
    connect,
    current_version,
    load_migrations,
    open_database,
    transaction,
)


def test_bundled_migrations_are_sequential() -> None:
    versions = [m.version for m in load_migrations()]
    assert versions == list(range(1, len(versions) + 1))


def test_fresh_database_is_migrated_to_latest(conn: sqlite3.Connection) -> None:
    assert current_version(conn) == load_migrations()[-1].version
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "schema_migrations"} <= tables


def test_migrations_are_idempotent(conn: sqlite3.Connection) -> None:
    assert apply_migrations(conn) == []


def test_file_database_persists_schema(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    open_database(path).close()
    reopened = connect(path)
    try:
        assert current_version(reopened) == load_migrations()[-1].version
        assert reopened.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert reopened.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        reopened.close()


def test_failed_migration_rolls_back_and_keeps_previous_version() -> None:
    db = connect(":memory:")
    migrations = [
        Migration(1, "0001_ok.sql", "CREATE TABLE a (x INTEGER);"),
        Migration(2, "0002_broken.sql", "CREATE TABLE b (y INTEGER); THIS IS NOT SQL;"),
    ]
    with pytest.raises(InternalError, match="0002_broken"):
        apply_migrations(db, migrations)
    assert current_version(db) == 1
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "a" in tables
    assert "b" not in tables
    assert not db.in_transaction


def test_newer_schema_than_app_is_rejected() -> None:
    db = connect(":memory:")
    apply_migrations(db, [Migration(5, "0005_future.sql", "SELECT 1;")])
    with pytest.raises(InternalError) as info:
        apply_migrations(db, [Migration(1, "0001_ok.sql", "SELECT 1;")])
    assert "versión más reciente" in info.value.user_message


def test_invalid_migration_name_is_rejected() -> None:
    db = connect(":memory:")
    with pytest.raises(InternalError, match="Invalid migration name"):
        apply_migrations(db, [Migration(1, "0001_x'); DROP TABLE t;--.sql", "SELECT 1;")])


def test_transaction_commits_and_rolls_back(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE t (x INTEGER)")
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO t VALUES (2)")
        raise RuntimeError("boom")
    assert [r[0] for r in conn.execute("SELECT x FROM t")] == [1]
