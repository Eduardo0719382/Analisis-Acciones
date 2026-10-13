from __future__ import annotations

import logging
from pathlib import Path

import pytest

from analisis_acciones.app.logging_setup import LOG_FILE_NAME, configure_logging
from analisis_acciones.app.paths import HOME_ENV_VAR, AppPaths


def test_home_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path / "data"))
    paths = AppPaths.default()
    paths.ensure()
    assert paths.root == tmp_path / "data"
    assert paths.logs.is_dir()
    assert paths.database.parent == paths.root


def test_default_location_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOME_ENV_VAR, raising=False)
    assert "AnalisisAcciones" in str(AppPaths.default().root)


def test_logging_writes_file(tmp_path: Path) -> None:
    log_file = configure_logging(tmp_path, level="DEBUG")
    try:
        logging.getLogger("test").info("hola registro")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert log_file.name == LOG_FILE_NAME
        assert "hola registro" in log_file.read_text(encoding="utf-8")
    finally:
        for handler in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_unknown_log_level_falls_back_to_info(tmp_path: Path) -> None:
    configure_logging(tmp_path, level="LOUD")
    try:
        assert logging.getLogger().level == logging.INFO
    finally:
        for handler in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(handler)
            handler.close()
