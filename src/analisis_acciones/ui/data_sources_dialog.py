"""Choose the price source of stocks and of cryptocurrencies, and save the API keys."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.models.errors import UserError
from analisis_acciones.services.api_keys import SERVICES, SIGNUP_URLS, KeyStore, masked
from analisis_acciones.services.data_sources import SOURCE_BY_KEY, SOURCES
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.ui import strings


class DataSourcesDialog(QDialog):
    #: The chosen sources changed (the open asset should be reloaded).
    sources_changed = Signal()

    def __init__(self, settings: SettingsService, keys: KeyStore,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._settings = settings
        self._keys = keys
        self.setWindowTitle(strings.DS_TITLE)
        self.resize(640, 560)

        intro = QLabel(strings.DS_INTRO)
        intro.setWordWrap(True)
        self.stock = QComboBox()
        self.crypto = QComboBox()
        for s in SOURCES:
            if s.stocks:
                self.stock.addItem(s.name, s.key)
            if s.crypto:
                self.crypto.addItem(s.name, s.key)
        self.stock.setCurrentIndex(max(self.stock.findData(settings.stock_source()), 0))
        self.crypto.setCurrentIndex(max(self.crypto.findData(settings.crypto_source()), 0))
        self.stock_info = QLabel()
        self.crypto_info = QLabel()
        for label in (self.stock_info, self.crypto_info):
            label.setWordWrap(True)
            label.setObjectName("detailsSource")
        self.stock.currentIndexChanged.connect(lambda _i: self._describe())
        self.crypto.currentIndexChanged.connect(lambda _i: self._describe())
        form = QFormLayout()
        form.addRow(strings.DS_STOCKS, self.stock)
        form.addRow("", self.stock_info)
        form.addRow(strings.DS_CRYPTO, self.crypto)
        form.addRow("", self.crypto_info)

        keys_box = QGroupBox(strings.DS_KEYS)
        keys_layout = QVBoxLayout(keys_box)
        note = QLabel(strings.DS_KEYS_NOTE)
        note.setWordWrap(True)
        note.setObjectName("detailsSource")
        keys_layout.addWidget(note)
        self.key_fields: dict[str, QLineEdit] = {}
        self.key_status: dict[str, QLabel] = {}
        for service, name in SERVICES.items():
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(strings.DS_KEY_PLACEHOLDER)
            save = QPushButton(strings.DS_SAVE)
            save.clicked.connect(lambda _c=False, s=service: self.save_key(s))
            delete = QPushButton(strings.DS_DELETE)
            delete.clicked.connect(lambda _c=False, s=service: self.delete_key(s))
            status = QLabel()
            link = QLabel(f'<a href="{SIGNUP_URLS[service]}">{strings.DS_GET_KEY}</a>')
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            row = QHBoxLayout()
            row.addWidget(QLabel(f"<b>{name}</b>"))
            row.addWidget(field, stretch=1)
            row.addWidget(save)
            row.addWidget(delete)
            keys_layout.addLayout(row)
            info = QHBoxLayout()
            info.addWidget(status, stretch=1)
            info.addWidget(link)
            keys_layout.addLayout(info)
            self.key_fields[service] = field
            self.key_status[service] = status

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setObjectName("panelEmpty")
        self.error.setProperty("error", True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(keys_box)
        layout.addWidget(self.error)
        layout.addStretch(1)
        layout.addWidget(buttons)
        self._describe()
        self._refresh_status()

    def _describe(self) -> None:
        self.stock_info.setText(SOURCE_BY_KEY[str(self.stock.currentData())].summary)
        self.crypto_info.setText(SOURCE_BY_KEY[str(self.crypto.currentData())].summary)

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
            self.error.setText(exc.user_message)
            return
        field.clear()
        self.error.setText("")
        self._refresh_status()

    def delete_key(self, service: str) -> None:
        self._keys.delete(service)
        self._refresh_status()

    def accept(self) -> None:
        stock, crypto = str(self.stock.currentData()), str(self.crypto.currentData())
        missing = [SOURCE_BY_KEY[k].name for k in dict.fromkeys((stock, crypto))
                   if SOURCE_BY_KEY[k].needs_key and not self._keys.get(k)]  # fmt: skip
        if missing:
            self.error.setText(strings.DS_NEEDS_KEY.format(names=", ".join(missing)))
            return
        changed = (stock, crypto) != (self._settings.stock_source(),
                                      self._settings.crypto_source())  # fmt: skip
        self._settings.set_stock_source(stock)
        self._settings.set_crypto_source(crypto)
        if changed:
            self.sources_changed.emit()
        super().accept()
