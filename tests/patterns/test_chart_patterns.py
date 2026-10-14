from __future__ import annotations

import pytest

from analisis_acciones.patterns.chart_patterns import (
    CONFIRMED,
    FORMING,
    INVALIDATED,
    TARGET_HIT,
    analyze,
    find_patterns,
)
from analisis_acciones.patterns.levels import Level, support_resistance
from analisis_acciones.patterns.zigzag import HIGH, LOW, Pivot, zigzag
from tests.synthetic import path, synthetic_daily

TOL = 0.02


def patterns_for(*prices: float, threshold: float = 0.05):  # type: ignore[no-untyped-def]
    bars = path(*prices)
    return find_patterns(bars, zigzag(bars["high"], bars["low"], threshold), TOL)


def by_name(patterns, name):  # type: ignore[no-untyped-def]
    found = [p for p in patterns if p.name == name]
    assert found, f"{name} not found in {[p.name for p in patterns]}"
    return found[0]


def test_double_top_confirmed_and_target_reached() -> None:
    top = by_name(patterns_for(100, 130, 115, 129.5, 112, 98), "Doble techo")
    assert top.bias == -1 and top.labels == ("T1", "", "T2")
    assert [p.price for p in top.points] == pytest.approx([130, 115, 129.5])
    assert top.breakout is not None and 30 < top.breakout <= 40
    assert top.targets[0].price == pytest.approx(115 - 15)  # neckline − height
    assert top.invalidation == pytest.approx(130)
    assert top.status == TARGET_HIT
    assert all(c.passed for c in top.checks)


def test_double_bottom_invalidated() -> None:
    bottom = by_name(patterns_for(130, 100, 115, 100.5, 118, 95), "Doble suelo")
    assert bottom.bias == 1 and bottom.breakout is not None
    assert bottom.targets[0].price == pytest.approx(130)
    # Price turned down from 118 and broke the lows before reaching 130.
    assert bottom.status == INVALIDATED


def test_head_and_shoulders_confirmed() -> None:
    hs = by_name(patterns_for(100, 120, 110, 135, 111, 121, 90), "Hombro-cabeza-hombro")
    assert [p.price for p in hs.points] == pytest.approx([120, 110, 135, 111, 121])
    assert hs.labels == ("HI", "", "C", "", "HD")
    assert hs.status == CONFIRMED  # target (~87) not reached at 90
    assert hs.targets[0].price == pytest.approx(86.9, abs=0.3)
    assert hs.invalidation == pytest.approx(121)


def test_inverse_head_and_shoulders() -> None:
    hs = by_name(patterns_for(150, 120, 130, 105, 129, 119, 150),
                 "Hombro-cabeza-hombro invertido")  # fmt: skip
    assert hs.bias == 1 and hs.breakout is not None


def test_ascending_triangle_forming() -> None:
    tri = by_name(patterns_for(100, 120, 105, 120.5, 110, 120.2, 114), "Triángulo ascendente")
    assert tri.status == FORMING and tri.breakout is None
    assert len(tri.lines) == 2
    assert tri.targets[0].label == "Objetivo si rompe al alza"


def test_bull_flag_breakout() -> None:
    flag = by_name(patterns_for(100, 112, 108, 111.5, 109, 120, threshold=0.02), "Bandera alcista")
    assert flag.breakout is not None and flag.status == CONFIRMED
    assert flag.invalidation == pytest.approx(108)


def test_old_unconfirmed_pattern_is_dropped() -> None:
    # 130/129.5 double top never broke 115, and later structures followed.
    patterns = patterns_for(100, 130, 115, 129.5, 117, 160, 140, 175)
    assert not [p for p in patterns if p.name == "Doble techo" and p.start == 10]


def test_support_resistance_groups_touches() -> None:
    pivots = [Pivot(0, 100, LOW), Pivot(10, 120, HIGH), Pivot(20, 101, LOW),
              Pivot(30, 119.5, HIGH), Pivot(40, 108, LOW), Pivot(50, 120.4, HIGH),
              Pivot(60, 140, HIGH)]  # fmt: skip
    levels = support_resistance(pivots, close=110, tolerance=0.01)
    assert [lv.touches for lv in levels] == [2, 3]
    support, resistance = levels
    assert support.price == pytest.approx(100.5) and support.role(110) == "support"
    assert resistance.price == pytest.approx((120 + 119.5 + 120.4) / 3)
    assert resistance.role(110) == "resistance" and (resistance.first, resistance.last) == (10, 50)
    assert isinstance(resistance, Level)


def test_analyze_synthetic_is_consistent() -> None:
    result = analyze(synthetic_daily(sessions=1200, seed=3))
    assert 0.005 <= result.tolerance <= 0.05
    assert all(lv.touches >= 2 for lv in result.levels)
    for pattern in result.patterns:
        assert all(c.passed for c in pattern.checks)
        assert pattern.status in {FORMING, CONFIRMED, TARGET_HIT, INVALIDATED}
        assert (pattern.breakout is None) == (pattern.status == FORMING)
    total, hit, failed = result.track_record()
    assert total == hit + failed
