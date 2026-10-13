"""SQLite connection handling and schema migrations.

Migrations are numbered SQL files in ``storage/migrations`` named
``NNNN_description.sql``. Each one runs inside its own transaction together
with the row that records it, so a failing migration leaves the database at
the previous version.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from analisis_acciones.models.errors import InternalError

logger = logging.getLogger(__name__)

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations(package: str = "analisis_acciones.storage.migrations") -> list[Migration]:
    migrations: list[Migration] = []
    for entry in resources.files(package).iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            migrations.append(Migration(int(match.group(1)), entry.name, entry.read_text("utf-8")))
    migrations.sort(key=lambda m: m.version)
    versions = [m.version for m in migrations]
    if len(versions) != len(set(versions)):
        raise InternalError(f"Duplicate migration versions: {versions}")
    return migrations


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with explicit transaction control (autocommit mode)."""
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0]) if row[0] is not None else 0


def apply_migrations(
    conn: sqlite3.Connection, migrations: list[Migration] | None = None
) -> list[int]:
    """Apply pending migrations in order. Returns the versions applied."""
    pending_source = load_migrations() if migrations is None else migrations
    version = current_version(conn)
    latest_known = max((m.version for m in pending_source), default=0)
    if version > latest_known:
        raise InternalError(
            f"Database schema version {version} is newer than this application "
            f"supports ({latest_known})",
            user_message=(
                "La base de datos fue creada por una versión más reciente de la aplicación."
            ),
        )

    applied: list[int] = []
    for migration in pending_source:
        if migration.version <= version:
            continue
        if not _MIGRATION_NAME.match(migration.name):
            raise InternalError(f"Invalid migration name: {migration.name!r}")
        logger.info("Applying migration %s", migration.name)
        try:
            # executescript() cannot run inside an open transaction managed by
            # the sqlite3 module, so the transaction is part of the script.
            conn.executescript(
                "BEGIN;\n"
                f"{migration.sql}\n;"
                f"INSERT INTO schema_migrations (version, name) "
                f"VALUES ({migration.version}, '{migration.name}');\n"
                "COMMIT;"
            )
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise InternalError(f"Migration {migration.name} failed: {exc}") from exc
        applied.append(migration.version)
    return applied


def open_database(path: Path | str) -> sqlite3.Connection:
    conn = connect(path)
    try:
        apply_migrations(conn)
    except Exception:
        conn.close()
        raise
    return conn
