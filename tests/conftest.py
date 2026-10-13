from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator

import pytest

# Qt must run headless in CI and in the development container.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Chromium (QtWebEngine) cannot use its sandbox as root in containers, and there is no GPU.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

# QtWebEngine must be imported before the QApplication is created.
from PySide6 import QtWebEngineWidgets  # noqa: F401

from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.storage.settings_repository import SettingsRepository


def wait_for_workers() -> None:
    """Background workers may still use a connection when a test ends."""
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(10_000)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_database(":memory:")
    yield connection
    wait_for_workers()
    connection.close()


@pytest.fixture
def settings(conn: sqlite3.Connection) -> SettingsService:
    return SettingsService(SettingsRepository(conn))


@pytest.fixture(scope="session", autouse=True)
def _dispose_widgets_at_exit() -> Iterator[None]:
    """Delete every widget (and its QWebEnginePage) before the QApplication goes away.

    Otherwise Chromium tears down its profile while pages still exist and the
    interpreter crashes on exit (PROBLEMS.md P-011).
    """
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    wait_for_workers()
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
