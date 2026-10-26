"""Simulated orders on Alpaca's paper-trading account: keys, account, positions and orders."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.broker.alpaca import (
    SIGNUP_URL,
    AlpacaPaperClient,
    BrokerOrder,
    OrderRequest,
    validate_order,
)
from analisis_acciones.models.errors import AppError, UserError
from analisis_acciones.services.api_keys import BROKER_SERVICES, KeyStore, masked
from analisis_acciones.ui import strings
from analisis_acciones.ui.workers import start_worker

_OPEN = {"new", "accepted", "pending_new", "partially_filled", "held", "pending_cancel"}


def _table(headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill(table: QTableWidget, rows: list[list[str]]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            item = QTableWidgetItem(text)
            if c > 0:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(r, c, item)


class AlpacaDialog(QDialog):
    def __init__(self, keys: KeyStore, client: AlpacaPaperClient,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._keys = keys
        self._client = client
        self._orders: list[BrokerOrder] = []
        #: Asks the user to confirm an order; replaced in tests.
        self.confirm: Callable[[str], bool] = self._ask
        self.setWindowTitle(strings.ALP_TITLE)
        self.resize(820, 720)

        intro = QLabel(strings.ALP_INTRO)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)

        keys_box = QGroupBox(strings.ALP_KEYS)
        keys_layout = QVBoxLayout(keys_box)
        self.key_fields: dict[str, QLineEdit] = {}
        self.key_status: dict[str, QLabel] = {}
        labels = {"alpaca_id": strings.ALP_KEY_ID, "alpaca_secret": strings.ALP_SECRET}
        for service in BROKER_SERVICES:
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(strings.DS_KEY_PLACEHOLDER)
            save = QPushButton(strings.DS_SAVE)
            save.clicked.connect(lambda _c=False, s=service: self.save_key(s))
            delete = QPushButton(strings.DS_DELETE)
            delete.clicked.connect(lambda _c=False, s=service: self.delete_key(s))
            status = QLabel()
            row = QHBoxLayout()
            row.addWidget(QLabel(f"<b>{labels[service]}</b>"))
            row.addWidget(field, stretch=1)
            row.addWidget(save)
            row.addWidget(delete)
            row.addWidget(status)
            keys_layout.addLayout(row)
            self.key_fields[service] = field
            self.key_status[service] = status
        link = QLabel(f'<a href="{SIGNUP_URL}">{strings.ALP_GET_KEYS}</a>')
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        keys_layout.addWidget(link)

        self.account_label = QLabel()
        self.account_label.setWordWrap(True)
        self.refresh_button = QPushButton(strings.ALP_REFRESH)
        self.refresh_button.clicked.connect(self.refresh)
        head = QHBoxLayout()
        head.addWidget(self.account_label, stretch=1)
        head.addWidget(self.refresh_button)

        self.positions_table = _table(strings.ALP_POS_HEADERS)
        self.orders_table = _table(strings.ALP_ORD_HEADERS)
        self.cancel_button = QPushButton(strings.ALP_CANCEL)
        self.cancel_button.clicked.connect(self.cancel_selected)

        order_box = QGroupBox(strings.ALP_NEW_ORDER)
        order_row = QHBoxLayout(order_box)
        self.symbol = QLineEdit()
        self.symbol.setPlaceholderText(strings.ALP_SYMBOL)
        self.side = QComboBox()
        self.side.addItem(strings.ALP_SIDE_BUY, "buy")
        self.side.addItem(strings.ALP_SIDE_SELL, "sell")
        self.type = QComboBox()
        self.type.addItem(strings.ALP_TYPE_MARKET, "market")
        self.type.addItem(strings.ALP_TYPE_LIMIT, "limit")
        self.qty = QDoubleSpinBox()
        self.qty.setDecimals(6)
        self.qty.setRange(0, 1_000_000)
        self.qty.setValue(1)
        self.limit = QDoubleSpinBox()
        self.limit.setDecimals(4)
        self.limit.setRange(0, 10_000_000)
        self.limit.setEnabled(False)
        self.type.currentIndexChanged.connect(
            lambda _i: self.limit.setEnabled(self.type.currentData() == "limit")
        )
        self.send_button = QPushButton(strings.ALP_SEND)
        self.send_button.clicked.connect(self.send_order)
        order_row.addWidget(self.symbol)
        order_row.addWidget(self.side)
        order_row.addWidget(self.type)
        order_row.addWidget(QLabel(strings.ALP_QTY))
        order_row.addWidget(self.qty)
        order_row.addWidget(QLabel(strings.ALP_LIMIT))
        order_row.addWidget(self.limit)
        order_row.addWidget(self.send_button)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName("panelEmpty")
        note = QLabel(strings.ALP_NOTE)
        note.setWordWrap(True)
        note.setObjectName("detailsSource")

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(keys_box)
        layout.addLayout(head)
        layout.addWidget(QLabel(f"<b>{strings.ALP_POSITIONS}</b>"))
        layout.addWidget(self.positions_table, stretch=1)
        layout.addWidget(QLabel(f"<b>{strings.ALP_ORDERS}</b>"))
        layout.addWidget(self.orders_table, stretch=1)
        layout.addWidget(self.cancel_button)
        layout.addWidget(order_box)
        layout.addWidget(self.message)
        layout.addWidget(note)
        self._refresh_status()
        if self._has_keys():
            self.refresh()
        else:
            self.account_label.setText(strings.ALP_NO_KEYS)

    # -- keys -----------------------------------------------------------------------------

    def _has_keys(self) -> bool:
        return all(self._keys.get(s) for s in BROKER_SERVICES)

    def _refresh_status(self) -> None:
        for service, label in self.key_status.items():
            key = self._keys.get(service)
            label.setText(strings.DS_KEY_SAVED.format(key=masked(key)) if key
                          else strings.DS_KEY_MISSING)  # fmt: skip

    def save_key(self, service: str) -> None:
        field = self.key_fields[service]
        try:
            self._keys.set(service, field.text())
        except UserError as exc:
            self.message.setText(exc.user_message)
            return
        field.clear()
        self.message.setText("")
        self._refresh_status()
        if self._has_keys():
            self.refresh()

    def delete_key(self, service: str) -> None:
        self._keys.delete(service)
        self._refresh_status()
        self.account_label.setText(strings.ALP_NO_KEYS)
        self._orders = []
        _fill(self.positions_table, [])
        _fill(self.orders_table, [])

    # -- reading --------------------------------------------------------------------------

    def refresh(self) -> None:
        self.message.setText("")
        self.account_label.setText(strings.ALP_LOADING)
        client = self._client

        def load() -> tuple[Any, Any, Any]:
            return client.account(), client.positions(), client.orders()

        start_worker(load, self._on_loaded, self._on_failed)

    def _on_loaded(self, result: Any) -> None:
        account, positions, orders = result
        self.account_label.setText(strings.ALP_ACCOUNT.format(
            status=account.status, equity=f"{account.equity:,.2f}",
            cash=f"{account.cash:,.2f}", power=f"{account.buying_power:,.2f}"))  # fmt: skip
        _fill(self.positions_table, [
            [p.symbol, f"{p.qty:g}", f"{p.avg_price:,.2f}", f"{p.market_value:,.2f}",
             f"{p.unrealized_pl:+,.2f}"] for p in positions])  # fmt: skip
        self._orders = orders
        _fill(self.orders_table, [
            [o.symbol, o.side, o.type, f"{o.qty:g}",
             f"{o.limit_price:,.2f}" if o.limit_price else "", o.status,
             f"{o.filled_avg_price:,.2f}" if o.filled_avg_price else ""]
            for o in orders])  # fmt: skip

    def _on_failed(self, exc: BaseException) -> None:
        self.account_label.setText("")
        self.message.setText(exc.user_message if isinstance(exc, AppError) else str(exc))

    # -- writing --------------------------------------------------------------------------

    def _ask(self, text: str) -> bool:
        answer = QMessageBox.question(
            self, strings.ALP_TITLE, strings.ALP_CONFIRM.format(text=text)
        )
        return answer == QMessageBox.StandardButton.Yes

    def current_order(self) -> OrderRequest:
        limit = self.limit.value() if self.type.currentData() == "limit" else None
        return OrderRequest(self.symbol.text().strip().upper(), str(self.side.currentData()),
                            self.qty.value(), str(self.type.currentData()), limit)  # fmt: skip

    def send_order(self) -> None:
        order = self.current_order()
        try:
            validate_order(order)
        except UserError as exc:
            self.message.setText(exc.user_message)
            return
        kind = self.type.currentText()
        if order.limit_price:
            kind += f" {order.limit_price:g}"
        text = f"{self.side.currentText()} {order.qty:g} {order.symbol} ({kind})"
        if not self.confirm(text):
            return
        self.message.setText(strings.ALP_LOADING)
        client = self._client
        start_worker(lambda: client.place_order(order), self._on_sent, self._on_failed)

    def _on_sent(self, order: Any) -> None:
        self.refresh()
        self.message.setText(strings.ALP_SENT.format(status=order.status))

    def cancel_selected(self) -> None:
        row = self.orders_table.currentRow()
        if not 0 <= row < len(self._orders):
            return
        order = self._orders[row]
        if order.status not in _OPEN:
            self.message.setText(strings.ALP_NOT_OPEN)
            return
        client = self._client
        start_worker(lambda: client.cancel_order(order.id), self._on_cancelled, self._on_failed)

    def _on_cancelled(self, _result: Any) -> None:
        self.refresh()
        self.message.setText(strings.ALP_CANCELLED)
