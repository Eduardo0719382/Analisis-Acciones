"""Daily scan: due once per session, baseline first, then new items become notifications."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.alerts.service import AlertService
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scanner import ScanResult
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui import daily_scan as daily_module
from analisis_acciones.ui.daily_scan import DailyScanController
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient
from tests.unit.test_scan_report import make_row

SATURDAY = datetime(2025, 3, 8, 15, 0, tzinfo=UTC)


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    service = MarketDataService(YahooFinanceProvider(FakeYahooClient()), open_database(":memory:"),
                                clock=lambda: SATURDAY)  # fmt: skip
    yield service
    service.close()


class FakeScans:
    def __init__(self) -> None:
        self.results: list[ScanResult] = []
        self.calls: list[list[str]] = []

    def __call__(self, _market: object, symbols: list[str]) -> ScanResult:
        self.calls.append(list(symbols))
        return self.results.pop(0)


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> FakeScans:
    fake = FakeScans()
    monkeypatch.setattr(daily_module, "run_scan", fake)
    return fake


def test_controller_runs_once_per_session(qtbot: QtBot, settings: SettingsService,
                                          market: MarketDataService,
                                          scans: FakeScans) -> None:  # fmt: skip
    now = [SATURDAY]
    controller = DailyScanController(settings, market, lambda: ["AAA"], clock=lambda: now[0])
    scans.results = [ScanResult([make_row()]), ScanResult([make_row(bearish=("Nueva",))])]
    with qtbot.waitSignal(controller.finished, timeout=5000) as first:
        assert controller.maybe_run()
    assert first.args[1] == []  # baseline
    assert settings.scan_snapshot()["session"] == "2025-03-07"
    assert not controller.maybe_run()  # same session: not due

    now[0] = datetime(2025, 3, 10, 22, 0, tzinfo=UTC)  # Monday after the close
    with qtbot.waitSignal(controller.finished, timeout=5000) as second:
        assert controller.maybe_run()
    assert [n.text for n in second.args[1]] == ["Señal bajista: Nueva"]
    settings.set_daily_scan_enabled(False)
    now[0] = datetime(2025, 3, 11, 22, 0, tzinfo=UTC)
    assert not controller.maybe_run()


def test_offline_scan_does_not_mark_session(qtbot: QtBot, settings: SettingsService,
                                            market: MarketDataService,
                                            scans: FakeScans) -> None:  # fmt: skip
    controller = DailyScanController(settings, market, lambda: ["AAA"], clock=lambda: SATURDAY)
    scans.results = [ScanResult([], ["AAA: sin conexión"])]
    with qtbot.waitSignal(controller.finished, timeout=5000):
        controller.maybe_run()
    assert settings.scan_snapshot() is None
    assert not DailyScanController(settings, market, list, clock=lambda: SATURDAY).maybe_run()


def test_window_records_and_notifies(
    qtbot: QtBot, settings: SettingsService, market: MarketDataService, scans: FakeScans
) -> None:
    alerts = AlertService(open_database(":memory:"), market, clock=lambda: SATURDAY)
    win = MainWindow(settings, market_service=market, alert_service=alerts)
    qtbot.addWidget(win)
    assert win.daily_scan is not None
    win.daily_scan._symbols = lambda: ["AAA"]
    win.daily_scan._clock = lambda: SATURDAY
    settings.set_scan_snapshot({"session": "2025-03-06", "items": {"AAA": []}})
    scans.results = [ScanResult([make_row()])]
    assert not win.last_daily_scan_action.isEnabled()
    with qtbot.waitSignal(win.daily_scan.finished, timeout=5000):
        win.daily_scan.maybe_run()
    events = alerts.events()
    assert len(events) == 3  # 1 signal + 2 patterns, all new against an empty snapshot
    assert events[0].description == "AAA · escaneo diario"
    assert "Escaneo diario: 3 novedades en 1 activos" in win.statusBar().currentMessage()
    assert win.last_daily_scan_action.isEnabled()
    win.open_last_daily_scan()
    assert win._scanner_dialog.table.rowCount() == 1
    win.daily_scan_action.setChecked(False)
    assert settings.daily_scan_enabled() is False
    alerts.close()
