"""Ticker/company search field with a suggestion list.

The line edit keeps keyboard focus while the suggestion list is shown, so the
user can keep typing; Up/Down/Enter/Escape are forwarded to the list. Typing
is debounced before ``query_changed`` is emitted.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QWidget

from analisis_acciones.models.market import SearchResult
from analisis_acciones.ui import strings

DEBOUNCE_MS = 300
MIN_QUERY_LENGTH = 1

_SYMBOL_ROLE = Qt.ItemDataRole.UserRole
_NAME_ROLE = Qt.ItemDataRole.UserRole + 1


class SearchBox(QLineEdit):
    #: Debounced, stripped query text (empty when the field was cleared).
    query_changed = Signal(str)
    #: The user picked a symbol: (symbol, name or "").
    symbol_chosen = Signal(str, str)
    #: The field gained focus while empty: show recent symbols.
    recent_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchBox")
        self.setPlaceholderText(strings.SEARCH_PLACEHOLDER)
        self.setClearButtonEnabled(True)

        # Parented so it is destroyed with the field; the flags make it a floating list.
        self.popup = QListWidget(self)
        self.popup.setObjectName("searchPopup")
        self.popup.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.popup.setUniformItemSizes(True)
        self.popup.itemClicked.connect(self._choose_item)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_query)
        self.textEdited.connect(self._on_text_edited)
        self.returnPressed.connect(self._on_return)

    # Results ---------------------------------------------------------------
    def show_results(self, results: list[SearchResult], heading: str | None = None) -> None:
        self.popup.clear()
        if heading:
            header = QListWidgetItem(heading)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.popup.addItem(header)
        for result in results:
            detail = " · ".join(
                p for p in (result.name, result.exchange) if p and p != result.symbol
            )
            if result.asset_type == "CRYPTOCURRENCY":
                detail = f"{detail} · {strings.SEARCH_CRYPTO}" if detail else strings.SEARCH_CRYPTO
            item = QListWidgetItem(f"{result.symbol}    {detail}" if detail else result.symbol)
            item.setData(_SYMBOL_ROLE, result.symbol)
            item.setData(_NAME_ROLE, result.name)
            self.popup.addItem(item)
        if not results:
            empty = QListWidgetItem(strings.SEARCH_NO_RESULTS)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.popup.addItem(empty)
        self._show_popup()

    def show_message(self, message: str) -> None:
        self.popup.clear()
        item = QListWidgetItem(message)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.popup.addItem(item)
        self._show_popup()

    def hide_popup(self) -> None:
        self.popup.hide()

    def _show_popup(self) -> None:
        if not self.hasFocus() and not self.isVisible():
            return
        rows = max(1, min(self.popup.count(), 10))
        height = rows * max(self.popup.sizeHintForRow(0), 18) + 4
        self.popup.setFixedSize(max(self.width(), 360), height)
        self.popup.move(self.mapToGlobal(QPoint(0, self.height())))
        self.popup.show()
        self.popup.raise_()

    # Input -----------------------------------------------------------------
    def _on_text_edited(self, text: str) -> None:
        if not text.strip():
            self._debounce.stop()
            self.query_changed.emit("")
            self.recent_requested.emit()
            return
        self._debounce.start()

    def _emit_query(self) -> None:
        query = self.text().strip()
        if len(query) >= MIN_QUERY_LENGTH:
            self.query_changed.emit(query)

    def _selectable_rows(self) -> list[int]:
        return [
            row
            for row in range(self.popup.count())
            if self.popup.item(row).flags() & Qt.ItemFlag.ItemIsSelectable
        ]

    def _move_selection(self, step: int) -> None:
        rows = self._selectable_rows()
        if not rows or not self.popup.isVisible():
            return
        current = self.popup.currentRow()
        if current not in rows:
            target = rows[0] if step > 0 else rows[-1]
        else:
            position = rows.index(current) + step
            target = rows[max(0, min(position, len(rows) - 1))]
        self.popup.setCurrentRow(target)

    def _on_return(self) -> None:
        item = self.popup.currentItem() if self.popup.isVisible() else None
        if item is not None and item.data(_SYMBOL_ROLE):
            self._choose_item(item)
            return
        text = self.text().strip()
        if text:
            self._choose(text.upper(), "")

    def _choose_item(self, item: QListWidgetItem) -> None:
        symbol = item.data(_SYMBOL_ROLE)
        if symbol:
            self._choose(str(symbol), str(item.data(_NAME_ROLE) or ""))

    def _choose(self, symbol: str, name: str) -> None:
        self._debounce.stop()
        self.hide_popup()
        self.clear()
        self.symbol_chosen.emit(symbol, name)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Down:
            self._move_selection(+1)
        elif key == Qt.Key.Key_Up:
            self._move_selection(-1)
        elif key == Qt.Key.Key_Escape and self.popup.isVisible():
            self.hide_popup()
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        if not self.text().strip():
            self.recent_requested.emit()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        # Delay so a click on a suggestion is processed before the list hides.
        QTimer.singleShot(150, self._hide_if_unfocused)

    def _hide_if_unfocused(self) -> None:
        if not self.hasFocus():
            self.hide_popup()
