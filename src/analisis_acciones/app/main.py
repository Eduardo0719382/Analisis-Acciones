"""Application entry point."""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QEvent, QProcess, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analisis_acciones import __version__
from analisis_acciones.alerts.service import AlertService
from analisis_acciones.app.crash_guard import (
    SessionGuard,
    apply_software_rendering,
    ensure_std_streams,
    install_diagnostics,
)
from analisis_acciones.app.error_handler import install_excepthook
from analisis_acciones.app.logging_setup import configure_logging
from analisis_acciones.app.paths import APP_NAME, AppPaths
from analisis_acciones.models.errors import AppError, user_message_for
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.drawing_service import DrawingService
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
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


SMOKE_TEST_FLAG = "--smoke-test"
SMOKE_TEST_TIMEOUT_MS = 60_000
SMOKE_EXIT_CHART_FAILED = 3


def _start_smoke_test(app: QApplication, window: MainWindow) -> None:
    """Quit with 0 once the chart page has loaded, or with an error code on timeout.

    Used to verify packaged builds (including the web engine) start correctly.
    """
    timer = QTimer(app)
    elapsed = {"ms": 0}

    def poll() -> None:
        elapsed["ms"] += 250
        if window.chart.is_loaded:
            logger.info("Smoke test passed after %d ms", elapsed["ms"])
            app.exit(0)
        elif elapsed["ms"] >= SMOKE_TEST_TIMEOUT_MS:
            logger.error("Smoke test failed: chart page did not load")
            app.exit(SMOKE_EXIT_CHART_FAILED)

    timer.timeout.connect(poll)
    timer.start(250)


def main(argv: Sequence[str] | None = None) -> int:
    ensure_std_streams()
    args = list(argv) if argv is not None else sys.argv[1:]
    smoke_test = SMOKE_TEST_FLAG in args
    paths = AppPaths.default()
    try:
        paths.ensure()
    except OSError as exc:
        print(f"Cannot create data directory {paths.root}: {exc}", file=sys.stderr)
        return 1

    log_file = configure_logging(paths.logs)
    crash_log = install_diagnostics(paths.logs)
    logger.info("Starting %s %s (data dir: %s)", APP_NAME, __version__, paths.root)
    guard = SessionGuard(paths.root)
    start = guard.begin()
    if start.previous_unclean:
        logger.warning(
            "Previous session ended unexpectedly (%d in a row); see %s",
            start.consecutive_unclean,
            crash_log,
        )
    existing = QApplication.instance()
    if start.software_rendering and existing is None:
        logger.info("Using software rendering for web views")
        apply_software_rendering()

    app = (
        existing
        if isinstance(existing, QApplication)
        else QApplication([sys.argv[0], *[a for a in args if a != SMOKE_TEST_FLAG]])
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
        portfolio_conn = open_database(paths.database)
    except (AppError, sqlite3.Error, OSError) as exc:
        logger.exception("Could not open database %s", paths.database)
        QMessageBox.critical(
            None,
            strings.ERROR_TITLE,
            f"{strings.STARTUP_ERROR}\n\n{user_message_for(exc)}\n\nRegistro: {log_file}",
        )
        guard.end()
        return 1

    window: MainWindow | None = None
    market: MarketDataService | None = None
    alerts: AlertService | None = None
    try:
        settings = SettingsService(SettingsRepository(conn))
        apply_theme(app, settings.theme())

        if not smoke_test and not settings.disclaimer_accepted():
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
            portfolio_service=PaperPortfolioService(portfolio_conn, market),
            session_guard=guard,
        )
        window.show()
        if smoke_test:
            _start_smoke_test(app, window)
        else:
            window.restore_last_symbol()
            window.schedule_startup_update_check()
            window.start_alert_schedule()
            window.start_daily_scan()
            window.show_day_summary_on_start()
            # Bound to the window: cancelled automatically if the window is destroyed first.
            notice_window = window
            QTimer.singleShot(
                1500,
                notice_window,
                lambda: notice_window.show_unclean_exit_notice(start, crash_log),
            )
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
        portfolio_conn.close()
        if market is not None:
            market.close()
        else:
            market_conn.close()
        conn.close()
        guard.end()
        logger.info("Shutdown complete")

    if restart:
        logger.info("Restarting after update")
        QProcess.startDetached(sys.executable, ["-m", "analisis_acciones"])
    return code
