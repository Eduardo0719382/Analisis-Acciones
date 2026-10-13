from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator

import pytest

# Qt must run headless in CI and in the development container.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.storage.settings_repository import SettingsRepository


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def settings(conn: sqlite3.Connection) -> SettingsService:
    return SettingsService(SettingsRepository(conn))
