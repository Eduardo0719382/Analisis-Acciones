"""Dialog to add, configure, hide and remove chart indicators.

Works on a copy of the configuration; changes apply only on "Aceptar".
Parameter forms are generated from the indicator registry.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.indicators.registry import SPECS, IndicatorConfig, get_spec, validate_params
from analisis_acciones.indicators.templates import BUILTIN, builtin_configs
from analisis_acciones.models.errors import UserError
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.ui import strings


class IndicatorDialog(QDialog):
    def __init__(self, configs: list[IndicatorConfig], parent: QWidget | None = None,
                 templates: SettingsService | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._templates = templates
        self.setWindowTitle(strings.INDICATORS_TITLE)
        self.setMinimumSize(560, 380)
        self._configs: list[IndicatorConfig] = list(configs)
        self._editors: dict[str, QSpinBox | QDoubleSpinBox] = {}

        # Add row
        self.available = QComboBox()
        for spec in SPECS:
            self.available.addItem(spec.name, spec.id)
        self.add_button = QPushButton(strings.INDICATORS_ADD)
        self.add_button.clicked.connect(self._add)
        add_row = QHBoxLayout()
        add_row.addWidget(self.available, stretch=1)
        add_row.addWidget(self.add_button)

        # Active list
        self.active = QListWidget()
        self.active.currentRowChanged.connect(self._show_editor)
        self.active.itemChanged.connect(self._on_item_changed)
        self.remove_button = QPushButton(strings.INDICATORS_REMOVE)
        self.remove_button.clicked.connect(self._remove)

        # Parameter editor
        self.editor_box = QGroupBox(strings.INDICATORS_PARAMS)
        self.editor_form = QFormLayout(self.editor_box)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setObjectName("detailsSource")
        self.apply_params_button = QPushButton(strings.INDICATORS_APPLY_PARAMS)
        self.apply_params_button.clicked.connect(self._apply_params)
        self.error_label = QLabel()
        self.error_label.setObjectName("panelEmpty")
        self.error_label.setProperty("error", True)
        self.error_label.setWordWrap(True)

        left = QVBoxLayout()
        left.addWidget(QLabel(strings.INDICATORS_ACTIVE))
        left.addWidget(self.active, stretch=1)
        left.addWidget(self.remove_button)
        right = QVBoxLayout()
        right.addWidget(self.editor_box)
        right.addWidget(self.description)
        right.addWidget(self.apply_params_button)
        right.addWidget(self.error_label)
        right.addStretch(1)
        body = QHBoxLayout()
        body.addLayout(left, stretch=1)
        body.addLayout(right, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(strings.DIALOG_OK)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.DIALOG_CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        if templates is not None:
            self.template_combo = QComboBox()
            self.load_template_button = QPushButton(strings.TEMPLATE_LOAD)
            self.load_template_button.clicked.connect(self.load_template)
            self.save_template_button = QPushButton(strings.TEMPLATE_SAVE)
            self.save_template_button.clicked.connect(self._ask_save_template)
            self.delete_template_button = QPushButton(strings.TEMPLATE_DELETE)
            self.delete_template_button.clicked.connect(self.delete_template)
            self.template_combo.currentIndexChanged.connect(self._on_template_selected)
            template_row = QHBoxLayout()
            template_row.addWidget(QLabel(strings.TEMPLATE_LABEL))
            template_row.addWidget(self.template_combo, stretch=1)
            for button in (self.load_template_button, self.save_template_button,
                           self.delete_template_button):  # fmt: skip
                template_row.addWidget(button)
            layout.addLayout(template_row)
            self._fill_templates()
        layout.addLayout(add_row)
        layout.addLayout(body, stretch=1)
        layout.addWidget(buttons)

        self._refresh_list(0 if self._configs else -1)

    # Templates -----------------------------------------------------------------
    def _fill_templates(self, select: str | None = None) -> None:
        assert self._templates is not None
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for name in BUILTIN:
            self.template_combo.addItem(strings.TEMPLATE_BUILTIN.format(name=name), ("b", name))
        for name in sorted(self._templates.indicator_templates(), key=str.casefold):
            self.template_combo.addItem(name, ("u", name))
        if select is not None:
            self.template_combo.setCurrentIndex(max(self.template_combo.findText(select), 0))
        self.template_combo.blockSignals(False)
        self._on_template_selected()

    def _on_template_selected(self, *_args: object) -> None:
        data = self.template_combo.currentData()
        self.delete_template_button.setEnabled(bool(data) and data[0] == "u")

    def load_template(self) -> None:
        data = self.template_combo.currentData()
        if not data or self._templates is None:
            return
        kind, name = data
        if kind == "b":
            configs = builtin_configs(name)
        else:
            stored = self._templates.indicator_templates().get(name, [])
            # Fresh ids so the loaded indicators never clash with ones already on the chart.
            configs = [replace(IndicatorConfig.create(c.indicator_id, dict(c.params)),
                               visible=c.visible) for c in stored]  # fmt: skip
        self._configs = configs
        self._refresh_list(0 if configs else -1)

    def _ask_save_template(self) -> None:
        name, ok = QInputDialog.getText(self, strings.TEMPLATE_SAVE, strings.TEMPLATE_NAME_PROMPT)
        if ok:
            self.save_template(name)

    def save_template(self, name: str) -> bool:
        if self._templates is None:
            return False
        try:
            clean = self._templates.save_indicator_template(name, self._configs)
        except UserError as exc:
            self.error_label.setText(exc.user_message)
            return False
        self.error_label.clear()
        self._fill_templates(select=clean)
        return True

    def delete_template(self) -> None:
        data = self.template_combo.currentData()
        if self._templates is None or not data or data[0] != "u":
            return
        self._templates.delete_indicator_template(data[1])
        self._fill_templates()

    # Result --------------------------------------------------------------------
    def configs(self) -> list[IndicatorConfig]:
        return list(self._configs)

    # List ----------------------------------------------------------------------
    def _refresh_list(self, select: int) -> None:
        self.active.blockSignals(True)
        self.active.clear()
        for config in self._configs:
            item = QListWidgetItem(config.label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if config.visible else Qt.CheckState.Unchecked)
            item.setToolTip(strings.INDICATORS_VISIBLE_TIP)
            self.active.addItem(item)
        self.active.blockSignals(False)
        self.remove_button.setEnabled(bool(self._configs))
        if 0 <= select < len(self._configs):
            self.active.setCurrentRow(select)
        else:
            self._show_editor(-1)

    def _add(self) -> None:
        config = IndicatorConfig.create(str(self.available.currentData()))
        self._configs.append(config)
        self._refresh_list(len(self._configs) - 1)

    def _remove(self) -> None:
        row = self.active.currentRow()
        if 0 <= row < len(self._configs):
            del self._configs[row]
            self._refresh_list(min(row, len(self._configs) - 1))

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        row = self.active.row(item)
        if 0 <= row < len(self._configs):
            visible = item.checkState() == Qt.CheckState.Checked
            self._configs[row] = replace(self._configs[row], visible=visible)

    # Editor --------------------------------------------------------------------
    def _show_editor(self, row: int) -> None:
        while self.editor_form.rowCount():
            self.editor_form.removeRow(0)
        self._editors.clear()
        self.error_label.setText("")
        has_row = 0 <= row < len(self._configs)
        self.editor_box.setEnabled(has_row)
        self.apply_params_button.setEnabled(has_row)
        if not has_row:
            self.description.setText(strings.INDICATORS_EMPTY)
            return
        config = self._configs[row]
        spec = get_spec(config.indicator_id)
        self.editor_box.setTitle(f"{strings.INDICATORS_PARAMS}: {spec.name}")
        self.description.setText(spec.description)
        for param in spec.params:
            editor: QSpinBox | QDoubleSpinBox
            if param.kind == "int":
                editor = QSpinBox()
                editor.setRange(int(param.minimum), int(param.maximum))
                editor.setValue(int(config.params[param.key]))
            else:
                editor = QDoubleSpinBox()
                editor.setDecimals(param.decimals)
                editor.setSingleStep(10**-param.decimals)
                editor.setRange(float(param.minimum), float(param.maximum))
                editor.setValue(float(config.params[param.key]))
            self._editors[param.key] = editor
            self.editor_form.addRow(param.label, editor)

    def _apply_params(self) -> None:
        row = self.active.currentRow()
        if not 0 <= row < len(self._configs):
            return
        config = self._configs[row]
        raw = {key: editor.value() for key, editor in self._editors.items()}
        try:
            params = validate_params(get_spec(config.indicator_id), raw)
        except UserError as exc:
            self.error_label.setText(exc.user_message)
            return
        self.error_label.setText("")
        self._configs[row] = replace(config, params=params)
        self._refresh_list(row)

    def accept(self) -> None:
        # Apply pending edits in the form before closing, as users expect.
        if self._editors:
            self._apply_params()
            if self.error_label.text():
                return
        super().accept()
