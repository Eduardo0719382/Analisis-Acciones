"""Main application window: toolbar, three resizable regions and status bar."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QWidget,
)

from analisis_acciones import __version__
from analisis_acciones.services.settings_service import SettingsService, Theme
from analisis_acciones.services.update_service import UpdateService
from analisis_acciones.ui import strings
from analisis_acciones.ui.disclaimer import DisclaimerDialog
from analisis_acciones.ui.panels import Panel
from analisis_acciones.ui.theme import apply_theme
from analisis_acciones.ui.update_dialog import UpdateDialog

logger = logging.getLogger(__name__)

DEFAULT_SIZE = (1400, 860)
DEFAULT_MAIN_SPLIT = [240, 900, 280]
DEFAULT_CENTER_SPLIT = [620, 200]


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: SettingsService,
        parent: QWidget | None = None,
        *,
        update_service: UpdateService | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._update_service = update_service
        self.restart_requested = False
        self.setWindowTitle(strings.APP_TITLE)
        self.setMinimumSize(800, 500)

        self._build_toolbar()
        self._build_regions()
        self._build_status_bar()
        self._build_menus()
        self._restore_layout()

    # Construction ----------------------------------------------------------
    def _build_toolbar(self) -> None:
        bar = QToolBar("main", self)
        bar.setObjectName("mainToolbar")
        bar.setMovable(False)
        bar.setFloatable(False)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText(strings.SEARCH_PLACEHOLDER)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumWidth(220)
        self.search_box.setMaximumWidth(340)
        self.search_box.setEnabled(False)
        self.search_box.setToolTip(strings.COMING_SOON)
        bar.addWidget(self.search_box)

        self.symbol_label = QLabel(strings.NO_SYMBOL)
        self.symbol_label.setObjectName("symbolLabel")
        bar.addWidget(self.symbol_label)

        # Populated from the active provider's supported intervals (phase 2/3).
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.setObjectName("timeframeCombo")
        self.timeframe_combo.setToolTip(strings.TIMEFRAME_TOOLTIP)
        self.timeframe_combo.setEnabled(False)
        self.timeframe_combo.setMinimumWidth(70)
        bar.addWidget(self.timeframe_combo)

        self.indicators_button = QPushButton(strings.INDICATORS_BUTTON)
        self.indicators_button.setObjectName("indicatorsButton")
        self.indicators_button.setEnabled(False)
        self.indicators_button.setToolTip(strings.COMING_SOON)
        bar.addWidget(self.indicators_button)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self.toolbar = bar

    def _build_regions(self) -> None:
        self.watchlist_panel = Panel(strings.PANEL_WATCHLIST, strings.EMPTY_WATCHLIST)
        self.chart_panel = Panel(strings.PANEL_CHART, strings.EMPTY_CHART)
        self.lower_panel = Panel(strings.PANEL_LOWER, strings.EMPTY_LOWER)
        self.details_panel = Panel(strings.PANEL_DETAILS, strings.EMPTY_DETAILS)

        self.center_splitter = QSplitter(Qt.Orientation.Vertical)
        self.center_splitter.setObjectName("centerSplitter")
        self.center_splitter.addWidget(self.chart_panel)
        self.center_splitter.addWidget(self.lower_panel)
        self.center_splitter.setChildrenCollapsible(False)
        self.center_splitter.setStretchFactor(0, 3)
        self.center_splitter.setStretchFactor(1, 1)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.addWidget(self.watchlist_panel)
        self.main_splitter.addWidget(self.center_splitter)
        self.main_splitter.addWidget(self.details_panel)
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
        status.addPermanentWidget(self.provider_label)
        status.addPermanentWidget(self.last_update_label)
        status.showMessage(strings.STATUS_READY)

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu(strings.MENU_FILE)
        quit_action = QAction(strings.ACTION_QUIT, self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

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
        about_action = QAction(strings.ACTION_ABOUT, self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # Theme -----------------------------------------------------------------
    def _on_dark_theme_toggled(self, checked: bool) -> None:
        theme = Theme.DARK if checked else Theme.LIGHT
        self._settings.set_theme(theme)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        logger.info("Theme changed to %s", theme.value)

    # Layout persistence ----------------------------------------------------
    def capture_layout(self) -> dict[str, Any]:
        return {
            "geometry": self._encode(self.saveGeometry()),
            "state": self._encode(self.saveState()),
            "main_split": self._encode(self.main_splitter.saveState()),
            "center_split": self._encode(self.center_splitter.saveState()),
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
        if not self._restore_part(layout.get("center_split"), self.center_splitter.restoreState):
            self.center_splitter.setSizes(DEFAULT_CENTER_SPLIT)

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
        self.center_splitter.setSizes(DEFAULT_CENTER_SPLIT)

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

    def check_for_updates(self) -> None:
        if self._update_service is None:
            return
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
