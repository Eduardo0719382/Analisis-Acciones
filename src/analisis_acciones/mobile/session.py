"""Everything the phone screens need, prepared as plain values (no UI toolkit here).

The phone keeps its own database (watchlist, cached prices, alerts) and downloads
prices from Yahoo Finance over plain HTTPS. Texts are Spanish and describe the
data; nothing here predicts prices or recommends buying or selling.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from analisis_acciones.alerts.rules import AlertKind, AlertRule
from analisis_acciones.alerts.service import AlertEvent, AlertService, CheckSummary, ImportSummary
from analisis_acciones.analysis.engine import analyze
from analisis_acciones.analysis.exhaustion import (
    READ_CONTINUE,
    READ_FEW,
    READ_MIXED,
    READ_NO_EDGE,
    READ_NONE,
    READ_USEFUL,
    UP,
    Assessment,
    Outcome,
    assess,
    record_reading,
)
from analisis_acciones.analysis.model import Direction
from analisis_acciones.data.freshness import is_crypto
from analisis_acciones.models.errors import AppError, UserError
from analisis_acciones.models.market import Interval, SearchResult
from analisis_acciones.providers.base import MarketDataProvider
from analisis_acciones.providers.yahoo import YahooClient, YahooFinanceProvider
from analisis_acciones.providers.yahoo_http import YahooHttpClient
from analisis_acciones.services.api_keys import FileKeyStore, KeyStore, clean_key
from analisis_acciones.services.data_sources import build_router
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import num, verdict
from analisis_acciones.services.scanner import ScanResult, run_scan
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.services.watchlist_service import (
    ALTCOIN_EXAMPLE,
    CRYPTO_EXAMPLE,
    WatchlistService,
)
from analisis_acciones.storage.database import open_database
from analisis_acciones.storage.settings_repository import SettingsRepository

logger = logging.getLogger(__name__)

DATABASE = "analisis_acciones_movil.sqlite3"
EXAMPLES = {
    "acciones": ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"),
    "cripto": CRYPTO_EXAMPLE,
    "altcoins": ALTCOIN_EXAMPLE,
}
#: Alert conditions offered on the phone (value = the number the user types).
PHONE_ALERTS = {
    AlertKind.PRICE_ABOVE: "Cierre mayor que",
    AlertKind.PRICE_BELOW: "Cierre menor que",
    AlertKind.CHANGE_ABOVE: "Cambio del día mayor que %",
    AlertKind.CHANGE_BELOW: "Cambio del día menor que %",
    AlertKind.RSI_ABOVE: "RSI 14 mayor que",
    AlertKind.RSI_BELOW: "RSI 14 menor que",
}
DISCLAIMER = (
    "Herramienta de análisis técnico. Describe lo que muestran los datos con reglas fijas; no "
    "predice el futuro ni es una recomendación de inversión. Datos de Yahoo Finance, que "
    "pueden tener retrasos o errores."
)


@dataclass(frozen=True)
class ListRow:
    symbol: str
    price: str
    change: str
    change_pct: float | None
    as_of: str
    crypto: bool
    error: str | None = None


@dataclass(frozen=True)
class SignalLine:
    title: str
    tone: str  # "up", "down" or "flat"
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ExhaustionView:
    headline: str
    tone: str  # "up", "down" or "flat"
    conditions: list[tuple[bool | None, str, str]] = field(default_factory=list)
    record: list[str] = field(default_factory=list)
    reading: str = ""


@dataclass(frozen=True)
class AssetView:
    symbol: str
    name: str
    price: str
    change: str
    change_pct: float | None
    as_of: str
    bars: pd.DataFrame
    in_progress: bool
    source: str
    signals: list[SignalLine]
    exhaustion: ExhaustionView
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanCard:
    symbol: str
    tone: str
    sentence: str
    #: (tone, text): "up" / "down" for bullish / bearish signals, "" for plain facts.
    details: list[tuple[str, str]]


@dataclass(frozen=True)
class AlertRow:
    id: int
    description: str
    enabled: bool
    last: str


def _tone(direction: Direction) -> str:
    return {Direction.BULLISH: "up", Direction.BEARISH: "down"}.get(direction, "flat")


def _fmt(value: float, decimals: int = 2) -> str:
    return num(value, decimals)


def change_text(pct: float | None) -> str:
    return "—" if pct is None else f"{num(pct, 2, sign=True)} %"


def price_text(value: float | None) -> str:
    if value is None:
        return "—"
    decimals = 2 if abs(value) >= 1 else 6 if abs(value) < 0.01 else 4
    return num(value, decimals)


# Exhaustion in plain words -------------------------------------------------------------
_READINGS = {
    READ_NONE: "Sin historial suficiente para comparar.",
    READ_FEW: "Muy pocos casos: el historial no permite sacar conclusiones.",
    READ_MIXED: "Resultados contradictorios según el plazo: no hay conclusión.",
    READ_NO_EDGE: "En este activo estas señales no anticiparon giros mejor que un día "
    "cualquiera (diferencia pequeña o posible azar).",
}


def _reading(a: Assessment) -> str:
    code = record_reading(a.outcomes)
    if code in _READINGS:
        return _READINGS[code]
    rise = a.direction == UP
    if code == READ_USEFUL:
        return ("En este activo estas señales precedieron bajadas bastante más a menudo que un "
                "día cualquiera. Aun así, muchas veces la subida continuó." if rise else
                "En este activo estas señales precedieron rebotes bastante más a menudo que un "
                "día cualquiera. Aun así, muchas veces la bajada continuó.")  # fmt: skip
    assert code == READ_CONTINUE
    what = "subida" if rise else "bajada"
    return f"Tras estas señales la {what} continuó incluso más a menudo de lo normal."


def _record_line(o: Outcome, rise: bool) -> str:
    if not o.events or o.against_pct is None:
        return f"A {o.horizon} sesiones: sin casos anteriores comparables."
    moved = "bajó" if rise else "subió"
    base = "—" if o.baseline_against_pct is None else f"{num(o.baseline_against_pct, 0)} %"
    median = "—" if o.median_return is None else f"{num(o.median_return, 1, sign=True)} %"
    return (
        f"A {o.horizon} sesiones {moved} en {o.against} de {o.events} casos "
        f"({num(o.against_pct, 0)} %; un día normal: {base}). Variación mediana {median}."
    )


def exhaustion_view(a: Assessment) -> ExhaustionView:
    if a.direction is None:
        return ExhaustionView(a.reason or "Sin tendencia clara.", "flat")
    rise = a.direction == UP
    trend = "La subida" if rise else "La bajada"
    if a.signalled:
        headline = (f"{trend} muestra señales de agotamiento ({a.met} de {a.available}). "
                    "Puede continuar: las señales no dicen cuándo terminará.")  # fmt: skip
        tone = "down" if rise else "up"
    else:
        headline = f"{trend} sin señales claras de agotamiento ({a.met} de {a.available})."
        tone = "up" if rise else "down"
    conditions = [(c.met, c.name, c.detail) for c in a.conditions]
    record = [_record_line(o, rise) for o in a.outcomes]
    return ExhaustionView(headline, tone, conditions, record, _reading(a))


# Session ---------------------------------------------------------------------------------
class MobileSession:
    def __init__(self, root: Path, client: YahooClient | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 keys: KeyStore | None = None,
                 router: MarketDataProvider | None = None) -> None:  # fmt: skip
        root.mkdir(parents=True, exist_ok=True)
        path = root / DATABASE
        self._conn = open_database(path)
        self.settings = SettingsService(SettingsRepository(self._conn))
        self.keys: KeyStore = keys or FileKeyStore(root / "claves.json")
        yahoo = YahooFinanceProvider(client or YahooHttpClient())
        provider = router or build_router(yahoo, self.settings, self.keys)
        self.market = MarketDataService(provider, open_database(path), clock)
        self.alerts = AlertService(open_database(path), self.market, clock)
        self.lists = WatchlistService(self._conn)
        self._list_id = self.lists.lists()[0].id

    def close(self) -> None:
        self.alerts.close()
        self.market.close()
        self._conn.close()

    # Crypto source ----------------------------------------------------------------------
    def crypto_source(self) -> str:
        return self.settings.crypto_source()

    def set_crypto_source(self, source: str) -> None:
        self.settings.set_crypto_source(source)

    def stock_source(self) -> str:
        return self.settings.stock_source()

    def set_stock_source(self, source: str) -> None:
        self.settings.set_stock_source(source)

    def has_key(self, service: str) -> bool:
        return bool(self.keys.get(service))

    def save_key(self, service: str, key: str) -> None:
        self.keys.set(service, clean_key(service, key))

    def delete_key(self, service: str) -> None:
        self.keys.delete(service)

    # Watchlist ------------------------------------------------------------------------
    def symbols(self) -> list[str]:
        return self.lists.symbols(self._list_id)

    def add(self, symbol: str) -> bool:
        return self.lists.add(self._list_id, symbol)

    def remove(self, symbol: str) -> None:
        self.lists.remove(self._list_id, symbol)

    def add_example(self, name: str) -> int:
        """Add an example set (acciones, cripto, altcoins); returns how many were new."""
        return sum(self.lists.add(self._list_id, s) for s in EXAMPLES[name])

    def rows(self) -> list[ListRow]:
        out = []
        for r in self.market.snapshot(self.symbols()):
            out.append(ListRow(r.symbol, price_text(r.last_close), change_text(r.change_pct),
                               r.change_pct, f"{r.as_of:%d/%m/%Y}" if r.as_of else "",
                               is_crypto(r.symbol), r.error))  # fmt: skip
        return out

    def search(self, query: str) -> list[SearchResult]:
        return self.market.search(query, limit=12)

    # One asset ----------------------------------------------------------------------
    def asset(self, symbol: str) -> AssetView:
        loaded = self.market.load(symbol, Interval.D1)
        bars = loaded.series.bars
        closed = bars.iloc[:-1] if loaded.session_in_progress and len(bars) else bars
        closes = bars["close"]
        last = float(closes.iloc[-1])
        change = (last / float(closes.iloc[-2]) - 1) * 100 if len(closes) > 1 else None
        report = analyze(loaded.series.symbol, bars, session_in_progress=loaded.session_in_progress,
                         fmt=_fmt)  # fmt: skip
        signals = [SignalLine(s.title, _tone(s.direction), s.evidence) for s in report.signals]
        name = next((r.name for r in self.market.recent(50) if r.symbol == loaded.series.symbol
                     and r.name and r.name != r.symbol), "")  # fmt: skip
        notices = list(loaded.notices)
        if loaded.stale:
            notices.append("Datos guardados: no se pudo actualizar (¿sin conexión?).")
        return AssetView(
            loaded.series.symbol, name, price_text(last), change_text(change), change,
            f"{pd.Timestamp(bars.index[-1]):%d/%m/%Y}", bars, loaded.session_in_progress,
            loaded.series.source,
            signals, exhaustion_view(assess(closed, self.settings.exhaustion_params())),
            tuple(notices),
        )  # fmt: skip

    def remember(self, symbol: str, name: str | None) -> None:
        self.market.remember(symbol, name)

    # Scanner ------------------------------------------------------------------------
    def scan(self, progress: Callable[[int, int, str], None] | None = None) -> tuple[
        list[ScanCard], list[str]
    ]:  # fmt: skip
        params = self.settings.exhaustion_params()
        result: ScanResult = run_scan(self.market, self.symbols(), progress,
                                      exhaustion_params=params)  # fmt: skip
        cards = []
        for row in sorted(result.rows, key=lambda r: r.symbol):
            tone, _icon, sentence = verdict(row)
            details = [("", f"Cierre {price_text(row.close)} ({change_text(row.change_pct)})")]
            if row.rsi14 is not None:
                details.append(("", f"RSI 14: {num(row.rsi14, 1)}"))
            details += [("up", t) for t in row.bullish] + [("down", t) for t in row.bearish]
            if row.exhaustion:
                what = "subida" if row.exhaustion > 0 else "bajada"
                details.append(("", f"Agotamiento de la {what}: {abs(row.exhaustion)} de "
                                    f"{row.exhaustion_total} señales"))  # fmt: skip
            cards.append(ScanCard(row.symbol, tone, sentence, details))
        return cards, list(result.problems)

    # Alerts -------------------------------------------------------------------------
    def alert_rows(self) -> list[AlertRow]:
        return [AlertRow(r.id or 0, r.description, r.enabled,
                         f"{r.last_triggered_at.astimezone():%d/%m %H:%M}"
                         if r.last_triggered_at else "")
                for r in self.alerts.alerts()]  # fmt: skip

    def add_alert(self, symbol: str, kind: AlertKind, value: float,
                  interval: str = "1D") -> AlertRule:  # fmt: skip
        params: dict[str, float] = {"value": value}
        if kind in (AlertKind.RSI_ABOVE, AlertKind.RSI_BELOW):
            params["period"] = 14
        return self.alerts.create(symbol, kind, params, interval=interval)

    def toggle_alert(self, alert_id: int, enabled: bool) -> None:
        self.alerts.set_enabled(alert_id, enabled)

    def delete_alert(self, alert_id: int) -> None:
        self.alerts.delete(alert_id)

    def check_alerts(self) -> CheckSummary:
        return self.alerts.check_all()

    def history(self, limit: int = 50) -> list[AlertEvent]:
        return self.alerts.events(limit)

    def export_alerts(self) -> str:
        return self.alerts.export_json()

    def import_alerts(self, text: str) -> ImportSummary:
        return self.alerts.import_json(text)


def friendly_error(exc: BaseException) -> str:
    """Message for the user; never a stack trace."""
    if isinstance(exc, AppError | UserError):
        return exc.user_message
    logger.exception("Unexpected error", exc_info=exc)
    return "Algo salió mal. Inténtelo de nuevo."
