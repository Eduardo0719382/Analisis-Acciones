"""Render an HTML string to PDF with Chromium (QtWebEngine) so CSS layout, SVG and
print rules come out as on screen. JavaScript is disabled for the page."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QMarginsF, QObject, QUrl
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

logger = logging.getLogger(__name__)


class HtmlPdfWriter(QObject):
    """One-shot writer. ``done(ok)`` is called once, after the file is written or on failure."""

    def __init__(self, html: str, path: Path, done: Callable[[bool], None],
                 parent: QObject | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._path = path
        self._done: Callable[[bool], None] | None = done
        self._page = QWebEnginePage(self)
        settings = self._page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self._page.loadFinished.connect(self._loaded)
        self._page.pdfPrintingFinished.connect(self._printed)
        self._page.setHtml(html, QUrl("about:blank"))

    def _loaded(self, ok: bool) -> None:
        if not ok:
            logger.error("Report page failed to load for PDF")
            self._finish(False)
            return
        layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                             QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)  # fmt: skip
        self._page.printToPdf(str(self._path), layout)

    def _printed(self, _path: str, ok: bool) -> None:
        self._finish(ok)

    def _finish(self, ok: bool) -> None:
        done, self._done = self._done, None
        if done is not None:
            done(ok)
        self.deleteLater()
