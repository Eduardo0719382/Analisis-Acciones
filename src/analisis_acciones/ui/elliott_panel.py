"""'Elliott' tab: rule-checked wave counts, past and in progress."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
import shiboken6
from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.models.errors import user_message_for
from analisis_acciones.models.market import BarSeries
from analisis_acciones.patterns.elliott import IMPULSE, ElliottResult, WaveCount, analyze
from analisis_acciones.ui import strings
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

COUNT_ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class ElliottView:
    """What the chart should draw."""

    series: BarSeries
    counts: list[WaveCount]
    selected: WaveCount | None


def count_name(count: WaveCount) -> str:
    direction = strings.ELL_UP if count.direction > 0 else strings.ELL_DOWN
    waves = "-".join(label for label in count.labels if label and label != "0")
    if count.kind == IMPULSE:
        if len(count.pivots) == 6:
            return strings.ELL_IMPULSE.format(direction=direction)
        return strings.ELL_IMPULSE_PARTIAL.format(direction=direction, waves=waves)
    if len(count.pivots) == 4 and not count.current:
        return strings.ELL_CORRECTION.format(direction=direction)
    return strings.ELL_CORRECTION_PARTIAL.format(direction=direction, waves=waves)


class ElliottPanel(QWidget):
    #: New ElliottView to draw, or None to clear the chart overlay.
    overlay_ready = Signal(object)
    #: [(note, price), ...] levels of the selected count to watch with price alerts.
    alerts_requested = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: BarSeries | None = None
        self._workers: set[Worker] = set()
        self._seq = 0
        self.result: ElliottResult | None = None

        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 30.0)
        self.threshold.setSingleStep(0.5)
        self.threshold.setDecimals(1)
        self.threshold.setSuffix(" %")
        self.threshold.setSpecialValueText(strings.ELL_AUTO)
        self.threshold.setValue(0.0)
        self.show_on_chart = QCheckBox(strings.ELL_SHOW)
        self.show_on_chart.setChecked(True)
        self.show_on_chart.toggled.connect(self._emit_current)
        self.run_button = QPushButton(strings.ELL_RUN)
        self.run_button.clicked.connect(self.run)

        form = QFormLayout()
        form.addRow(strings.ELL_THRESHOLD, self.threshold)
        form.addRow(self.show_on_chart)

        self.summary = QLabel(strings.ELL_EMPTY)
        self.summary.setObjectName("detailsSource")
        self.summary.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setObjectName("analysisTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.currentItemChanged.connect(self._on_selection)
        self.details = QLabel()
        self.details.setObjectName("detailsSource")
        self.details.setWordWrap(True)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details_scroll.setWidget(self.details)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(details_scroll)
        splitter.setStretchFactor(1, 2)
        self.alert_button = QPushButton(strings.CREATE_LEVEL_ALERTS)
        self.alert_button.setToolTip(strings.CREATE_LEVEL_ALERTS_TIP)
        self.alert_button.setEnabled(False)
        self.alert_button.clicked.connect(self._request_alerts)
        disclaimer = QLabel(strings.ELL_DISCLAIMER)
        disclaimer.setObjectName("detailsSource")
        disclaimer.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(form)
        layout.addWidget(self.run_button)
        layout.addWidget(self.summary)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self.alert_button)
        layout.addWidget(disclaimer)

    # Data ----------------------------------------------------------------------
    def set_series(self, series: BarSeries) -> None:
        """New data on the chart: previous counts no longer apply."""
        self._series = series
        self._seq += 1
        if self.result is not None:
            self.result = None
            self.tree.clear()
            self.details.clear()
            self.alert_button.setEnabled(False)
            self.summary.setText(strings.ELL_STALE)
            self.overlay_ready.emit(None)

    def run(self) -> None:
        if self._series is None:
            self.summary.setText(strings.ELL_EMPTY)
            return
        self._seq += 1
        seq = self._seq
        series = self._series
        value = self.threshold.value()
        threshold = value / 100 if value > 0 else None
        self.run_button.setEnabled(False)
        self.summary.setText(strings.ELL_RUNNING)

        def done(result: ElliottResult) -> None:
            if not shiboken6.isValid(self):
                return
            self.run_button.setEnabled(True)
            if seq == self._seq:
                self.result = result
                self._show(result)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.summary.setText(user_message_for(exc))

        worker = start_worker(lambda: analyze(series.bars, threshold), done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    # Presentation -----------------------------------------------------------------
    def _date(self, index: int) -> str:
        assert self._series is not None
        return pd.Timestamp(self._series.bars.index[index]).strftime("%d/%m/%Y")

    def _item_text(self, count: WaveCount) -> str:
        if count.guidelines:
            score = strings.ELL_SCORE.format(passed=sum(g.passed for g in count.guidelines),
                                             total=len(count.guidelines))  # fmt: skip
        else:
            score = strings.ELL_NO_GUIDES
        return strings.ELL_ITEM.format(name=count_name(count), start=self._date(count.start),
                                       end=self._date(count.end), score=score)  # fmt: skip

    def _show(self, result: ElliottResult) -> None:
        self.summary.setText(strings.ELL_SUMMARY.format(
            threshold=result.threshold * 100, pivots=len(result.pivots),
            past=len(result.past), current=len(result.current),
        ))  # fmt: skip
        self.tree.blockSignals(True)
        self.tree.clear()
        first: QTreeWidgetItem | None = None
        groups = ((strings.ELL_CURRENT_GROUP, result.current),
                  (strings.ELL_PAST_GROUP, list(reversed(result.past))))  # fmt: skip
        for title, counts in groups:
            group = QTreeWidgetItem(self.tree, [title])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setExpanded(True)
            if not counts:
                QTreeWidgetItem(group, [strings.ELL_NONE]).setFlags(Qt.ItemFlag.ItemIsEnabled)
            for count in counts:
                item = QTreeWidgetItem(group, [self._item_text(count)])
                item.setData(0, COUNT_ROLE, count)
                item.setToolTip(0, item.text(0))
                first = first or item
        self.tree.blockSignals(False)
        if first is not None:
            self.tree.setCurrentItem(first)  # shows details and draws
        else:
            self.details.clear()
            self._emit_current()

    @property
    def selected(self) -> WaveCount | None:
        item = self.tree.currentItem()
        data = item.data(0, COUNT_ROLE) if item is not None else None
        return data if isinstance(data, WaveCount) else None

    def _on_selection(self, *_args: object) -> None:
        count = self.selected
        self.details.setText(self._details(count) if count is not None else "")
        self.alert_button.setEnabled(bool(self.alert_levels()))
        self._emit_current()

    def alert_levels(self) -> list[tuple[str, float]]:
        count = self.selected
        if count is None:
            return []
        name = f"Elliott {count_name(count)}"
        levels = [(f"{name}: {t.label}", t.price) for t in count.targets]
        if count.invalidation is not None:
            levels.append((f"{name}: invalidación", count.invalidation))
        return levels

    def _request_alerts(self) -> None:
        levels = self.alert_levels()
        if levels:
            self.alerts_requested.emit(levels)

    def _details(self, count: WaveCount) -> str:
        loc = QLocale()

        def price(value: float) -> str:
            return loc.toString(float(value), "f", 2)

        lines = [count_name(count)]
        if count.stage:
            lines.append(count.stage)
        pairs = zip(count.pivots, count.labels, strict=True)
        points = ", ".join(f"{label or '·'} {price(p.price)} ({self._date(p.index)})"
                           for p, label in pairs)  # fmt: skip
        lines += [points, "", strings.ELL_RULES]
        lines += [f"{'✓' if r.passed else '✗'} {r.text} — {r.detail}" for r in count.rules]
        if count.guidelines:
            lines += ["", strings.ELL_GUIDES]
            lines += [f"{'✓' if g.passed else '·'} {g.text} — {g.detail}" for g in count.guidelines]
        if count.targets:
            lines += ["", strings.ELL_TARGETS]
            lines += [f"• {t.label}: {price(t.price)}" for t in count.targets]
        if count.invalidation is not None:
            # Levels sit at the count's start or wave-1 end: a rising count breaks below them.
            rising = count.direction > 0
            template = strings.ELL_INVALIDATION_DOWN if rising else strings.ELL_INVALIDATION
            lines += ["", template.format(price=price(count.invalidation))]
        if count.current:
            lines.append(strings.ELL_LAST_POINT)
        return "\n".join(lines)

    def _emit_current(self, *_args: object) -> None:
        if self.result is None or self._series is None or not self.show_on_chart.isChecked():
            self.overlay_ready.emit(None)
            return
        # Alternative counts in progress share pivots; drawing them all would stack labels.
        selected = self.selected
        counts = list(self.result.past)
        if selected is not None and selected.current:
            counts.append(selected)
        self.overlay_ready.emit(ElliottView(self._series, counts, selected))
