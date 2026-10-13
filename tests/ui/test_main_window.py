from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.services.settings_service import SettingsService, Theme
from analisis_acciones.ui import strings
from analisis_acciones.ui.disclaimer import DisclaimerDialog
from analisis_acciones.ui.main_window import DEFAULT_MAIN_SPLIT, MainWindow


@pytest.fixture
def window(qtbot: QtBot, settings: SettingsService) -> MainWindow:
    win = MainWindow(settings)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


def test_window_has_all_regions(window: MainWindow) -> None:
    assert window.windowTitle() == strings.APP_TITLE
    assert window.main_splitter.count() == 3
    assert window.center_splitter.count() == 2
    assert window.watchlist_panel.header.text() == strings.PANEL_WATCHLIST
    assert window.details_panel.header.text() == strings.PANEL_DETAILS
    assert "ninguno" in window.provider_label.text()
    assert window.statusBar().currentMessage() == strings.STATUS_READY


def test_features_from_later_phases_are_disabled(window: MainWindow) -> None:
    assert not window.search_box.isEnabled()
    assert not window.timeframe_combo.isEnabled()
    assert window.timeframe_combo.count() == 0  # no provider: no intervals shown
    assert not window.indicators_button.isEnabled()


def test_theme_toggle_is_persisted(window: MainWindow, settings: SettingsService) -> None:
    assert window.dark_theme_action.isChecked()
    window.dark_theme_action.setChecked(False)
    assert settings.theme() is Theme.LIGHT
    window.dark_theme_action.setChecked(True)
    assert settings.theme() is Theme.DARK


def test_layout_saved_on_close_and_restored(qtbot: QtBot, settings: SettingsService) -> None:
    first = MainWindow(settings)
    qtbot.addWidget(first)
    # Stay inside the offscreen platform's virtual screen (800x600): restoreGeometry()
    # clamps windows to the available screen, which would change splitter sizes.
    first.resize(800, 560)
    first.show()
    qtbot.waitExposed(first)
    first.main_splitter.setSizes([150, 500, 150])
    expected = first.main_splitter.sizes()
    first.close()

    saved = settings.layout()
    assert {"geometry", "state", "main_split", "center_split"} <= saved.keys()

    second = MainWindow(settings)
    qtbot.addWidget(second)
    second.show()
    qtbot.waitExposed(second)
    assert second.size() == first.size()
    assert second.main_splitter.sizes() == expected


def test_invalid_layout_uses_defaults(qtbot: QtBot, settings: SettingsService) -> None:
    settings.set_layout(
        {"main_split": "not-base64!!", "geometry": 42, "center_split": [0, 0], "state": ""}
    )
    win = MainWindow(settings)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    assert win.main_splitter.count() == 3
    assert all(size > 0 for size in win.main_splitter.sizes())


def test_reset_layout_clears_saved_state(window: MainWindow, settings: SettingsService) -> None:
    settings.set_layout({"main_split": "AAAA"})
    window.reset_layout()
    assert settings.layout() == {}
    sizes = window.main_splitter.sizes()
    assert len(sizes) == len(DEFAULT_MAIN_SPLIT)


def test_window_usable_when_resized_small(window: MainWindow, qtbot: QtBot) -> None:
    window.resize(window.minimumSize())
    qtbot.wait(10)
    # The chart region must never collapse.
    assert window.main_splitter.sizes()[1] > 0


def test_disclaimer_dialog_buttons(qtbot: QtBot) -> None:
    required = DisclaimerDialog(require_acceptance=True)
    qtbot.addWidget(required)
    texts = {b.text() for b in required.buttons.buttons()}
    assert texts == {strings.DISCLAIMER_ACCEPT, strings.DISCLAIMER_REJECT}

    info = DisclaimerDialog(require_acceptance=False)
    qtbot.addWidget(info)
    assert len(info.buttons.buttons()) == 1
