from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scanner import FORMING_NOTE, PatternNote, ScanResult, ScanRow
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui import strings
from analisis_acciones.ui.main_window import MainWindow
from analisis_acciones.ui.scanner_dialog import ScannerDialog
from tests.synthetic import FakeYahooClient, synthetic_daily


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    client = FakeYahooClient(synthetic_daily(sessions=400))
    client.known = {"AAA", "BBB"}
    fixed = datetime(2025, 9, 1, 23, 0, tzinfo=UTC)
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: fixed)  # fmt: skip
    yield service
    service.close()


def row(symbol: str, bullish: int, bearish: int, patterns: tuple[str, ...] = (),
        elliott: str = "") -> ScanRow:  # fmt: skip
    notes = tuple(PatternNote(p, FORMING_NOTE, -1) for p in patterns)
    return ScanRow(symbol, 10.0, 1.0, 50.0, ("b",) * bullish, ("s",) * bearish, notes,
                   elliott, 2.0, 3.0)  # fmt: skip


def test_scan_fills_table_and_reports_problems(qtbot: QtBot, market: MarketDataService) -> None:
    dialog = ScannerDialog(market, ["AAA", "bbb", "ZZZ"])
    qtbot.addWidget(dialog)
    dialog.run()
    qtbot.waitUntil(lambda: dialog.scan is not None, timeout=20000)
    assert dialog.table.rowCount() == 2
    assert "ZZZ" in dialog.status.text()
    with qtbot.waitSignal(dialog.symbol_activated, timeout=2000) as blocker:
        dialog.table.cellDoubleClicked.emit(0, 3)
    assert blocker.args[0] in {"AAA", "BBB"}


def test_filters_and_numeric_sort(qtbot: QtBot, market: MarketDataService) -> None:
    dialog = ScannerDialog(market, [])
    qtbot.addWidget(dialog)
    dialog.run()
    assert dialog.status.text() == strings.SCAN_EMPTY
    dialog.show_result(ScanResult([
        row("UP", 3, 1), row("DOWN", 0, 2, ("Doble techo",)),
        row("WAVE", 1, 1, elliott="impulso alcista 1-2-3"), row("TEN", 10, 0),
    ]))  # fmt: skip
    assert dialog.table.rowCount() == 4
    assert [dialog.table.item(r, 0).text() for r in range(4)] == ["DOWN", "TEN", "UP", "WAVE"]
    dialog.table.sortItems(4)  # "Alcistas": 0, 1, 3, 10 numerically (not "10" < "3")
    assert [dialog.table.item(r, 0).text() for r in range(4)] == ["DOWN", "WAVE", "UP", "TEN"]
    for mode, expected in (("bullish", {"UP", "TEN"}), ("bearish", {"DOWN"}),
                           ("patterns", {"DOWN"}), ("elliott", {"WAVE"})):  # fmt: skip
        dialog.filter.setCurrentIndex(dialog.filter.findData(mode))
        shown = {dialog.table.item(r, 0).text() for r in range(dialog.table.rowCount())}
        assert shown == expected


def test_menu_opens_scanner_with_watchlist(qtbot: QtBot, settings: SettingsService,
                                          market: MarketDataService) -> None:  # fmt: skip
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    win.scanner_action.trigger()
    dialog = win._scanner_dialog
    assert isinstance(dialog, ScannerDialog)


def test_export_html_csv_pdf(qtbot: QtBot, market: MarketDataService, tmp_path) -> None:  # type: ignore[no-untyped-def]
    dialog = ScannerDialog(market, [])
    qtbot.addWidget(dialog)
    dialog.open_after_export = False
    assert not dialog.export_button.isEnabled()
    dialog.show_result(ScanResult([row("UP", 3, 1), row("DOWN", 0, 2)], ["ZZZ: no encontrado"]))
    assert dialog.export_button.isEnabled()

    dialog.filter.setCurrentIndex(dialog.filter.findData("bullish"))
    dialog.export("html", tmp_path / "informe")  # extension added
    html = (tmp_path / "informe.html").read_text(encoding="utf-8")
    assert "<h2>UP</h2>" in html and "<h2>DOWN</h2>" not in html
    assert "Filtro aplicado" in html

    dialog.export("csv", tmp_path / "datos.csv")
    assert (tmp_path / "datos.csv").read_bytes().startswith(b"\xef\xbb\xbfticker,")

    target = tmp_path / "informe.pdf"
    dialog.export("pdf", target)
    qtbot.waitUntil(lambda: dialog.last_export == target, timeout=30000)
    assert target.read_bytes().startswith(b"%PDF")
