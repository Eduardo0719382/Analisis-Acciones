from __future__ import annotations

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.models.market import BarSeries, Interval
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.ui import strings
from analisis_acciones.ui.backtest_dialog import BacktestDialog, run_strategy
from analisis_acciones.ui.main_window import MainWindow
from analisis_acciones.ui.theme import DARK
from tests.analysis.test_rules import make_bars

SERIES = BarSeries(
    "TEST",
    Interval.D1,
    make_bars(
        np.concatenate(
            [np.linspace(100, 60, 80), np.linspace(60, 130, 80), np.linspace(130, 80, 80)]
        )
    ),
    "synthetic",
)


def test_dialog_runs_and_shows_results(qtbot: QtBot) -> None:
    dialog = BacktestDialog(SERIES, "TEST · Diario", DARK)
    qtbot.addWidget(dialog)
    assert "EMA 20" in dialog.rules_label.text()
    dialog.run()
    qtbot.waitUntil(lambda: dialog.outcome is not None, timeout=10000)
    outcome = dialog.outcome
    assert outcome is not None
    expected = run_strategy(SERIES, "ema_cross", {"fast": 20, "slow": 50},
                            outcome.result.config)  # fmt: skip
    assert outcome.stats == expected.stats  # UI shows exactly the engine's numbers
    assert dialog.stat_labels["trades"].text() == str(expected.stats.trades)
    rows = expected.stats.trades + (1 if expected.result.open_trade else 0)
    assert dialog.trades.rowCount() == rows


def test_invalid_parameters_reported(qtbot: QtBot) -> None:
    dialog = BacktestDialog(SERIES, "TEST", DARK)
    qtbot.addWidget(dialog)
    dialog.editors["fast"].setValue(60)
    dialog.run()
    qtbot.waitUntil(lambda: bool(dialog.error.text()), timeout=10000)
    assert "rápida" in dialog.error.text()


def test_rsi_strategy_switch(qtbot: QtBot) -> None:
    dialog = BacktestDialog(SERIES, "TEST", DARK)
    qtbot.addWidget(dialog)
    dialog.strategy.setCurrentIndex(dialog.strategy.findData("rsi_reversion"))
    assert set(dialog.editors) == {"period", "low", "high"}
    assert "RSI 14" in dialog.rules_label.text()


def test_menu_requires_open_series(
    qtbot: QtBot, settings: SettingsService, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        "analisis_acciones.ui.main_window.QMessageBox.information",
        lambda *args: shown.append(args[2]),
    )
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.backtest_action.trigger()
    assert shown == [strings.BT_NEED_DATA]
