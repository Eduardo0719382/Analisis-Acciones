from __future__ import annotations

import re

from pytestqt.qtbot import QtBot

from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.services.user_guide import SECTIONS, guide_html
from analisis_acciones.ui import strings
from analisis_acciones.ui.guide_dialog import GuideDialog
from analisis_acciones.ui.main_window import MainWindow


def test_guide_links_and_content() -> None:
    html = guide_html()
    targets = re.findall(r'href="#([\w-]+)"', html)
    ids = set(re.findall(r'id="([\w-]+)"', html))
    assert targets and set(targets) <= ids and len(targets) == len(SECTIONS)
    assert "<script" not in html.lower() and "http" not in html
    assert "no es asesoramiento financiero" in html.lower()
    # Menu paths named in the guide exist in the program.
    for label in (strings.ACTION_SCANNER, strings.ACTION_PORTFOLIO, strings.ACTION_SUMMARY,
                  strings.ACTION_BACKTEST, strings.ACTION_COMPARE):  # fmt: skip
        assert label.replace("&", "") in html


def test_help_menu_opens_guide(qtbot: QtBot, settings: SettingsService) -> None:
    win = MainWindow(settings)
    qtbot.addWidget(win)
    assert win.guide_action.shortcut().toString() == "F1"
    win.guide_action.trigger()
    assert isinstance(win._guide_dialog, GuideDialog)
    first = win._guide_dialog
    win.open_guide()
    assert win._guide_dialog is first and first.isVisible()
