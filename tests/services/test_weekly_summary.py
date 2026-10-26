"""Weekly exhaustion summary on SYNTHETIC series."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.analysis.exhaustion import UP, signal_series
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.weekly_summary import week_signals, weekly_html, weekly_summary
from analisis_acciones.ui.weekly_summary_dialog import WeeklySummaryDialog
from tests.synthetic import FakeYahooClient
from tests.unit.test_exhaustion import bars_from, rally


def rally_bars() -> pd.DataFrame:
    """The rally cut three bars after its exhaustion signs start (a "this week" case)."""
    close = rally()
    bars = bars_from(close, np.full(len(close), 1e6))
    bars["adj_close"] = bars["close"]
    bars["dividends"] = 0.0
    bars["splits"] = 0.0
    bars = bars[["open", "high", "low", "close", "adj_close", "volume", "dividends", "splits"]]
    first = int(np.flatnonzero(signal_series(bars).to_numpy() > 0)[-20])
    start = first
    signals = signal_series(bars).to_numpy()
    while start > 0 and signals[start - 1] > 0:
        start -= 1
    return bars.iloc[: start + 3]


def test_signals_that_started_this_week() -> None:
    bars = rally_bars()
    today = bars.index[-1].date()
    found = week_signals("RUN", bars, today)
    assert found and all(s.direction == UP for s in found)
    signals = signal_series(bars)
    for s in found:
        assert today - timedelta(days=6) <= s.started <= today
        i = bars.index.get_loc(pd.Timestamp(s.started))
        assert signals.iloc[i] > 0 and signals.iloc[i - 1] <= 0  # a run starts there
    assert found[0].week_change_pct is not None and found[0].week_change_pct > 0
    with pytest.raises(ValueError):
        week_signals("RUN", bars.iloc[:50], today)


@pytest.fixture
def market(conn: sqlite3.Connection) -> MarketDataService:
    client = FakeYahooClient(rally_bars())
    client.known = {"RUN"}
    return MarketDataService(YahooFinanceProvider(client), conn,
                             lambda: datetime(2030, 1, 1, tzinfo=UTC))  # fmt: skip


def test_summary_and_report(market: MarketDataService) -> None:
    today = rally_bars().index[-1].date()
    summary = weekly_summary(market, ["RUN", "ZZZ"], today)
    assert summary.signals and summary.signals[0].symbol == "RUN"
    assert summary.problems and summary.problems[0].startswith("ZZZ")
    assert summary.analysed == 1
    html = weekly_html(summary, datetime(2030, 1, 1, 9))
    assert "Resumen semanal de agotamiento" in html and "RUN" in html
    assert "no una\npredicción" in html or "no una predicción" in html
    assert "<script" not in html
    early = weekly_summary(market, ["RUN"], date(2000, 1, 1))  # before the data starts
    assert not early.signals and early.problems  # too few sessions up to that date


def test_window_lists_and_exports(qtbot: QtBot, market: MarketDataService,
                                  tmp_path: Path) -> None:  # fmt: skip
    today = rally_bars().index[-1].date()
    dialog = WeeklySummaryDialog(market, ["RUN"], lambda: today)
    qtbot.addWidget(dialog)
    dialog.open_after_export = False
    dialog.run()
    qtbot.waitUntil(lambda: dialog.summary is not None, timeout=10000)
    assert dialog.table.rowCount() >= 1
    assert dialog.table.item(0, 0).text() == "RUN"  # type: ignore[union-attr]
    dialog.export("html", tmp_path / "semana")
    assert "RUN" in (tmp_path / "semana.html").read_text(encoding="utf-8")
