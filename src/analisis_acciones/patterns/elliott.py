"""Rule-based Elliott wave counts on ZigZag pivots.

Elliott wave labelling is interpretive: the same chart usually admits several
valid counts, and the degree of the waves found depends on the ZigZag
threshold. This module therefore only reports counts that satisfy the three
classic hard rules, lists every rule and guideline it checked with the
measured value, and calls ongoing counts "possible".

Impulse (5 waves, points p0..p5), for a rising impulse:

* rule: wave 2 does not retrace beyond the start of wave 1 (p2 > p0);
* rule: wave 3 ends beyond the end of wave 1 (p3 > p1);
* rule: wave 4 does not enter wave 1's price territory (p4 > p1);
* rule: wave 3 is not the shortest of waves 1, 3 and 5.

Correction (A-B-C zigzag after an impulse, points p0..p3):

* rule: B does not go beyond the start of A;
* rule: C goes beyond the end of A.

Guidelines (Fibonacci ratios, alternation) only affect the score. A falling
impulse is the mirror image. Lengths are price differences.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from analisis_acciones.patterns.zigzag import LOW, Pivot, auto_threshold, zigzag

IMPULSE, CORRECTION = "impulse", "correction"
IMPULSE_LABELS = ("0", "1", "2", "3", "4", "5")
CORRECTION_LABELS = ("", "A", "B", "C")
MAX_PAST = 12
MAX_CURRENT = 3


@dataclass(frozen=True)
class Check:
    text: str
    passed: bool
    detail: str
    wave: int = 0  # last wave the check depends on


@dataclass(frozen=True)
class Target:
    label: str
    price: float


@dataclass(frozen=True)
class WaveCount:
    kind: str  # IMPULSE or CORRECTION
    direction: int  # +1 rising, -1 falling
    pivots: tuple[Pivot, ...]
    labels: tuple[str, ...]
    rules: tuple[Check, ...]
    guidelines: tuple[Check, ...]
    current: bool = False
    stage: str = ""
    targets: tuple[Target, ...] = ()
    invalidation: float | None = None

    @property
    def valid(self) -> bool:
        return all(rule.passed for rule in self.rules)

    @property
    def score(self) -> float:
        if not self.guidelines:
            return 0.0
        return sum(g.passed for g in self.guidelines) / len(self.guidelines)

    @property
    def start(self) -> int:
        return self.pivots[0].index

    @property
    def end(self) -> int:
        return self.pivots[-1].index


@dataclass(frozen=True)
class ElliottResult:
    threshold: float
    pivots: list[Pivot]
    past: list[WaveCount] = field(default_factory=list)
    current: list[WaveCount] = field(default_factory=list)


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _ratio(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _within(value: float, low: float, high: float) -> bool:
    return low <= value <= high


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def impulse_checks(points: list[Pivot]) -> tuple[list[Check], list[Check]]:
    """Rules and guidelines applicable to the first ``len(points) - 1`` waves."""
    p = [pt.price for pt in points]
    d = 1 if points[0].kind == LOW else -1
    n = len(points) - 1
    w = [0.0] + [abs(p[k] - p[k - 1]) for k in range(1, n + 1)]
    rules: list[Check] = []
    guides: list[Check] = []
    if n >= 2:
        r2 = w[2] / w[1]
        rules.append(
            Check(
                "La onda 2 no retrocede más allá del inicio de la onda 1",
                d * (p[2] - p[0]) > 0,
                f"retrocede {_pct(r2)} de la onda 1",
                2,
            )
        )
        guides.append(
            Check(
                "Onda 2 retrocede 38,2–78,6 % de la onda 1 (habitual 50–61,8 %)",
                _within(r2, 0.382, 0.786),
                _pct(r2),
                2,
            )
        )
    if n >= 3:
        rules.append(
            Check(
                "La onda 3 supera el final de la onda 1",
                d * (p[3] - p[1]) > 0,
                f"onda 3 = {_ratio(w[3] / w[1])} × onda 1",
                3,
            )
        )
        guides.append(
            Check(
                "Onda 3 mide 1,382–2,618 × la onda 1 (habitual 1,618)",
                _within(w[3] / w[1], 1.382, 2.618),
                _ratio(w[3] / w[1]),
                3,
            )
        )
    if n >= 4:
        r4 = w[4] / w[3]
        rules.append(
            Check(
                "La onda 4 no entra en el territorio de la onda 1",
                d * (p[4] - p[1]) > 0,
                f"fin de la onda 4 {_num(p[4])} frente a fin de la onda 1 {_num(p[1])}",
                4,
            )
        )
        guides.append(
            Check("Onda 4 retrocede 23,6–50 % de la onda 3", _within(r4, 0.236, 0.5), _pct(r4), 4)
        )
        r2 = w[2] / w[1]
        guides.append(
            Check(
                "Alternancia: las ondas 2 y 4 tienen profundidad distinta",
                abs(r2 - r4) >= 0.15,
                f"onda 2 {_pct(r2)}, onda 4 {_pct(r4)}",
                4,
            )
        )
    if n >= 5:
        shortest = w[3] < w[1] and w[3] < w[5]
        rules.append(
            Check(
                "La onda 3 no es la más corta de las ondas 1, 3 y 5",
                not shortest,
                f"longitudes 1/3/5: {_num(w[1])} / {_num(w[3])} / {_num(w[5])}",
                5,
            )
        )
        guides.append(
            Check(
                "Onda 5 mide 0,618–1,618 × la onda 1",
                _within(w[5] / w[1], 0.618, 1.618),
                _ratio(w[5] / w[1]),
                5,
            )
        )
        guides.append(
            Check(
                "La onda 5 supera el final de la onda 3 (sin truncamiento)",
                d * (p[5] - p[3]) > 0,
                f"{_num(p[5])} frente a {_num(p[3])}",
                5,
            )
        )
        guides.append(
            Check(
                "La onda 3 es la más larga",
                w[3] >= max(w[1], w[5]),
                f"longitudes 1/3/5: {_num(w[1])} / {_num(w[3])} / {_num(w[5])}",
                5,
            )
        )
    return rules, guides


def correction_checks(points: list[Pivot]) -> tuple[list[Check], list[Check]]:
    p = [pt.price for pt in points]
    d = 1 if points[0].kind == LOW else -1
    n = len(points) - 1
    w = [0.0] + [abs(p[k] - p[k - 1]) for k in range(1, n + 1)]
    rules: list[Check] = []
    guides: list[Check] = []
    if n >= 2:
        rb = w[2] / w[1]
        rules.append(
            Check(
                "B no supera el inicio de A",
                d * (p[2] - p[0]) > 0,
                f"B retrocede {_pct(rb)} de A",
                2,
            )
        )
        guides.append(Check("B retrocede 38,2–78,6 % de A", _within(rb, 0.382, 0.786), _pct(rb), 2))
    if n >= 3:
        rules.append(
            Check(
                "C supera el final de A", d * (p[3] - p[1]) > 0, f"C = {_ratio(w[3] / w[1])} × A", 3
            )
        )
        guides.append(
            Check(
                "C mide 0,618–1,618 × A (habitual C ≈ A)",
                _within(w[3] / w[1], 0.618, 1.618),
                _ratio(w[3] / w[1]),
                3,
            )
        )
    return rules, guides


# ---------------------------------------------------------------------------
# Targets for counts in progress
# ---------------------------------------------------------------------------
def _impulse_projection(points: list[Pivot]) -> tuple[str, list[Target], float | None]:
    p = [pt.price for pt in points]
    d = 1 if points[0].kind == LOW else -1
    n = len(points) - 1
    w1 = abs(p[1] - p[0])

    def at(base: float, length: float, ratio: float) -> float:
        return base + d * ratio * length

    if n == 2:
        return (
            "Posible onda 2 (corrección) en formación; después vendría la onda 3",
            [
                Target("Onda 2: retroceso 50 %", at(p[1], w1, -0.5)),
                Target("Onda 2: retroceso 61,8 %", at(p[1], w1, -0.618)),
                Target("Onda 3 = 1,618 × onda 1", at(p[2], w1, 1.618)),
            ],
            p[0],
        )
    w3 = abs(p[3] - p[2])
    if n == 3:
        return (
            "Posible onda 3 en curso",
            [
                Target("Onda 3 = 1,618 × onda 1", at(p[2], w1, 1.618)),
                Target("Onda 3 = 2,618 × onda 1", at(p[2], w1, 2.618)),
            ],
            p[1],
        )
    if n == 4:
        targets = [
            Target("Onda 4: retroceso 38,2 % de la 3", at(p[3], w3, -0.382)),
            Target("Onda 5 = onda 1", at(p[4], w1, 1.0)),
            Target("Onda 5 = 0,618 × (ondas 1 a 3)", at(p[4], abs(p[3] - p[0]), 0.618)),
        ]
        if w3 < w1:  # wave 5 may not be longer than wave 3, or 3 would be the shortest
            targets.append(Target("Máximo de la onda 5 (no más larga que la 3)", at(p[4], w3, 1)))
        return "Posible onda 4 (corrección) en formación; después vendría la onda 5", targets, p[1]
    total = abs(p[5] - p[0])
    targets = [
        Target("Corrección A-B-C: retroceso 38,2 % del impulso", at(p[5], total, -0.382)),
        Target("Corrección A-B-C: retroceso 61,8 % del impulso", at(p[5], total, -0.618)),
    ]
    return (
        "Posible quinta onda en curso o impulso completado; después suele venir una "
        "corrección A-B-C",
        targets,
        None,
    )


def _correction_projection(
    points: list[Pivot], impulse_size: float
) -> tuple[str, list[Target], float | None]:
    p = [pt.price for pt in points]
    d = 1 if points[0].kind == LOW else -1
    n = len(points) - 1

    def at(base: float, length: float, ratio: float) -> float:
        return base + d * ratio * length

    if n == 1:
        return (
            "Posible onda A en curso tras un impulso",
            [
                Target("A: retroceso 38,2 % del impulso", at(p[0], impulse_size, 0.382)),
                Target("A: retroceso 50 % del impulso", at(p[0], impulse_size, 0.5)),
            ],
            None,
        )
    wa = abs(p[1] - p[0])
    if n == 2:
        return (
            "Posible onda B en formación; después vendría la onda C",
            [
                Target("B: retroceso 50 % de A", at(p[1], wa, -0.5)),
                Target("B: retroceso 61,8 % de A", at(p[1], wa, -0.618)),
                Target("C = A", at(p[2], wa, 1.0)),
            ],
            p[0],
        )
    return (
        "Posible onda C en curso",
        [
            Target("C = A", at(p[2], wa, 1.0)),
            Target("C = 1,618 × A", at(p[2], wa, 1.618)),
        ],
        p[0],
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _count(
    kind: str,
    points: list[Pivot],
    checks: Callable[[list[Pivot]], tuple[list[Check], list[Check]]],
    *,
    current: bool = False,
    stage: str = "",
    targets: tuple[Target, ...] = (),
    invalidation: float | None = None,
) -> WaveCount:
    rules, guides = checks(points)
    labels = IMPULSE_LABELS if kind == IMPULSE else CORRECTION_LABELS
    direction = 1 if points[0].kind == LOW else -1
    if current:
        # The last wave is still forming: its guidelines are not judged yet.
        guides = [g for g in guides if g.wave < len(points) - 1]
    return WaveCount(
        kind,
        direction,
        tuple(points),
        labels[: len(points)],
        tuple(rules),
        tuple(guides),
        current,
        stage,
        targets,
        invalidation,
    )


def find_impulses(pivots: list[Pivot]) -> list[WaveCount]:
    """Valid, non-overlapping completed impulses, best guideline score first."""
    candidates = []
    for i in range(len(pivots) - 5):
        count = _count(IMPULSE, pivots[i : i + 6], impulse_checks)
        if count.valid:
            candidates.append(count)
    candidates.sort(key=lambda c: (c.score, c.end), reverse=True)
    chosen: list[WaveCount] = []
    for count in candidates:
        if all(count.end <= other.start or count.start >= other.end for other in chosen):
            chosen.append(count)
    return sorted(chosen, key=lambda c: c.start)


def _position(pivots: list[Pivot], index: int) -> int:
    return next(k for k, pt in enumerate(pivots) if pt.index == index)


def analyze(bars: pd.DataFrame, threshold: float | None = None) -> ElliottResult:
    """Find completed counts in the history and possible counts in progress."""
    threshold = auto_threshold(bars) if threshold is None else threshold
    pivots = zigzag(bars["high"], bars["low"], threshold)
    confirmed = [pt for pt in pivots if pt.confirmed]

    impulses = find_impulses(confirmed)
    past: list[WaveCount] = []
    current: list[WaveCount] = []
    for impulse in impulses:
        past.append(impulse)
        j = _position(pivots, impulse.end)
        after = pivots[j : j + 4]
        size = abs(impulse.pivots[-1].price - impulse.pivots[0].price)
        if len(after) == 4 and all(pt.confirmed for pt in after):
            correction = _count(CORRECTION, after, correction_checks)
            if correction.valid:
                past.append(correction)
        elif len(after) >= 2 and after[-1] is pivots[-1] and not pivots[-1].confirmed:
            stage, targets, invalidation = _correction_projection(after, size)
            correction = _count(
                CORRECTION,
                after,
                correction_checks,
                current=True,
                stage=stage,
                targets=tuple(targets),
                invalidation=invalidation,
            )
            if correction.valid:
                current.append(correction)

    if pivots and not pivots[-1].confirmed:
        for n in (5, 4, 3, 2):
            if len(pivots) < n + 1:
                continue
            window = pivots[-(n + 1) :]
            stage, targets, invalidation = _impulse_projection(window)
            count = _count(
                IMPULSE,
                window,
                impulse_checks,
                current=True,
                stage=stage,
                targets=tuple(t for t in targets if t.price > 0),
                invalidation=invalidation,
            )
            if count.valid:
                current.append(count)
    current.sort(key=lambda c: (len(c.pivots) if c.kind == IMPULSE else 4.5, c.score), reverse=True)
    past.sort(key=lambda c: c.start)
    return ElliottResult(threshold, pivots, past[-MAX_PAST:], current[:MAX_CURRENT])
