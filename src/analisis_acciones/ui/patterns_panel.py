"""'Patrones' tab: support/resistance levels and classic chart patterns."""

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
from analisis_acciones.patterns.chart_patterns import (
    CONFIRMED,
    FORMING,
    ChartPattern,
    PatternResult,
    analyze,
)
from analisis_acciones.patterns.levels import Level
from analisis_acciones.ui import strings
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

ITEM_ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class PatternsView:
    """What the chart should draw."""

    series: BarSeries
    close: float
    levels: list[Level]
    patterns: list[ChartPattern]
    selected: ChartPattern | None


class PatternsPanel(QWidget):
    #: New PatternsView to draw, or None to clear the chart overlays.
    overlay_ready = Signal(object)
    #: [(note, price), ...] levels of the selection to watch with price alerts.
    alerts_requested = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: BarSeries | None = None
        self._workers: set[Worker] = set()
        self._seq = 0
        self.result: PatternResult | None = None

        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 30.0)
        self.threshold.setSingleStep(0.5)
        self.threshold.setDecimals(1)
        self.threshold.setSuffix(" %")
        self.threshold.setSpecialValueText(strings.ELL_AUTO)
        self.show_levels = QCheckBox(strings.PAT_SHOW_LEVELS)
        self.show_levels.setChecked(True)
        self.show_levels.toggled.connect(self._emit_current)
        self.show_patterns = QCheckBox(strings.PAT_SHOW_PATTERNS)
        self.show_patterns.setChecked(True)
        self.show_patterns.toggled.connect(self._emit_current)
        self.run_button = QPushButton(strings.PAT_RUN)
        self.run_button.clicked.connect(self.run)

        form = QFormLayout()
        form.addRow(strings.PAT_THRESHOLD, self.threshold)
        form.addRow(self.show_levels)
        form.addRow(self.show_patterns)

        self.summary = QLabel(strings.PAT_EMPTY)
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.details)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 2)
        self.alert_button = QPushButton(strings.CREATE_LEVEL_ALERTS)
        self.alert_button.setToolTip(strings.CREATE_LEVEL_ALERTS_TIP)
        self.alert_button.setEnabled(False)
        self.alert_button.clicked.connect(self._request_alerts)
        disclaimer = QLabel(strings.PAT_DISCLAIMER)
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
        """New data on the chart: previous results no longer apply."""
        self._series = series
        self._seq += 1
        if self.result is not None:
            self.result = None
            self.tree.clear()
            self.details.clear()
            self.alert_button.setEnabled(False)
            self.summary.setText(strings.PAT_STALE)
            self.overlay_ready.emit(None)

    def run(self) -> None:
        if self._series is None:
            self.summary.setText(strings.PAT_EMPTY)
            return
        self._seq += 1
        seq = self._seq
        series = self._series
        value = self.threshold.value()
        threshold = value / 100 if value > 0 else None
        self.run_button.setEnabled(False)
        self.summary.setText(strings.PAT_RUNNING)

        def done(result: PatternResult) -> None:
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

    @staticmethod
    def _price(value: float) -> str:
        return QLocale().toString(float(value), "f", 2)

    def _role(self, level: Level, close: float) -> str:
        return strings.PAT_SUPPORT if level.role(close) == "support" else strings.PAT_RESISTANCE

    def _show(self, result: PatternResult) -> None:
        total, hit, failed = result.track_record()
        track = (strings.PAT_TRACK.format(total=total, hit=hit, failed=failed) if total
                 else strings.PAT_TRACK_NONE)  # fmt: skip
        self.summary.setText(strings.PAT_SUMMARY.format(
            threshold=result.threshold * 100, tolerance=result.tolerance * 100,
            levels=len(result.levels), patterns=len(result.patterns),
        ) + "\n" + track)  # fmt: skip
        self.tree.blockSignals(True)
        self.tree.clear()
        first_pattern: QTreeWidgetItem | None = None

        def group(title: str) -> QTreeWidgetItem:
            item = QTreeWidgetItem(self.tree, [title])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setExpanded(True)
            return item

        def empty(parent: QTreeWidgetItem) -> None:
            QTreeWidgetItem(parent, [strings.PAT_NONE]).setFlags(Qt.ItemFlag.ItemIsEnabled)

        levels = group(strings.PAT_LEVELS_GROUP)
        for level in sorted(result.levels, key=lambda lv: -lv.price):
            text = strings.PAT_LEVEL_ITEM.format(role=self._role(level, result.close),
                                                 price=self._price(level.price),
                                                 touches=level.touches,
                                                 last=self._date(level.last))  # fmt: skip
            QTreeWidgetItem(levels, [text]).setData(0, ITEM_ROLE, level)
        if not result.levels:
            empty(levels)
        forming = [p for p in result.patterns if p.status == FORMING]
        past = [p for p in reversed(result.patterns) if p.status != FORMING]
        for title, patterns in ((strings.PAT_FORMING_GROUP, forming),
                                (strings.PAT_PAST_GROUP, past)):  # fmt: skip
            parent = group(title)
            for pattern in patterns:
                text = strings.PAT_ITEM.format(
                    name=pattern.name, start=self._date(pattern.start),
                    end=self._date(pattern.breakout or pattern.end),
                    status=strings.PAT_STATUS[pattern.status],
                )  # fmt: skip
                item = QTreeWidgetItem(parent, [text])
                item.setData(0, ITEM_ROLE, pattern)
                item.setToolTip(0, text)
                first_pattern = first_pattern or item
            if not patterns:
                empty(parent)
        self.tree.blockSignals(False)
        if first_pattern is not None:
            self.tree.setCurrentItem(first_pattern)
        else:
            self.details.clear()
            self._emit_current()

    @property
    def selected(self) -> ChartPattern | Level | None:
        item = self.tree.currentItem()
        data = item.data(0, ITEM_ROLE) if item is not None else None
        return data if isinstance(data, ChartPattern | Level) else None

    def _on_selection(self, *_args: object) -> None:
        chosen = self.selected
        if isinstance(chosen, ChartPattern):
            self.details.setText(self._pattern_details(chosen))
        elif isinstance(chosen, Level) and self.result is not None:
            self.details.setText(strings.PAT_LEVEL_DETAILS.format(
                role=self._role(chosen, self.result.close), price=self._price(chosen.price),
                low=self._price(chosen.low), high=self._price(chosen.high),
                touches=chosen.touches, first=self._date(chosen.first),
                last=self._date(chosen.last),
            ))  # fmt: skip
        else:
            self.details.clear()
        self.alert_button.setEnabled(bool(self.alert_levels()))
        self._emit_current()

    def alert_levels(self) -> list[tuple[str, float]]:
        chosen = self.selected
        if isinstance(chosen, Level) and self.result is not None:
            role = self._role(chosen, self.result.close)
            return [(f"{role} ×{chosen.touches}", chosen.price)]
        if not isinstance(chosen, ChartPattern) or chosen.status not in (FORMING, CONFIRMED):
            return []  # finished patterns have nothing left to watch
        levels = [(f"{chosen.name}: {t.label.lower()}", t.price) for t in chosen.targets]
        if chosen.invalidation is not None:
            levels.append((f"{chosen.name}: invalidación", chosen.invalidation))
        return levels

    def _request_alerts(self) -> None:
        levels = self.alert_levels()
        if levels:
            self.alerts_requested.emit(levels)

    def _pattern_details(self, pattern: ChartPattern) -> str:
        lines = [f"{pattern.name} — {strings.PAT_STATUS[pattern.status]}"]
        labels = pattern.labels or ("",) * len(pattern.points)
        pairs = zip(pattern.points, labels, strict=True)
        points = ", ".join(f"{label or '·'} {self._price(p.price)} ({self._date(p.index)})"
                           for p, label in pairs)  # fmt: skip
        lines += [points, "", strings.PAT_CONDITIONS]
        lines += [f"{'✓' if c.passed else '✗'} {c.text}" + (f" — {c.detail}" if c.detail else "")
                  for c in pattern.checks]  # fmt: skip
        lines.append("")
        if pattern.breakout is not None:
            lines.append(strings.PAT_BREAKOUT.format(date=self._date(pattern.breakout)))
        else:
            lines.append(strings.PAT_NO_BREAKOUT)
        lines += [f"• {t.label}: {self._price(t.price)}" for t in pattern.targets]
        if pattern.invalidation is not None:
            lines.append(strings.PAT_INVALIDATION.format(price=self._price(pattern.invalidation)))
        return "\n".join(lines)

    def _emit_current(self, *_args: object) -> None:
        if self.result is None or self._series is None:
            self.overlay_ready.emit(None)
            return
        chosen = self.selected
        selected = chosen if isinstance(chosen, ChartPattern) else None
        patterns: list[ChartPattern] = []
        if self.show_patterns.isChecked():
            # Forming patterns are always drawn; past ones only when selected.
            patterns = [p for p in self.result.patterns if p.status == FORMING]
            if selected is not None and selected not in patterns:
                patterns.append(selected)
        else:
            selected = None
        levels = list(self.result.levels) if self.show_levels.isChecked() else []
        self.overlay_ready.emit(PatternsView(self._series, self.result.close, levels,
                                             patterns, selected))  # fmt: skip
