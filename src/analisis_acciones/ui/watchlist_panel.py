"""Left panel: selectable watchlists with last close and daily change."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.models.errors import UserError
from analisis_acciones.services.market_data_service import WatchRow
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.services.watchlist_service import (
    ALTCOIN_EXAMPLE,
    ALTCOIN_LIST_NAME,
    CRYPTO_EXAMPLE,
    CRYPTO_LIST_NAME,
    WatchlistService,
)
from analisis_acciones.ui import strings
from analisis_acciones.ui.market_controller import MarketController
from analisis_acciones.ui.theme import ThemeTokens, tokens_for

logger = logging.getLogger(__name__)

COL_SYMBOL, COL_LAST, COL_CHANGE = range(3)


class WatchlistPanel(QFrame):
    #: The user picked a symbol to open.
    symbol_activated = Signal(str)
    #: The example cryptocurrency list was created (its symbols).
    example_created = Signal(list)

    def __init__(
        self,
        lists: WatchlistService,
        market: MarketController | None,
        settings: SettingsService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self._lists = lists
        self._market = market
        self._settings = settings
        self._tokens = tokens_for(settings.theme())
        #: Returns the symbol currently shown on the chart (for the "+" button).
        self.current_symbol_provider: Callable[[], str | None] | None = None

        header = QLabel(strings.PANEL_WATCHLIST)
        header.setObjectName("panelHeader")

        self.list_combo = QComboBox()
        self.list_combo.setObjectName("watchlistCombo")
        self.list_combo.currentIndexChanged.connect(self._on_list_changed)
        self.menu_button = QToolButton()
        self.menu_button.setText("⋯")
        self.menu_button.setToolTip(strings.WATCHLIST_MENU)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.menu_button)
        self.new_action = menu.addAction(strings.WATCHLIST_NEW, self.create_list)
        self.rename_action = menu.addAction(strings.WATCHLIST_RENAME, self.rename_list)
        self.delete_action = menu.addAction(strings.WATCHLIST_DELETE, self.delete_list)
        menu.addSeparator()
        self.crypto_action = menu.addAction(strings.WATCHLIST_CRYPTO_EXAMPLE,
                                            self.create_crypto_example)  # fmt: skip
        self.altcoin_action = menu.addAction(strings.WATCHLIST_ALTCOIN_EXAMPLE,
                                             self.create_altcoin_example)  # fmt: skip
        self.menu_button.setMenu(menu)
        top = QHBoxLayout()
        top.setContentsMargins(6, 6, 6, 0)
        top.addWidget(self.list_combo, stretch=1)
        top.addWidget(self.menu_button)

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("watchlistTable")
        self.table.setHorizontalHeaderLabels(
            [strings.WATCHLIST_COL_SYMBOL, strings.WATCHLIST_COL_LAST, strings.WATCHLIST_COL_CHANGE]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(COL_SYMBOL, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(COL_LAST, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(COL_CHANGE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        remove_action = QAction(strings.WATCHLIST_REMOVE, self.table)
        remove_action.setShortcut(QKeySequence.StandardKey.Delete)
        remove_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        remove_action.triggered.connect(self.remove_selected)
        self.table.addAction(remove_action)

        self.empty_label = QLabel(strings.EMPTY_WATCHLIST)
        self.empty_label.setObjectName("panelEmpty")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def tool(text: str, tip: str, slot: Callable[[], None]) -> QToolButton:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            return button

        self.add_button = tool("+", strings.WATCHLIST_ADD_CURRENT, self.add_current)
        self.remove_button = tool("-", strings.WATCHLIST_REMOVE, self.remove_selected)
        self.up_button = tool("▲", strings.WATCHLIST_UP, lambda: self.move_selected(-1))
        self.down_button = tool("▼", strings.WATCHLIST_DOWN, lambda: self.move_selected(+1))
        self.refresh_button = tool("⟳", strings.WATCHLIST_REFRESH, self.refresh_values)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(6, 0, 6, 6)
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            bottom.addWidget(button)
        bottom.addStretch(1)
        bottom.addWidget(self.refresh_button)

        self.status_label = QLabel()
        self.status_label.setObjectName("detailsSource")
        self.status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(header)
        layout.addLayout(top)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.empty_label, stretch=1)
        layout.addWidget(self.status_label)
        layout.addLayout(bottom)

        if self._market is not None:
            self._market.snapshot_finished.connect(self._on_snapshot)
        self.reload_lists(select_id=self._settings.current_watchlist())

    # Lists -------------------------------------------------------------------
    def current_list_id(self) -> int | None:
        value = self.list_combo.currentData()
        return int(value) if value is not None else None

    def reload_lists(self, select_id: int | None = None) -> None:
        lists = self._lists.lists()
        self.list_combo.blockSignals(True)
        self.list_combo.clear()
        for watchlist in lists:
            self.list_combo.addItem(watchlist.name, watchlist.id)
        index = self.list_combo.findData(select_id) if select_id is not None else -1
        self.list_combo.setCurrentIndex(max(index, 0))
        self.list_combo.blockSignals(False)
        self.delete_action.setEnabled(len(lists) > 1)
        self._on_list_changed()

    def _on_list_changed(self, _index: int = 0) -> None:
        list_id = self.current_list_id()
        if list_id is not None:
            self._settings.set_current_watchlist(list_id)
        self.reload_items()
        self.refresh_values()

    def _ask_name(self, title: str, text: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, strings.WATCHLIST_NAME_PROMPT, text=text)
        return name if ok else None

    def create_list(self, name: str | None = None) -> None:
        name = name if name is not None else self._ask_name(strings.WATCHLIST_NEW)
        if name is None:
            return
        try:
            created = self._lists.create(name)
        except UserError as exc:
            self._show_error(exc.user_message)
            return
        self.reload_lists(select_id=created.id)

    def create_crypto_example(self) -> None:
        self._create_example(CRYPTO_LIST_NAME, CRYPTO_EXAMPLE)

    def create_altcoin_example(self) -> None:
        self._create_example(ALTCOIN_LIST_NAME, ALTCOIN_EXAMPLE)

    def _create_example(self, name: str, symbols: tuple[str, ...]) -> None:
        try:
            created = self._lists.create_example(name, symbols)
        except UserError as exc:
            self._show_error(exc.user_message)
            return
        self.reload_lists(select_id=created.id)
        self.example_created.emit(self._lists.symbols(created.id))

    def rename_list(self, name: str | None = None) -> None:
        list_id = self.current_list_id()
        if list_id is None:
            return
        if name is None:
            name = self._ask_name(strings.WATCHLIST_RENAME, self.list_combo.currentText())
            if name is None:
                return
        try:
            self._lists.rename(list_id, name)
        except UserError as exc:
            self._show_error(exc.user_message)
            return
        self.reload_lists(select_id=list_id)

    def delete_list(self, confirm: bool = True) -> None:
        list_id = self.current_list_id()
        if list_id is None:
            return
        if confirm:
            answer = QMessageBox.question(
                self,
                strings.WATCHLIST_DELETE,
                strings.WATCHLIST_DELETE_CONFIRM.format(name=self.list_combo.currentText()),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self._lists.delete(list_id)
        except UserError as exc:
            self._show_error(exc.user_message)
            return
        self.reload_lists()

    # Items -------------------------------------------------------------------
    def symbols(self) -> list[str]:
        list_id = self.current_list_id()
        return self._lists.symbols(list_id) if list_id is not None else []

    def reload_items(self, select: str | None = None) -> None:
        symbols = self.symbols()
        self.table.setRowCount(len(symbols))
        for row, symbol in enumerate(symbols):
            item = QTableWidgetItem(symbol)
            item.setData(Qt.ItemDataRole.UserRole, symbol)
            self.table.setItem(row, COL_SYMBOL, item)
            for col in (COL_LAST, COL_CHANGE):
                cell = QTableWidgetItem("…")
                cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, cell)
            if symbol == select:
                self.table.selectRow(row)
        self.table.setVisible(bool(symbols))
        self.empty_label.setVisible(not symbols)
        has_rows = bool(symbols)
        for button in (self.remove_button, self.up_button, self.down_button):
            button.setEnabled(has_rows)

    def selected_symbol(self) -> str | None:
        row = self.table.currentRow()
        item = self.table.item(row, COL_SYMBOL) if row >= 0 else None
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def add_symbol(self, symbol: str) -> None:
        list_id = self.current_list_id()
        if list_id is None:
            return
        try:
            added = self._lists.add(list_id, symbol)
        except UserError as exc:
            self._show_error(exc.user_message)
            return
        self.status_label.setText(
            "" if added else strings.WATCHLIST_ALREADY.format(symbol=symbol.upper())
        )
        self.reload_items(select=symbol.upper())
        self.refresh_values()

    def add_current(self) -> None:
        provider = self.current_symbol_provider
        symbol = provider() if provider else None
        if not symbol:
            self.status_label.setText(strings.WATCHLIST_NOTHING_OPEN)
            return
        self.add_symbol(symbol)

    def remove_selected(self) -> None:
        list_id, symbol = self.current_list_id(), self.selected_symbol()
        if list_id is None or symbol is None:
            return
        row = self.table.currentRow()
        self._lists.remove(list_id, symbol)
        self.reload_items()
        if self.table.rowCount():
            self.table.selectRow(min(row, self.table.rowCount() - 1))
        self.refresh_values()

    def move_selected(self, offset: int) -> None:
        list_id, symbol = self.current_list_id(), self.selected_symbol()
        if list_id is None or symbol is None:
            return
        self._lists.move(list_id, symbol, offset)
        self.reload_items(select=symbol)
        self.refresh_values()

    def _on_cell_clicked(self, row: int, _column: int) -> None:
        item = self.table.item(row, COL_SYMBOL)
        if item is not None:
            self.symbol_activated.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    # Values ------------------------------------------------------------------
    def refresh_values(self) -> None:
        symbols = self.symbols()
        if self._market is not None and symbols:
            self._market.snapshot(symbols)

    def _on_snapshot(self, rows: list[WatchRow]) -> None:
        locale = QLocale()
        tokens = self._tokens
        by_symbol = {r.symbol: r for r in rows}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_SYMBOL)
            data = by_symbol.get(str(item.data(Qt.ItemDataRole.UserRole))) if item else None
            if data is None:
                continue
            last = self.table.item(row, COL_LAST)
            change = self.table.item(row, COL_CHANGE)
            if last is None or change is None:
                continue
            if data.error is not None or data.last_close is None:
                last.setText("—")
                change.setText("—")
                last.setToolTip(data.error or "")
                continue
            last.setText(locale.toString(data.last_close, "f", 2))
            if data.change_pct is None:
                change.setText("—")
            else:
                sign = "+" if data.change_pct > 0 else ""
                change.setText(f"{sign}{locale.toString(data.change_pct, 'f', 2)} %")
                colour = "up" if data.change_pct > 0 else "down" if data.change_pct < 0 else ""
                change.setData(Qt.ItemDataRole.UserRole, colour)
                change.setForeground(self._colour(tokens, colour))
            when = data.as_of.strftime("%d/%m/%Y") if data.as_of else ""
            tip = strings.WATCHLIST_ROW_TIP.format(date=when)
            if data.stale:
                tip += "\n" + strings.STALE_DATA
            last.setToolTip(tip)
            change.setToolTip(tip)

    def set_theme(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self.refresh_values()

    @staticmethod
    def _colour(tokens: ThemeTokens, direction: str) -> QColor:
        return QColor(tokens.up if direction == "up" else tokens.down if direction else tokens.text)

    def _show_error(self, message: str) -> None:
        self.status_label.setText(message)
