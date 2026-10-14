from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scanner import run_scan, scan_bars
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, path, synthetic_daily


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    client = FakeYahooClient(synthetic_daily(sessions=400))
    client.known = {"AAA", "BBB"}
    fixed = datetime(2025, 9, 1, 23, 0, tzinfo=UTC)
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: fixed)  # fmt: skip
    yield service
    service.close()


def test_scan_row_describes_last_bar() -> None:
    bars = synthetic_daily(sessions=400)
    row = scan_bars("AAA", bars)
    close = bars["close"]
    assert row.close == pytest.approx(close.iloc[-1])
    assert row.change_pct == pytest.approx((close.iloc[-1] / close.iloc[-2] - 1) * 100)
    assert row.rsi14 is not None and 0 <= row.rsi14 <= 100
    if row.support_pct is not None:
        assert row.support_pct > 0
    if row.resistance_pct is not None:
        assert row.resistance_pct >= 0


def test_scan_reports_forming_pattern_and_recent_breakout() -> None:
    # Long flat lead-in so every indicator has data, then a double top that breaks down.
    lead = [100.0 + (i % 2) * 0.5 for i in range(8)]
    bars = path(*lead, 130, 115, 129.5, 108)
    row = scan_bars("XYZ", bars)
    assert "Doble techo (ruptura reciente)" in row.patterns
    assert "Doble techo" in row.bearish


def test_short_history_is_rejected() -> None:
    with pytest.raises(ValueError):
        scan_bars("AAA", synthetic_daily(sessions=30))


def test_run_scan_collects_rows_and_problems(market: MarketDataService) -> None:
    seen: list[str] = []
    result = run_scan(market, ["aaa", "BBB", "AAA", "ZZZ", " "],
                      progress=lambda _d, _t, s: seen.append(s))  # fmt: skip
    assert [r.symbol for r in result.rows] == ["AAA", "BBB"]
    assert seen == ["AAA", "BBB", "ZZZ"]
    assert len(result.problems) == 1 and result.problems[0].startswith("ZZZ")
