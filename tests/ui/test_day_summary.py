"""Resumen del día: page content, ticker links open the chart, start-up option."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from pytestqt.qtbot import QtBot

from analisis_acciones.alerts.service import AlertEvent, AlertService
from analisis_acciones.data.freshness import market_open
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.day_summary import SummaryItem, open_link, summary_html
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.day_summary_dialog import DaySummaryDialog
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient

NOW = datetime(2025, 3, 7, 22, 0, tzinfo=UTC)


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    service = MarketDataService(YahooFinanceProvider(FakeYahooClient()), open_database(":memory:"),
                                clock=lambda: NOW)  # fmt: skip
    yield service
    service.close()


def test_market_open() -> None:
    assert market_open(datetime(2025, 3, 7, 15, 0, tzinfo=UTC))  # 10:00 New York, Friday
    assert not market_open(datetime(2025, 3, 7, 22, 0, tzinfo=UTC))  # 17:00
    assert not market_open(datetime(2025, 3, 8, 15, 0, tzinfo=UTC))  # Saturday


def test_summary_html_content_and_escaping() -> None:
    items = [
        SummaryItem("AAA", 10.0, 2.5, date(2025, 3, 7), (9.0, 9.5, 10.0)),
        SummaryItem("BBB", 20.0, -1.0, date(2025, 3, 7), (21.0, 20.0)),
        SummaryItem("<x>", None, None, None, error="No se encontraron <datos>"),
    ]
    events = [AlertEvent(None, "AAA", "AAA · escaneo diario", "▲ Patrón Doble suelo (ruptura)",
                         date(2025, 3, 7), NOW)]  # fmt: skip
    html = summary_html(items, events, NOW, False, "Favoritos")
    assert "<x>" not in html and "&lt;x&gt;" in html and "&lt;datos&gt;" in html
    assert f'href="{open_link("AAA")}"' in html and open_link("<x>") == "http://abrir.local/%3Cx%3E"
    assert "Mercado de EE. UU. cerrado" in html and "Favoritos" in html
    assert "AAA +2,5 %" in html and "BBB −1,0 %" in html  # movers in the tiles
    assert "— Patrón Doble suelo (ruptura)" in html  # icon shown once, by the row marker
    assert "<script" not in html


def test_dialog_links_open_symbols(qtbot: QtBot, settings: SettingsService,
                                   market: MarketDataService) -> None:  # fmt: skip
    alerts = AlertService(open_database(":memory:"), market, clock=lambda: NOW)
    alerts.record_event("TEST", "TEST · escaneo diario", "▲ algo", date(2025, 3, 7))
    dialog = DaySummaryDialog(market, settings, lambda: ["TEST", "ZZZ"], alerts,
                              clock=lambda: NOW)  # fmt: skip
    qtbot.addWidget(dialog)
    dialog.refresh()
    qtbot.waitUntil(lambda: dialog.items is not None, timeout=10000)
    assert dialog.items is not None and [i.symbol for i in dialog.items] == ["TEST", "ZZZ"]
    assert dialog.items[1].error and "TEST · escaneo diario" in dialog.html
    link = QWebEnginePage.NavigationType.NavigationTypeLinkClicked
    with qtbot.waitSignal(dialog.symbol_activated) as blocker:
        assert not dialog.page.acceptNavigationRequest(QUrl(open_link("TEST")), link, True)
    assert blocker.args == ["TEST"]
    assert not dialog.page.acceptNavigationRequest(QUrl("https://example.com"), link, True)
    dialog.show_on_start.setChecked(False)
    assert settings.summary_on_start() is False
    alerts.close()


def test_window_menu_and_start_option(qtbot: QtBot, settings: SettingsService,
                                      market: MarketDataService) -> None:  # fmt: skip
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    win.show_day_summary_on_start()  # no watchlist: nothing to summarise
    assert win._summary_dialog is None
    win.summary_action.trigger()
    assert isinstance(win._summary_dialog, DaySummaryDialog)
