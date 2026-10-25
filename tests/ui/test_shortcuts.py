from __future__ import annotations

from pytestqt.qtbot import QtBot

from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.ui.main_window import MainWindow


def test_shortcuts_are_unique_and_tabs_switch(qtbot: QtBot, settings: SettingsService) -> None:
    win = MainWindow(settings)
    qtbot.addWidget(win)
    keys = [a.shortcut().toString() for a in win.findChildren(type(win.search_action))
            if not a.shortcut().isEmpty()]  # fmt: skip
    assert len(keys) == len(set(keys)), keys
    for expected in ("Ctrl+F", "F5", "Ctrl+I", "Ctrl+Shift+P", "Ctrl+Q", "F1"):
        assert expected in keys
    win._select_tab(1)
    assert win.right_tabs.currentIndex() == 1
    win._select_tab(99)  # out of range: ignored
    assert win.right_tabs.currentIndex() == 1
    win.focus_search()
    win.refresh_current()  # nothing open: no error
