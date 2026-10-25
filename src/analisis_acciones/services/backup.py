"""Backup and restore of everything the program stores (to move it to another PC).

A backup is a consistent copy of the SQLite database made with SQLite's online
backup API: settings, watchlists, alerts, drawings, paper portfolios and the
market-data cache (including imported CSV series).

A file chosen for restoring is external data: it is opened read-only, checked
with SQLite's integrity check, must look like this program's database and must
not come from a newer version. The restore itself happens at the next start,
before any connection is opened; the current database is kept next to it.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from analisis_acciones.models.errors import UserError
from analisis_acciones.storage.database import load_migrations

logger = logging.getLogger(__name__)

PENDING_NAME = "restaurar_pendiente.sqlite3"
PREVIOUS_SUFFIX = ".antes-de-restaurar"
REQUIRED_TABLES = ("schema_migrations", "settings", "watchlists", "paper_portfolios")
MAX_BACKUP_BYTES = 4 * 1024**3


@dataclass(frozen=True)
class BackupInfo:
    version: int
    watchlists: int
    symbols: int
    alerts: int
    portfolios: int
    trades: int
    size_bytes: int


def default_backup_name(now: datetime) -> str:
    return f"copia_analisis_acciones_{now:%Y-%m-%d}.sqlite3"


def create_backup(conn: sqlite3.Connection, destination: Path) -> BackupInfo:
    """Write a consistent copy of the open database to ``destination``."""
    tmp = destination.with_name(destination.name + ".tmp")
    try:
        target = sqlite3.connect(str(tmp))
        try:
            conn.backup(target)
        finally:
            target.close()
        os.replace(tmp, destination)
    except (OSError, sqlite3.Error) as exc:
        tmp.unlink(missing_ok=True)
        raise UserError(
            f"backup failed: {exc}", user_message=f"No se pudo crear la copia: {exc}"
        ) from exc
    logger.info("Backup written to %s", destination)
    return inspect_backup(destination)


def inspect_backup(path: Path) -> BackupInfo:
    """Validate a backup file (read-only) and summarise what it contains."""
    invalid = UserError(
        f"not a valid backup: {path}",
        user_message="El archivo no es una copia de seguridad válida de este programa.",
    )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise UserError(f"cannot read {path}", user_message=f"No se puede leer: {exc}") from exc
    if not 0 < size <= MAX_BACKUP_BYTES:
        raise invalid
    try:
        with path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                raise invalid
        uri = f"{path.resolve().as_uri()}?mode=ro"
        db = sqlite3.connect(uri, uri=True)
    except (OSError, sqlite3.Error) as exc:
        raise invalid from exc
    try:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise invalid
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(REQUIRED_TABLES) <= tables:
            raise invalid
        version = int(db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0)
        latest = max(m.version for m in load_migrations())
        if version > latest:
            raise UserError(
                f"backup version {version} > {latest}",
                user_message=(
                    "La copia es de una versión más reciente del programa. Actualice el "
                    "programa antes de restaurarla."
                ),
            )

        def count(table: str) -> int:
            if table not in tables:
                return 0
            return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        return BackupInfo(version, count("watchlists"), count("watchlist_items"),
                          count("alerts"), count("paper_portfolios"), count("paper_trades"),
                          size)  # fmt: skip
    except sqlite3.Error as exc:
        raise invalid from exc
    finally:
        db.close()


def schedule_restore(source: Path, data_root: Path) -> BackupInfo:
    """Validate ``source`` and stage it to replace the database at the next start."""
    info = inspect_backup(source)
    pending = data_root / PENDING_NAME
    try:
        shutil.copyfile(source, pending)
    except OSError as exc:
        raise UserError(
            f"cannot stage restore: {exc}", user_message=f"No se pudo preparar la copia: {exc}"
        ) from exc
    logger.info("Restore of %s scheduled for the next start", source)
    return info


def apply_pending_restore(database: Path) -> bool:
    """At startup, before opening the database: swap in a staged backup.

    The current database (and its WAL files) is renamed with PREVIOUS_SUFFIX. A
    staged file that fails validation is discarded and the current data is kept.
    """
    pending = database.with_name(PENDING_NAME)
    if not pending.exists():
        return False
    try:
        inspect_backup(pending)
    except UserError as exc:
        logger.error("Discarding staged restore: %s", exc)
        pending.unlink(missing_ok=True)
        return False
    previous = database.with_name(database.name + PREVIOUS_SUFFIX)
    for suffix in ("", "-wal", "-shm"):
        Path(str(previous) + suffix).unlink(missing_ok=True)  # an older restore's leftovers
        current = Path(str(database) + suffix)
        if current.exists():
            os.replace(current, Path(str(previous) + suffix))
    os.replace(pending, database)
    logger.info("Database restored from backup; previous copy kept as %s", previous)
    return True
