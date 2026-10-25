from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from analisis_acciones.models.errors import UserError
from analisis_acciones.services import backup
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.services.watchlist_service import WatchlistService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow


def populated(path: Path) -> sqlite3.Connection:
    conn = open_database(path)
    WatchlistService(conn).add(WatchlistService(conn).lists()[0].id, "AAPL")
    PaperPortfolioService(conn, None).create("Prueba", 5000)  # type: ignore[arg-type]
    return conn


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "datos"
    root.mkdir()
    database = root / "analisis_acciones.sqlite3"
    conn = populated(database)
    copy = tmp_path / "copia.sqlite3"
    info = backup.create_backup(conn, copy)
    assert info.portfolios == 1 and info.symbols == 1 and info.watchlists >= 1
    # Changes after the backup are replaced by the restore.
    PaperPortfolioService(conn, None).create("Después", 100)  # type: ignore[arg-type]
    conn.close()

    staged = backup.schedule_restore(copy, root)
    assert staged == backup.inspect_backup(copy)
    assert backup.apply_pending_restore(database)
    assert not (root / backup.PENDING_NAME).exists()
    assert (root / ("analisis_acciones.sqlite3" + backup.PREVIOUS_SUFFIX)).exists()
    restored = open_database(database)
    names = [r["name"] for r in restored.execute("SELECT name FROM paper_portfolios")]
    assert names == ["Prueba"]
    restored.close()
    assert not backup.apply_pending_restore(database)  # nothing staged any more


def test_invalid_files_are_rejected(tmp_path: Path) -> None:
    text = tmp_path / "nota.sqlite3"
    text.write_text("no soy una base de datos")
    other = tmp_path / "otra.sqlite3"
    sqlite3.connect(other).execute("CREATE TABLE x (a)").connection.close()
    empty = tmp_path / "vacio.sqlite3"
    empty.write_bytes(b"")
    for path in (text, other, empty, tmp_path / "no_existe.sqlite3"):
        with pytest.raises(UserError):
            backup.inspect_backup(path)


def test_newer_backup_is_refused(tmp_path: Path) -> None:
    conn = open_database(tmp_path / "a.sqlite3")
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (9999, '9999_x.sql')")
    copy = tmp_path / "nueva.sqlite3"
    with pytest.raises(UserError) as exc:
        backup.create_backup(conn, copy)
    assert "más reciente" in exc.value.user_message
    conn.close()


def test_corrupt_staged_restore_keeps_current_data(tmp_path: Path) -> None:
    database = tmp_path / "analisis_acciones.sqlite3"
    populated(database).close()
    (tmp_path / backup.PENDING_NAME).write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    assert not backup.apply_pending_restore(database)
    assert not (tmp_path / backup.PENDING_NAME).exists()
    conn = open_database(database)
    assert conn.execute("SELECT COUNT(*) FROM paper_portfolios").fetchone()[0] == 1
    conn.close()


def test_window_backup_and_restore_actions(
    qtbot: QtBot,
    settings: SettingsService,
    conn: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "datos"
    root.mkdir()
    win = MainWindow(settings, backup_conn=conn, data_root=root)
    qtbot.addWidget(win)
    assert win.backup_action.isEnabled() and win.restore_action.isEnabled()
    copy = tmp_path / "copia.sqlite3"
    info = win.create_backup(copy)
    assert info is not None and copy.exists()
    assert "Copia de seguridad guardada" in win.statusBar().currentMessage()
    assert win.restore_backup(copy, confirm=False)
    assert (root / backup.PENDING_NAME).exists()
    bad = tmp_path / "mal.sqlite3"
    bad.write_text("x")
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _w, _t, text: warned.append(text))
    assert not win.restore_backup(bad, confirm=False)
    assert warned and "no es una copia" in warned[0]
    plain = MainWindow(settings)
    qtbot.addWidget(plain)
    assert not plain.backup_action.isEnabled()
