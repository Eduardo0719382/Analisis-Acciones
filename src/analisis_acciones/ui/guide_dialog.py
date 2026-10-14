"""Ayuda → Guía de uso: the in-app guide in a read-only web view (no scripts)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from analisis_acciones.services.user_guide import guide_html
from analisis_acciones.ui import strings


class GuideDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.GUIDE_TITLE)
        self.resize(980, 760)
        self.view = QWebEngineView()
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.html = guide_html()
        self.view.setHtml(self.html, QUrl("about:blank"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
