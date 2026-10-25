"""End-to-end startup of ``main()`` with a temporary data directory."""

from __future__ import annotations

import faulthandler
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from pytestqt.qtbot import QtBot

from analisis_acciones.app import main as main_module
from analisis_acciones.app.crash_guard import MARKER_NAME, SOFTWARE_FLAG_NAME
from analisis_acciones.app.paths import HOME_ENV_VAR, AppPaths
from analisis_acciones.services.backup import PREVIOUS_SUFFIX, create_backup, schedule_restore
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.storage.settings_repository import SettingsRepository


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[AppPaths]:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    # main() installs global hooks (exceptions, threads, crash log); restore them afterwards.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    yield AppPaths(tmp_path)
    faulthandler.enable(file=sys.__stderr__ or sys.stderr)


def test_unclean_exit_is_detected_and_cleared(
    qtbot: QtBot, home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        main_module.DisclaimerDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    home.ensure()
    (home.root / MARKER_NAME).write_text("1", encoding="utf-8")  # previous run "crashed"
    assert main_module.main([]) == 0
    assert not (home.root / MARKER_NAME).exists()  # this run ended cleanly
    assert (home.root / SOFTWARE_FLAG_NAME).exists()  # second unexpected exit in a row
    log = (home.logs / "analisis_acciones.log").read_text("utf-8")
    assert "Previous session ended unexpectedly (2 in a row)" in log
    assert (home.logs / "crash.log").exists()


def _settings_after_run(paths: AppPaths) -> SettingsService:
    return SettingsService(SettingsRepository(open_database(paths.database)))


def test_first_run_accepting_disclaimer(
    qtbot: QtBot, home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        main_module.DisclaimerDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    assert main_module.main([]) == 0
    assert home.database.exists()
    assert (home.logs / "analisis_acciones.log").exists()
    assert _settings_after_run(home).disclaimer_accepted()


def test_first_run_rejecting_disclaimer_exits_cleanly(
    qtbot: QtBot, home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        main_module.DisclaimerDialog, "exec", lambda self: QDialog.DialogCode.Rejected
    )
    assert main_module.main([]) == 0
    assert not _settings_after_run(home).disclaimer_accepted()


def test_corrupt_database_reports_error(
    qtbot: QtBot, home: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    home.ensure()
    home.database.write_bytes(b"this is not a sqlite database" * 100)
    shown: list[str] = []
    monkeypatch.setattr(main_module.QMessageBox, "critical", lambda *args: shown.append(args[2]))
    assert main_module.main([]) == 1
    assert shown and "No se pudo iniciar" in shown[0]


def test_staged_backup_is_restored_at_start(
    qtbot: QtBot, home: AppPaths, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        main_module.DisclaimerDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    home.ensure()
    source = open_database(tmp_path / "otro_pc.sqlite3")
    SettingsService(SettingsRepository(source)).set_last_opened("MSFT", "1d")
    copy = tmp_path / "copia.sqlite3"
    create_backup(source, copy)
    source.close()
    open_database(home.database).close()  # current data, to be replaced
    schedule_restore(copy, home.root)
    assert main_module.main([]) == 0
    assert _settings_after_run(home).last_symbol() == "MSFT"
    assert (home.root / ("analisis_acciones.sqlite3" + PREVIOUS_SUFFIX)).exists()
