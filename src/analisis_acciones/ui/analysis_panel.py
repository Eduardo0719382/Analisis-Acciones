"""'Análisis' tab: explainable rule-based signals for the series on the chart."""

from __future__ import annotations

import logging

import shiboken6
from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.analysis.engine import analyze
from analisis_acciones.analysis.model import AnalysisReport, Direction
from analisis_acciones.models.market import BarSeries
from analisis_acciones.ui import strings
from analisis_acciones.ui.theme import ThemeTokens
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)


def _locale_format(value: float, decimals: int = 2) -> str:
    return QLocale().toString(float(value), "f", decimals)


class AnalysisPanel(QWidget):
    def __init__(self, tokens: ThemeTokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._seq = 0
        self._workers: set[Worker] = set()
        self.report: AnalysisReport | None = None
        self._title = ""

        self.summary = QLabel(strings.ANALYSIS_EMPTY)
        self.summary.setObjectName("detailsSource")
        self.summary.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setObjectName("analysisTree")
        self.tree.setHeaderHidden(True)
        self.tree.setWordWrap(True)
        self.tree.setIndentation(14)
        # Evidence lines are never truncated: scroll horizontally instead.
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.notes = QLabel()
        self.notes.setObjectName("detailsSource")
        self.notes.setWordWrap(True)
        disclaimer = QLabel(strings.ANALYSIS_DISCLAIMER)
        disclaimer.setObjectName("detailsSource")
        disclaimer.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree, stretch=1)
        layout.addWidget(self.notes)
        layout.addWidget(disclaimer)

    def set_theme(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        if self.report is not None:
            self._show(self.report, "")

    def analyze(self, series: BarSeries, title: str, session_in_progress: bool) -> None:
        self._seq += 1
        seq = self._seq
        self.summary.setText(strings.ANALYSIS_RUNNING)
        bars = series.bars

        def job() -> AnalysisReport:
            return analyze(
                series.symbol, bars, session_in_progress=session_in_progress, fmt=_locale_format
            )

        def done(report: AnalysisReport) -> None:
            if shiboken6.isValid(self) and seq == self._seq:
                self._show(report, title)

        def fail(exc: BaseException) -> None:
            logger.error("Analysis failed: %s", exc)
            if shiboken6.isValid(self) and seq == self._seq:
                self.summary.setText(strings.ANALYSIS_FAILED)

        worker = start_worker(job, done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def _show(self, report: AnalysisReport, title: str) -> None:
        self.report = report
        if title:
            self._title = title
        when = report.as_of.strftime("%d/%m/%Y") if report.as_of else "—"
        text = strings.ANALYSIS_SUMMARY.format(
            title=self._title or report.symbol, date=when, bars=report.bars_used
        )
        if report.excluded_partial_bar:
            text += "\n" + strings.ANALYSIS_PARTIAL_EXCLUDED
        self.summary.setText(text)

        colours = {
            Direction.BULLISH: self._tokens.up,
            Direction.BEARISH: self._tokens.down,
            Direction.NEUTRAL: self._tokens.text_muted,
        }
        self.tree.clear()
        for signal in report.signals:
            marker = {"bullish": "▲", "bearish": "▼"}.get(signal.direction.value, "●")
            item = QTreeWidgetItem([f"{marker}  {signal.title}"])
            item.setForeground(0, QColor(colours[signal.direction]))
            item.setData(0, Qt.ItemDataRole.UserRole, signal.rule_id)
            item.setToolTip(0, strings.ANALYSIS_DIRECTION[signal.direction.value])
            for line in signal.evidence:
                child = QTreeWidgetItem(item, [line])
                child.setToolTip(0, line)
            QTreeWidgetItem(
                item, [strings.ANALYSIS_BAR_DATE.format(date=f"{signal.bar_date:%d/%m/%Y}")]
            )
            self.tree.addTopLevelItem(item)
            item.setExpanded(True)
        if not report.signals:
            self.tree.addTopLevelItem(QTreeWidgetItem([strings.ANALYSIS_NO_SIGNALS]))
        self.notes.setText("\n".join(report.skipped))
