"""Search, load and display flow in the main window (synthetic data, no network)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from analisis_acciones.models.market import Interval
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui import strings
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient


@pytest.fixture
def client() -> FakeYahooClient:
    fake = FakeYahooClient()
    fake.search_payload = [
        {"symbol": "TEST", "longname": "Test Corp", "quoteType": "EQUITY", "exchDisp": "NASDAQ"}
    ]
    return fake


@pytest.fixture
def market(client: FakeYahooClient) -> Iterator[MarketDataService]:
    conn = open_database(":memory:")
    fixed = datetime(2025, 3, 3, 23, 0, tzinfo=UTC)
    yield MarketDataService(YahooFinanceProvider(client), conn, clock=lambda: fixed)
    conn.close()


@pytest.fixture
def window(qtbot: QtBot, settings: SettingsService, market: MarketDataService) -> MainWindow:
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


def wait_loaded(qtbot: QtBot, win: MainWindow) -> None:
    assert win.market is not None
    with qtbot.waitSignal(win.market.load_finished, timeout=5000):
        pass


def test_controls_enabled_with_service(window: MainWindow) -> None:
    assert window.search_box.isEnabled()
    assert window.timeframe_combo.isEnabled()
    labels = [window.timeframe_combo.itemText(i) for i in range(window.timeframe_combo.count())]
    assert labels == ["Diario", "Semanal", "Mensual"]
    assert "Yahoo Finance" in window.provider_label.text()


def test_open_symbol_shows_summary_and_persists(
    qtbot: QtBot, window: MainWindow, settings: SettingsService
) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST", "Test Corp")
    assert window.symbol_label.text() == "TEST"
    text = window.chart_panel.empty_label.text()
    assert "TEST" in text and "300" in text  # 300 synthetic sessions
    assert settings.last_symbol() == "TEST"
    assert settings.last_interval() == "1D"
    assert window.market.service.recent()[0].symbol == "TEST"


def test_interval_change_reloads(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    with qtbot.waitSignal(window.market.load_finished, timeout=5000) as blocker:
        window.timeframe_combo.setCurrentIndex(1)
    assert blocker.args[0].series.interval is Interval.W1
    assert "Semanal" in window.chart_panel.empty_label.text()


def test_invalid_ticker_shows_error(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_failed, timeout=5000):
        window.open_symbol("NOPE")
    assert "NOPE" in window.chart_panel.empty_label.text()
    assert window.chart_panel.empty_label.property("error") is True
    assert window.symbol_label.text() == strings.NO_SYMBOL


def test_failed_load_keeps_previous_data(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    summary = window.chart_panel.empty_label.text()
    with qtbot.waitSignal(window.market.load_failed, timeout=5000):
        window.open_symbol("NOPE")
    assert window.chart_panel.empty_label.text() == summary
    assert window.symbol_label.text() == "TEST"
    assert "NOPE" in window.statusBar().currentMessage()
    # Changing interval reloads the symbol actually shown, not the failed one.
    with qtbot.waitSignal(window.market.load_finished, timeout=5000) as blocker:
        window.timeframe_combo.setCurrentIndex(2)
    assert blocker.args[0].series.symbol == "TEST"


def test_network_error_message(qtbot: QtBot, window: MainWindow, client: FakeYahooClient) -> None:
    client.error = ConnectionError("offline")
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_failed, timeout=5000):
        window.open_symbol("TEST")
    assert "conexión" in window.chart_panel.empty_label.text()


def test_typing_searches_and_enter_opens(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    window.search_box.setFocus()
    with qtbot.waitSignal(window.market.search_finished, timeout=5000):
        qtbot.keyClicks(window.search_box, "tes")
    assert window.search_box.popup.isVisible()
    texts = [window.search_box.popup.item(i).text() for i in range(window.search_box.popup.count())]
    assert any(t.startswith("TEST") for t in texts)

    qtbot.keyClick(window.search_box, Qt.Key.Key_Down)
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        qtbot.keyClick(window.search_box, Qt.Key.Key_Return)
    assert window.symbol_label.text() == "TEST"
    assert window.search_box.text() == ""
    assert not window.search_box.popup.isVisible()


def test_enter_on_raw_text_opens_ticker(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    window.search_box.setText("test")
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        qtbot.keyClick(window.search_box, Qt.Key.Key_Return)
    assert window.symbol_label.text() == "TEST"


def test_restore_last_symbol(
    qtbot: QtBot, settings: SettingsService, market: MarketDataService
) -> None:
    settings.set_last_opened("TEST", "1W")
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    win.show()
    assert win.market is not None
    with qtbot.waitSignal(win.market.load_finished, timeout=5000) as blocker:
        win.restore_last_symbol()
    assert win.timeframe_combo.currentData() == "1W"
    assert blocker.args[0].series.interval is Interval.W1


def test_import_csv(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    path = tmp_path / "mis datos.csv"
    path.write_text(
        "date,open,high,low,close\n2024-01-02,10,11,9,10.5\n2024-01-03,10.5,12,10,11\n",
        encoding="utf-8",
    )
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.market.import_csv(path, "MIS-DATOS")
    assert window.symbol_label.text() == "CSV:MIS-DATOS"
    assert "Archivo CSV" in window.provider_label.text()


def test_stale_replies_are_ignored(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    received: list[str] = []
    window.market.load_finished.connect(lambda r: received.append(r.series.symbol))
    window.market.load("NOPE", Interval.D1)  # superseded by the next request
    window.market.load("TEST", Interval.D1)
    qtbot.waitUntil(lambda: bool(received), timeout=5000)
    qtbot.wait(100)
    assert received == ["TEST"]
