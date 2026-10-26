"""Typed access to persisted application settings.

Values read from storage are validated; anything unexpected falls back to the
default (and is logged) rather than propagating into the UI.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from analisis_acciones.analysis.exhaustion import Params as ExhaustionParams
from analisis_acciones.indicators.registry import IndicatorConfig
from analisis_acciones.indicators.templates import MAX_TEMPLATES, clean_name
from analisis_acciones.models.errors import AppError, UserError
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
KEY_INDICATORS = "chart.indicators"
KEY_WATCHLIST = "watchlist.current"
CHART_TYPES = ("candles", "line")
KEY_LAST_INTERVAL = "market.last_interval"
KEY_DAILY_SCAN = "scanner.daily_enabled"
KEY_VOLUME_PROFILE = "chart.volume_profile"
KEY_SUMMARY_ON_START = "ui.summary_on_start"
KEY_INDICATOR_TEMPLATES = "chart.indicator_templates"
KEY_BENCHMARK = "chart.benchmark"
KEY_BENCHMARK_ON = "chart.benchmark_on"
DEFAULT_BENCHMARK = "SPY"
KEY_SCAN_SNAPSHOT = "scanner.daily_snapshot"
KEY_PORTFOLIO_BENCHMARKS = "portfolio.benchmarks"
KEY_CALENDAR_DAYS = "scanner.calendar_notice_days"
KEY_CALENDAR_NOTIFIED = "scanner.calendar_notified"
KEY_EXHAUSTION = "analysis.exhaustion_params"
KEY_EXHAUSTION_MARKERS = "chart.exhaustion_markers"
KEY_CRYPTO_SOURCE = "data.crypto_source"
KEY_STOCK_SOURCE = "data.stock_source"
CRYPTO_SOURCES = ("yahoo", "coingecko", "twelvedata", "alphavantage", "finnhub")
STOCK_SOURCES = ("yahoo", "twelvedata", "alphavantage", "finnhub")
KEY_EXHAUSTION_PROVEN = "scanner.exhaustion_proven_only"
DEFAULT_CALENDAR_DAYS = 3
MAX_CALENDAR_DAYS = 30


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

    # Indicators ----------------------------------------------------------------
    def indicators(self) -> list[IndicatorConfig]:
        """Saved chart indicators; invalid stored entries are skipped (and logged)."""
        raw = self._repo.get(KEY_INDICATORS)
        if not isinstance(raw, list):
            return []
        configs: list[IndicatorConfig] = []
        for item in raw:
            try:
                configs.append(IndicatorConfig.from_dict(item))
            except (AppError, TypeError, ValueError, AttributeError):
                logger.warning("Ignoring invalid stored indicator %r", item)
        return configs

    def set_indicators(self, configs: list[IndicatorConfig]) -> None:
        self._repo.set(KEY_INDICATORS, [c.to_dict() for c in configs])

    # Indicator templates -----------------------------------------------------------
    def indicator_templates(self) -> dict[str, list[IndicatorConfig]]:
        """User templates (name -> configs); invalid stored entries are skipped."""
        raw = self._repo.get(KEY_INDICATOR_TEMPLATES)
        if not isinstance(raw, dict):
            return {}
        templates: dict[str, list[IndicatorConfig]] = {}
        for name, items in raw.items():
            if not isinstance(name, str) or not isinstance(items, list):
                continue
            configs = []
            for item in items:
                try:
                    configs.append(IndicatorConfig.from_dict(item))
                except (AppError, TypeError, ValueError, AttributeError):
                    logger.warning("Ignoring invalid indicator in template %r", name)
            templates[name] = configs
        return templates

    def save_indicator_template(self, name: str, configs: list[IndicatorConfig]) -> str:
        clean = clean_name(name)
        templates = self.indicator_templates()
        if clean not in templates and len(templates) >= MAX_TEMPLATES:
            raise UserError(
                "too many templates",
                user_message=f"Como máximo {MAX_TEMPLATES} plantillas propias.",
            )
        templates[clean] = list(configs)
        self._store_templates(templates)
        return clean

    def delete_indicator_template(self, name: str) -> None:
        templates = self.indicator_templates()
        templates.pop(name, None)
        self._store_templates(templates)

    def _store_templates(self, templates: dict[str, list[IndicatorConfig]]) -> None:
        self._repo.set(KEY_INDICATOR_TEMPLATES,
                       {n: [c.to_dict() for c in cs] for n, cs in templates.items()})  # fmt: skip

    # Watchlist -----------------------------------------------------------------
    def current_watchlist(self) -> int | None:
        raw = self._repo.get(KEY_WATCHLIST)
        return raw if isinstance(raw, int) and not isinstance(raw, bool) else None

    def set_current_watchlist(self, list_id: int) -> None:
        self._repo.set(KEY_WATCHLIST, int(list_id))

    # Layout ----------------------------------------------------------------
    def benchmark(self) -> str:
        raw = self._repo.get(KEY_BENCHMARK)
        return raw if isinstance(raw, str) and raw else DEFAULT_BENCHMARK

    def set_benchmark(self, symbol: str) -> None:
        self._repo.set(KEY_BENCHMARK, symbol)

    def portfolio_benchmarks(self) -> list[str]:
        """References for the paper portfolio (default: the chart's benchmark)."""
        raw = self._repo.get(KEY_PORTFOLIO_BENCHMARKS)
        if isinstance(raw, list) and raw and all(isinstance(s, str) for s in raw):
            return [str(s) for s in raw][:3]
        return [self.benchmark()]

    def set_portfolio_benchmarks(self, symbols: list[str]) -> None:
        self._repo.set(KEY_PORTFOLIO_BENCHMARKS, list(symbols)[:3])

    def benchmark_on(self) -> bool:
        return self._repo.get(KEY_BENCHMARK_ON) is True

    def set_benchmark_on(self, enabled: bool) -> None:
        self._repo.set(KEY_BENCHMARK_ON, bool(enabled))

    def summary_on_start(self) -> bool:
        return self._repo.get(KEY_SUMMARY_ON_START) is not False

    def set_summary_on_start(self, enabled: bool) -> None:
        self._repo.set(KEY_SUMMARY_ON_START, bool(enabled))

    def volume_profile(self) -> bool:
        return self._repo.get(KEY_VOLUME_PROFILE) is True

    def set_volume_profile(self, enabled: bool) -> None:
        self._repo.set(KEY_VOLUME_PROFILE, bool(enabled))

    # Daily scan ----------------------------------------------------------------
    def daily_scan_enabled(self) -> bool:
        return self._repo.get(KEY_DAILY_SCAN) is not False

    def set_daily_scan_enabled(self, enabled: bool) -> None:
        self._repo.set(KEY_DAILY_SCAN, bool(enabled))

    def scan_snapshot(self) -> dict[str, Any] | None:
        raw = self._repo.get(KEY_SCAN_SNAPSHOT)
        return raw if isinstance(raw, dict) else None

    def set_scan_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._repo.set(KEY_SCAN_SNAPSHOT, snapshot)

    def calendar_notice_days(self) -> int:
        """Days ahead to announce earnings/ex-dividend dates (0 = off)."""
        raw = self._repo.get(KEY_CALENDAR_DAYS)
        if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= MAX_CALENDAR_DAYS:
            return raw
        return DEFAULT_CALENDAR_DAYS

    def set_calendar_notice_days(self, days: int) -> None:
        self._repo.set(KEY_CALENDAR_DAYS, max(0, min(int(days), MAX_CALENDAR_DAYS)))

    def calendar_notified(self) -> list[str]:
        raw = self._repo.get(KEY_CALENDAR_NOTIFIED)
        return [str(k) for k in raw] if isinstance(raw, list) else []

    def set_calendar_notified(self, keys: list[str]) -> None:
        self._repo.set(KEY_CALENDAR_NOTIFIED, list(keys))

    # Exhaustion thresholds ------------------------------------------------------
    def exhaustion_params(self) -> ExhaustionParams:
        """Thresholds of the exhaustion signs (invalid stored values fall back to defaults)."""
        return ExhaustionParams.from_dict(self._repo.get(KEY_EXHAUSTION))

    def set_exhaustion_params(self, params: ExhaustionParams) -> None:
        self._repo.set(KEY_EXHAUSTION, params.to_dict())

    def exhaustion_proven_only(self) -> bool:
        """Daily scan: announce exhaustion only where it anticipated turns (default on)."""
        return self._repo.get(KEY_EXHAUSTION_PROVEN) is not False

    def set_exhaustion_proven_only(self, enabled: bool) -> None:
        self._repo.set(KEY_EXHAUSTION_PROVEN, bool(enabled))

    def stock_source(self) -> str:
        """Price source for stocks and funds (one of STOCK_SOURCES; default "yahoo")."""
        raw = self._repo.get(KEY_STOCK_SOURCE)
        return raw if raw in STOCK_SOURCES else "yahoo"

    def set_stock_source(self, source: str) -> None:
        if source not in STOCK_SOURCES:
            raise UserError(f"unknown source {source!r}", user_message="Fuente no válida.")
        self._repo.set(KEY_STOCK_SOURCE, source)

    def crypto_source(self) -> str:
        """Price source for cryptocurrencies (one of CRYPTO_SOURCES; default "yahoo")."""
        raw = self._repo.get(KEY_CRYPTO_SOURCE)
        return raw if raw in CRYPTO_SOURCES else "yahoo"

    def set_crypto_source(self, source: str) -> None:
        if source not in CRYPTO_SOURCES:
            raise UserError(f"unknown source {source!r}", user_message="Fuente no válida.")
        self._repo.set(KEY_CRYPTO_SOURCE, source)

    def exhaustion_markers(self) -> bool:
        return self._repo.get(KEY_EXHAUSTION_MARKERS) is True

    def set_exhaustion_markers(self, enabled: bool) -> None:
        self._repo.set(KEY_EXHAUSTION_MARKERS, bool(enabled))

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
