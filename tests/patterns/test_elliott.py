from __future__ import annotations

import itertools

import numpy as np
import pytest

from analisis_acciones.patterns.elliott import CORRECTION, IMPULSE, analyze, find_impulses
from analisis_acciones.patterns.zigzag import HIGH, LOW, auto_threshold, zigzag
from tests.synthetic import path, synthetic_daily

LEG = 10  # bars per leg in tests.synthetic.path


IMPULSE_THEN_ABC = (100, 120, 108, 150, 135, 165, 148, 158, 138, 150)


def test_zigzag_finds_turning_points() -> None:
    bars = path(*IMPULSE_THEN_ABC)
    pivots = zigzag(bars["high"], bars["low"], 0.05)
    assert [p.price for p in pivots] == pytest.approx(IMPULSE_THEN_ABC)
    assert [p.index for p in pivots] == [k * LEG for k in range(len(IMPULSE_THEN_ABC))]
    assert [p.kind for p in pivots[:2]] == [LOW, HIGH]
    assert all(p.confirmed for p in pivots[:-1]) and not pivots[-1].confirmed


def test_zigzag_ignores_moves_below_threshold() -> None:
    bars = path(100, 110, 108, 125, 100)  # the 110 -> 108 dip is under 5 %
    pivots = zigzag(bars["high"], bars["low"], 0.05)
    assert [p.price for p in pivots] == pytest.approx([100, 125, 100])


def test_zigzag_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError):
        zigzag(np.array([1.0]), np.array([1.0]), 0)


def test_past_impulse_and_correction_found() -> None:
    result = analyze(path(*IMPULSE_THEN_ABC), threshold=0.05)
    impulse, correction = result.past
    assert impulse.kind == IMPULSE and impulse.direction == 1
    assert [p.price for p in impulse.pivots] == pytest.approx([100, 120, 108, 150, 135, 165])
    assert impulse.labels == ("0", "1", "2", "3", "4", "5")
    assert impulse.valid and len(impulse.rules) == 4
    assert impulse.score == 1.0  # every Fibonacci guideline holds for this path
    assert correction.kind == CORRECTION and correction.direction == -1
    assert [p.price for p in correction.pivots] == pytest.approx([165, 148, 158, 138])
    assert correction.labels == ("", "A", "B", "C")


def test_current_count_after_correction() -> None:
    result = analyze(path(*IMPULSE_THEN_ABC), threshold=0.05)
    # Only "start of a falling impulse" fits the last three points (158, 138, 150).
    (count,) = result.current
    assert count.current and count.kind == IMPULSE and count.direction == -1
    assert "onda 2" in count.stage
    assert count.invalidation == pytest.approx(158)
    assert [t.price for t in count.targets][-1] == pytest.approx(150 - 1.618 * 20)


def test_wave_three_in_progress_targets() -> None:
    result = analyze(path(100, 120, 108, 150), threshold=0.05)
    assert result.past == []
    count = result.current[0]
    assert "onda 3" in count.stage
    assert count.invalidation == pytest.approx(120)  # wave 4 may not go below wave 1's top
    assert count.targets[0].price == pytest.approx(108 + 1.618 * 20)
    assert count.guidelines and all(g.wave < 3 for g in count.guidelines)


def test_wave_four_overlap_is_not_an_impulse() -> None:
    bars = path(100, 120, 108, 150, 118, 165, 140)
    pivots = zigzag(bars["high"], bars["low"], 0.05)
    assert find_impulses([p for p in pivots if p.confirmed]) == []


def test_shortest_wave_three_is_not_an_impulse() -> None:
    bars = path(100, 130, 115, 140, 133, 170, 150)
    pivots = zigzag(bars["high"], bars["low"], 0.04)
    assert find_impulses([p for p in pivots if p.confirmed]) == []


def test_falling_impulse_is_mirrored() -> None:
    mirrored = [300 - p for p in (100, 120, 108, 150, 135, 165)] + [180]
    result = analyze(path(*mirrored), threshold=0.05)
    impulse = result.past[0]
    assert impulse.direction == -1 and impulse.valid
    assert [p.price for p in impulse.pivots] == pytest.approx(mirrored[:6])


def test_analyze_real_like_series_is_consistent() -> None:
    bars = synthetic_daily(sessions=600)
    result = analyze(bars)
    assert 0.02 <= result.threshold <= 0.30
    assert result.threshold == pytest.approx(auto_threshold(bars))
    for count in result.past + result.current:
        assert count.valid
        kinds = [p.kind for p in count.pivots]
        assert all(a != b for a, b in itertools.pairwise(kinds))
    impulses = [c for c in result.past if c.kind == IMPULSE]
    for a, b in itertools.pairwise(impulses):
        assert a.end <= b.start  # completed impulses never overlap
