"""End-to-end startup of ``main()`` with a temporary data directory."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from pytestqt.qtbot import QtBot

from analisis_acciones.app import main as main_module
from analisis_acciones.app.paths import HOME_ENV_VAR, AppPaths
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.storage.settings_repository import SettingsRepository


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AppPaths:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    return AppPaths(tmp_path)


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
