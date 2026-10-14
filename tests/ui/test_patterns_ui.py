"""Patrones tab: levels and chart patterns listed, explained and drawn."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient, path

WAVES = (100, 130, 115, 129.5, 112, 98, 104)


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    fixed = datetime(2024, 5, 20, 23, 0, tzinfo=UTC)
    client = FakeYahooClient(path(*WAVES))
    client.known = {"TEST", "OTHER"}
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: fixed)  # fmt: skip
    yield service
    service.close()


@pytest.fixture
def window(qtbot: QtBot, settings: SettingsService, market: MarketDataService) -> MainWindow:
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    win.show()
    assert win.market is not None
    with qtbot.waitSignal(win.market.load_finished, timeout=5000):
        win.open_symbol("TEST")
    qtbot.waitUntil(lambda: win.chart.is_loaded, timeout=20000)
    return win


def state(qtbot: QtBot, win: MainWindow) -> dict[str, Any]:
    out: list[str] = []
    win.chart.evaluate("JSON.stringify(window.chartApp.state())", out.append)
    qtbot.waitUntil(lambda: bool(out), timeout=10000)
    return json.loads(out[0])  # type: ignore[no-any-return]


def test_patterns_listed_and_drawn(qtbot: QtBot, window: MainWindow) -> None:
    panel = window.patterns_panel
    panel.threshold.setValue(5.0)
    panel.run()
    qtbot.waitUntil(lambda: panel.result is not None, timeout=10000)
    assert panel.result is not None
    top = next(p for p in panel.result.patterns if p.name == "Doble techo")
    assert top.status == "target"
    assert "1 alcanzaron su objetivo" in panel.summary.text()
    past_group = panel.tree.topLevelItem(2)
    assert past_group is not None
    texts = [past_group.child(i).text(0) for i in range(past_group.childCount())]
    assert any(t.startswith("Doble techo") and "objetivo alcanzado" in t for t in texts)
    # The selected (first) pattern is described and drawn with its target and invalidation.
    assert panel.selected is not None
    assert "Condiciones comprobadas" in panel.details.text()
    groups = lambda: state(qtbot, window)["overlayGroups"]  # noqa: E731
    qtbot.waitUntil(lambda: bool(groups().get("patterns")), timeout=10000)

    panel.show_patterns.setChecked(False)
    qtbot.waitUntil(lambda: "patterns" not in groups(), timeout=10000)
    panel.show_levels.setChecked(False)
    qtbot.waitUntil(lambda: "levels" not in groups(), timeout=10000)


def test_new_data_clears_patterns(qtbot: QtBot, window: MainWindow) -> None:
    panel = window.patterns_panel
    panel.run()
    qtbot.waitUntil(lambda: panel.result is not None, timeout=10000)
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("OTHER")
    assert panel.result is None and panel.tree.topLevelItemCount() == 0
