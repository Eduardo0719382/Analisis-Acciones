"""Watchlist panel inside the main window (synthetic data, no network)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.services.watchlist_service import WatchlistService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui import strings
from analisis_acciones.ui.main_window import MainWindow
from analisis_acciones.ui.watchlist_panel import COL_CHANGE, COL_LAST, WatchlistPanel
from tests.synthetic import FakeYahooClient, synthetic_daily


@pytest.fixture
def client() -> FakeYahooClient:
    fake = FakeYahooClient()
    fake.known = {"TEST", "AAA", "BBB"}
    return fake


@pytest.fixture
def market(client: FakeYahooClient) -> Iterator[MarketDataService]:
    conn = open_database(":memory:")
    fixed = datetime(2025, 3, 3, 23, 0, tzinfo=UTC)
    service = MarketDataService(YahooFinanceProvider(client), conn, clock=lambda: fixed)
    yield service
    service.close()


@pytest.fixture
def lists(conn: sqlite3.Connection) -> WatchlistService:
    return WatchlistService(conn)


@pytest.fixture
def window(
    qtbot: QtBot, settings: SettingsService, market: MarketDataService, lists: WatchlistService
) -> MainWindow:
    win = MainWindow(settings, market_service=market, watchlist_service=lists)
    qtbot.addWidget(win)
    win.show()
    return win


def panel_of(win: MainWindow) -> WatchlistPanel:
    assert isinstance(win.watchlist_panel, WatchlistPanel)
    return win.watchlist_panel


def column(panel: WatchlistPanel, col: int) -> list[str]:
    return [panel.table.item(r, col).text() for r in range(panel.table.rowCount())]  # type: ignore[union-attr]


def test_starts_with_empty_favourites(window: MainWindow) -> None:
    panel = panel_of(window)
    assert panel.list_combo.currentText() == "Favoritos"
    assert panel.table.isHidden() and not panel.empty_label.isHidden()
    panel.add_current()
    assert panel.status_label.text() == strings.WATCHLIST_NOTHING_OPEN


def test_add_current_symbol_shows_values(qtbot: QtBot, window: MainWindow) -> None:
    panel = panel_of(window)
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("TEST")
    with qtbot.waitSignal(window.market.snapshot_finished, timeout=5000):
        panel.add_button.click()
    assert panel.symbols() == ["TEST"]
    closes = synthetic_daily()["close"]
    expected_pct = (closes.iloc[-1] / closes.iloc[-2] - 1) * 100
    assert column(panel, COL_LAST)[0].replace(",", ".") == f"{closes.iloc[-1]:.2f}"
    assert (
        column(panel, COL_CHANGE)[0]
        .replace(",", ".")
        .startswith(f"{'+' if expected_pct > 0 else ''}{expected_pct:.2f}")
    )
    panel.add_current()
    assert "ya está" in panel.status_label.text()


def test_unknown_symbol_row_shows_dash_with_reason(qtbot: QtBot, window: MainWindow) -> None:
    panel = panel_of(window)
    assert window.market is not None
    with qtbot.waitSignal(window.market.snapshot_finished, timeout=5000):
        panel.add_symbol("ZZZ")
    assert column(panel, COL_LAST) == ["—"]
    assert "ZZZ" in panel.table.item(0, COL_LAST).toolTip()  # type: ignore[union-attr]


def test_click_opens_symbol(qtbot: QtBot, window: MainWindow) -> None:
    panel = panel_of(window)
    panel.add_symbol("AAA")
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000) as blocker:
        panel.table.cellClicked.emit(0, 0)
    assert blocker.args[0].series.symbol == "AAA"


def test_reorder_and_remove(window: MainWindow, lists: WatchlistService) -> None:
    panel = panel_of(window)
    for s in ("AAA", "BBB", "TEST"):
        panel.add_symbol(s)
    panel.table.selectRow(2)
    panel.up_button.click()
    assert panel.symbols() == ["AAA", "TEST", "BBB"]
    assert panel.selected_symbol() == "TEST"
    panel.remove_button.click()
    assert panel.symbols() == ["AAA", "BBB"]
    assert lists.symbols(panel.current_list_id() or 0) == ["AAA", "BBB"]


def test_multiple_lists_and_selection_persist(
    qtbot: QtBot,
    window: MainWindow,
    settings: SettingsService,
    market: MarketDataService,
    lists: WatchlistService,
) -> None:
    panel = panel_of(window)
    panel.add_symbol("AAA")
    panel.create_list("Tecnología")
    assert panel.list_combo.currentText() == "Tecnología"
    assert panel.symbols() == []
    panel.add_symbol("BBB")
    panel.rename_list("Tech")
    assert panel.list_combo.currentText() == "Tech"
    panel.create_list("tech")  # duplicate name
    assert "Ya existe" in panel.status_label.text()

    second = MainWindow(settings, market_service=market, watchlist_service=lists)
    qtbot.addWidget(second)
    restored = panel_of(second)
    assert restored.list_combo.currentText() == "Tech"
    assert restored.symbols() == ["BBB"]

    restored.delete_list(confirm=False)
    assert restored.list_combo.currentText() == "Favoritos"
    assert restored.symbols() == ["AAA"]
    restored.delete_list(confirm=False)  # last list cannot be deleted
    assert "única lista" in restored.status_label.text()


def test_crypto_example_list_opens_the_exhaustion_comparison(
    qtbot: QtBot, window: MainWindow, lists: WatchlistService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analisis_acciones.services.watchlist_service import CRYPTO_EXAMPLE, CRYPTO_LIST_NAME

    opened: list[list[str]] = []
    monkeypatch.setattr(window, "open_exhaustion_compare", lambda s=None: opened.append(s))
    panel = panel_of(window)
    panel.example_created.disconnect()
    panel.example_created.connect(window.open_exhaustion_compare)
    panel.create_crypto_example()
    assert panel.list_combo.currentText() == CRYPTO_LIST_NAME
    assert panel.symbols() == list(CRYPTO_EXAMPLE)
    assert opened == [list(CRYPTO_EXAMPLE)]
    # Running it again keeps a single list and adds only what is missing.
    target = next(w for w in lists.lists() if w.name == CRYPTO_LIST_NAME)
    lists.remove(target.id, "BTC-USD")
    panel.create_crypto_example()
    assert [w.name for w in lists.lists()].count(CRYPTO_LIST_NAME) == 1
    assert "BTC-USD" in lists.symbols(target.id)


def test_altcoin_example_list(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analisis_acciones.data.freshness import is_crypto
    from analisis_acciones.services.watchlist_service import ALTCOIN_EXAMPLE, ALTCOIN_LIST_NAME

    monkeypatch.setattr(window, "open_exhaustion_compare", lambda s=None: None)
    panel = panel_of(window)
    panel.example_created.disconnect()
    panel.create_altcoin_example()
    assert panel.list_combo.currentText() == ALTCOIN_LIST_NAME
    assert panel.symbols() == list(ALTCOIN_EXAMPLE)
    assert "BTC-USD" not in ALTCOIN_EXAMPLE
    assert all(is_crypto(s) for s in ALTCOIN_EXAMPLE)


def test_data_sources_dialog(qtbot: QtBot, window: MainWindow, settings: SettingsService) -> None:
    from analisis_acciones.services.api_keys import MemoryKeyStore

    window._key_store = MemoryKeyStore()
    dialog = window.open_data_sources()
    qtbot.addWidget(dialog)
    dialog.crypto.setCurrentIndex(dialog.crypto.findData("twelvedata"))
    dialog.accept()
    assert "Twelve Data" in dialog.error.text() and settings.crypto_source() == "yahoo"
    dialog.key_fields["twelvedata"].setText("NOT VALID!")
    dialog.save_key("twelvedata")
    assert "formato" in dialog.error.text()
    dialog.key_fields["twelvedata"].setText("ABCDEF1234567890")
    dialog.save_key("twelvedata")
    assert dialog.key_status["twelvedata"].text() == "Clave guardada (ABC…890)."
    assert dialog.key_fields["twelvedata"].text() == ""
    dialog.stock.setCurrentIndex(dialog.stock.findData("twelvedata"))
    assert dialog.auto_fallback.isChecked() and dialog.realtime.isChecked()  # defaults
    dialog.auto_fallback.setChecked(False)
    dialog.accept()
    assert settings.crypto_source() == "twelvedata" and settings.stock_source() == "twelvedata"
    assert not settings.auto_fallback() and settings.realtime_quotes()
