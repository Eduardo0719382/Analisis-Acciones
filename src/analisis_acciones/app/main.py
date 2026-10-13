"""Application entry point."""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QEvent, QProcess, QThreadPool
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analisis_acciones import __version__
from analisis_acciones.alerts.service import AlertService
from analisis_acciones.app.error_handler import install_excepthook
from analisis_acciones.app.logging_setup import configure_logging
from analisis_acciones.app.paths import APP_NAME, AppPaths
from analisis_acciones.models.errors import AppError, user_message_for
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.drawing_service import DrawingService
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.services.update_service import UpdateService
from analisis_acciones.services.watchlist_service import WatchlistService
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
        # Separate connection for market data: it is used from worker threads.
        market_conn = open_database(paths.database)
        alerts_conn = open_database(paths.database)
    except (AppError, sqlite3.Error, OSError) as exc:
        logger.exception("Could not open database %s", paths.database)
        QMessageBox.critical(
            None,
            strings.ERROR_TITLE,
            f"{strings.STARTUP_ERROR}\n\n{user_message_for(exc)}\n\nRegistro: {log_file}",
        )
        return 1

    window: MainWindow | None = None
    market: MarketDataService | None = None
    alerts: AlertService | None = None
    try:
        settings = SettingsService(SettingsRepository(conn))
        apply_theme(app, settings.theme())

        if not settings.disclaimer_accepted():
            if DisclaimerDialog().exec() != QDialog.DialogCode.Accepted:
                logger.info("Disclaimer not accepted; exiting")
                return 0
            settings.accept_disclaimer()

        market = MarketDataService(YahooFinanceProvider(), market_conn)
        alerts = AlertService(alerts_conn, market)
        window = MainWindow(
            settings,
            update_service=UpdateService(),
            market_service=market,
            watchlist_service=WatchlistService(conn),
            alert_service=alerts,
            drawing_service=DrawingService(conn),
        )
        window.show()
        window.restore_last_symbol()
        window.schedule_startup_update_check()
        window.start_alert_schedule()
        code = app.exec()
        restart = window.restart_requested
    finally:
        if window is not None:
            # Destroy the window before its services' connections are closed.
            window.hide()
            window.deleteLater()
            # processEvents() does not run deferred deletions; without this the
            # chart's web page outlives the application and Chromium crashes on exit.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        QThreadPool.globalInstance().waitForDone(5000)
        # Closing through the service waits for any worker still inside a query
        # (a slow network request may outlive the wait above).
        if alerts is not None:
            alerts.close()
        else:
            alerts_conn.close()
        if market is not None:
            market.close()
        else:
            market_conn.close()
        conn.close()
        logger.info("Shutdown complete")

    if restart:
        logger.info("Restarting after update")
        QProcess.startDetached(sys.executable, ["-m", "analisis_acciones"])
    return code
