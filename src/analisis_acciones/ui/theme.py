"""Dark and light themes built from a small set of colour tokens."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from analisis_acciones.services.settings_service import Theme


@dataclass(frozen=True)
class ThemeTokens:
    background: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    up: str
    down: str
    grid: str


DARK = ThemeTokens(
    background="#0f1216",
    surface="#161a20",
    surface_alt="#1d222a",
    border="#2a303a",
    text="#e3e7ee",
    text_muted="#8a93a3",
    accent="#4c8dff",
    up="#26a69a",
    down="#ef5350",
    grid="#1c2129",
)

LIGHT = ThemeTokens(
    background="#f4f6f9",
    surface="#ffffff",
    surface_alt="#eef1f5",
    border="#d5dbe3",
    text="#1b2330",
    text_muted="#5f6b7c",
    accent="#2563eb",
    up="#00897b",
    down="#d32f2f",
    grid="#edf0f4",
)


def tokens_for(theme: Theme) -> ThemeTokens:
    return DARK if theme is Theme.DARK else LIGHT


def _palette(t: ThemeTokens) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.background,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.surface,
        QPalette.ColorRole.AlternateBase: t.surface_alt,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.surface_alt,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: t.surface_alt,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.text_muted,
        QPalette.ColorRole.Link: t.accent,
    }
    for role, colour in roles.items():
        p.setColor(role, QColor(colour))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.text_muted))
    return p


def _stylesheet(t: ThemeTokens) -> str:
    return f"""
    QMainWindow, QStatusBar {{ background: {t.background}; }}
    QToolBar {{ background: {t.surface}; border: none;
               border-bottom: 1px solid {t.border}; spacing: 6px; padding: 4px; }}
    QStatusBar {{ border-top: 1px solid {t.border}; color: {t.text_muted}; }}
    QStatusBar QLabel {{ color: {t.text_muted}; padding: 0 8px; }}
    QSplitter::handle {{ background: {t.border}; }}
    QFrame#panel {{ background: {t.surface}; }}
    QLabel#panelHeader {{ color: {t.text_muted}; font-weight: 600; padding: 6px 10px;
                         border-bottom: 1px solid {t.border}; background: {t.surface_alt}; }}
    QLabel#panelEmpty {{ color: {t.text_muted}; padding: 16px; }}
    QLabel#panelEmpty[error="true"] {{ color: {t.down}; }}
    QListWidget#searchPopup {{ background: {t.surface}; color: {t.text};
        border: 1px solid {t.border}; padding: 2px; }}
    QListWidget#searchPopup::item {{ padding: 4px 6px; }}
    QListWidget#searchPopup::item:selected {{ background: {t.accent}; color: #ffffff; }}
    QPushButton#updateNotice {{ background: transparent; border: none; color: {t.accent};
                               font-weight: 600; padding: 0 8px; }}
    QPushButton#updateNotice:hover {{ text-decoration: underline; }}
    QLabel#detailsSymbol {{ font-size: 18px; font-weight: 700; }}
    QLabel#detailsName {{ color: {t.text_muted}; padding-bottom: 8px; }}
    QLabel#detailsCaption {{ color: {t.text_muted}; }}
    QLabel#detailsValue {{ font-weight: 600; }}
    QLabel#detailsValue[direction="up"] {{ color: {t.up}; }}
    QLabel#detailsValue[direction="down"] {{ color: {t.down}; }}
    QLabel#detailsSource {{ color: {t.text_muted}; font-size: 11px; padding-top: 10px; }}
    QTabWidget::pane {{ border: none; background: {t.surface}; }}
    QTabBar::tab {{ background: {t.surface_alt}; color: {t.text_muted}; padding: 6px 14px;
                   border: none; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}
    QTreeWidget, QTableWidget {{ background: {t.surface}; border: none; }}
    QLabel#symbolLabel {{ font-weight: 700; font-size: 14px; padding: 0 8px; }}
    QLineEdit, QComboBox, QPushButton {{ background: {t.surface_alt}; color: {t.text};
        border: 1px solid {t.border}; border-radius: 4px; padding: 4px 8px; }}
    QLineEdit:focus {{ border-color: {t.accent}; }}
    """


def apply_theme(app: QApplication, theme: Theme) -> None:
    tokens = tokens_for(theme)
    app.setStyle("Fusion")
    app.setPalette(_palette(tokens))
    app.setStyleSheet(_stylesheet(tokens))
