"""'Agotamiento' tab: exhaustion signs of the current trend and their record in this asset."""

from __future__ import annotations

from html import escape

from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from analisis_acciones.analysis.exhaustion import (
    SIGNIFICANCE,
    SMALL_SAMPLE,
    THRESHOLD,
    UP,
    Assessment,
    Outcome,
    assess,
)
from analisis_acciones.models.market import BarSeries
from analisis_acciones.services.scan_report import num
from analisis_acciones.ui import strings

EDGE_POINTS = 10.0  # difference vs baseline (percentage points) considered noticeable


def verdict(a: Assessment) -> str:
    if a.direction is None:
        return escape(a.reason)
    up = a.direction == UP
    if a.signalled:
        return (strings.EXH_UP_SIGNAL if up else strings.EXH_DOWN_SIGNAL).format(
            met=a.met, total=a.available
        )
    return (strings.EXH_UP_QUIET if up else strings.EXH_DOWN_QUIET).format(
        met=a.met, total=a.available
    )


def outcome_line(o: Outcome, up: bool) -> str:
    move = strings.EXH_FELL if up else strings.EXH_ROSE
    if not o.events:
        return strings.EXH_NO_CASES.format(h=o.horizon)
    line = strings.EXH_OUTCOME.format(
        h=o.horizon, move=move, against=o.against, events=o.events,
        pct=num(o.against_pct, 0), median=num(o.median_return, 1, sign=True),
        base=num(o.baseline_against_pct, 0),
    )  # fmt: skip
    p = o.p_value
    chance = o.events < SMALL_SAMPLE or p is None or p >= SIGNIFICANCE
    return f"{line} {strings.EXH_CHANCE if chance else strings.EXH_NOT_CHANCE}"


def _effect(o: Outcome) -> int:
    """+1 / -1 when the record differs clearly (and not by luck) from the baseline, else 0."""
    if o.against_pct is None or o.baseline_against_pct is None or o.events < SMALL_SAMPLE:
        return 0
    diff = o.against_pct - o.baseline_against_pct
    p = o.p_value
    if abs(diff) < EDGE_POINTS or p is None or p >= SIGNIFICANCE:
        return 0
    return 1 if diff > 0 else -1


def reading(a: Assessment) -> str:
    """Plain-words reading of the record (never a forecast).

    A difference counts only with enough cases, at least 10 points from the baseline and an
    exact binomial test below 5 %; horizons pointing in opposite ways are reported as mixed.
    """
    usable = [o for o in a.outcomes if o.against_pct is not None]
    if not usable or all(o.baseline_against_pct is None for o in usable):
        return strings.EXH_READ_NONE
    if all(o.events < SMALL_SAMPLE for o in usable):
        return strings.EXH_READ_FEW
    effects = {_effect(o) for o in usable}
    up = a.direction == UP
    if effects >= {1, -1}:
        return strings.EXH_READ_MIXED
    if 1 in effects:
        return strings.EXH_READ_USEFUL_UP if up else strings.EXH_READ_USEFUL_DOWN
    if -1 in effects:
        return strings.EXH_READ_CONTINUE_UP if up else strings.EXH_READ_CONTINUE_DOWN
    return strings.EXH_READ_NO_EDGE


def assessment_html(a: Assessment) -> str:
    parts = [f"<p><b>{verdict(a)}</b></p>"]
    if a.direction is None:
        return "".join(parts)
    up = a.direction == UP
    items = []
    for c in a.conditions:
        mark = "—" if c.met is None else ("✔" if c.met else "✘")
        items.append(f"<li>{mark} <b>{escape(c.name)}</b>: {escape(c.detail)}</li>")
    parts.append(f"<ul>{''.join(items)}</ul>")
    parts.append(
        f"<p><b>{strings.EXH_HISTORY_TITLE.format(n=THRESHOLD)}</b></p><ul>"
        + "".join(f"<li>{outcome_line(o, up)}</li>" for o in a.outcomes)
        + f"</ul><p>{reading(a)}</p>"
    )
    parts.append(f"<p><small>{strings.EXH_NOTE}</small></p>")
    return "".join(parts)


class ExhaustionPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.assessment: Assessment | None = None
        self.title = QLabel(strings.EXH_EMPTY)
        self.title.setObjectName("detailsSource")
        self.title.setWordWrap(True)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.view, stretch=1)

    def set_series(self, series: BarSeries, session_in_progress: bool = False) -> None:
        bars = series.bars.iloc[:-1] if session_in_progress and len(series.bars) else series.bars
        self.assessment = assess(bars)
        when = f"{self.assessment.as_of:%d/%m/%Y}" if self.assessment.as_of is not None else "—"
        self.title.setText(strings.EXH_TITLE.format(symbol=series.symbol, when=when))
        self.view.setHtml(assessment_html(self.assessment))
