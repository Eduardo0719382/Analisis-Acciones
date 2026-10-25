"""'Agotamiento' tab: exhaustion signs of the current trend and their record in this asset."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

import pandas as pd
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.analysis.exhaustion import (
    DEFAULT_PARAMS,
    LIMITS,
    READ_CONTINUE,
    READ_FEW,
    READ_MIXED,
    READ_NO_EDGE,
    READ_NONE,
    READ_USEFUL,
    SIGNIFICANCE,
    SMALL_SAMPLE,
    UP,
    Assessment,
    Outcome,
    Params,
    assess,
    record_reading,
    signal_series,
)
from analisis_acciones.models.market import BarSeries
from analisis_acciones.services.scan_report import num
from analisis_acciones.ui import strings

if TYPE_CHECKING:
    from analisis_acciones.services.settings_service import SettingsService


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


_READINGS = {
    (READ_USEFUL, True): strings.EXH_READ_USEFUL_UP,
    (READ_USEFUL, False): strings.EXH_READ_USEFUL_DOWN,
    (READ_CONTINUE, True): strings.EXH_READ_CONTINUE_UP,
    (READ_CONTINUE, False): strings.EXH_READ_CONTINUE_DOWN,
}
_PLAIN = {
    READ_NONE: strings.EXH_READ_NONE,
    READ_FEW: strings.EXH_READ_FEW,
    READ_MIXED: strings.EXH_READ_MIXED,
    READ_NO_EDGE: strings.EXH_READ_NO_EDGE,
}


def reading(a: Assessment) -> str:
    """Plain-words reading of the record (never a forecast); see ``record_reading``."""
    code = record_reading(a.outcomes)
    return _PLAIN.get(code) or _READINGS[(code, a.direction == UP)]


def params_line(p: Params) -> str:
    return strings.EXH_CUSTOM.format(
        hi=num(p.rsi_high, 0), lo=num(p.rsi_low, 0), atr=num(p.atr_multiple, 1),
        vol=num(p.volume_ratio * 100, 0), z=num(p.z_limit, 1), n=p.threshold,
    )  # fmt: skip


def brief_outcome(o: Outcome, up: bool) -> str:
    if not o.events:
        return strings.EXH_NO_CASES.format(h=o.horizon)
    return strings.EXH_BRIEF.format(h=o.horizon, move=strings.EXH_FELL if up else strings.EXH_ROSE,
                                    against=o.against, events=o.events,
                                    pct=num(o.against_pct, 0))  # fmt: skip


def assessment_html(a: Assessment, default: Assessment | None = None,
                    params: Params = DEFAULT_PARAMS) -> str:  # fmt: skip
    """The verdict, the conditions and the record; with custom ``params`` also the record
    that the default thresholds give (``default``), so the effect of the change is visible."""
    parts = [f"<p><b>{verdict(a)}</b></p>"]
    if params != DEFAULT_PARAMS:
        parts.append(f"<p><small>{params_line(params)}</small></p>")
    if a.direction is None:
        return "".join(parts)
    up = a.direction == UP
    items = []
    for c in a.conditions:
        mark = "—" if c.met is None else ("✔" if c.met else "✘")
        items.append(f"<li>{mark} <b>{escape(c.name)}</b>: {escape(c.detail)}</li>")
    parts.append(f"<ul>{''.join(items)}</ul>")
    parts.append(
        f"<p><b>{strings.EXH_HISTORY_TITLE.format(n=a.threshold)}</b></p><ul>"
        + "".join(f"<li>{outcome_line(o, up)}</li>" for o in a.outcomes)
        + f"</ul><p>{reading(a)}</p>"
    )
    if default is not None and default.direction == a.direction and params != DEFAULT_PARAMS:
        parts.append(
            f"<p><b>{strings.EXH_DEFAULT_COMPARE.format(n=default.threshold)}</b></p><ul>"
            + "".join(f"<li>{brief_outcome(o, up)}</li>" for o in default.outcomes)
            + f"</ul><p>{reading(default)}</p>"
        )
    parts.append(f"<p><small>{strings.EXH_NOTE}</small></p>")
    return "".join(parts)


class ParamsDialog(QDialog):
    """Edit the exhaustion thresholds (limits from ``LIMITS``)."""

    def __init__(self, params: Params, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.EXH_PARAMS_TITLE)
        intro = QLabel(strings.EXH_PARAMS_INTRO)
        intro.setWordWrap(True)
        self.spins: dict[str, QDoubleSpinBox | QSpinBox] = {}
        form = QFormLayout()
        for name, label, decimals, step in (
            ("rsi_high", strings.EXH_P_RSI_HIGH, 0, 1.0),
            ("rsi_low", strings.EXH_P_RSI_LOW, 0, 1.0),
            ("atr_multiple", strings.EXH_P_ATR, 1, 0.5),
            ("volume_ratio", strings.EXH_P_VOLUME, 2, 0.05),
            ("z_limit", strings.EXH_P_Z, 1, 0.5),
            ("threshold", strings.EXH_P_THRESHOLD, 0, 1.0),
        ):
            low, high = LIMITS[name]
            spin: QDoubleSpinBox | QSpinBox
            if name == "threshold":
                spin = QSpinBox()
                spin.setRange(int(low), int(high))
            else:
                spin = QDoubleSpinBox()
                spin.setDecimals(decimals)
                spin.setRange(low, high)
                spin.setSingleStep(step)
            self.spins[name] = spin
            form.addRow(label, spin)
        self.set_params(params)
        defaults = QPushButton(strings.EXH_PARAMS_DEFAULTS)
        defaults.clicked.connect(lambda: self.set_params(DEFAULT_PARAMS))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.addButton(defaults, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def set_params(self, params: Params) -> None:
        for name, spin in self.spins.items():
            value = getattr(params, name)
            if isinstance(spin, QSpinBox):
                spin.setValue(int(value))
            else:
                spin.setValue(float(value))

    def params(self) -> Params:
        # Every value is inside its spin box range, so Params accepts it.
        s = self.spins
        return Params(
            rsi_high=float(s["rsi_high"].value()), rsi_low=float(s["rsi_low"].value()),
            atr_multiple=float(s["atr_multiple"].value()),
            volume_ratio=float(s["volume_ratio"].value()), z_limit=float(s["z_limit"].value()),
            threshold=int(s["threshold"].value()),
        )  # fmt: skip


class ExhaustionPanel(QWidget):
    #: (bar index of the shown series, signal per bar) to mark on the chart, or None.
    markers_ready = Signal(object)

    def __init__(self, settings: SettingsService | None = None,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._settings = settings
        self.params = settings.exhaustion_params() if settings is not None else DEFAULT_PARAMS
        self.assessment: Assessment | None = None
        self.series: BarSeries | None = None
        self._in_progress = False
        self.title = QLabel(strings.EXH_EMPTY)
        self.title.setObjectName("detailsSource")
        self.title.setWordWrap(True)
        self.markers = QCheckBox(strings.EXH_MARKERS)
        self.markers.setToolTip(strings.EXH_MARKERS_TIP)
        self.markers.setChecked(settings is not None and settings.exhaustion_markers())
        self.markers.toggled.connect(self._markers_toggled)
        self.params_button = QPushButton(strings.EXH_PARAMS_BUTTON)
        self.params_button.clicked.connect(self.edit_params)
        row = QHBoxLayout()
        row.addWidget(self.markers, stretch=1)
        row.addWidget(self.params_button)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addLayout(row)
        layout.addWidget(self.view, stretch=1)

    def set_series(self, series: BarSeries, session_in_progress: bool = False) -> None:
        self.series = series
        self._in_progress = session_in_progress
        self.refresh()

    def _closed_bars(self) -> pd.DataFrame:
        assert self.series is not None
        bars = self.series.bars
        return bars.iloc[:-1] if self._in_progress and len(bars) else bars

    def refresh(self) -> None:
        if self.series is None:
            return
        bars = self._closed_bars()
        self.assessment = assess(bars, self.params)
        default = assess(bars) if self.params != DEFAULT_PARAMS else None
        when = f"{self.assessment.as_of:%d/%m/%Y}" if self.assessment.as_of is not None else "—"
        self.title.setText(strings.EXH_TITLE.format(symbol=self.series.symbol, when=when))
        self.view.setHtml(assessment_html(self.assessment, default, self.params))
        self._emit_markers()

    def _emit_markers(self) -> None:
        if self.series is None or not self.markers.isChecked():
            self.markers_ready.emit(None)
            return
        signals = signal_series(self._closed_bars(), self.params).tolist()
        signals += [0] * (len(self.series.bars) - len(signals))  # the bar still forming
        self.markers_ready.emit((self.series.bars.index, signals))

    def _markers_toggled(self, on: bool) -> None:
        if self._settings is not None:
            self._settings.set_exhaustion_markers(on)
        self._emit_markers()

    def edit_params(self) -> None:
        dialog = ParamsDialog(self.params, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_params(dialog.params())

    def set_params(self, params: Params) -> None:
        self.params = params
        if self._settings is not None:
            self._settings.set_exhaustion_params(params)
        self.refresh()
