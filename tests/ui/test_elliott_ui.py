"""Elliott tab: search in a worker -> tree of counts -> details and chart overlay."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from PySide6.QtCore import QLocale
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient, path

WAVES = (100, 120, 108, 150, 135, 165, 148, 158, 138, 150)


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


def test_elliott_counts_listed_and_drawn(qtbot: QtBot, window: MainWindow) -> None:
    panel = window.elliott_panel
    panel.threshold.setValue(5.0)
    assert panel.threshold.text() != ""
    panel.run()
    qtbot.waitUntil(lambda: panel.result is not None, timeout=10000)
    assert panel.result is not None
    assert len(panel.result.past) == 2 and len(panel.result.current) == 1
    current_group, past_group = panel.tree.topLevelItem(0), panel.tree.topLevelItem(1)
    assert current_group is not None and past_group is not None
    assert current_group.childCount() == 1 and past_group.childCount() == 2
    # The possible current count is selected first; its details show rules and levels.
    assert panel.selected is panel.result.current[0]
    assert "✓ La onda 2 no retrocede" in panel.details.text()
    level = QLocale().toString(158.0, "f", 2)
    assert f"invalidada si el precio supera {level}" in panel.details.text()

    # 3 count lines + 3 target levels + invalidation level.
    qtbot.waitUntil(lambda: state(qtbot, window)["overlayGroups"].get("elliott") == 7,
                    timeout=10000)  # fmt: skip
    past_impulse = past_group.child(1)
    assert past_impulse is not None and "Impulso alcista 1-2-3-4-5" in past_impulse.text(0)
    panel.tree.setCurrentItem(past_impulse)
    assert "La onda 3 no es la más corta" in panel.details.text()
    # Only the two past counts remain: alternative current counts are drawn when selected.
    qtbot.waitUntil(lambda: state(qtbot, window)["overlayGroups"].get("elliott") == 2,
                    timeout=10000)  # fmt: skip

    panel.show_on_chart.setChecked(False)
    qtbot.waitUntil(lambda: "elliott" not in state(qtbot, window)["overlayGroups"],
                    timeout=10000)  # fmt: skip


def test_new_data_clears_counts(qtbot: QtBot, window: MainWindow) -> None:
    panel = window.elliott_panel
    panel.run()  # automatic threshold
    qtbot.waitUntil(lambda: panel.result is not None, timeout=10000)
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("OTHER")
    assert panel.result is None and panel.tree.topLevelItemCount() == 0
    qtbot.waitUntil(lambda: "elliott" not in state(qtbot, window)["overlayGroups"],
                    timeout=10000)  # fmt: skip
