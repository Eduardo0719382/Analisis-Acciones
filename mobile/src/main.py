"""Análisis de Acciones for Android (Flet). Screens only: the logic is in
``analisis_acciones.mobile`` and is shared with the desktop program.

Tabs: Lista (watchlist and search), Escáner, Alertas and Ajustes. Tapping an asset
opens its page: price, candlestick chart, rule-based analysis and exhaustion signs.
Everything shown describes the data; nothing predicts or recommends.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import flet as ft
import flet.canvas as cv

from analisis_acciones.alerts.rules import AlertKind
from analisis_acciones.mobile.chart import PERIODS, geometry
from analisis_acciones.mobile.session import (
    DISCLAIMER,
    PHONE_ALERTS,
    AssetView,
    MobileSession,
    friendly_error,
)
from analisis_acciones.mobile.updates import (
    RELEASE_PAGE,
    current_build,
    latest_build,
    newer_than,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("analisis_acciones.mobile.app")

UP = "#2a78d6"
DOWN = "#e34948"
FLAT = "#8a8984"
SMA20 = "#1a9a55"
SMA50 = "#9a998f"
ALERT_EVERY_S = 15 * 60
TONE = {"up": UP, "down": DOWN, "flat": FLAT}


def data_dir() -> Path:
    """Private app storage on Android (set by Flet), a local folder elsewhere."""
    base = os.environ.get("FLET_APP_STORAGE_DATA") or str(Path.home() / ".analisis_acciones_movil")
    return Path(base)


def tone_of(change: float | None) -> str:
    if change is None or change == 0:
        return FLAT
    return UP if change > 0 else DOWN


def small(text: str, color: str | None = None) -> ft.Text:
    return ft.Text(text, size=12, color=color or ft.Colors.ON_SURFACE_VARIANT)


def section(title: str) -> ft.Text:
    return ft.Text(title, size=17, weight=ft.FontWeight.W_600)


# Chart ------------------------------------------------------------------------------------
def chart_canvas(view: AssetView, width: float, period: str, dark: bool) -> ft.Control:
    height = 250.0
    g = geometry(view.bars, width, height, period)
    shapes: list[Any] = []
    for c in g.candles:
        color = UP if c.up else DOWN
        shapes.append(cv.Line(c.x, c.high, c.x, c.low, paint=ft.Paint(color=color, stroke_width=1)))
        shapes.append(
            cv.Rect(
                c.x - c.width / 2,
                c.top,
                c.width,
                max(c.bottom - c.top, 1),
                paint=ft.Paint(color=color),
            )
        )
    for x, w, top, up in g.volume:
        shapes.append(
            cv.Rect(
                x - w / 2, top, w, height - top, paint=ft.Paint(color=(UP if up else DOWN) + "55")
            )
        )
    for points, color in ((g.sma50, SMA50), (g.sma20, SMA20)):
        if len(points) > 1:
            elements: list[Any] = [cv.Path.MoveTo(*points[0])]
            elements += [cv.Path.LineTo(x, y) for x, y in points[1:]]
            shapes.append(
                cv.Path(
                    elements,
                    paint=ft.Paint(color=color, stroke_width=1.6, style=ft.PaintingStyle.STROKE),
                )
            )
    from analisis_acciones.services.scan_report import num

    axis = ft.Row(
        [small(g.first), small(f"máx {num(g.price_high)} · mín {num(g.price_low)}"), small(g.last)],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    legend = ft.Row(
        [
            ft.Container(width=14, height=3, bgcolor=SMA20),
            small("Media 20"),
            ft.Container(width=14, height=3, bgcolor=SMA50),
            small("Media 50"),
            small("· barras: volumen"),
        ],
        spacing=6,
    )
    return ft.Column([cv.Canvas(shapes, width=width, height=height), axis, legend], spacing=4)


# App --------------------------------------------------------------------------------------
class MobileApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.session = MobileSession(data_dir())
        self.share = ft.Share()
        self.picker = ft.FilePicker()
        self.launcher = ft.UrlLauncher()
        self.haptics = ft.HapticFeedback()
        self.tab = 0
        self.period = "6M"
        self.current: AssetView | None = None
        self.body = ft.Container(expand=True)
        self.progress = ft.ProgressBar(visible=False)
        self.nav = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.LIST_ALT, label="Lista"),
                ft.NavigationBarDestination(icon=ft.Icons.RADAR, label="Escáner"),
                ft.NavigationBarDestination(icon=ft.Icons.NOTIFICATIONS, label="Alertas"),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, label="Ajustes"),
            ],
            on_change=self.on_tab,
        )
        self.appbar = ft.AppBar(
            title=ft.Text("Mi lista"),
            actions=[
                ft.IconButton(ft.Icons.REFRESH, tooltip="Actualizar", on_click=self.on_refresh),
            ],
        )

    # Plumbing -----------------------------------------------------------------------
    def start(self) -> None:
        page = self.page
        page.title = "Análisis de Acciones"
        page.theme = ft.Theme(color_scheme_seed=UP)
        page.dark_theme = ft.Theme(color_scheme_seed=UP)
        page.theme_mode = ft.ThemeMode.SYSTEM
        page.padding = 0
        page.on_app_lifecycle_state_change = self.on_lifecycle
        page.on_view_pop = self.on_view_pop
        page.views.clear()
        page.views.append(
            ft.View(
                route="/",
                appbar=self.appbar,
                navigation_bar=self.nav,
                controls=[self.progress, self.body],
                padding=0,
            )
        )
        page.update()
        self.show_list()
        page.run_task(self.alert_loop)

    def toast(self, text: str) -> None:
        self.page.show_dialog(ft.SnackBar(ft.Text(text), duration=4000))

    async def busy(self, work: Callable[[], Any], done: Callable[[Any], Any] | None = None) -> None:
        """Run blocking ``work`` off the UI thread; errors become a friendly message."""
        self.progress.visible = True
        self.page.update()
        try:
            result = await asyncio.to_thread(work)
        except Exception as exc:  # shown to the user, logged with its trace
            self.toast(friendly_error(exc))
            result = None
        finally:
            self.progress.visible = False
            self.page.update()
        if done is not None and result is not None:
            outcome = done(result)
            if isinstance(outcome, Awaitable):
                await outcome

    def on_tab(self, e: Any) -> None:
        self.tab = int(e.control.selected_index)
        [self.show_list, self.show_scanner, self.show_alerts, self.show_settings][self.tab]()

    async def on_refresh(self, _e: Any) -> None:
        if self.tab == 0:
            await self.refresh_list()
        elif self.tab == 2:
            await self.check_alerts(manual=True)

    def set_body(
        self, title: str, content: ft.Control, actions: list[ft.Control] | None = None
    ) -> None:
        self.appbar.title = ft.Text(title)
        self.appbar.actions = (
            actions
            if actions is not None
            else [ft.IconButton(ft.Icons.REFRESH, tooltip="Actualizar", on_click=self.on_refresh)]
        )
        self.body.content = content
        self.page.update()

    # Lista --------------------------------------------------------------------------
    def show_list(self) -> None:
        self.search = ft.TextField(
            hint_text="Buscar ticker, empresa o cripto",
            prefix_icon=ft.Icons.SEARCH,
            on_submit=self.on_search,
            dense=True,
        )
        self.results = ft.Column(spacing=0)
        self.rows = ft.ListView(expand=True, spacing=0)
        self.set_body(
            "Mi lista",
            ft.Column(
                [
                    ft.Container(self.search, padding=ft.Padding(12, 8, 12, 4)),
                    self.results,
                    self.rows,
                ],
                expand=True,
                spacing=0,
            ),
        )
        self.page.run_task(self.refresh_list)

    async def refresh_list(self) -> None:
        symbols = self.session.symbols()
        if not symbols:
            self.rows.controls = [self.empty_list()]
            self.page.update()
            return
        await self.busy(self.session.rows, self.fill_rows)

    def fill_rows(self, rows: list[Any]) -> None:
        tiles: list[ft.Control] = []
        for r in rows:
            change = ft.Container(
                ft.Text(r.change, color=ft.Colors.WHITE, size=13, weight=ft.FontWeight.W_600),
                bgcolor=tone_of(r.change_pct),
                border_radius=8,
                padding=ft.Padding(8, 3, 8, 3),
            )
            icon = ft.Icons.CURRENCY_BITCOIN if r.crypto else ft.Icons.SHOW_CHART
            tiles.append(
                ft.ListTile(
                    leading=ft.Icon(icon),
                    title=ft.Text(r.symbol, weight=ft.FontWeight.W_600),
                    subtitle=small(r.error or r.as_of),
                    trailing=ft.Row([ft.Text(r.price, size=15), change], tight=True, spacing=8),
                    on_click=lambda e, s=r.symbol: self.page.run_task(self.open_asset, s),
                    on_long_press=lambda e, s=r.symbol: self.confirm_remove(s),
                )
            )
            tiles.append(ft.Divider(height=1))
        tiles.append(ft.Container(small("Mantenga pulsado un activo para quitarlo."), padding=12))
        self.rows.controls = tiles
        self.page.update()

    def empty_list(self) -> ft.Control:
        def add(name: str) -> Callable[[Any], Any]:
            async def handler(_e: Any) -> None:
                self.session.add_example(name)
                await self.refresh_list()

            return handler

        return ft.Container(
            ft.Column(
                [
                    ft.Text("Su lista está vacía", size=18, weight=ft.FontWeight.W_600),
                    small(
                        "Busque un ticker arriba (AAPL, SPY, BTC-USD…) o empiece con un ejemplo:"
                    ),
                    ft.FilledButton("Acciones y fondos de EE. UU.", on_click=add("acciones")),
                    ft.FilledButton("Criptomonedas principales", on_click=add("cripto")),
                    ft.FilledButton("Altcoins", on_click=add("altcoins")),
                ],
                spacing=12,
            ),
            padding=20,
        )

    async def on_search(self, e: Any) -> None:
        query = str(e.control.value or "").strip()
        if not query:
            self.results.controls = []
            self.page.update()
            return

        def show(found: list[Any]) -> None:
            items: list[ft.Control] = [
                ft.ListTile(
                    title=ft.Text(f"{r.symbol} · {r.name}", max_lines=1),
                    subtitle=small(
                        r.exchange or ("criptomoneda" if r.asset_type == "CRYPTOCURRENCY" else "")
                    ),
                    trailing=ft.IconButton(
                        ft.Icons.ADD,
                        tooltip="Añadir a la lista",
                        on_click=lambda e, r=r: self.page.run_task(self.add, r),
                    ),
                    on_click=lambda e, s=r.symbol: self.page.run_task(self.open_asset, s),
                    dense=True,
                )
                for r in found
            ] or [ft.Container(small("Sin resultados."), padding=12)]
            items.append(ft.TextButton("Cerrar resultados", on_click=self.close_results))
            self.results.controls = items
            self.page.update()

        await self.busy(lambda: self.session.search(query), show)

    def close_results(self, _e: Any) -> None:
        self.results.controls = []
        self.search.value = ""
        self.page.update()

    async def add(self, result: Any) -> None:
        try:
            self.session.add(result.symbol)
            self.session.remember(result.symbol, result.name)
        except Exception as exc:
            self.toast(friendly_error(exc))
            return
        self.toast(f"{result.symbol} añadido a la lista.")
        self.results.controls = []
        self.search.value = ""
        await self.refresh_list()

    def confirm_remove(self, symbol: str) -> None:
        async def remove(_e: Any) -> None:
            self.page.pop_dialog()
            self.session.remove(symbol)
            await self.refresh_list()

        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text(f"¿Quitar {symbol} de la lista?"),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda e: self.page.pop_dialog()),
                    ft.FilledButton("Quitar", on_click=remove),
                ],
            )
        )

    # Asset page ---------------------------------------------------------------------
    async def open_asset(self, symbol: str) -> None:
        await self.busy(lambda: self.session.asset(symbol), self.show_asset)

    def show_asset(self, view: AssetView) -> None:
        self.current = view
        page = self.page
        if len(page.views) > 1:
            page.views.pop()
        in_list = view.symbol in self.session.symbols()
        star = ft.IconButton(
            ft.Icons.STAR if in_list else ft.Icons.STAR_BORDER,
            tooltip="Quitar de la lista" if in_list else "Añadir a la lista",
            on_click=self.toggle_star,
        )
        bell = ft.IconButton(
            ft.Icons.NOTIFICATION_ADD,
            tooltip="Nueva alerta",
            on_click=lambda e: self.new_alert(view.symbol),
        )
        page.views.append(
            ft.View(
                route=f"/activo/{view.symbol}",
                appbar=ft.AppBar(title=ft.Text(view.symbol), actions=[bell, star]),
                controls=[self.asset_content(view)],
                padding=0,
            )
        )
        page.update()

    def asset_content(self, view: AssetView) -> ft.Control:
        width = max(min((self.page.width or 400) - 32, 900), 240)
        header = ft.Column(
            [
                small(view.name) if view.name else ft.Container(),
                ft.Row(
                    [
                        ft.Text(view.price, size=30, weight=ft.FontWeight.W_700),
                        ft.Text(
                            view.change,
                            size=17,
                            color=tone_of(view.change_pct),
                            weight=ft.FontWeight.W_600,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                small(
                    f"Último dato: {view.as_of}"
                    + (
                        " (sesión en curso: el análisis usa la última vela cerrada)"
                        if view.in_progress
                        else ""
                    )
                ),
                *[small(n, DOWN) for n in view.notices],
            ],
            spacing=2,
        )
        periods = ft.SegmentedButton(
            segments=[ft.Segment(value=p, label=ft.Text(p)) for p in PERIODS],
            selected=[self.period],
            on_change=self.on_period,
            show_selected_icon=False,
        )
        dark = self.page.platform_brightness == ft.Brightness.DARK
        self.chart_box = ft.Container(chart_canvas(view, width, self.period, dark))
        signals: list[ft.Control] = [
            ft.ExpansionTile(
                title=ft.Text(s.title, size=14),
                leading=ft.Icon(ft.Icons.CIRCLE, color=TONE[s.tone], size=12),
                controls=[
                    ft.Container(small(line), padding=ft.Padding(16, 0, 16, 4))
                    for line in s.evidence
                ],
            )
            for s in view.signals
        ] or [small("Ninguna regla se cumple en la última vela cerrada.")]
        ex = view.exhaustion
        marks = {
            True: (ft.Icons.CHECK_CIRCLE, UP),
            False: (ft.Icons.CANCEL_OUTLINED, FLAT),
            None: (ft.Icons.REMOVE_CIRCLE_OUTLINE, FLAT),
        }
        exhaustion: list[ft.Control] = [
            ft.Container(
                ft.Text(ex.headline, size=14, weight=ft.FontWeight.W_600),
                border=ft.Border.only(left=ft.BorderSide(4, TONE[ex.tone])),
                padding=ft.Padding(10, 6, 6, 6),
            ),
            *[
                ft.Row(
                    [
                        ft.Icon(marks[met][0], color=marks[met][1], size=18),
                        ft.Text(
                            spans=[
                                ft.TextSpan(f"{name}: ", ft.TextStyle(weight=ft.FontWeight.W_600)),
                                ft.TextSpan(detail),
                            ],
                            size=13,
                            expand=True,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=8,
                )
                for met, name, detail in ex.conditions
            ],
            *[small(line) for line in ex.record],
            ft.Text(ex.reading, size=13, italic=True) if ex.reading else ft.Container(),
        ]
        return ft.ListView(
            [
                header,
                ft.Container(height=8),
                periods,
                self.chart_box,
                ft.Divider(),
                section("Análisis"),
                *signals,
                ft.Divider(),
                section("Agotamiento de la tendencia"),
                *exhaustion,
                ft.Divider(),
                small(DISCLAIMER),
                ft.Container(height=24),
            ],
            padding=16,
            spacing=6,
            expand=True,
        )

    def on_period(self, e: Any) -> None:
        selected = list(e.control.selected or [])
        if not selected or self.current is None:
            return
        self.period = str(selected[0])
        width = max(min((self.page.width or 400) - 32, 900), 240)
        dark = self.page.platform_brightness == ft.Brightness.DARK
        self.chart_box.content = chart_canvas(self.current, width, self.period, dark)
        self.page.update()

    async def toggle_star(self, e: Any) -> None:
        if self.current is None:
            return
        symbol = self.current.symbol
        if symbol in self.session.symbols():
            self.session.remove(symbol)
            e.control.icon = ft.Icons.STAR_BORDER
            self.toast(f"{symbol} quitado de la lista.")
        else:
            self.session.add(symbol)
            e.control.icon = ft.Icons.STAR
            self.toast(f"{symbol} añadido a la lista.")
        self.page.update()

    async def on_view_pop(self, _e: Any) -> None:
        if len(self.page.views) > 1:
            self.page.views.pop()
            self.current = None
            self.page.update()
            if self.tab == 0:
                await self.refresh_list()

    # Escáner ------------------------------------------------------------------------
    def show_scanner(self) -> None:
        self.scan_list = ft.ListView(expand=True, spacing=8, padding=12)
        self.scan_list.controls = [
            small(
                "Aplica las reglas del programa a todos los activos de su lista: tendencia, "
                "RSI, cruces, volumen, patrones y agotamiento."
            ),
            ft.FilledButton("Escanear mi lista", icon=ft.Icons.RADAR, on_click=self.on_scan),
        ]
        self.set_body("Escáner", self.scan_list, actions=[])

    async def on_scan(self, _e: Any) -> None:
        if not self.session.symbols():
            self.toast("Su lista está vacía: añada activos en la pestaña Lista.")
            return

        def show(result: tuple[list[Any], list[str]]) -> None:
            cards, problems = result
            items: list[ft.Control] = []
            for c in cards:
                items.append(
                    ft.Card(
                        ft.Container(
                            ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text(c.symbol, size=16, weight=ft.FontWeight.W_700),
                                            ft.Text(
                                                c.sentence, color=TONE[c.tone], size=13, expand=True
                                            ),
                                        ]
                                    ),
                                    *[self.detail_row(tone, text) for tone, text in c.details],
                                ],
                                spacing=3,
                            ),
                            padding=12,
                            border=ft.Border.only(left=ft.BorderSide(5, TONE[c.tone])),
                            on_click=lambda e, s=c.symbol: self.page.run_task(self.open_asset, s),
                        )
                    )
                )
            items += [small(p, DOWN) for p in problems]
            items.append(small(DISCLAIMER))
            self.scan_list.controls = items
            self.page.update()

        await self.busy(self.session.scan, show)

    @staticmethod
    def detail_row(tone: str, text: str) -> ft.Control:
        if not tone:
            return small(text)
        icon = ft.Icons.ARROW_UPWARD if tone == "up" else ft.Icons.ARROW_DOWNWARD
        return ft.Row([ft.Icon(icon, color=TONE[tone], size=16), small(text)], spacing=6)

    # Alertas ------------------------------------------------------------------------
    def show_alerts(self) -> None:
        self.nav.destinations[2].badge = None
        self.alert_list = ft.ListView(expand=True, spacing=0)
        actions: list[ft.Control] = [
            ft.IconButton(
                ft.Icons.ADD, tooltip="Nueva alerta", on_click=lambda e: self.new_alert("")
            ),
            ft.IconButton(ft.Icons.REFRESH, tooltip="Comprobar ahora", on_click=self.on_refresh),
        ]
        self.set_body("Alertas", self.alert_list, actions)
        self.fill_alerts()

    def fill_alerts(self) -> None:
        items: list[ft.Control] = []
        for a in self.session.alert_rows():
            items.append(
                ft.ListTile(
                    title=ft.Text(a.description, size=14),
                    subtitle=small(f"Último aviso: {a.last}" if a.last else "Aún no ha avisado"),
                    leading=ft.Switch(
                        value=a.enabled, on_change=lambda e, i=a.id: self.toggle_alert(i, e)
                    ),
                    trailing=ft.IconButton(
                        ft.Icons.DELETE_OUTLINE,
                        tooltip="Borrar",
                        on_click=lambda e, i=a.id: self.delete_alert(i),
                    ),
                )
            )
        if not items:
            items.append(
                ft.Container(
                    small(
                        "No hay alertas. Créelas con + o desde la página de un activo (campana)."
                    ),
                    padding=16,
                )
            )
        items += [
            ft.Container(
                ft.Row(
                    [
                        ft.OutlinedButton(
                            "Importar del PC",
                            icon=ft.Icons.FILE_DOWNLOAD,
                            on_click=self.import_alerts,
                        ),
                        ft.OutlinedButton(
                            "Enviar al PC", icon=ft.Icons.SHARE, on_click=self.export_alerts
                        ),
                    ],
                    wrap=True,
                ),
                padding=12,
            ),
            ft.Container(
                small(
                    "Se comprueban al abrir la app, al volver a ella y cada 15 minutos "
                    "mientras está abierta. Las de criptomonedas también de noche y en "
                    "fin de semana."
                ),
                padding=ft.Padding(16, 0, 16, 8),
            ),
            ft.Container(section("Historial"), padding=ft.Padding(16, 8, 16, 0)),
        ]
        history = self.session.history(30)
        items += [
            ft.ListTile(
                title=ft.Text(ev.description, size=13),
                subtitle=small(f"{ev.message} · {ev.triggered_at.astimezone():%d/%m %H:%M}"),
                dense=True,
            )
            for ev in history
        ]
        if not history:
            items.append(ft.Container(small("Todavía no ha saltado ninguna alerta."), padding=16))
        self.alert_list.controls = items
        self.page.update()

    def toggle_alert(self, alert_id: int, e: Any) -> None:
        self.session.toggle_alert(alert_id, bool(e.control.value))

    def delete_alert(self, alert_id: int) -> None:
        self.session.delete_alert(alert_id)
        self.fill_alerts()

    def new_alert(self, symbol: str) -> None:
        symbol_field = ft.TextField(
            label="Ticker", value=symbol, capitalization=ft.TextCapitalization.CHARACTERS
        )
        kind = ft.Dropdown(
            label="Condición",
            value=AlertKind.PRICE_ABOVE.value,
            options=[ft.DropdownOption(key=k.value, text=text) for k, text in PHONE_ALERTS.items()],
        )
        value = ft.TextField(label="Valor", keyboard_type=ft.KeyboardType.NUMBER)
        interval = ft.SegmentedButton(
            segments=[
                ft.Segment(value="1D", label=ft.Text("Vela diaria")),
                ft.Segment(value="1h", label=ft.Text("Vela de 1 hora")),
            ],
            selected=["1D"],
            show_selected_icon=False,
        )
        error = ft.Text("", color=DOWN, size=12)

        def create(_e: Any) -> None:
            try:
                number = float(str(value.value or "").replace(",", "."))
            except ValueError:
                error.value = "Escriba un número (por ejemplo 150 o 2,5)."
                self.page.update()
                return
            try:
                self.session.add_alert(
                    str(symbol_field.value or ""),
                    AlertKind(str(kind.value)),
                    number,
                    str((interval.selected or ["1D"])[0]),
                )
            except Exception as exc:
                error.value = friendly_error(exc)
                self.page.update()
                return
            self.page.pop_dialog()
            self.toast("Alerta creada.")
            if self.tab == 2 and len(self.page.views) == 1:
                self.fill_alerts()

        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text("Nueva alerta"),
                content=ft.Column(
                    [symbol_field, kind, value, interval, error], tight=True, spacing=12
                ),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda e: self.page.pop_dialog()),
                    ft.FilledButton("Crear", on_click=create),
                ],
            )
        )

    async def check_alerts(self, manual: bool = False) -> None:
        def done(summary: Any) -> None:
            if summary.events:
                self.page.run_task(self.haptics.vibrate)
                text = "; ".join(f"{e.description}" for e in summary.events[:3])
                self.toast(f"Alerta: {text}")
                if self.tab != 2:
                    self.nav.destinations[2].badge = str(len(summary.events))
            elif manual:
                self.toast(f"Comprobadas {summary.checked} alertas: ninguna nueva.")
            if self.tab == 2 and len(self.page.views) == 1:
                self.fill_alerts()
            self.page.update()

        if any(a.enabled for a in self.session.alert_rows()):
            await self.busy(self.session.check_alerts, done)
        elif manual:
            self.toast("No hay alertas activas.")

    async def alert_loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                await self.check_alerts()
            except Exception:
                logger.exception("Alert check failed")
            await asyncio.sleep(ALERT_EVERY_S)

    async def on_lifecycle(self, e: Any) -> None:
        if e.state == ft.AppLifecycleState.RESUME:
            await self.check_alerts()

    async def export_alerts(self, _e: Any) -> None:
        data = self.session.export_alerts().encode("utf-8")
        from flet.controls.services.share import ShareFile

        await self.share.share_files(
            [
                ShareFile.from_bytes(
                    data, mime_type="application/json", name="alertas_analisis_acciones.json"
                )
            ],
            text="Alertas de Análisis de Acciones: impórtelas en el PC "
            "(pestaña Alertas → Importar).",
        )

    async def import_alerts(self, _e: Any) -> None:
        files = await self.picker.pick_files(
            dialog_title="Archivo de alertas", allowed_extensions=["json"], with_data=True
        )
        if not files:
            return
        f = files[0]
        try:
            raw = (
                f.bytes
                if isinstance(f.bytes, bytes | bytearray)
                else Path(str(f.path)).read_bytes()
            )
            summary = self.session.import_alerts(bytes(raw).decode("utf-8"))
        except Exception as exc:
            self.toast(friendly_error(exc))
            return
        text = f"{summary.added} alertas importadas; {summary.duplicates} ya existían."
        if summary.problems:
            text += f" {len(summary.problems)} no válidas."
        self.toast(text)
        self.fill_alerts()

    # Ajustes ------------------------------------------------------------------------
    def show_settings(self) -> None:
        build = current_build()
        self.update_box = ft.Column()
        theme = ft.SegmentedButton(
            segments=[
                ft.Segment(value="system", label=ft.Text("Sistema")),
                ft.Segment(value="light", label=ft.Text("Claro")),
                ft.Segment(value="dark", label=ft.Text("Oscuro")),
            ],
            selected=[str(self.page.theme_mode.value if self.page.theme_mode else "system")],
            on_change=self.on_theme,
            show_selected_icon=False,
        )
        content = ft.ListView(
            [
                section("Versión"),
                ft.Text(
                    f"{build.version} · compilación {build.build or 'de desarrollo'}"
                    + (f" ({build.commit})" if build.commit else "")
                ),
                ft.FilledButton(
                    "Buscar actualización",
                    icon=ft.Icons.SYSTEM_UPDATE,
                    on_click=self.on_check_update,
                ),
                self.update_box,
                small(
                    "Cada vez que se actualiza el programa del PC se publica también una "
                    "versión nueva para el celular. Android no deja que una app se reinstale "
                    "sola: la app la descarga y usted confirma la instalación."
                ),
                ft.Divider(),
                section("Tema"),
                theme,
                ft.Divider(),
                section("Aviso"),
                small(DISCLAIMER),
            ],
            padding=16,
            spacing=10,
            expand=True,
        )
        self.set_body("Ajustes", content, actions=[])

    def on_theme(self, e: Any) -> None:
        mode = str((e.control.selected or ["system"])[0])
        self.page.theme_mode = ft.ThemeMode(mode)
        self.page.update()

    async def on_check_update(self, _e: Any) -> None:
        current = current_build()

        def show(result: tuple[Any]) -> None:
            (found,) = result
            if found is None:
                self.update_box.controls = [
                    ft.Text("Todavía no hay ninguna versión publicada."),
                    ft.TextButton(
                        "Ver versiones en GitHub",
                        on_click=lambda e: self.page.run_task(
                            self.launcher.launch_url, RELEASE_PAGE
                        ),
                    ),
                ]
            elif newer_than(current, found):
                self.update_box.controls = [
                    ft.Text(
                        f"Hay una versión nueva: compilación {found.build} ({found.size_mb} MB).",
                        color=UP,
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.FilledButton(
                        "Descargar e instalar",
                        icon=ft.Icons.FILE_DOWNLOAD,
                        on_click=lambda e: self.page.run_task(self.launcher.launch_url, found.url),
                    ),
                ]
            else:
                self.update_box.controls = [ft.Text("Tiene la última versión.")]
            self.page.update()

        await self.busy(lambda: (latest_build(),), show)


async def main(page: ft.Page) -> None:
    app = MobileApp(page)
    app.start()
    logger.info("MOBILE_APP_READY")  # the emulator smoke test waits for this line


if __name__ == "__main__":
    ft.run(main)
