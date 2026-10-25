"""Exhaustion record compared across several assets (service, exports and window)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.analysis.exhaustion import DOWN, UP, Params, history, record_reading
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.exhaustion_compare import (
    READING_LABELS,
    analyse_bars,
    compare_exhaustion,
    comparison_csv,
    comparison_html,
)
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.ui.exhaustion_compare_dialog import ExhaustionCompareDialog
from tests.synthetic import FakeYahooClient
from tests.unit.test_exhaustion import bars_from


def long_series(seed: int = 11, n: int = 1500) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n)))
    bars = bars_from(close, rng.integers(500_000, 2_000_000, n).astype(float))
    bars["adj_close"] = bars["close"]
    bars["dividends"] = 0.0
    bars["splits"] = 0.0
    return bars[["open", "high", "low", "close", "adj_close", "volume", "dividends", "splits"]]


@pytest.fixture
def market(conn: sqlite3.Connection) -> MarketDataService:
    client = FakeYahooClient(long_series())
    client.known = {"AAA", "BBB"}
    return MarketDataService(YahooFinanceProvider(client), conn,
                             lambda: datetime(2026, 1, 10, 12, tzinfo=UTC))  # fmt: skip


def test_each_asset_gets_both_records_and_readings() -> None:
    bars = long_series()
    row = analyse_bars("AAA", bars)
    assert row.rises.outcomes == history(bars, UP)
    assert row.falls.outcomes == history(bars, DOWN)
    assert row.rises.reading == record_reading(row.rises.outcomes)
    assert row.rises.at(20) is not None and row.rises.at(20).events > 0  # type: ignore[union-attr]
    assert row.bars == len(bars) and row.last == bars.index[-1].date()
    with pytest.raises(ValueError):
        analyse_bars("AAA", bars.iloc[:50])


def test_thresholds_change_the_record() -> None:
    bars = long_series()
    loose = analyse_bars("AAA", bars, Params(threshold=2))
    strict = analyse_bars("AAA", bars, Params(threshold=5))
    assert loose.rises.at(20).events >= strict.rises.at(20).events  # type: ignore[union-attr]


def test_comparison_reports_problems_and_cancels(market: MarketDataService) -> None:
    result = compare_exhaustion(market, ["aaa", "BBB", "ZZZ", "AAA"])
    assert [r.symbol for r in result.rows] == ["AAA", "BBB"]
    assert len(result.problems) == 1 and result.problems[0].startswith("ZZZ")
    groups = result.by_reading(UP)
    assert sum(len(v) for v in groups.values()) == 2
    stopped = compare_exhaustion(market, ["AAA", "BBB"], cancelled=lambda: True)
    assert stopped.cancelled and not stopped.rows


def test_exports_are_safe_and_complete(market: MarketDataService) -> None:
    result = compare_exhaustion(market, ["AAA", "BBB"])
    result.problems.append('=HYPERLINK("x") <script>alert(1)</script>')
    text = comparison_csv(result)
    header = text.splitlines()[0].split(",")
    assert header[:5] == ["ticker", "desde", "hasta", "sesiones", "situacion_actual"]
    assert "subidas_casos_20" in header and "bajadas_lectura" in header
    assert len(text.splitlines()) == 3
    html = comparison_html(result, datetime(2026, 1, 10, 12))
    assert "<script>alert" not in html
    assert "Agotamiento de las subidas" in html and "AAA" in html
    assert "no una predicción" in html
    labels = {READING_LABELS[r.rises.reading][UP] for r in result.rows}
    assert all(label in html for label in labels)


def test_window_runs_and_exports(qtbot: QtBot, market: MarketDataService,
                                 tmp_path: Path) -> None:  # fmt: skip
    dialog = ExhaustionCompareDialog(market, ["AAA", "BBB", "ZZZ"])
    qtbot.addWidget(dialog)
    dialog.open_after_export = False
    dialog.run()
    qtbot.waitUntil(lambda: dialog.comparison is not None, timeout=20000)
    assert dialog.table.rowCount() == 2
    assert "ZZZ" in dialog.status.text()
    assert "Agotamiento de las subidas" in dialog.summary.text()
    dialog.horizon.setCurrentIndex(1)  # 10 sessions
    assert dialog.table.rowCount() == 2
    dialog.export("csv", tmp_path / "comp")
    assert (tmp_path / "comp.csv").read_text(encoding="utf-8-sig").startswith("ticker")
    dialog.export("html", tmp_path / "comp.html")
    assert "Señales de agotamiento" in (tmp_path / "comp.html").read_text(encoding="utf-8")
    seen: list[str] = []
    dialog.symbol_activated.connect(seen.append)
    dialog._activate(0, 0)
    assert seen and seen[0] in ("AAA", "BBB")
