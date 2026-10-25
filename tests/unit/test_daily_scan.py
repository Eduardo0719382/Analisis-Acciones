from __future__ import annotations

from datetime import UTC, date, datetime

from analisis_acciones.services.daily_scan import (
    find_novelties,
    is_due,
    make_snapshot,
    notable_items,
    previous_items,
    session_of,
)
from analisis_acciones.services.scanner import BREAKOUT_NOTE, FORMING_NOTE, PatternNote, ScanResult
from analisis_acciones.services.settings_service import SettingsService
from tests.unit.test_scan_report import make_row

# Friday 2025-03-07 21:00 UTC = 16:00 New York: the session has not settled yet.
FRIDAY_CLOSE = datetime(2025, 3, 7, 21, 0, tzinfo=UTC)
FRIDAY_NIGHT = datetime(2025, 3, 7, 23, 0, tzinfo=UTC)
SATURDAY = datetime(2025, 3, 8, 15, 0, tzinfo=UTC)


def test_session_and_due() -> None:
    assert session_of(FRIDAY_CLOSE) == date(2025, 3, 6)
    assert session_of(FRIDAY_NIGHT) == date(2025, 3, 7)
    assert session_of(SATURDAY) == date(2025, 3, 7)
    assert is_due(SATURDAY, None) and is_due(SATURDAY, {"session": 5})
    assert is_due(SATURDAY, {"session": "2025-03-06"})
    assert not is_due(SATURDAY, {"session": "2025-03-07"})


def test_first_sight_is_baseline_then_only_new_items() -> None:
    row = make_row(pattern_notes=(PatternNote("Doble suelo", FORMING_NOTE, 1),))
    assert find_novelties({}, ScanResult([row])) == []
    snapshot = make_snapshot(ScanResult([row]), date(2025, 3, 6))
    assert snapshot["session"] == "2025-03-06"

    later = make_row(bearish=("Condición de sobrecompra (RSI)",),
                     pattern_notes=(PatternNote("Doble suelo", BREAKOUT_NOTE, 1),))  # fmt: skip
    found = find_novelties(previous_items(snapshot), ScanResult([later]))
    assert {(n.text, n.bias) for n in found} == {
        ("Señal bajista: Condición de sobrecompra (RSI)", -1),
        ("Patrón Doble suelo (ruptura)", 1),
    }
    assert all(n.symbol == "AAA" and n.bar_date == date(2025, 3, 7) for n in found)


def test_snapshot_keeps_symbols_that_failed() -> None:
    first = make_snapshot(ScanResult([make_row("AAA"), make_row("BBB")]), date(2025, 3, 6))
    second = make_snapshot(ScanResult([make_row("AAA")], ["BBB: sin conexión"]),
                           date(2025, 3, 7), previous_items(first))  # fmt: skip
    assert set(second["items"]) == {"AAA", "BBB"}


def test_malformed_snapshot_is_ignored() -> None:
    assert previous_items({"items": "x"}) == {}
    assert previous_items({"items": {"AAA": "x", "BBB": [1, "a"]}}) == {"BBB": ["1", "a"]}
    assert previous_items(None) == {}


def test_notable_items_keep_pattern_state() -> None:
    items = notable_items(make_row())
    assert items["Patrón Doble suelo (ruptura)"] == 1
    assert items["Patrón Triángulo simétrico (en formación)"] == 0
    assert items["Señal alcista: Tendencia alcista detectada"] == 1


def test_exhaustion_announced_only_where_it_anticipated_turns() -> None:
    from analisis_acciones.analysis.exhaustion import READ_NO_EDGE, READ_USEFUL

    proven = make_row("AAA", exhaustion=4, exhaustion_total=6, exhaustion_reading=READ_USEFUL)
    unproven = make_row("BBB", exhaustion=-3, exhaustion_total=6, exhaustion_reading=READ_NO_EDGE)
    assert any("agotamiento de la subida" in t for t in notable_items(proven, proven_only=True))
    assert any("han precedido bajadas" in t for t in notable_items(proven, proven_only=True))
    assert not any("agotamiento" in t for t in notable_items(unproven, proven_only=True))
    assert any("agotamiento de la bajada" in t for t in notable_items(unproven))
    previous = {"AAA": [], "BBB": []}
    found = find_novelties(previous, ScanResult([proven, unproven]), proven_only=True)
    assert [(n.symbol, n.bias) for n in found if "agotamiento" in n.text] == [("AAA", -1)]
    found_all = find_novelties(previous, ScanResult([proven, unproven]))
    assert {n.symbol for n in found_all if "agotamiento" in n.text} == {"AAA", "BBB"}


def test_scan_row_carries_the_record_reading() -> None:
    from analisis_acciones.analysis.exhaustion import assess, record_reading
    from analisis_acciones.services.scanner import scan_bars
    from tests.unit.test_exhaustion import bars_from, rally

    bars = bars_from(rally())
    row = scan_bars("RUN", bars)
    assert row.exhaustion > 0
    assert row.exhaustion_reading == record_reading(assess(bars).outcomes)


def test_setting_defaults_to_proven_only(settings: SettingsService) -> None:
    assert settings.exhaustion_proven_only()
    settings.set_exhaustion_proven_only(False)
    assert not settings.exhaustion_proven_only()
