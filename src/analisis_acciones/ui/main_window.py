"""Main application window: toolbar, three resizable regions and status bar."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QLocale, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from analisis_acciones import __version__
from analisis_acciones.alerts.service import AlertEvent, AlertService
from analisis_acciones.charts.chart_widget import ChartWidget
from analisis_acciones.charts.overlays import (
    elliott_overlay,
    levels_overlay,
    patterns_overlay,
    projection_overlay,
)
from analisis_acciones.charts.payload import chart_times, future_times
from analisis_acciones.data.export import bars_to_csv
from analisis_acciones.indicators.registry import IndicatorConfig
from analisis_acciones.models.errors import AppError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.services.daily_scan import Novelty
from analisis_acciones.services.drawing_service import DrawingService
from analisis_acciones.services.market_data_service import LoadResult, MarketDataService
from analisis_acciones.services.scanner import ScanResult
from analisis_acciones.services.settings_service import SettingsService, Theme
from analisis_acciones.services.update_service import UpdateCheck, UpdateService
from analisis_acciones.services.watchlist_service import WatchlistService
from analisis_acciones.ui import strings
from analisis_acciones.ui.alerts_panel import AlertsPanel
from analisis_acciones.ui.analysis_panel import AnalysisPanel
from analisis_acciones.ui.backtest_dialog import BacktestDialog
from analisis_acciones.ui.comparison_dialog import ComparisonDialog
from analisis_acciones.ui.daily_scan import DailyScanController
from analisis_acciones.ui.details_panel import DetailsPanel
from analisis_acciones.ui.disclaimer import DisclaimerDialog
from analisis_acciones.ui.elliott_panel import ElliottPanel, ElliottView
from analisis_acciones.ui.indicator_dialog import IndicatorDialog
from analisis_acciones.ui.market_controller import MarketController
from analisis_acciones.ui.panels import Panel
from analisis_acciones.ui.pattern_backtest_dialog import PatternBacktestDialog
from analisis_acciones.ui.patterns_panel import PatternsPanel, PatternsView
from analisis_acciones.ui.projection_panel import ProjectionOutcome, ProjectionPanel
from analisis_acciones.ui.report import build_report_html, write_pdf
from analisis_acciones.ui.scanner_dialog import ScannerDialog
from analisis_acciones.ui.search_box import SearchBox
from analisis_acciones.ui.theme import apply_theme, tokens_for
from analisis_acciones.ui.update_dialog import UpdateDialog
from analisis_acciones.ui.watchlist_panel import WatchlistPanel
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

DEFAULT_SIZE = (1400, 860)
DEFAULT_MAIN_SPLIT = [240, 900, 280]
STARTUP_UPDATE_CHECK_DELAY_MS = 3000


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: SettingsService,
        parent: QWidget | None = None,
        *,
        update_service: UpdateService | None = None,
        market_service: MarketDataService | None = None,
        watchlist_service: WatchlistService | None = None,
        alert_service: AlertService | None = None,
        drawing_service: DrawingService | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._update_service = update_service
        self.market = MarketController(market_service, self) if market_service else None
        self._watchlists = watchlist_service
        self._alert_service = alert_service
        self._drawings = drawing_service
        self._tray: QSystemTrayIcon | None = None
        self.current_symbol: str | None = None
        self.current_result: LoadResult | None = None
        self.restart_requested = False
        self._update_worker: Worker | None = None
        self.daily_scan: DailyScanController | None = None
        if market_service is not None:
            self.daily_scan = DailyScanController(settings, market_service,
                                                  self._watchlist_symbols, parent=self)  # fmt: skip
            self.daily_scan.finished.connect(self._on_daily_scan_finished)
        self.setWindowTitle(strings.APP_TITLE)
        self.setMinimumSize(800, 500)

        self._build_toolbar()
        self._build_regions()
        self._build_status_bar()
        self._build_menus()
        self._restore_layout()
        self._wire_market()
        self._wire_chart_type()

    # Construction ----------------------------------------------------------
    def _build_toolbar(self) -> None:
        bar = QToolBar("main", self)
        bar.setObjectName("mainToolbar")
        bar.setMovable(False)
        bar.setFloatable(False)

        self.search_box = SearchBox()
        self.search_box.setMinimumWidth(220)
        self.search_box.setMaximumWidth(340)
        bar.addWidget(self.search_box)

        self.symbol_label = QLabel(strings.NO_SYMBOL)
        self.symbol_label.setObjectName("symbolLabel")
        bar.addWidget(self.symbol_label)

        # Populated from the data service's available intervals only.
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.setObjectName("timeframeCombo")
        self.timeframe_combo.setToolTip(strings.TIMEFRAME_TOOLTIP)
        self.timeframe_combo.setEnabled(False)
        self.timeframe_combo.setMinimumWidth(70)
        bar.addWidget(self.timeframe_combo)

        self.chart_type_combo = QComboBox()
        self.chart_type_combo.setObjectName("chartTypeCombo")
        self.chart_type_combo.setToolTip(strings.CHART_TYPE_TOOLTIP)
        for key, label in strings.CHART_TYPE_LABELS.items():
            self.chart_type_combo.addItem(label, key)
        bar.addWidget(self.chart_type_combo)

        self.draw_button = QToolButton()
        self.draw_button.setObjectName("drawButton")
        self.draw_button.setText(strings.MENU_DRAW)
        self.draw_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        draw_menu = QMenu(self.draw_button)
        self.draw_actions: dict[str, QAction] = {}
        for mode, label in (
            ("hline", strings.DRAW_HLINE),
            ("trend", strings.DRAW_TREND),
            ("fib", strings.DRAW_FIB),
            ("note", strings.DRAW_NOTE),
        ):
            action = QAction(label, self)
            action.triggered.connect(partial(self.start_drawing, mode))
            draw_menu.addAction(action)
            self.draw_actions[mode] = action
        draw_menu.addSeparator()
        draw_menu.addAction(strings.DRAW_UNDO, self.undo_drawing)
        draw_menu.addAction(strings.DRAW_CLEAR, self.clear_drawings)
        self.draw_button.setMenu(draw_menu)
        bar.addWidget(self.draw_button)

        self.indicators_button = QPushButton(strings.INDICATORS_BUTTON)
        self.indicators_button.setObjectName("indicatorsButton")
        self.indicators_button.clicked.connect(self.edit_indicators)
        bar.addWidget(self.indicators_button)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self.toolbar = bar

    def _build_regions(self) -> None:
        self.watchlist_panel: Panel | WatchlistPanel
        if self._watchlists is not None:
            panel = WatchlistPanel(self._watchlists, self.market, self._settings)
            panel.symbol_activated.connect(self.open_symbol)
            panel.current_symbol_provider = lambda: (
                self.current_result.series.symbol if self.current_result else None
            )
            self.watchlist_panel = panel
        else:
            self.watchlist_panel = Panel(strings.PANEL_WATCHLIST, strings.EMPTY_WATCHLIST)
        # Price, volume and (later) indicator panes live inside one chart so their
        # time axes and crosshair stay synchronised (DECISIONS.md D-014).
        self.chart = ChartWidget()
        self.chart.set_theme(tokens_for(self._settings.theme()))
        self.chart.set_indicators(self._settings.indicators())
        self.chart.bridge.drawing_created.connect(self._on_drawing_created)
        self.chart.bridge.drawing_cancelled.connect(
            lambda: self.statusBar().showMessage(strings.STATUS_READY)
        )
        self.chart.indicators_failed.connect(
            lambda names: self.statusBar().showMessage(
                strings.INDICATORS_FAILED.format(names=", ".join(names))
            )
        )
        self.details_panel = DetailsPanel()
        self.details_panel.header.hide()  # the tab title already names it
        self.analysis_panel = AnalysisPanel(tokens_for(self._settings.theme()))
        self.right_tabs = QTabWidget()
        self.right_tabs.setObjectName("rightTabs")
        self.right_tabs.addTab(self.details_panel, strings.TAB_DETAILS)
        self.right_tabs.addTab(self.analysis_panel, strings.TAB_ANALYSIS)
        self.projection_panel = ProjectionPanel()
        self.projection_panel.projection_ready.connect(self._draw_projection)
        self.right_tabs.addTab(self.projection_panel, strings.TAB_PROJECTION)
        self.elliott_panel = ElliottPanel()
        self.elliott_panel.overlay_ready.connect(self._draw_elliott)
        self.elliott_panel.alerts_requested.connect(self.create_level_alerts)
        self.right_tabs.addTab(self.elliott_panel, strings.TAB_ELLIOTT)
        self.patterns_panel = PatternsPanel()
        self.patterns_panel.overlay_ready.connect(self._draw_patterns)
        self.patterns_panel.alerts_requested.connect(self.create_level_alerts)
        self.right_tabs.addTab(self.patterns_panel, strings.TAB_PATTERNS)
        self.alerts_panel: AlertsPanel | None = None
        if self._alert_service is not None:
            self.alerts_panel = AlertsPanel(self._alert_service)
            self.alerts_panel.current_symbol_provider = lambda: (
                self.current_result.series.symbol if self.current_result else None
            )
            self.alerts_panel.alerts_triggered.connect(self._notify_alerts)
            self.right_tabs.addTab(self.alerts_panel, strings.TAB_ALERTS)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.addWidget(self.watchlist_panel)
        self.main_splitter.addWidget(self.chart)
        self.main_splitter.addWidget(self.right_tabs)
        # Side panels may collapse; the chart region may not.
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setStretchFactor(1, 1)

        self.setCentralWidget(self.main_splitter)

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        self.provider_label = QLabel(
            strings.STATUS_PROVIDER.format(name=strings.STATUS_PROVIDER_NONE)
        )
        self.last_update_label = QLabel(
            strings.STATUS_LAST_UPDATE.format(when=strings.STATUS_NEVER)
        )
        self.update_notice = QPushButton(strings.UPDATE_NOTICE)
        self.update_notice.setObjectName("updateNotice")
        self.update_notice.setFlat(True)
        self.update_notice.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_notice.clicked.connect(self.check_for_updates)
        self.update_notice.hide()
        status.addPermanentWidget(self.update_notice)
        status.addPermanentWidget(self.provider_label)
        status.addPermanentWidget(self.last_update_label)
        status.showMessage(strings.STATUS_READY)

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu(strings.MENU_FILE)
        self.import_csv_action = QAction(strings.ACTION_IMPORT_CSV, self)
        self.import_csv_action.triggered.connect(self._import_csv)
        file_menu.addAction(self.import_csv_action)
        file_menu.addSeparator()
        self.export_image_action = QAction(strings.ACTION_EXPORT_IMAGE, self)
        self.export_image_action.triggered.connect(lambda: self.export_image())
        self.export_csv_action = QAction(strings.ACTION_EXPORT_CSV, self)
        self.export_csv_action.triggered.connect(lambda: self.export_csv())
        self.export_pdf_action = QAction(strings.ACTION_EXPORT_PDF, self)
        self.export_pdf_action.triggered.connect(lambda: self.export_pdf())
        for action in (self.export_image_action, self.export_csv_action, self.export_pdf_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction(strings.ACTION_QUIT, self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        tools_menu = menu_bar.addMenu(strings.MENU_TOOLS)
        self.backtest_action = QAction(strings.ACTION_BACKTEST, self)
        self.backtest_action.setShortcut(QKeySequence("Ctrl+B"))
        self.backtest_action.triggered.connect(self.open_backtest)
        tools_menu.addAction(self.backtest_action)
        self.compare_action = QAction(strings.ACTION_COMPARE, self)
        self.compare_action.triggered.connect(self.open_comparison)
        tools_menu.addAction(self.compare_action)
        self.pattern_backtest_action = QAction(strings.ACTION_PATTERN_BACKTEST, self)
        self.pattern_backtest_action.triggered.connect(self.open_pattern_backtest)
        tools_menu.addAction(self.pattern_backtest_action)
        self.scanner_action = QAction(strings.ACTION_SCANNER, self)
        self.scanner_action.setShortcut(QKeySequence("Ctrl+E"))
        self.scanner_action.triggered.connect(self.open_scanner)
        tools_menu.addAction(self.scanner_action)
        self.daily_scan_action = QAction(strings.ACTION_DAILY_SCAN, self)
        self.daily_scan_action.setCheckable(True)
        self.daily_scan_action.setChecked(self._settings.daily_scan_enabled())
        self.daily_scan_action.toggled.connect(self._on_daily_scan_toggled)
        tools_menu.addAction(self.daily_scan_action)
        self.last_daily_scan_action = QAction(strings.ACTION_LAST_DAILY_SCAN, self)
        self.last_daily_scan_action.setEnabled(False)
        self.last_daily_scan_action.triggered.connect(self.open_last_daily_scan)
        tools_menu.addAction(self.last_daily_scan_action)

        view_menu = menu_bar.addMenu(strings.MENU_VIEW)
        self.dark_theme_action = QAction(strings.ACTION_DARK_THEME, self)
        self.dark_theme_action.setCheckable(True)
        self.dark_theme_action.setChecked(self._settings.theme() is Theme.DARK)
        self.dark_theme_action.toggled.connect(self._on_dark_theme_toggled)
        view_menu.addAction(self.dark_theme_action)
        self.reset_layout_action = QAction(strings.ACTION_RESET_LAYOUT, self)
        self.reset_layout_action.triggered.connect(self.reset_layout)
        view_menu.addAction(self.reset_layout_action)

        help_menu = menu_bar.addMenu(strings.MENU_HELP)
        disclaimer_action = QAction(strings.ACTION_DISCLAIMER, self)
        disclaimer_action.triggered.connect(self._show_disclaimer)
        help_menu.addAction(disclaimer_action)
        self.check_updates_action = QAction(strings.ACTION_CHECK_UPDATES, self)
        self.check_updates_action.triggered.connect(self.check_for_updates)
        self.check_updates_action.setEnabled(self._update_service is not None)
        help_menu.addAction(self.check_updates_action)
        self.check_on_startup_action = QAction(strings.ACTION_CHECK_UPDATES_ON_STARTUP, self)
        self.check_on_startup_action.setCheckable(True)
        self.check_on_startup_action.setChecked(self._settings.check_updates_on_startup())
        self.check_on_startup_action.setEnabled(self._update_service is not None)
        self.check_on_startup_action.toggled.connect(self._settings.set_check_updates_on_startup)
        help_menu.addAction(self.check_on_startup_action)
        about_action = QAction(strings.ACTION_ABOUT, self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # Market data -----------------------------------------------------------
    def _wire_market(self) -> None:
        enabled = self.market is not None
        self.search_box.setEnabled(enabled)
        self.import_csv_action.setEnabled(enabled)
        self.compare_action.setEnabled(enabled)
        if self.market is None:
            self.search_box.setToolTip(strings.COMING_SOON)
            return
        service = self.market.service
        self.provider_label.setText(strings.STATUS_PROVIDER.format(name=service.provider_name))
        for interval in service.available_intervals():
            label = strings.INTERVAL_LABELS.get(interval.value, interval.value)
            self.timeframe_combo.addItem(label, interval.value)
        self.timeframe_combo.setCurrentIndex(
            max(self.timeframe_combo.findData(Interval.D1.value), 0)
        )
        self.timeframe_combo.setEnabled(self.timeframe_combo.count() > 0)
        self.timeframe_combo.currentIndexChanged.connect(self._on_interval_changed)

        self.search_box.query_changed.connect(self._on_query_changed)
        self.search_box.recent_requested.connect(self._show_recent)
        self.search_box.symbol_chosen.connect(self.open_symbol)
        self.market.search_finished.connect(self._on_search_finished)
        self.market.search_failed.connect(lambda _q, msg: self.search_box.show_message(msg))
        self.market.load_started.connect(self._on_load_started)
        self.market.load_finished.connect(self._on_load_finished)
        self.market.load_failed.connect(self._on_load_failed)
        self.market.details_finished.connect(self.details_panel.show_details)
        self.market.details_failed.connect(
            lambda _s, msg: self.details_panel.source_label.setText(msg)
        )

    def _wire_chart_type(self) -> None:
        index = self.chart_type_combo.findData(self._settings.chart_type())
        self.chart_type_combo.setCurrentIndex(max(index, 0))
        self.chart.set_chart_type(self.chart_type_combo.currentData())
        self.chart_type_combo.currentIndexChanged.connect(self._on_chart_type_changed)

    def _on_chart_type_changed(self, _index: int) -> None:
        chart_type = str(self.chart_type_combo.currentData())
        self.chart.set_chart_type(chart_type)
        self._settings.set_chart_type(chart_type)

    def _notify_alerts(self, events: list[AlertEvent]) -> None:
        """Tell the user about new alerts: status bar, taskbar flash and a desktop toast."""
        lines = [AlertsPanel.format_event(e) for e in events]
        self.statusBar().showMessage(lines[0] + (f" (+{len(lines) - 1})" if len(lines) > 1 else ""))
        if self.isVisible():
            # Taskbar flash; only for a window that exists on screen (a never-shown
            # window has no native window to flash — see PROBLEMS.md P-015).
            QApplication.alert(self)
        if QSystemTrayIcon.isSystemTrayAvailable():
            if self._tray is None:
                icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
                self._tray = QSystemTrayIcon(icon, self)
                self._tray.setToolTip(strings.APP_TITLE)
                self._tray.messageClicked.connect(self._show_alerts_tab)
                self._tray.show()
            for event in events[:5]:
                self._tray.showMessage(
                    strings.ALERT_NOTIFY_TITLE.format(description=event.description),
                    event.message,
                    QSystemTrayIcon.MessageIcon.Information,
                    10_000,
                )

    def _show_alerts_tab(self) -> None:
        if self.alerts_panel is not None:
            self.right_tabs.setCurrentWidget(self.alerts_panel)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def start_alert_schedule(self) -> None:
        if self.alerts_panel is not None:
            self.alerts_panel.start_schedule()

    def _draw_projection(self, outcome: object) -> None:
        if not isinstance(outcome, ProjectionOutcome):
            self.chart.set_overlay("projection", [])
            return
        bars = outcome.series.bars
        tokens = tokens_for(self._settings.theme())
        items = projection_overlay(
            outcome.projection,
            chart_times(bars.index)[-max(len(outcome.projection.fitted.get("p50", [])), 1) :],
            future_times(bars, outcome.projection.horizon),
            tokens.text_muted,
            tokens.accent,
        )
        self.chart.set_overlay("projection", items)

    def _draw_elliott(self, view: object) -> None:
        if not isinstance(view, ElliottView):
            self.chart.set_overlay("elliott", [])
            return
        tokens = tokens_for(self._settings.theme())
        dates = chart_times(view.series.bars.index)
        colors = {"up": tokens.up, "down": tokens.down, "correction": tokens.text_muted,
                  "current": tokens.accent, "invalid": tokens.down}  # fmt: skip
        items = elliott_overlay(view.counts, dates, view.selected, colors)
        self.chart.set_overlay("elliott", items)

    def create_level_alerts(self, levels: list[tuple[str, float]]) -> None:
        """Price alerts for levels picked in the Elliott or Patrones tab."""
        if self._alert_service is None or self.alerts_panel is None:
            self.statusBar().showMessage(strings.LEVEL_ALERTS_UNAVAILABLE, 8000)
            return
        if self.current_result is None:
            return
        series = self.current_result.series
        close = float(series.bars["close"].iloc[-1])
        try:
            created = self._alert_service.create_level_alerts(series.symbol, close, levels)
        except AppError as exc:
            QMessageBox.warning(self, strings.APP_TITLE, exc.user_message)
            return
        self.alerts_panel.reload()
        self.statusBar().showMessage(
            strings.LEVEL_ALERTS_CREATED.format(count=len(created), symbol=series.symbol), 8000
        )

    def _draw_patterns(self, view: object) -> None:
        if not isinstance(view, PatternsView):
            self.chart.set_overlay("levels", [])
            self.chart.set_overlay("patterns", [])
            return
        tokens = tokens_for(self._settings.theme())
        dates = chart_times(view.series.bars.index)
        self.chart.set_overlay("levels", levels_overlay(view.levels, view.close, tokens.up,
                                                        tokens.down))  # fmt: skip
        colors = {"up": tokens.up, "down": tokens.down, "neutral": tokens.text_muted,
                  "target": tokens.accent, "invalid": tokens.down}  # fmt: skip
        items = patterns_overlay(view.patterns, dates, view.selected, colors)
        self.chart.set_overlay("patterns", items)

    # Drawings ----------------------------------------------------------------
    def _drawing_symbol(self) -> str | None:
        if self._drawings is None or self.current_result is None:
            return None
        return self.current_result.series.symbol

    def _intraday_chart(self) -> bool:
        return self.current_result is not None and self.current_result.series.interval.is_intraday

    def _refresh_drawings(self) -> None:
        # Drawings are anchored to session dates: shown on daily/weekly/monthly charts only.
        intraday = self._intraday_chart()
        self.draw_button.setEnabled(not intraday)
        self.draw_button.setToolTip(strings.DRAW_INTRADAY if intraday else "")
        if intraday:
            self.chart.set_draw_mode(None)
            self.chart.set_drawings([])
            return
        symbol = self._drawing_symbol()
        if symbol is not None and self._drawings is not None:
            self.chart.set_drawings(self._drawings.drawings(symbol))

    def start_drawing(self, mode: str) -> None:
        if self._drawing_symbol() is None:
            self.statusBar().showMessage(strings.DRAW_NEED_SYMBOL)
            return
        if self._intraday_chart():
            self.statusBar().showMessage(strings.DRAW_INTRADAY)
            return
        self.chart.set_draw_mode(mode)
        self.statusBar().showMessage(strings.DRAW_HINTS[mode][0])

    def _on_drawing_created(self, kind: str, points: list[Any], text: str | None = None) -> None:
        symbol = self._drawing_symbol()
        if symbol is None or self._drawings is None:
            return
        if kind == "note" and text is None:
            text, ok = QInputDialog.getText(self, strings.DRAW_NOTE, strings.DRAW_NOTE_PROMPT)
            if not ok:
                return
        try:
            self._drawings.add(symbol, kind, points, text or "")
        except UserError as exc:
            self.statusBar().showMessage(exc.user_message)
            return
        self.statusBar().showMessage(strings.STATUS_READY)
        self._refresh_drawings()

    def undo_drawing(self) -> None:
        symbol = self._drawing_symbol()
        if symbol is not None and self._drawings is not None:
            self._drawings.delete_last(symbol)
            self._refresh_drawings()

    def clear_drawings(self) -> None:
        symbol = self._drawing_symbol()
        if symbol is not None and self._drawings is not None:
            self._drawings.clear(symbol)
            self._refresh_drawings()

    # Export --------------------------------------------------------------------
    def _export_target(self, suffix: str, file_filter: str, path: Path | None) -> Path | None:
        series = self.chart.current_series
        if series is None:
            QMessageBox.information(self, strings.APP_TITLE, strings.EXPORT_NOTHING)
            return None
        if path is not None:
            return path
        stem = series.symbol.replace(":", "_")
        default = f"{stem}_{series.interval.value}_{series.last_date:%Y%m%d}.{suffix}"
        chosen, _ = QFileDialog.getSaveFileName(self, strings.APP_TITLE, default, file_filter)
        return Path(chosen) if chosen else None

    def _report_saved(self, ok: bool, path: Path, error: str = "") -> None:
        if ok:
            self.statusBar().showMessage(strings.EXPORT_DONE.format(path=path))
        else:
            QMessageBox.warning(self, strings.APP_TITLE, strings.EXPORT_FAILED.format(error=error))

    def export_image(self, path: Path | None = None) -> None:
        target = self._export_target("png", strings.EXPORT_IMAGE_FILTER, path)
        if target is None:
            return
        ok = self.chart.view.grab().save(str(target), "PNG")
        self._report_saved(ok, target, "PNG")

    def export_csv(self, path: Path | None = None) -> None:
        target = self._export_target("csv", strings.EXPORT_CSV_FILTER, path)
        series = self.chart.current_series
        if target is None or series is None:
            return
        try:
            target.write_text(bars_to_csv(series, self.chart.indicators), encoding="utf-8")
        except (OSError, ValueError) as exc:
            logger.exception("CSV export failed")
            self._report_saved(False, target, str(exc))
            return
        self._report_saved(True, target)

    def export_pdf(self, path: Path | None = None) -> None:
        target = self._export_target("pdf", strings.EXPORT_PDF_FILTER, path)
        series = self.chart.current_series
        if target is None or series is None:
            return
        locale = QLocale()
        interval = strings.INTERVAL_LABELS.get(series.interval.value, series.interval.value)
        html = build_report_html(
            f"{series.symbol} · {interval}",
            self.chart.view.grab(),
            self.details_panel.details,
            self.analysis_panel.report,
            [c.label for c in self.chart.indicators if c.visible],
            lambda v: locale.toString(float(v), "f", 2),
        )
        try:
            write_pdf(target, html)
        except OSError as exc:
            self._report_saved(False, target, str(exc))
            return
        self._report_saved(target.exists(), target, "PDF")

    def _candidate_symbols(self) -> list[str]:
        """The symbol on the chart followed by the active watchlist."""
        symbols: list[str] = []
        if self.current_result is not None and not self.current_result.series.symbol.startswith(
            "CSV:"
        ):
            symbols.append(self.current_result.series.symbol)
        if isinstance(self.watchlist_panel, WatchlistPanel):
            symbols += [s for s in self.watchlist_panel.symbols() if s not in symbols]
        return symbols

    def open_scanner(self) -> None:
        if self.market is None:
            return
        symbols = self._candidate_symbols()
        dialog = ScannerDialog(self.market.service, symbols, self)
        dialog.symbol_activated.connect(self.open_symbol)
        dialog.show()
        self._scanner_dialog = dialog
        if symbols:
            dialog.run()

    # Daily scan ----------------------------------------------------------------
    def _watchlist_symbols(self) -> list[str]:
        if isinstance(self.watchlist_panel, WatchlistPanel):
            return [s for s in self.watchlist_panel.symbols() if not s.startswith("CSV:")]
        return []

    def start_daily_scan(self, first_delay_ms: int | None = None) -> None:
        if self.daily_scan is None:
            return
        if first_delay_ms is None:
            self.daily_scan.start()
        else:
            self.daily_scan.start(first_delay_ms)

    def _on_daily_scan_toggled(self, enabled: bool) -> None:
        self._settings.set_daily_scan_enabled(enabled)
        if enabled and self.daily_scan is not None:
            self.daily_scan.maybe_run()

    def _on_daily_scan_finished(self, result: ScanResult, novelties: list[Novelty]) -> None:
        self.last_daily_scan_action.setEnabled(True)
        if not result.rows:
            self.statusBar().showMessage(strings.DAILY_SCAN_FAILED, 15000)
            return
        if not novelties:
            self.statusBar().showMessage(strings.DAILY_SCAN_NONE.format(count=len(result.rows)),
                                         15000)  # fmt: skip
            return
        symbols = len({n.symbol for n in novelties})
        summary = strings.DAILY_SCAN_DONE.format(count=len(novelties), symbols=symbols)
        events: list[AlertEvent] = []
        if self._alert_service is not None:
            for novelty in novelties:
                icon = "▲" if novelty.bias > 0 else "▼" if novelty.bias < 0 else "●"
                try:
                    events.append(self._alert_service.record_event(
                        novelty.symbol, strings.DAILY_SCAN_EVENT.format(symbol=novelty.symbol),
                        f"{icon} {novelty.text}", novelty.bar_date or date.today(),
                    ))  # fmt: skip
                except AppError as exc:
                    logger.warning("Could not record daily scan event: %s", exc)
            if self.alerts_panel is not None:
                self.alerts_panel.reload()
        if events:
            self._notify_alerts(events)
        self.statusBar().showMessage(summary, 30000)

    def open_last_daily_scan(self) -> None:
        if self.market is None or self.daily_scan is None or self.daily_scan.last_result is None:
            return
        result = self.daily_scan.last_result
        dialog = ScannerDialog(self.market.service, [r.symbol for r in result.rows], self)
        dialog.symbol_activated.connect(self.open_symbol)
        dialog.show_result(result)
        dialog.show()
        self._scanner_dialog = dialog

    def open_pattern_backtest(self) -> None:
        if self.market is None:
            return
        dialog = PatternBacktestDialog(self.market.service, self._candidate_symbols(), self)
        dialog.symbol_activated.connect(self.open_symbol)
        dialog.show()
        self._pattern_backtest_dialog = dialog

    def open_comparison(self) -> None:
        if self.market is None:
            return
        symbols = self._candidate_symbols()
        dialog = ComparisonDialog(self.market.service, tokens_for(self._settings.theme()),
                                  symbols, self)  # fmt: skip
        dialog.show()
        self._comparison_dialog = dialog

    def open_backtest(self) -> None:
        series = self.chart.current_series
        if series is None:
            QMessageBox.information(self, strings.ACTION_BACKTEST.replace("&", ""),
                                    strings.BT_NEED_DATA)  # fmt: skip
            return
        interval = strings.INTERVAL_LABELS.get(series.interval.value, series.interval.value)
        dialog = BacktestDialog(series, f"{series.symbol} · {interval}",
                                tokens_for(self._settings.theme()), self)  # fmt: skip
        dialog.show()
        self._backtest_dialog = dialog

    def edit_indicators(self) -> None:
        dialog = IndicatorDialog(self.chart.indicators, self)
        if dialog.exec() == IndicatorDialog.DialogCode.Accepted:
            self.apply_indicators(dialog.configs())

    def apply_indicators(self, configs: list[IndicatorConfig]) -> None:
        self.chart.set_indicators(configs)
        self._settings.set_indicators(configs)

    def current_interval(self) -> Interval:
        value = self.timeframe_combo.currentData()
        return Interval(value) if value else Interval.D1

    def open_symbol(self, symbol: str, name: str = "") -> None:
        if self.market is None:
            return
        self.current_symbol = symbol
        self.market.remember(symbol, name or None)
        self.market.load(symbol, self.current_interval())

    def restore_last_symbol(self) -> None:
        """Reopen the symbol and interval from the previous session."""
        interval = self._settings.last_interval()
        index = self.timeframe_combo.findData(interval) if interval else -1
        if index >= 0:
            self.timeframe_combo.blockSignals(True)
            self.timeframe_combo.setCurrentIndex(index)
            self.timeframe_combo.blockSignals(False)
        symbol = self._settings.last_symbol()
        if symbol:
            self.open_symbol(symbol)

    def _on_query_changed(self, query: str) -> None:
        if self.market is None or not query:
            return
        self.search_box.show_message(strings.SEARCH_SEARCHING)
        self.market.search(query)

    def _show_recent(self) -> None:
        if self.market is None:
            return
        try:
            recent = self.market.service.recent()
        except Exception:
            # Recent symbols are a convenience; never let them break typing.
            logger.exception("Could not read recent symbols")
            return
        if recent:
            self.search_box.show_results(recent, strings.SEARCH_RECENT)
        else:
            self.search_box.hide_popup()

    def _on_search_finished(self, query: str, results: list[Any]) -> None:
        if self.search_box.text().strip() == query:
            self.search_box.show_results(results)

    def _on_interval_changed(self, _index: int) -> None:
        if self.current_symbol and self.market is not None:
            self.market.load(self.current_symbol, self.current_interval())

    def _on_load_started(self, symbol: str, _interval: object) -> None:
        self.statusBar().showMessage(strings.LOADING.format(symbol=symbol))
        self.setCursor(Qt.CursorShape.BusyCursor)

    def _on_load_finished(self, result: LoadResult) -> None:
        self.unsetCursor()
        previous = self.current_result.series.symbol if self.current_result else None
        self.current_result = result
        series = result.series
        if series.symbol != previous and self.market is not None:
            self.details_panel.show_loading(series.symbol)
            self.market.load_details(series.symbol)
        self.current_symbol = series.symbol
        self._set_label(self.symbol_label, series.symbol)
        self._set_label(self.provider_label, strings.STATUS_PROVIDER.format(name=series.source))
        self._settings.set_last_opened(series.symbol, series.interval.value)

        interval_label = strings.INTERVAL_LABELS.get(series.interval.value, series.interval.value)
        self.chart.show_series(series, f"{series.symbol} · {interval_label}")
        self._refresh_drawings()
        self.projection_panel.set_series(series)
        self.elliott_panel.set_series(series)
        self.patterns_panel.set_series(series)
        self.analysis_panel.analyze(
            series, f"{series.symbol} · {interval_label}", result.session_in_progress
        )

        when = strings.STATUS_NEVER
        if result.fetched_at is not None:
            local = result.fetched_at.astimezone()
            when = local.strftime("%d/%m/%Y %H:%M")
            if result.from_cache:
                when += f" ({strings.FROM_CACHE})"
        self._set_label(self.last_update_label, strings.STATUS_LAST_UPDATE.format(when=when))

        notes = list(result.notices)
        if result.stale:
            notes.insert(0, strings.STALE_DATA)
        if result.session_in_progress:
            notes.append(strings.SESSION_IN_PROGRESS)
        self.statusBar().showMessage(" ".join(notes) if notes else strings.STATUS_READY)

    def _on_load_failed(self, symbol: str, message: str) -> None:
        self.unsetCursor()
        title = strings.LOAD_ERROR.format(symbol=symbol)
        self.statusBar().showMessage(f"{title}: {message}")
        if self.current_result is None:
            self.chart.show_message(f"{title}.\n\n{message}", error=True)
        else:
            # Keep showing the data already on screen; it is still consistent with
            # the symbol label. The status bar explains why the new request failed.
            self.current_symbol = self.current_result.series.symbol

    @staticmethod
    def _set_label(label: QLabel, text: str) -> None:
        """Set text and let toolbar/status-bar layouts grow the label to fit it."""
        label.setText(text)
        label.setMinimumWidth(label.sizeHint().width())

    def _import_csv(self) -> None:
        if self.market is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, strings.IMPORT_CSV_TITLE, "", strings.IMPORT_CSV_FILTER
        )
        if not path:
            return
        default = "".join(ch for ch in Path(path).stem.upper() if ch.isalnum() or ch in "-_.")
        name, ok = QInputDialog.getText(
            self, strings.IMPORT_CSV_TITLE, strings.IMPORT_CSV_NAME_PROMPT, text=default[:30]
        )
        if ok and name.strip():
            self.market.import_csv(Path(path), name)

    # Theme -----------------------------------------------------------------
    def _on_dark_theme_toggled(self, checked: bool) -> None:
        theme = Theme.DARK if checked else Theme.LIGHT
        self._settings.set_theme(theme)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        self.chart.set_theme(tokens_for(theme))
        if isinstance(self.watchlist_panel, WatchlistPanel):
            self.watchlist_panel.set_theme(tokens_for(theme))
        self.analysis_panel.set_theme(tokens_for(theme))
        logger.info("Theme changed to %s", theme.value)

    # Layout persistence ----------------------------------------------------
    def capture_layout(self) -> dict[str, Any]:
        return {
            "geometry": self._encode(self.saveGeometry()),
            "state": self._encode(self.saveState()),
            "main_split": self._encode(self.main_splitter.saveState()),
        }

    def _restore_layout(self) -> None:
        """Restore saved state; any missing or invalid part falls back to defaults.

        Qt's own saveState()/restoreState() formats are used for splitters
        because sizes set before the first layout pass are redistributed.
        """
        layout = self._settings.layout()
        self._apply_default_sizes()
        if not self._restore_part(layout.get("geometry"), self.restoreGeometry):
            self.resize(*DEFAULT_SIZE)
        self._restore_part(layout.get("state"), self.restoreState)
        if not self._restore_part(layout.get("main_split"), self.main_splitter.restoreState):
            self.main_splitter.setSizes(DEFAULT_MAIN_SPLIT)

    def _restore_part(self, value: object, restore: Callable[[QByteArray], bool]) -> bool:
        if not isinstance(value, str):
            if value is not None:
                logger.warning("Ignoring invalid stored layout value of type %s", type(value))
            return False
        try:
            ok = restore(self._decode(value))
        except (ValueError, UnicodeEncodeError):
            ok = False
        if not ok:
            logger.warning("Stored layout value could not be restored; using default")
        return bool(ok)

    def _apply_default_sizes(self) -> None:
        self.main_splitter.setSizes(DEFAULT_MAIN_SPLIT)

    def reset_layout(self) -> None:
        self._settings.reset_layout()
        self._apply_default_sizes()
        self.resize(*DEFAULT_SIZE)

    @staticmethod
    def _encode(data: QByteArray) -> str:
        return bytes(data.toBase64().data()).decode("ascii")

    @staticmethod
    def _decode(text: str) -> QByteArray:
        return QByteArray.fromBase64(text.encode("ascii"))

    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            self._settings.set_layout(self.capture_layout())
        except Exception:
            # Failing to save the layout must not prevent closing.
            logger.exception("Could not save window layout")
        super().closeEvent(event)

    # Dialogs ---------------------------------------------------------------
    def _show_disclaimer(self) -> None:
        DisclaimerDialog(self, require_acceptance=False).exec()

    def schedule_startup_update_check(self, delay_ms: int = STARTUP_UPDATE_CHECK_DELAY_MS) -> None:
        """Quietly check for updates shortly after startup, if enabled."""
        if self._update_service is None or not self._settings.check_updates_on_startup():
            return
        QTimer.singleShot(delay_ms, self._start_background_update_check)

    def _start_background_update_check(self) -> None:
        if self._update_service is None:
            return
        self._update_worker = start_worker(
            self._update_service.check,
            self._on_background_update_checked,
            self._on_background_update_failed,
        )

    def _on_background_update_checked(self, result: object) -> None:
        if isinstance(result, UpdateCheck) and result.available:
            self.update_notice.setToolTip(strings.UPDATE_NOTICE_TOOLTIP.format(count=result.behind))
            self.update_notice.show()

    def _on_background_update_failed(self, exc: BaseException) -> None:
        # A background check must not interrupt the user (e.g. offline, ZIP install).
        # The failure is already logged by the worker; the manual check shows the reason.
        logger.info("Startup update check skipped: %s", exc)

    def check_for_updates(self) -> None:
        if self._update_service is None:
            return
        self.update_notice.hide()
        dialog = UpdateDialog(self._update_service, self)
        dialog.start()
        dialog.exec()
        if dialog.restart_requested:
            self.restart_requested = True
            self.close()

    def _show_about(self) -> None:
        QMessageBox.about(
            self, strings.ACTION_ABOUT, strings.ABOUT_TEXT.format(version=__version__)
        )
