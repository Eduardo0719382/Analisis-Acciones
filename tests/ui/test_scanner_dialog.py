from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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


def test_fundamental_filters(qtbot: QtBot, market: MarketDataService) -> None:
    dialog = ScannerDialog(market, [])
    qtbot.addWidget(dialog)
    cheap = replace(row("CHEAP", 1, 0), fundamentals_checked=True, pe=12.0, dividend_yield=0.04)
    dear = replace(row("DEAR", 1, 0), fundamentals_checked=True, pe=40.0, dividend_yield=0.0)
    unknown = replace(row("NONE", 1, 0), fundamentals_checked=True)
    dialog.show_result(ScanResult([cheap, dear, unknown]))
    assert dialog.table.rowCount() == 3
    pe_col = strings.SCAN_COLUMNS.index("PER")
    dialog.max_pe.setValue(20)
    assert dialog.table.rowCount() == 1 and dialog.table.item(0, 0).text() == "CHEAP"
    assert dialog.table.item(0, pe_col + 1).text() in {"4.00", "4,00"}
    dialog.max_pe.setValue(0)
    dialog.min_yield.setValue(1)
    assert dialog.table.rowCount() == 1
    assert [r.symbol for r in dialog.visible_result().rows] == ["CHEAP"]
    # Without fundamentals in the scan the limits do not hide rows; a hint explains why.
    dialog.show_result(ScanResult([row("AAA", 1, 0)]))
    assert dialog.table.rowCount() == 1
    dialog.min_yield.setValue(2)
    assert "Incluir fundamentales" in dialog.status.text()


def test_more_fundamental_filters(qtbot: QtBot, market: MarketDataService,
                                  tmp_path: Path) -> None:  # fmt: skip
    dialog = ScannerDialog(market, [])
    qtbot.addWidget(dialog)
    dialog.open_after_export = False
    big = replace(row("BIG", 1, 0), fundamentals_checked=True, market_cap=3e12,
                  revenue_growth=0.06, profit_margin=0.25)  # fmt: skip
    small = replace(row("SMALL", 1, 0), fundamentals_checked=True, market_cap=2e9,
                    revenue_growth=-0.03, profit_margin=-0.1)  # fmt: skip
    dialog.show_result(ScanResult([big, small]))
    assert not dialog.limits().active  # every spin box starts at "sin límite"
    cap_col = strings.SCAN_COLUMNS.index("Cap. (mil M)")
    shown = {dialog.table.item(r, 0).text(): dialog.table.item(r, cap_col).text()
             for r in range(2)}  # fmt: skip
    assert shown["BIG"] in {"3,000.0", "3000.0", "3.000,0", "3000,0"}
    dialog.min_cap.setValue(10)
    assert [r.symbol for r in dialog.visible_result().rows] == ["BIG"]
    dialog.min_cap.setValue(0)
    dialog.min_growth.setValue(-5)
    assert len(dialog.visible_result().rows) == 2
    dialog.min_margin.setValue(0)
    assert [r.symbol for r in dialog.visible_result().rows] == ["BIG"]
    dialog.export("html", tmp_path / "f.html")
    page = (tmp_path / "f.html").read_text("utf-8")
    assert "crecimiento de ingresos ≥ -5 %, margen neto ≥ 0 %" in page
