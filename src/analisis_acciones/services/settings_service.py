"""Typed access to persisted application settings.

Values read from storage are validated; anything unexpected falls back to the
default (and is logged) rather than propagating into the UI.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from analisis_acciones.storage.settings_repository import SettingsRepository

logger = logging.getLogger(__name__)


class Theme(StrEnum):
    DARK = "dark"
    LIGHT = "light"


KEY_THEME = "ui.theme"
KEY_DISCLAIMER = "app.disclaimer_accepted"
KEY_LAYOUT = "ui.layout"
KEY_CHECK_UPDATES = "updates.check_on_startup"
KEY_LAST_SYMBOL = "market.last_symbol"
KEY_CHART_TYPE = "chart.type"
CHART_TYPES = ("candles", "line")
KEY_LAST_INTERVAL = "market.last_interval"


class SettingsService:
    def __init__(self, repository: SettingsRepository) -> None:
        self._repo = repository

    # Theme -----------------------------------------------------------------
    def theme(self) -> Theme:
        raw = self._repo.get(KEY_THEME)
        if raw is None:
            return Theme.DARK
        try:
            return Theme(raw)
        except ValueError:
            logger.warning("Invalid stored theme %r; using default", raw)
            return Theme.DARK

    def set_theme(self, theme: Theme) -> None:
        self._repo.set(KEY_THEME, Theme(theme).value)

    # Disclaimer ------------------------------------------------------------
    def disclaimer_accepted(self) -> bool:
        return self._repo.get(KEY_DISCLAIMER) is True

    def accept_disclaimer(self) -> None:
        self._repo.set(KEY_DISCLAIMER, True)

    # Updates ---------------------------------------------------------------
    def check_updates_on_startup(self) -> bool:
        return self._repo.get(KEY_CHECK_UPDATES) is not False

    def set_check_updates_on_startup(self, enabled: bool) -> None:
        self._repo.set(KEY_CHECK_UPDATES, bool(enabled))

    # Last opened symbol ------------------------------------------------------
    def last_symbol(self) -> str | None:
        raw = self._repo.get(KEY_LAST_SYMBOL)
        return raw if isinstance(raw, str) and 0 < len(raw) <= 40 else None

    def last_interval(self) -> str | None:
        raw = self._repo.get(KEY_LAST_INTERVAL)
        return raw if isinstance(raw, str) and len(raw) <= 5 else None

    def set_last_opened(self, symbol: str, interval: str) -> None:
        self._repo.set(KEY_LAST_SYMBOL, symbol)
        self._repo.set(KEY_LAST_INTERVAL, interval)

    # Chart -------------------------------------------------------------------
    def chart_type(self) -> str:
        raw = self._repo.get(KEY_CHART_TYPE)
        return raw if raw in CHART_TYPES else "candles"

    def set_chart_type(self, chart_type: str) -> None:
        if chart_type not in CHART_TYPES:
            raise ValueError(f"unknown chart type {chart_type!r}")
        self._repo.set(KEY_CHART_TYPE, chart_type)

    # Layout ----------------------------------------------------------------
    def layout(self) -> dict[str, Any]:
        """Opaque UI layout state (window geometry, splitter sizes, ...)."""
        raw = self._repo.get(KEY_LAYOUT)
        if not isinstance(raw, dict):
            if raw is not None:
                logger.warning("Invalid stored layout; ignoring")
            return {}
        return raw

    def set_layout(self, layout: dict[str, Any]) -> None:
        self._repo.set(KEY_LAYOUT, layout)

    def reset_layout(self) -> None:
        self._repo.delete(KEY_LAYOUT)
