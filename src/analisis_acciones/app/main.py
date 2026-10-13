"""Application entry point."""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analisis_acciones import __version__
from analisis_acciones.app.error_handler import install_excepthook, user_message_for
from analisis_acciones.app.logging_setup import configure_logging
from analisis_acciones.app.paths import APP_NAME, AppPaths
from analisis_acciones.models.errors import AppError
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.storage.settings_repository import SettingsRepository
from analisis_acciones.ui import strings
from analisis_acciones.ui.disclaimer import DisclaimerDialog
from analisis_acciones.ui.main_window import MainWindow
from analisis_acciones.ui.theme import apply_theme

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    paths = AppPaths.default()
    try:
        paths.ensure()
    except OSError as exc:
        print(f"Cannot create data directory {paths.root}: {exc}", file=sys.stderr)
        return 1

    log_file = configure_logging(paths.logs)
    logger.info("Starting %s %s (data dir: %s)", APP_NAME, __version__, paths.root)

    existing = QApplication.instance()
    app = (
        existing
        if isinstance(existing, QApplication)
        else QApplication(list(argv) if argv is not None else sys.argv)
    )
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(strings.APP_TITLE)
    app.setApplicationVersion(__version__)
    install_excepthook()

    try:
        conn = open_database(paths.database)
    except (AppError, sqlite3.Error, OSError) as exc:
        logger.exception("Could not open database %s", paths.database)
        QMessageBox.critical(
            None,
            strings.ERROR_TITLE,
            f"{strings.STARTUP_ERROR}\n\n{user_message_for(exc)}\n\nRegistro: {log_file}",
        )
        return 1

    try:
        settings = SettingsService(SettingsRepository(conn))
        apply_theme(app, settings.theme())

        if not settings.disclaimer_accepted():
            if DisclaimerDialog().exec() != QDialog.DialogCode.Accepted:
                logger.info("Disclaimer not accepted; exiting")
                return 0
            settings.accept_disclaimer()

        window = MainWindow(settings)
        window.show()
        return app.exec()
    finally:
        conn.close()
        logger.info("Shutdown complete")
