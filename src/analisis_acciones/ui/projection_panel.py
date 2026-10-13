"""'Proyección' tab: statistical price ranges with historical calibration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import shiboken6
from PySide6.QtCore import QLocale, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.forecast.projection import Calibration, Projection, calibrate, project
from analisis_acciones.models.errors import user_message_for
from analisis_acciones.models.market import BarSeries
from analisis_acciones.ui import strings
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK = {"cone": 252, "regression": 120}


@dataclass(frozen=True)
class ProjectionOutcome:
    series: BarSeries
    projection: Projection
    calibration: Calibration | None


def compute_projection(series: BarSeries, method: str, horizon: int,
                       lookback: int) -> ProjectionOutcome:  # fmt: skip
    closes = series.bars["close"].to_numpy(dtype=float)
    projection = project(method, closes, horizon, lookback)
    return ProjectionOutcome(series, projection, calibrate(closes, method, horizon, lookback))


class ProjectionPanel(QWidget):
    #: New outcome to draw (or None to clear the chart overlay).
    projection_ready = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: BarSeries | None = None
        self._workers: set[Worker] = set()
        self._seq = 0
        self.outcome: ProjectionOutcome | None = None

        self.method = QComboBox()
        self.method.addItem(strings.PROJ_CONE, "cone")
        self.method.addItem(strings.PROJ_REGRESSION, "regression")
        self.method.currentIndexChanged.connect(self._on_method_changed)
        self.horizon = QSpinBox()
        self.horizon.setRange(1, 250)
        self.horizon.setValue(20)
        self.horizon.setSuffix(strings.PROJ_BARS_SUFFIX)
        self.lookback = QSpinBox()
        self.lookback.setRange(20, 5000)
        self.lookback.setValue(DEFAULT_LOOKBACK["cone"])
        self.lookback.setSuffix(strings.PROJ_BARS_SUFFIX)
        self.show_on_chart = QCheckBox(strings.PROJ_SHOW)
        self.show_on_chart.setChecked(True)
        self.show_on_chart.toggled.connect(self._emit_current)
        self.run_button = QPushButton(strings.PROJ_RUN)
        self.run_button.clicked.connect(self.run)

        form = QFormLayout()
        form.addRow(strings.PROJ_METHOD, self.method)
        form.addRow(strings.PROJ_HORIZON, self.horizon)
        form.addRow(strings.PROJ_LOOKBACK, self.lookback)
        form.addRow(self.show_on_chart)

        self.result = QLabel(strings.PROJ_EMPTY)
        self.result.setObjectName("detailsSource")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(self.result.textInteractionFlags())
        disclaimer = QLabel(strings.PROJ_DISCLAIMER)
        disclaimer.setObjectName("detailsSource")
        disclaimer.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(form)
        layout.addWidget(self.run_button)
        layout.addWidget(self.result, stretch=1)
        layout.addWidget(disclaimer)

    def _on_method_changed(self, _index: int) -> None:
        self.lookback.setValue(DEFAULT_LOOKBACK[str(self.method.currentData())])

    def set_series(self, series: BarSeries) -> None:
        """New data on the chart: previous results no longer apply."""
        self._series = series
        self._seq += 1
        if self.outcome is not None:
            self.outcome = None
            self.result.setText(strings.PROJ_STALE)
            self.projection_ready.emit(None)

    def run(self) -> None:
        if self._series is None:
            self.result.setText(strings.PROJ_EMPTY)
            return
        self._seq += 1
        seq = self._seq
        series, method = self._series, str(self.method.currentData())
        horizon, lookback = self.horizon.value(), self.lookback.value()
        self.run_button.setEnabled(False)
        self.result.setText(strings.PROJ_RUNNING)

        def done(outcome: ProjectionOutcome) -> None:
            if not shiboken6.isValid(self):
                return
            self.run_button.setEnabled(True)
            if seq == self._seq:
                self.outcome = outcome
                self._show(outcome)
                self._emit_current()

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.result.setText(user_message_for(exc))

        worker = start_worker(lambda: compute_projection(series, method, horizon, lookback),
                              done, fail)  # fmt: skip
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def _emit_current(self) -> None:
        show = self.show_on_chart.isChecked() and self.outcome is not None
        self.projection_ready.emit(self.outcome if show else None)

    def _show(self, outcome: ProjectionOutcome) -> None:
        loc = QLocale()
        p = outcome.projection
        ends = p.at_horizon()

        def line(name: str, label: str) -> str:
            change = (ends[name] / p.base_price - 1) * 100
            return f"{label}: {loc.toString(ends[name], 'f', 2)} ({change:+.1f} %)"

        method = strings.PROJ_CONE if p.method == "cone" else strings.PROJ_REGRESSION
        parts = [
            strings.PROJ_HEADER.format(method=method, horizon=p.horizon,
                                       base=loc.toString(p.base_price, "f", 2)),
            line("p95", "P95"), line("p75", "P75"), line("p50", strings.PROJ_MEDIAN),
            line("p25", "P25"), line("p05", "P5"), "", *p.explanation, "",
        ]  # fmt: skip
        cal = outcome.calibration
        if cal is None:
            parts.append(strings.PROJ_NO_CALIBRATION)
        else:
            parts.append(strings.PROJ_CALIBRATION.format(
                samples=cal.samples, step=cal.step, horizon=p.horizon,
                in90=cal.inside_90 * 100, in50=cal.inside_50 * 100,
                error=cal.median_abs_error_pct,
            ))  # fmt: skip
        self.result.setText("\n".join(parts))
