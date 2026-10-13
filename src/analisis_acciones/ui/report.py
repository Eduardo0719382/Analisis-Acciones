"""PDF analysis report (chart image + details + explained signals).

All external text (names, messages) is HTML-escaped before it is placed in
the document: data is never interpreted as markup.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QPixmap, QTextDocument

from analisis_acciones import __version__
from analisis_acciones.analysis.model import AnalysisReport
from analisis_acciones.data.details import AssetDetails
from analisis_acciones.ui import strings


def _png_base64(pixmap: QPixmap) -> str:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(data.toBase64().data()).decode("ascii")


def _muted(text: str) -> str:
    return f"<p style='color:#666'>{text}</p>"


def build_report_html(
    title: str,
    chart: QPixmap | None,
    details: AssetDetails | None,
    analysis: AnalysisReport | None,
    indicators: list[str],
    number: Callable[[float], str],
) -> str:
    generated = strings.REPORT_GENERATED.format(
        when=datetime.now().strftime("%d/%m/%Y %H:%M"), version=__version__
    )
    parts = [f"<h1>{escape(title)}</h1>", _muted(escape(generated))]
    if chart is not None and not chart.isNull():
        image = _png_base64(chart)
        parts.append(f"<p><img src='data:image/png;base64,{image}' width='640'></p>")
    if indicators:
        names = escape(", ".join(indicators))
        parts.append(f"<p><b>{escape(strings.REPORT_INDICATORS)}:</b> {names}</p>")
    if details is not None:
        rows = [
            (strings.DETAIL_PRICE, details.price),
            (strings.DETAIL_CHANGE_PCT, details.change_pct),
            (strings.DETAIL_OPEN, details.open),
            (strings.DETAIL_HIGH, details.high),
            (strings.DETAIL_LOW, details.low),
            (strings.DETAIL_PREV_CLOSE, details.previous_close),
            (strings.DETAIL_52W_HIGH, details.week52_high),
            (strings.DETAIL_52W_LOW, details.week52_low),
        ]
        cells = "".join(
            f"<tr><td>{escape(k)}</td>"
            f"<td align='right'>{escape('—' if v is None else number(v))}</td></tr>"
            for k, v in rows
        )
        name = escape(details.name or details.symbol)
        parts.append(f"<h2>{escape(strings.TAB_DETAILS)}: {name}</h2>")
        parts.append(f"<table cellpadding='3'>{cells}</table>")
    if analysis is not None:
        when = analysis.as_of.strftime("%d/%m/%Y") if analysis.as_of else "—"
        header = strings.REPORT_ANALYSIS_DATE.format(date=when, bars=analysis.bars_used)
        parts.append(f"<h2>{escape(strings.TAB_ANALYSIS)}</h2><p>{escape(header)}</p>")
        for signal in analysis.signals:
            evidence = "".join(f"<li>{escape(line)}</li>" for line in signal.evidence)
            parts.append(f"<p><b>{escape(signal.title)}</b></p><ul>{evidence}</ul>")
        if not analysis.signals:
            parts.append(f"<p>{escape(strings.ANALYSIS_NO_SIGNALS)}</p>")
        if analysis.skipped:
            parts.append(_muted("<br>".join(escape(s) for s in analysis.skipped)))
    parts.append(_muted(f"<i>{escape(strings.ANALYSIS_DISCLAIMER)}</i>"))
    return "\n".join(parts)


def write_pdf(path: Path, html: str) -> None:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setTitle(strings.APP_TITLE)
    document = QTextDocument()
    document.setHtml(html)
    layout = writer.pageLayout().paintRectPixels(writer.resolution())
    document.setPageSize(QSizeF(layout.width(), layout.height()))
    document.print_(writer)
