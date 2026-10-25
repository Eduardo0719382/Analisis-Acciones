"""Chart renderer failure -> page reloaded and redrawn; crash guard bookkeeping."""

from __future__ import annotations

import faulthandler
import os
import signal
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.app import crash_guard, error_handler
from analisis_acciones.app.crash_guard import SessionGuard
from analisis_acciones.charts import chart_widget
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient
from tests.ui.test_projection_ui import state


@pytest.fixture
def window(qtbot: QtBot, settings: SettingsService) -> Iterator[MainWindow]:
    client = FakeYahooClient()
    market = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                               clock=lambda: datetime(2025, 3, 3, 23, 0, tzinfo=UTC))  # fmt: skip
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    win.show()
    assert win.market is not None
    with qtbot.waitSignal(win.market.load_finished, timeout=5000):
        win.open_symbol("TEST")
    qtbot.waitUntil(lambda: win.chart.is_loaded, timeout=20000)
    yield win
    market.close()


def test_chart_recovers_after_renderer_dies(qtbot: QtBot, window: MainWindow) -> None:
    panel = window.projection_panel
    panel.horizon.setValue(10)
    with qtbot.waitSignal(panel.projection_ready, timeout=20000):
        panel.run()
    qtbot.waitUntil(lambda: state(qtbot, window)["overlayGroups"].get("projection") == 5,
                    timeout=10000)  # fmt: skip
    before = state(qtbot, window)
    assert before["bars"] > 0
    pid = window.chart.view.page().renderProcessPid()
    if pid <= 0 or pid == os.getpid():
        pytest.skip("renderer runs in-process here")
    with qtbot.waitSignal(window.chart.view.page().renderProcessTerminated, timeout=10000):
        os.kill(pid, signal.SIGTERM)
    qtbot.waitUntil(lambda: window.chart.is_loaded and window.chart.showing_chart, timeout=20000)
    qtbot.waitUntil(lambda: state(qtbot, window).get("bars") == before.get("bars")
                    and state(qtbot, window)["overlayGroups"].get("projection") == 5,
                    timeout=20000)  # fmt: skip


def test_chart_gives_up_after_repeated_failures(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    reloads: list[int] = []
    monkeypatch.setattr(window.chart, "_reload_page", lambda: reloads.append(1))
    for _ in range(chart_widget.MAX_RECOVERIES + 1):
        window.chart._on_render_crash("crashed", 1)
    qtbot.waitUntil(lambda: len(reloads) == chart_widget.MAX_RECOVERIES, timeout=5000)
    assert "Gráficos compatibles" in window.chart.message.text()
    assert not window.chart.showing_chart


def test_session_guard_detects_unclean_exits(tmp_path: Path) -> None:
    guard = SessionGuard(tmp_path)
    first = guard.begin()
    assert not first.previous_unclean and not first.software_rendering
    guard.end()
    assert not guard.begin().previous_unclean  # clean exit before
    second = guard.begin()  # no end(): the previous run "crashed"
    assert second.previous_unclean and second.consecutive_unclean == 1
    assert not second.switched_to_software
    third = guard.begin()
    assert third.consecutive_unclean == 2 and third.switched_to_software
    assert third.software_rendering and guard.software_rendering
    guard.end()
    later = guard.begin()
    assert not later.previous_unclean and later.software_rendering  # the choice is kept
    guard.set_software_rendering(False)
    assert not guard.software_rendering


def test_software_rendering_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
    crash_guard.apply_software_rendering()
    crash_guard.apply_software_rendering()  # idempotent
    assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].split() == [
        "--no-sandbox",
        "--disable-gpu",
        "--disable-gpu-compositing",
    ]


def test_std_streams_for_pythonw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdout", None)
    monkeypatch.setattr("sys.stderr", None)
    crash_guard.ensure_std_streams()
    import sys

    print("sin consola")  # must not fail
    sys.stderr.write("x")
    assert sys.stdout is not None and sys.stderr is not None


def test_error_box_only_on_gui_thread_and_not_stacked(monkeypatch: pytest.MonkeyPatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.critical",
                        lambda _p, _t, text: shown.append(text))  # fmt: skip
    monkeypatch.setitem(error_handler._state, "last", 0.0)
    thread = threading.Thread(target=error_handler._show_error, args=("hilo",))
    thread.start()
    thread.join()
    assert shown == []  # never from a worker thread
    error_handler._show_error("uno")
    error_handler._show_error("dos")  # within the quiet period: logged only
    assert shown == ["uno"]


def test_thread_exceptions_are_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = crash_guard.install_diagnostics(tmp_path)
    assert path.exists()

    def boom() -> None:
        raise ValueError("fallo en hilo")

    thread = threading.Thread(target=boom, name="prueba")
    thread.start()
    thread.join()
    assert "Uncaught exception in thread prueba" in caplog.text
    faulthandler.disable()
    threading.excepthook = threading.__excepthook__
