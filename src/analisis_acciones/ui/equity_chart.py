"""Small native line chart for backtest equity curves (no web engine needed)."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QLocale, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from analisis_acciones.ui.theme import ThemeTokens


class EquityChart(QWidget):
    def __init__(self, tokens: ThemeTokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._series: list[tuple[str, pd.Series, str]] = []
        self.setMinimumHeight(180)

    def set_series(self, series: list[tuple[str, pd.Series, str]]) -> None:
        """[(label, values indexed by date, colour)]; all share the same index."""
        self._series = [(label, s.dropna(), colour) for label, s, colour in series]
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._tokens
        painter.fillRect(self.rect(), QColor(t.surface))
        if not self._series or all(s.empty for _, s, _ in self._series):
            return
        left, right, top, bottom = 70, 12, 22, 24
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        values = pd.concat([s for _, s, _ in self._series])
        lo, hi = float(values.min()), float(values.max())
        if hi == lo:
            hi, lo = hi + 1, lo - 1
        n = max(len(s) for _, s, _ in self._series)

        def point(i: int, v: float) -> QPointF:
            x = plot.left() + plot.width() * (i / max(n - 1, 1))
            y = plot.bottom() - plot.height() * ((v - lo) / (hi - lo))
            return QPointF(x, y)

        painter.setPen(QPen(QColor(t.grid), 1))
        for k in range(5):
            y = plot.top() + plot.height() * k / 4
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            value = hi - (hi - lo) * k / 4
            painter.setPen(QColor(t.text_muted))
            painter.drawText(QRectF(0, y - 8, left - 6, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             QLocale().toString(value, "f", 0))  # fmt: skip
            painter.setPen(QPen(QColor(t.grid), 1))

        first = self._series[0][1]
        painter.setPen(QColor(t.text_muted))
        painter.drawText(QRectF(plot.left(), plot.bottom() + 4, 120, 16),
                         Qt.AlignmentFlag.AlignLeft, f"{first.index[0]:%d/%m/%Y}")  # fmt: skip
        painter.drawText(QRectF(plot.right() - 120, plot.bottom() + 4, 120, 16),
                         Qt.AlignmentFlag.AlignRight, f"{first.index[-1]:%d/%m/%Y}")  # fmt: skip

        legend_x = plot.left()
        for label, series, colour in self._series:
            path = QPainterPath()
            for i, v in enumerate(series.to_numpy(dtype=float)):
                p = point(i, v)
                if i == 0:
                    path.moveTo(p)
                else:
                    path.lineTo(p)
            painter.setPen(QPen(QColor(colour), 1.6))
            painter.drawPath(path)
            painter.drawText(QRectF(legend_x, 2, 200, 16), Qt.AlignmentFlag.AlignLeft, f"— {label}")
            legend_x += painter.fontMetrics().horizontalAdvance(f"— {label}") + 18
        painter.end()
