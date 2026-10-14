"""Search, load and display flow in the main window (synthetic data, no network)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from analisis_acciones.indicators.registry import IndicatorConfig
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
    service = MarketDataService(YahooFinanceProvider(client), conn, clock=lambda: fixed)
    yield service
    service.close()


@pytest.fixture
def window(qtbot: QtBot, settings: SettingsService, market: MarketDataService) -> MainWindow:
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


def chart_state(qtbot: QtBot, win: MainWindow) -> dict[str, Any]:
    """Ask the real chart page what it is drawing."""
    qtbot.waitUntil(lambda: win.chart.is_loaded, timeout=20000)
    result: list[str] = []
    qtbot.waitUntil(
        lambda: (
            (
                result
                or win.chart.evaluate("JSON.stringify(window.chartApp.state())", result.append)
                or False
            )
            and bool(result)
        ),
        timeout=10000,
    )
    state: dict[str, Any] = json.loads(result[0])
    return state


def test_controls_enabled_with_service(window: MainWindow) -> None:
    assert window.search_box.isEnabled()
    assert window.timeframe_combo.isEnabled()
    labels = [window.timeframe_combo.itemText(i) for i in range(window.timeframe_combo.count())]
    assert labels == ["15 min", "1 hora", "Diario", "Semanal", "Mensual"]
    assert window.timeframe_combo.currentText() == "Diario"
    assert "Yahoo Finance" in window.provider_label.text()


def test_open_symbol_shows_summary_and_persists(
    qtbot: QtBot, window: MainWindow, settings: SettingsService
) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST", "Test Corp")
    assert window.symbol_label.text() == "TEST"
    assert window.chart.showing_chart
    assert window.chart.current_series is not None
    assert len(window.chart.current_series) == 300  # 300 synthetic sessions
    assert settings.last_symbol() == "TEST"
    assert settings.last_interval() == "1D"
    assert window.market.service.recent()[0].symbol == "TEST"


def test_interval_change_reloads(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    with qtbot.waitSignal(window.market.load_finished, timeout=5000) as blocker:
        window.timeframe_combo.setCurrentIndex(window.timeframe_combo.findData("1W"))
    assert blocker.args[0].series.interval is Interval.W1
    assert window.chart.current_series is not None
    assert window.chart.current_series.interval is Interval.W1


def test_invalid_ticker_shows_error(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_failed, timeout=5000):
        window.open_symbol("NOPE")
    assert "NOPE" in window.chart.message.text()
    assert window.chart.message.property("error") is True
    assert not window.chart.showing_chart
    assert window.symbol_label.text() == strings.NO_SYMBOL


def test_failed_load_keeps_previous_data(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    shown = window.chart.current_series
    with qtbot.waitSignal(window.market.load_failed, timeout=5000):
        window.open_symbol("NOPE")
    assert window.chart.showing_chart
    assert window.chart.current_series is shown
    assert window.symbol_label.text() == "TEST"
    assert "NOPE" in window.statusBar().currentMessage()
    # Changing interval reloads the symbol actually shown, not the failed one.
    with qtbot.waitSignal(window.market.load_finished, timeout=5000) as blocker:
        window.timeframe_combo.setCurrentIndex(window.timeframe_combo.findData("1M"))
    assert blocker.args[0].series.symbol == "TEST"


def test_network_error_message(qtbot: QtBot, window: MainWindow, client: FakeYahooClient) -> None:
    client.error = ConnectionError("offline")
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_failed, timeout=5000):
        window.open_symbol("TEST")
    assert "conexión" in window.chart.message.text()


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


def test_details_panel_filled_after_load(
    qtbot: QtBot, window: MainWindow, client: FakeYahooClient
) -> None:
    client.info_payload = {"regularMarketPrice": 110.0, "regularMarketPreviousClose": 100.0,
                           "longName": "Synthetic Test Corp", "currency": "USD",
                           "marketState": "CLOSED"}  # fmt: skip
    assert window.market is not None
    with qtbot.waitSignal(window.market.details_finished, timeout=5000):
        window.open_symbol("TEST")
    panel = window.details_panel
    assert panel.symbol_label.text() == "TEST"
    assert panel.name_label.text() == "Synthetic Test Corp"
    assert "110" in panel.values["price"].text()
    assert panel.values["change_pct"].text().startswith("+10")
    assert panel.values["change"].property("direction") == "up"
    assert "Mercado cerrado" in panel.source_label.text()


def test_details_offline_shows_bar_data_and_notice(
    qtbot: QtBot, window: MainWindow, client: FakeYahooClient
) -> None:
    assert window.market is not None
    # No live quote available (empty payload), so details come from the cached bars.
    with qtbot.waitSignal(window.market.details_finished, timeout=5000):
        window.open_symbol("TEST")
    window.current_result = None  # force a details refresh on the next load
    client.error = ConnectionError("offline")
    with qtbot.waitSignal(window.market.details_finished, timeout=5000):
        window.open_symbol("TEST")
    panel = window.details_panel
    assert panel.values["price"].text() != "—"
    assert "última barra" in panel.source_label.text()
    assert "conectar" in panel.source_label.text()


def test_chart_page_draws_loaded_series(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    qtbot.waitUntil(lambda: chart_state(qtbot, window)["bars"] == 300, timeout=20000)
    state = chart_state(qtbot, window)
    assert state["priceSeriesType"] == "Candlestick"
    assert state["hasVolume"] and state["panes"] == 2
    assert state["legend"].startswith("TEST · Diario")
    # Starts on the most recent bars (right edge at the last bar), not the whole history.
    assert state["visibleTo"] >= 299
    assert state["visibleFrom"] > 0


def test_chart_type_switch_and_persistence(
    qtbot: QtBot, window: MainWindow, settings: SettingsService
) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    window.chart_type_combo.setCurrentIndex(window.chart_type_combo.findData("line"))
    qtbot.waitUntil(lambda: chart_state(qtbot, window)["priceSeriesType"] == "Line", timeout=20000)
    assert settings.chart_type() == "line"


def test_theme_change_reaches_chart(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    dark_bg = chart_state(qtbot, window)["background"]
    window.dark_theme_action.setChecked(False)
    qtbot.waitUntil(lambda: chart_state(qtbot, window)["background"] != dark_bg, timeout=20000)


def test_indicators_drawn_persisted_and_restored(
    qtbot: QtBot, window: MainWindow, settings: SettingsService, market: MarketDataService
) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    configs = [IndicatorConfig.create(i) for i in ("sma", "bollinger", "rsi", "macd")]
    window.apply_indicators(configs)
    qtbot.waitUntil(lambda: len(chart_state(qtbot, window)["indicators"]) == 4, timeout=20000)
    state = chart_state(qtbot, window)
    assert state["panes"] == 4  # price + volume + RSI + MACD
    assert state["indicatorSeries"] == 1 + 3 + 1 + 3
    assert "RSI (14)" in state["indicatorLegend"]
    assert settings.indicators() == configs

    # Hidden indicators are kept in the list but not drawn.
    hidden = [configs[0], replace(configs[2], visible=False)]
    window.apply_indicators(hidden)
    qtbot.waitUntil(lambda: chart_state(qtbot, window)["indicators"] == ["SMA (20)"], timeout=20000)
    assert chart_state(qtbot, window)["panes"] == 2
    assert chart_state(qtbot, window)["bandFills"] == 0

    # Volume profile from the View menu, remembered in the settings.
    window.volume_profile_action.setChecked(True)
    qtbot.waitUntil(lambda: chart_state(qtbot, window)["overlayPrimitives"] == 1, timeout=20000)
    assert settings.volume_profile() is True
    window.volume_profile_action.setChecked(False)
    qtbot.waitUntil(lambda: chart_state(qtbot, window)["overlayPrimitives"] == 0, timeout=20000)

    # Ichimoku's cloud is shaded between Senkou A and B.
    window.apply_indicators([IndicatorConfig.create("ichimoku")])
    qtbot.waitUntil(lambda: chart_state(qtbot, window)["bandFills"] == 1, timeout=20000)
    window.apply_indicators(hidden)

    # A new window restores the saved indicators.
    second = MainWindow(settings, market_service=market)
    qtbot.addWidget(second)
    assert second.chart.indicators == hidden


def test_indicators_follow_interval_change(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    window.apply_indicators([IndicatorConfig.create("sma", {"period": 5})])
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.timeframe_combo.setCurrentIndex(window.timeframe_combo.findData("1W"))  # weekly
    qtbot.waitUntil(lambda: chart_state(qtbot, window)["bars"] == 60, timeout=20000)
    assert chart_state(qtbot, window)["indicators"] == ["SMA (5)"]


def test_analysis_tab_lists_explained_signals(qtbot: QtBot, window: MainWindow) -> None:
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    panel = window.analysis_panel
    qtbot.waitUntil(lambda: panel.report is not None, timeout=10000)
    assert panel.report is not None
    assert panel.report.bars_used == 300
    assert panel.tree.topLevelItemCount() >= 1
    trend = next(
        panel.tree.topLevelItem(i)
        for i in range(panel.tree.topLevelItemCount())
        if panel.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == "trend"  # type: ignore[union-attr]
    )
    assert trend is not None and trend.childCount() >= 3  # evidence lines
    assert "TEST · Diario" in panel.summary.text()


def test_exports_write_files(qtbot: QtBot, window: MainWindow, tmp_path: Path) -> None:
    assert window.market is not None
    window.apply_indicators([IndicatorConfig.create("rsi")])
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    qtbot.waitUntil(lambda: window.analysis_panel.report is not None, timeout=10000)
    window.export_csv(tmp_path / "datos.csv")
    window.export_image(tmp_path / "grafico.png")
    window.export_pdf(tmp_path / "informe.pdf")
    csv_text = (tmp_path / "datos.csv").read_text(encoding="utf-8")
    assert csv_text.startswith("date,open,high,low,close") and "RSI (14)" in csv_text
    assert (tmp_path / "grafico.png").read_bytes()[:4] == b"\x89PNG"
    assert (tmp_path / "informe.pdf").read_bytes()[:4] == b"%PDF"
    assert "Guardado" in window.statusBar().currentMessage()


def test_benchmark_overlay(qtbot: QtBot, window: MainWindow, settings: SettingsService,
                           client: FakeYahooClient) -> None:  # fmt: skip
    client.known = {"TEST", "SPY"}
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    assert window.benchmark_action.text() == "Comparar con índice (SPY)"
    window.benchmark_action.setChecked(True)
    qtbot.waitUntil(lambda: "benchmark" in chart_state(qtbot, window)["overlayGroups"],
                    timeout=20000)  # fmt: skip
    assert "TEST" in window.benchmark_summary and "SPY" in window.benchmark_summary
    assert settings.benchmark_on() is True

    window.set_benchmark("qqq")  # unknown to the fake provider: overlay removed, message shown
    assert settings.benchmark() == "QQQ"
    qtbot.waitUntil(lambda: "QQQ" in window.statusBar().currentMessage(), timeout=10000)
    assert "benchmark" not in chart_state(qtbot, window)["overlayGroups"]
    window.benchmark_action.setChecked(False)
    assert settings.benchmark_on() is False
