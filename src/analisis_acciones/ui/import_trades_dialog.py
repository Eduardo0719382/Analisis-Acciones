"""Preview of a broker CSV import: what will be added, what was rejected and the cash needed."""

from __future__ import annotations

import math

from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.data.trades_import import TradesFile
from analisis_acciones.portfolio.engine import BUY
from analisis_acciones.services.paper_portfolio import ImportPreview, Portfolio
from analisis_acciones.services.portfolio_report import local_price, qty
from analisis_acciones.services.scan_report import num
from analisis_acciones.ui import strings

PREVIEW_ROWS = 500


class ImportTradesDialog(QDialog):
    def __init__(self, parsed: TradesFile, preview: ImportPreview, portfolio: Portfolio,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self.setWindowTitle(strings.IMP_TITLE)
        self.resize(900, 640)
        self.preview = preview
        problems = [*parsed.errors, *preview.problems]

        lines = [strings.IMP_COUNT.format(count=len(preview.trades), errors=len(problems))]
        if preview.cash_needed is not None:
            lines.append(strings.IMP_CASH.format(needed=num(preview.cash_needed),
                                                 name=portfolio.name,
                                                 cash=num(portfolio.initial_cash)))  # fmt: skip
        if parsed.missing_commission:
            lines.append(strings.IMP_NO_COMMISSION)
        lines += preview.fx_notes
        summary = QLabel("\n".join(lines))
        summary.setWordWrap(True)

        table = QTableWidget(min(len(preview.trades), PREVIEW_ROWS), len(strings.IMP_COLUMNS))
        table.setHorizontalHeaderLabels(strings.IMP_COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        for r, t in enumerate(preview.trades[:PREVIEW_ROWS]):
            cells = [f"{t.trade_date:%d/%m/%Y}", t.symbol,
                     strings.PF_BUY if t.side == BUY else strings.PF_SELL, qty(t.quantity),
                     local_price(t), num(t.commission), t.note]  # fmt: skip
            for c, text in enumerate(cells):
                table.setItem(r, c, QTableWidgetItem(text))
        self.table = table

        self.errors = QPlainTextEdit("\n".join(problems) or strings.IMP_NO_ERRORS)
        self.errors.setReadOnly(True)
        self.errors.setMaximumHeight(120)

        self.into_current = QRadioButton(strings.IMP_INTO_CURRENT.format(name=portfolio.name))
        self.into_new = QRadioButton(strings.IMP_INTO_NEW)
        group = QButtonGroup(self)
        group.addButton(self.into_current)
        group.addButton(self.into_new)
        self.new_name = QLineEdit(strings.IMP_DEFAULT_NAME)
        self.new_name.setMaxLength(40)
        self.new_cash = QDoubleSpinBox()
        self.new_cash.setRange(1, 1e12)
        self.new_cash.setDecimals(2)
        alone = preview.cash_needed_alone or 0.0
        self.new_cash.setValue(max(math.ceil(alone), 1))
        self.new_cash.setSuffix(" $")
        new_form = QFormLayout()
        new_form.addRow(strings.IMP_NEW_NAME, self.new_name)
        new_form.addRow(strings.IMP_NEW_CASH, self.new_cash)
        fits = preview.cash_needed is not None and preview.cash_needed <= portfolio.initial_cash
        (self.into_current if fits else self.into_new).setChecked(True)
        self.into_new.toggled.connect(self._toggle_new)
        self._toggle_new(self.into_new.isChecked())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(strings.IMP_IMPORT)
        ok.setEnabled(bool(preview.trades))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(table, stretch=1)
        layout.addWidget(QLabel(strings.IMP_ERRORS))
        layout.addWidget(self.errors)
        layout.addWidget(self.into_current)
        layout.addWidget(self.into_new)
        layout.addLayout(new_form)
        layout.addWidget(buttons)

    def _toggle_new(self, on: bool) -> None:
        self.new_name.setEnabled(on)
        self.new_cash.setEnabled(on)
