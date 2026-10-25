"""Chart view: a sandboxed QWebEngineView running Lightweight Charts.

Python owns all data and calculations; the page only draws what it is sent.
The page is local (bundled files), cannot reach the network, cannot navigate
away, and JavaScript errors are forwarded to the application log.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import QLocale, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QStackedLayout, QVBoxLayout, QWidget

from analisis_acciones.charts.payload import build_indicator_payload, build_payload
from analisis_acciones.indicators.registry import IndicatorConfig
from analisis_acciones.models.market import BarSeries
from analisis_acciones.services.drawing_service import Drawing
from analisis_acciones.ui import strings
from analisis_acciones.ui.theme import ThemeTokens
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

CHART_TYPES = ("candles", "line")
FALLBACK_LOCALE = "es-ES"
# Renderer failures: reload the page up to MAX_RECOVERIES times within RECOVERY_WINDOW_S.
MAX_RECOVERIES = 3
RECOVERY_WINDOW_S = 600.0
RECOVERY_DELAY_MS = 500


def chart_page_path() -> Path:
    return Path(str(resources.files("analisis_acciones.charts") / "web" / "chart.html"))


def chart_locale(bcp47: str) -> str:
    """BCP-47 tag for number/date formatting in the page; Spanish when unusable."""
    tag = bcp47.strip()
    if (
        not tag
        or tag.upper() == "C"
        or "POSIX" in tag.upper()
        or not all(part.isalnum() for part in tag.split("-"))
    ):
        return FALLBACK_LOCALE
    return tag


class _ChartPage(QWebEnginePage):
    """Local-only page: logs console output and blocks any navigation."""

    def __init__(self, allowed: QUrl, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._allowed = allowed

    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line: int,
        source: str,
    ) -> None:
        log = (
            logger.error
            if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel
            else logger.debug
        )
        log("chart.js:%s %s", line, message)

    def acceptNavigationRequest(
        self, url: QUrl | str, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        target = QUrl(url)
        if (
            is_main_frame
            and target.isLocalFile()
            and (target.toLocalFile() == self._allowed.toLocalFile())
        ):
            return True
        logger.warning("Blocked chart navigation to %s", target.toString())
        return False


MAX_BRIDGE_MESSAGE = 10_000


class ChartBridge(QObject):
    """Receives messages from the page. Their content is untrusted data."""

    drawing_created = Signal(str, list)  # kind, raw points
    drawing_cancelled = Signal()

    @Slot(str)
    def drawingCreated(self, message: str) -> None:
        if len(message) > MAX_BRIDGE_MESSAGE:
            logger.warning("Ignoring oversized message from chart page")
            return
        try:
            data = json.loads(message)
            kind, points = str(data["kind"]), list(data["points"])
        except (ValueError, KeyError, TypeError):
            logger.warning("Ignoring malformed drawing message from chart page")
            return
        self.drawing_created.emit(kind, points)

    @Slot()
    def drawingCancelled(self) -> None:
        self.drawing_cancelled.emit()


class ChartWidget(QWidget):
    """Shows either a message (no data / error) or the interactive chart."""

    ready = Signal()
    #: Labels of indicators that could not be computed for the current series.
    indicators_failed = Signal(list)
    #: The latest data/indicator payload was handed to the page.
    rendered = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartWidget")
        self._loaded = False
        self._pending: list[str] = []
        self._theme: ThemeTokens | None = None
        self._chart_type = "candles"
        self.current_series: BarSeries | None = None
        self._indicators: list[IndicatorConfig] = []
        self._title = ""
        self._render_seq = 0
        self._workers: set[Worker] = set()
        #: Latest overlay/drawing scripts, replayed after the page is reloaded.
        self._state_scripts: dict[str, str] = {}
        self._recovering = False
        self._crash_times: list[float] = []

        self.message = QLabel(strings.EMPTY_CHART)
        self.message.setObjectName("panelEmpty")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        message_page = QWidget()
        message_page.setObjectName("panel")
        QVBoxLayout(message_page).addWidget(self.message)

        page_url = QUrl.fromLocalFile(str(chart_page_path()))
        self.view = QWebEngineView()
        self.view.setPage(_ChartPage(page_url, self.view))
        self.bridge = ChartBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self._channel)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        settings = self.view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.page().renderProcessTerminated.connect(self._on_render_crash)

        self._stack = QStackedLayout(self)
        self._stack.addWidget(message_page)
        self._stack.addWidget(self.view)
        self._stack.setCurrentIndex(0)

        self.view.load(page_url)

    # Page lifecycle ----------------------------------------------------------
    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            logger.error("Chart page failed to load: %s", chart_page_path())
            self.show_message(strings.CHART_LOAD_ERROR, error=True)
            return
        self._loaded = True
        self._configure()
        if self._recovering:
            self._recovering = False
            self._pending.clear()  # superseded by the full replay below
            self._run(self._call("setChartType", self._chart_type))
            if self.current_series is not None:
                self._render(keep_range=False, replay_state=True)
                self._stack.setCurrentIndex(1)
            logger.info("Chart page recovered after a renderer failure")
        for script in self._pending:
            self.view.page().runJavaScript(script)
        self._pending.clear()
        self.ready.emit()

    def _on_render_crash(self, status: object, code: int) -> None:
        """The page's renderer process died: reload it and redraw (a few times at most)."""
        logger.error("Chart renderer terminated (status=%s, code=%s)", status, code)
        self._loaded = False
        now = time.monotonic()
        self._crash_times = [t for t in self._crash_times if now - t < RECOVERY_WINDOW_S]
        self._crash_times.append(now)
        if len(self._crash_times) > MAX_RECOVERIES:
            self.show_message(strings.CHART_RENDER_FAILED, error=True)
            return
        self.show_message(strings.CHART_RECOVERING)
        self._recovering = True
        QTimer.singleShot(RECOVERY_DELAY_MS, self._reload_page)

    def _reload_page(self) -> None:
        if shiboken6.isValid(self):
            self.view.load(QUrl.fromLocalFile(str(chart_page_path())))

    def _run(self, script: str) -> None:
        if self._loaded:
            self.view.page().runJavaScript(script)
        else:
            self._pending.append(script)

    @staticmethod
    def _call(function: str, argument: Any) -> str:
        # json.dumps produces a valid JS literal; allow_nan=False rejects NaN/inf.
        literal = json.dumps(argument, allow_nan=False)
        return f"window.chartApp && window.chartApp.{function}({literal});"

    def _configure(self) -> None:
        if self._theme is None:
            return
        locale = chart_locale(QLocale().bcp47Name())
        self._run(self._call("configure", {
            "theme": asdict(self._theme),
            "locale": locale,
            "labels": {
                "open": strings.LEGEND_OPEN, "high": strings.LEGEND_HIGH,
                "low": strings.LEGEND_LOW, "close": strings.LEGEND_CLOSE,
                "volume": strings.LEGEND_VOLUME,
            },
        }))  # fmt: skip

    # Public API --------------------------------------------------------------
    def set_theme(self, theme: ThemeTokens) -> None:
        self._theme = theme
        if self._loaded:
            self._configure()

    def set_chart_type(self, chart_type: str) -> None:
        self._chart_type = chart_type if chart_type in CHART_TYPES else "candles"
        self._run(self._call("setChartType", self._chart_type))

    @property
    def chart_type(self) -> str:
        return self._chart_type

    def show_series(self, series: BarSeries, title: str) -> None:
        if self._theme is None:
            raise RuntimeError("set_theme() must be called before show_series()")
        if series.bars.empty:
            self.show_message(strings.CHART_NO_DATA)
            return
        self.current_series = series
        self._title = title
        self._run(self._call("setChartType", self._chart_type))
        self._render(keep_range=False)
        self._stack.setCurrentIndex(1)

    def set_indicators(self, configs: list[IndicatorConfig]) -> None:
        """Replace the indicators drawn on the chart (recomputed for the current series)."""
        self._indicators = list(configs)
        if self.current_series is not None and self._theme is not None:
            self._render(keep_range=True)

    def _render(self, *, keep_range: bool, replay_state: bool = False) -> None:
        """Build the page payload in a worker thread; only the latest request is applied.

        Computing indicators and serialising ~10k bars takes long enough
        (100-300 ms) to stutter the UI if done on the main thread.
        """
        assert self.current_series is not None and self._theme is not None
        series, theme, indicators, title = (
            self.current_series, self._theme, list(self._indicators), self._title,
        )  # fmt: skip
        self._render_seq += 1
        seq = self._render_seq

        def job() -> tuple[str, list[str]]:
            payload = build_payload(series, title, theme.up, theme.down)
            payload["indicators"], failed = build_indicator_payload(
                indicators, series.bars, theme.up, theme.down, theme.text_muted
            )
            payload["keepRange"] = keep_range
            return self._call("setData", payload), failed

        def done(result: tuple[str, list[str]]) -> None:
            if not shiboken6.isValid(self) or seq != self._render_seq:
                return  # superseded by a newer request
            script, failed = result
            self._run(script)
            if replay_state:
                for state_script in self._state_scripts.values():
                    self._run(state_script)
            self.rendered.emit()
            if failed:
                self.indicators_failed.emit(failed)

        def fail(exc: BaseException) -> None:
            logger.error("Could not prepare chart data: %s", exc, exc_info=exc)
            if shiboken6.isValid(self) and seq == self._render_seq:
                self.show_message(strings.CHART_LOAD_ERROR, error=True)

        worker = start_worker(job, done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    @property
    def indicators(self) -> list[IndicatorConfig]:
        return list(self._indicators)

    # Overlays ----------------------------------------------------------------
    def set_overlay(self, group: str, items: list[dict[str, Any]]) -> None:
        """Replace one named group of overlay items (projection, Elliott, ...)."""
        script = (f"window.chartApp && window.chartApp.setOverlay({json.dumps(group)}, "
                  f"{json.dumps(items, allow_nan=False)});")  # fmt: skip
        self._state_scripts[f"overlay:{group}"] = script
        self._run(script)

    # Drawings ----------------------------------------------------------------
    def set_drawings(self, drawings: list[Drawing]) -> None:
        script = self._call("setDrawings", [d.to_payload() for d in drawings])
        self._state_scripts["drawings"] = script
        self._run(script)

    def set_draw_mode(self, mode: str | None) -> None:
        hints = {"first": strings.DRAW_HINTS.get(mode or "", ("", ""))[0],
                 "second": strings.DRAW_HINTS.get(mode or "", ("", ""))[1]}  # fmt: skip
        self._run(f"window.chartApp && window.chartApp.setDrawMode({json.dumps(mode)}, "
                  f"{json.dumps(hints)});")  # fmt: skip

    def show_message(self, text: str, *, error: bool = False) -> None:
        self.message.setText(text)
        self.message.setProperty("error", error)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self._stack.setCurrentIndex(0)

    @property
    def showing_chart(self) -> bool:
        return self._stack.currentIndex() == 1

    def evaluate(self, script: str, callback: Any) -> None:
        """Run a script in the page and pass its result to ``callback`` (tests, export)."""
        self.view.page().runJavaScript(script, 0, callback)
