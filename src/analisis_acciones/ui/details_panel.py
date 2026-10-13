"""Right-hand panel with the selected asset's key figures."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QVBoxLayout, QWidget

from analisis_acciones.data.details import AssetDetails
from analisis_acciones.ui import strings

_ROWS = (
    ("price", strings.DETAIL_PRICE),
    ("change", strings.DETAIL_CHANGE),
    ("change_pct", strings.DETAIL_CHANGE_PCT),
    ("open", strings.DETAIL_OPEN),
    ("high", strings.DETAIL_HIGH),
    ("low", strings.DETAIL_LOW),
    ("previous_close", strings.DETAIL_PREV_CLOSE),
    ("volume", strings.DETAIL_VOLUME),
    ("week52_high", strings.DETAIL_52W_HIGH),
    ("week52_low", strings.DETAIL_52W_LOW),
    ("currency", strings.DETAIL_CURRENCY),
    ("exchange", strings.DETAIL_EXCHANGE),
    ("sector", strings.DETAIL_SECTOR),
    ("industry", strings.DETAIL_INDUSTRY),
)
UNKNOWN = "—"


class DetailsPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.details: AssetDetails | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QLabel(strings.PANEL_DETAILS)
        self.header.setObjectName("panelHeader")
        outer.addWidget(self.header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 10)

        self.symbol_label = QLabel(UNKNOWN)
        self.symbol_label.setObjectName("detailsSymbol")
        self.name_label = QLabel(strings.EMPTY_DETAILS)
        self.name_label.setObjectName("detailsName")
        self.name_label.setWordWrap(True)
        body_layout.addWidget(self.symbol_label)
        body_layout.addWidget(self.name_label)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        self.values: dict[str, QLabel] = {}
        for key, title in _ROWS:
            caption = QLabel(title)
            caption.setObjectName("detailsCaption")
            value = QLabel(UNKNOWN)
            value.setObjectName("detailsValue")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(caption, value)
            self.values[key] = value
        body_layout.addLayout(form)

        self.source_label = QLabel()
        self.source_label.setObjectName("detailsSource")
        self.source_label.setWordWrap(True)
        body_layout.addWidget(self.source_label)
        body_layout.addStretch(1)
        outer.addWidget(body, stretch=1)

    # Display -----------------------------------------------------------------
    def show_loading(self, symbol: str) -> None:
        self.symbol_label.setText(symbol)
        self.source_label.setText(strings.DETAILS_LOADING)

    def show_details(self, details: AssetDetails) -> None:
        self.details = details
        locale = QLocale()
        self.symbol_label.setText(details.symbol)
        self.name_label.setText(details.name or "")

        def price(value: float | None) -> str:
            return UNKNOWN if value is None else locale.toString(value, "f", 2)

        change, pct = details.change, details.change_pct
        texts = {
            "price": price(details.price),
            "change": UNKNOWN if change is None else f"{'+' if change > 0 else ''}{price(change)}",
            "change_pct": UNKNOWN
            if pct is None
            else f"{'+' if pct > 0 else ''}{locale.toString(pct, 'f', 2)} %",
            "open": price(details.open),
            "high": price(details.high),
            "low": price(details.low),
            "previous_close": price(details.previous_close),
            "volume": UNKNOWN if details.volume is None else locale.toString(int(details.volume)),
            "week52_high": price(details.week52_high),
            "week52_low": price(details.week52_low),
            "currency": details.currency or UNKNOWN,
            "exchange": details.exchange or UNKNOWN,
            "sector": details.sector or UNKNOWN,
            "industry": details.industry or UNKNOWN,
        }
        for key, text in texts.items():
            self.values[key].setText(text)

        direction = "" if change is None or change == 0 else ("up" if change > 0 else "down")
        for key in ("change", "change_pct"):
            label = self.values[key]
            label.setProperty("direction", direction)
            label.style().unpolish(label)
            label.style().polish(label)

        self.source_label.setText(self._source_text(details))

    @staticmethod
    def _source_text(details: AssetDetails) -> str:
        when = details.as_of
        if isinstance(when, datetime):
            stamp = when.astimezone().strftime("%d/%m/%Y %H:%M")
        elif isinstance(when, date):
            stamp = when.strftime("%d/%m/%Y")
        else:
            stamp = UNKNOWN
        if details.price_source == "quote":
            text = strings.DETAILS_SOURCE_QUOTE.format(when=stamp)
            if details.market_state:
                state = strings.MARKET_STATES.get(details.market_state, details.market_state)
                text += f" · {state}"
        else:
            text = strings.DETAILS_SOURCE_BARS.format(when=stamp)
        if details.notice:
            text += f"\n{details.notice}"
        return text

    def clear(self) -> None:
        self.symbol_label.setText(UNKNOWN)
        self.name_label.setText(strings.EMPTY_DETAILS)
        for label in self.values.values():
            label.setText(UNKNOWN)
        self.source_label.setText("")
