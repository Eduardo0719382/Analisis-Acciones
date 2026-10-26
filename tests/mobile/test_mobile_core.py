"""Phone logic (no UI toolkit) on SYNTHETIC data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.alerts.rules import AlertKind
from analisis_acciones.analysis.exhaustion import assess
from analisis_acciones.mobile.chart import PERIODS, geometry
from analisis_acciones.mobile.session import (
    EXAMPLES,
    MobileSession,
    exhaustion_view,
    price_text,
)
from analisis_acciones.mobile.updates import (
    RELEASE_API,
    AvailableBuild,
    BuildInfo,
    current_build,
    latest_build,
    newer_than,
)
from tests.synthetic import FakeYahooClient, synthetic_daily
from tests.unit.test_exhaustion import bars_from, rally

NOW = datetime(2026, 1, 10, 12, tzinfo=UTC)


@pytest.fixture
def session(tmp_path: Path) -> MobileSession:
    client = FakeYahooClient(synthetic_daily(sessions=400))
    client.known = {"TEST", "AAA"}
    client.search_payload = [{"symbol": "AAA", "longname": "Aaa Inc.", "quoteType": "EQUITY"}]
    s = MobileSession(tmp_path / "datos", client, clock=lambda: NOW)
    yield s
    s.close()


def test_watchlist_rows_and_examples(session: MobileSession) -> None:
    assert session.symbols() == []
    assert session.add("test") and not session.add("TEST")
    session.add("ZZZ")
    rows = {r.symbol: r for r in session.rows()}
    assert rows["TEST"].error is None and rows["TEST"].price != "—"
    assert rows["ZZZ"].error is not None  # unknown: shown with its reason, not invented
    assert session.add_example("cripto") == len(EXAMPLES["cripto"])
    assert "BTC-USD" in session.symbols()
    session.remove("ZZZ")
    assert "ZZZ" not in session.symbols()
    assert [r.symbol for r in session.search("aaa")] == ["AAA"]


def test_asset_view(session: MobileSession) -> None:
    view = session.asset("TEST")
    assert view.symbol == "TEST" and view.price != "—" and len(view.bars) == 400
    assert view.exhaustion.headline
    assert all(s.tone in ("up", "down", "flat") for s in view.signals)


def test_scan_cards(session: MobileSession) -> None:
    session.add("TEST")
    session.add("ZZZ")
    cards, problems = session.scan()
    assert [c.symbol for c in cards] == ["TEST"]
    assert cards[0].details[0][1].startswith("Cierre ")
    assert {tone for tone, _ in cards[0].details} <= {"", "up", "down"}
    assert problems and problems[0].startswith("ZZZ")


def test_alerts_on_the_phone(session: MobileSession) -> None:
    rule = session.add_alert("TEST", AlertKind.RSI_BELOW, 30)
    assert rule.params == {"period": 14, "value": 30}
    session.add_alert("TEST", AlertKind.PRICE_ABOVE, 1.0)
    summary = session.check_alerts()
    assert summary.checked == 2 and any("Cierre" in e.description for e in summary.events)
    assert session.history()
    rows = session.alert_rows()
    session.toggle_alert(rows[0].id, False)
    assert not session.alert_rows()[0].enabled
    exported = session.export_alerts()
    session.delete_alert(rows[0].id)
    assert session.import_alerts(exported).added == 1


def test_exhaustion_view_words() -> None:
    view = exhaustion_view(assess(bars_from(rally())))
    assert "La subida muestra señales de agotamiento" in view.headline
    assert view.tone == "down" and len(view.conditions) == 6 and len(view.record) == 2
    assert "Puede continuar" in view.headline and view.reading
    flat = exhaustion_view(assess(bars_from(np.full(50, 10.0))))
    assert flat.tone == "flat" and "120" in flat.headline


def test_price_text_keeps_small_coins_readable() -> None:
    assert price_text(64250.5) == "64.250,50"
    assert price_text(0.5) == "0,5000"
    assert price_text(0.00001234) == "0,000012"
    assert price_text(None) == "—"


def test_chart_geometry() -> None:
    bars = synthetic_daily(sessions=400)
    g = geometry(bars, 360, 240, "3M")
    assert len(g.candles) == PERIODS["3M"]
    assert all(0 <= c.high <= c.top <= c.bottom <= c.low + 1 <= 240 * 0.78 + 1 for c in g.candles)
    assert g.sma20 and g.sma50 and len(g.volume) == len(g.candles)
    assert all(240 * 0.82 - 0.01 <= v[2] <= 240 for v in g.volume)
    assert g.candles[0].x < g.candles[-1].x <= 360
    assert g.last == f"{bars.index[-1]:%d/%m/%Y}"
    long = geometry(synthetic_daily(sessions=1500), 360, 240, "5A")
    assert len(long.candles) <= 270  # merged into weeks so each candle stays visible
    assert geometry(pd.DataFrame(), 360, 240).candles == []


def _release(*assets: dict[str, object]) -> bytes:
    return json.dumps({"tag_name": "movil", "assets": list(assets)}).encode()


def test_update_check() -> None:
    url = "https://github.com/Eduardo0719382/Analisis-Acciones/releases/download/movil/"
    payload = _release(
        {"name": "AnalisisAcciones-0.1.0-build41.apk", "browser_download_url": url + "a.apk",
         "size": 52_428_800},
        {"name": "AnalisisAcciones-0.1.0-build42.apk", "browser_download_url": url + "b.apk",
         "size": 52_428_800},
        {"name": "AnalisisAcciones-0.1.0-build99.apk",
         "browser_download_url": "https://evil.example/x.apk"},  # not GitHub: ignored
        {"name": "otro.apk", "browser_download_url": url + "c.apk"},
    )  # fmt: skip
    seen: list[str] = []

    def fetch(u: str) -> bytes:
        seen.append(u)
        return payload

    found = latest_build(fetch)
    assert seen == [RELEASE_API]
    assert found == AvailableBuild("0.1.0", 42, url + "b.apk", 50.0)
    assert newer_than(BuildInfo("0.1.0", 41), found)
    assert not newer_than(BuildInfo("0.1.0", 42), found)
    assert latest_build(lambda u: _release()) is None
    assert current_build().build == 0  # development copy: no build_info.json
