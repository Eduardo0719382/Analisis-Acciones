from __future__ import annotations

import sqlite3
from pathlib import Path

from analisis_acciones.services.settings_service import (
    KEY_LAYOUT,
    KEY_THEME,
    SettingsService,
    Theme,
)
from analisis_acciones.storage.database import open_database
from analisis_acciones.storage.settings_repository import SettingsRepository


def test_defaults(settings: SettingsService) -> None:
    assert settings.theme() is Theme.DARK
    assert settings.disclaimer_accepted() is False
    assert settings.layout() == {}


def test_round_trip(settings: SettingsService) -> None:
    settings.set_theme(Theme.LIGHT)
    settings.accept_disclaimer()
    settings.set_layout({"main_split": [1, 2, 3], "geometry": "abc"})
    assert settings.theme() is Theme.LIGHT
    assert settings.disclaimer_accepted() is True
    assert settings.layout() == {"main_split": [1, 2, 3], "geometry": "abc"}


def test_settings_survive_reopening_the_database(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    first = open_database(path)
    SettingsService(SettingsRepository(first)).set_theme(Theme.LIGHT)
    first.close()

    second = open_database(path)
    try:
        assert SettingsService(SettingsRepository(second)).theme() is Theme.LIGHT
    finally:
        second.close()


def test_invalid_stored_values_fall_back_to_defaults(conn: sqlite3.Connection) -> None:
    repo = SettingsRepository(conn)
    repo.set(KEY_THEME, "purple")
    repo.set(KEY_LAYOUT, [1, 2])
    service = SettingsService(repo)
    assert service.theme() is Theme.DARK
    assert service.layout() == {}


def test_corrupt_json_is_ignored(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (KEY_THEME, "{not json"))
    assert SettingsRepository(conn).get(KEY_THEME) is None
    assert SettingsService(SettingsRepository(conn)).theme() is Theme.DARK


def test_reset_layout(settings: SettingsService) -> None:
    settings.set_layout({"a": 1})
    settings.reset_layout()
    assert settings.layout() == {}


def test_unicode_values(conn: sqlite3.Connection) -> None:
    repo = SettingsRepository(conn)
    repo.set("x", "Acción ñ €")
    assert repo.get("x") == "Acción ñ €"
