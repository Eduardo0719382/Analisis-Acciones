from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from analisis_acciones.indicators.registry import IndicatorConfig
from analisis_acciones.services.settings_service import KEY_INDICATORS, SettingsService
from analisis_acciones.ui.indicator_dialog import IndicatorDialog


def make(qtbot: QtBot, configs: list[IndicatorConfig] | None = None) -> IndicatorDialog:
    dialog = IndicatorDialog(configs or [])
    qtbot.addWidget(dialog)
    return dialog


def select_available(dialog: IndicatorDialog, indicator_id: str) -> None:
    dialog.available.setCurrentIndex(dialog.available.findData(indicator_id))


def test_add_with_defaults(qtbot: QtBot) -> None:
    dialog = make(qtbot)
    select_available(dialog, "rsi")
    dialog.add_button.click()
    assert [c.label for c in dialog.configs()] == ["RSI (14)"]
    assert dialog.active.currentRow() == 0
    assert set(dialog._editors) == {"period"}


def test_edit_parameters(qtbot: QtBot) -> None:
    dialog = make(qtbot, [IndicatorConfig.create("bollinger")])
    dialog._editors["period"].setValue(30)
    dialog._editors["k"].setValue(2.5)
    dialog.apply_params_button.click()
    assert dialog.configs()[0].params == {"period": 30, "k": 2.5}
    assert dialog.active.item(0).text() == "BB (30, 2.5)"


def test_invalid_combination_is_reported_not_applied(qtbot: QtBot) -> None:
    original = IndicatorConfig.create("macd")
    dialog = make(qtbot, [original])
    dialog._editors["fast"].setValue(40)
    dialog._editors["slow"].setValue(30)
    dialog.apply_params_button.click()
    assert "rápida" in dialog.error_label.text()
    assert dialog.configs()[0].params == original.params
    dialog.accept()  # pending invalid edits block closing
    assert dialog.result() != IndicatorDialog.DialogCode.Accepted


def test_toggle_visibility_and_remove(qtbot: QtBot) -> None:
    dialog = make(qtbot, [IndicatorConfig.create("sma"), IndicatorConfig.create("ema")])
    dialog.active.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.configs()[0].visible is False
    dialog.active.setCurrentRow(1)
    dialog.remove_button.click()
    assert [c.indicator_id for c in dialog.configs()] == ["sma"]
    dialog.remove_button.click()
    assert dialog.configs() == []
    assert not dialog.remove_button.isEnabled()


def test_original_list_untouched_until_accepted(qtbot: QtBot) -> None:
    original = [IndicatorConfig.create("sma")]
    dialog = make(qtbot, original)
    dialog.remove_button.click()
    assert len(original) == 1


def test_settings_persistence(settings: SettingsService) -> None:
    configs = [IndicatorConfig.create("rsi", {"period": 9}), IndicatorConfig.create("sma")]
    settings.set_indicators(configs)
    assert settings.indicators() == configs


def test_corrupt_stored_indicators_are_skipped(settings: SettingsService) -> None:
    settings._repo.set(
        KEY_INDICATORS,
        [{"id": "sma", "params": {"period": 10}}, {"id": "nope"}, "junk",
         {"id": "rsi", "params": {"period": -1}}],
    )  # fmt: skip
    assert [c.label for c in settings.indicators()] == ["SMA (10)"]
