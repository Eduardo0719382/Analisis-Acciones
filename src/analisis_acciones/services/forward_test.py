"""Forward test of the strategy profiles with virtual money (no broker involved).

Every profile gets ``BUDGET`` dollars, split into two sleeves: a stock ETF and a
cryptocurrency. The test is *replayed* from its start date each time it runs: the signals
are computed on all the completed bars, and the virtual orders (long-only, filled at the
open of the next bar, with the same costs as the backtest) are simulated from the start
date on. So the result depends only on the start date and on the data, and a missed run
loses nothing, not even for the hourly profiles.

Only completed bars are used: the bar still in progress would repaint its signal.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from analisis_acciones.backtesting.engine import BacktestConfig, run_backtest
from analisis_acciones.data.resample import resample_daily
from analisis_acciones.models.market import Interval
from analisis_acciones.strategies.profiles import PROFILES, Profile
from analisis_acciones.strategies.registry import STRATEGY_REGISTRY

BUDGET = 100.0
SLIPPAGE_PCT = 0.05


@dataclass(frozen=True)
class Sleeve:
    symbol: str
    label: str
    commission_pct: float  # percent of each order's value


SLEEVES = (
    Sleeve("QQQ", "Acciones (QQQ)", 0.0),
    Sleeve("BTC-USD", "Cripto (BTC-USD)", 0.25),
)

#: (symbol, interval) -> bars. Daily bars are resampled for weekly and monthly profiles.
Fetch = Callable[[str, Interval], pd.DataFrame]


@dataclass(frozen=True)
class SleeveResult:
    sleeve: Sleeve
    start_value: float
    value: float
    closed_trades: int
    open_position: str | None  # e.g. "0.0012 BTC-USD desde 2026-10-26 a 67,000.00"
    pending: str | None  # "buy" / "sell" decided on the last completed bar
    buy_and_hold_pct: float | None
    last_bar: str


@dataclass(frozen=True)
class ProfileResult:
    profile: Profile
    sleeves: tuple[SleeveResult, ...]

    @property
    def start_value(self) -> float:
        return sum(s.start_value for s in self.sleeves)

    @property
    def value(self) -> float:
        return sum(s.value for s in self.sleeves)

    @property
    def return_pct(self) -> float:
        return (self.value / self.start_value - 1) * 100 if self.start_value else 0.0


def completed(bars: pd.DataFrame, interval: Interval, now: datetime) -> pd.DataFrame:
    """``bars`` without the last one when its period has not finished yet."""
    if bars.empty:
        return bars
    last = pd.Timestamp(bars.index[-1])
    today = pd.Timestamp(now.date())
    if interval.is_intraday:
        unfinished = True  # Yahoo's last hourly bar is the one in progress
    elif interval is Interval.D1:
        unfinished = last.normalize().tz_localize(None) >= today
    elif interval is Interval.W1:
        week_end = last.tz_localize(None).to_period("W-SUN").end_time.normalize()
        unfinished = today <= week_end
    else:
        unfinished = (last.year, last.month) == (today.year, today.month)
    return bars.iloc[:-1] if unfinished else bars


def _since(index: pd.DatetimeIndex, start: datetime) -> pd.Series:
    stamp = pd.Timestamp(start)
    stamp = stamp.tz_convert(None) if index.tz is None else stamp.tz_convert(index.tz)
    return pd.Series(index >= stamp, index=index)


def run_sleeve(profile: Profile, sleeve: Sleeve, bars: pd.DataFrame, start: datetime,
               budget: float) -> SleeveResult:  # fmt: skip
    spec = STRATEGY_REGISTRY[profile.strategy_id]
    params = profile.validated_params()
    bars = bars.dropna(subset=["open", "high", "low", "close"])
    signals = spec.signals(bars, params).reindex(bars.index).fillna(False)
    mask = _since(pd.DatetimeIndex(bars.index), start)
    live, live_signals = bars[mask], signals[mask]
    if len(live) < 2:  # nothing has happened yet since the start
        last = "—" if bars.empty else str(pd.Timestamp(bars.index[-1]))[:16]
        return SleeveResult(sleeve, budget, budget, 0, None, None, None, last)
    config = BacktestConfig(initial_capital=budget, commission_pct=sleeve.commission_pct,
                            slippage_pct=SLIPPAGE_PCT, fractional=True)  # fmt: skip
    result = run_backtest(live, live_signals, config)
    open_trade = result.open_trade
    position = (
        f"{open_trade.shares:.6g} {sleeve.symbol} desde {open_trade.entry_date} a "
        f"{open_trade.entry_price:,.2f}" if open_trade else None
    )  # fmt: skip
    return SleeveResult(
        sleeve=sleeve,
        start_value=budget,
        value=float(result.equity.iloc[-1]),
        closed_trades=len(result.trades),
        open_position=position,
        pending=result.pending_signal,
        buy_and_hold_pct=(float(live["close"].iloc[-1]) / float(live["open"].iloc[0]) - 1) * 100,
        last_bar=str(pd.Timestamp(live.index[-1]))[:16],
    )


def run_all(fetch: Fetch, start: datetime, now: datetime | None = None,
            budget: float = BUDGET) -> list[ProfileResult]:  # fmt: skip
    now = now or datetime.now(UTC)
    cache: dict[tuple[str, Interval], pd.DataFrame] = {}

    def bars_for(symbol: str, interval: Interval) -> pd.DataFrame:
        key = (symbol, interval)
        if key not in cache:
            if interval in (Interval.W1, Interval.MN1):
                raw = resample_daily(bars_for(symbol, Interval.D1), interval)
            else:
                raw = fetch(symbol, interval)
            cache[key] = completed(raw, interval, now)
        return cache[key]

    results = []
    for profile in PROFILES:
        sleeves = tuple(
            run_sleeve(profile, sleeve, bars_for(sleeve.symbol, profile.interval), start,
                       budget / len(SLEEVES))
            for sleeve in SLEEVES
        )  # fmt: skip
        results.append(ProfileResult(profile, sleeves))
    return results


def render_report(results: list[ProfileResult], start: datetime, now: datetime,
                  hypothetical: bool = False) -> str:  # fmt: skip
    kind = "Reproducción histórica (no es una prueba en vivo)" if hypothetical else \
        "Prueba hacia adelante"  # fmt: skip
    lines = [
        f"# {kind} de los 12 perfiles — {BUDGET:,.0f} USD virtuales cada uno",
        f"Inicio: {start:%Y-%m-%d %H:%M} UTC · Corte: {now:%Y-%m-%d %H:%M} UTC · "
        f"{len(SLEEVES)} tramos por perfil: "
        + ", ".join(f"{s.label} (comisión {s.commission_pct:g} %)" for s in SLEEVES)
        + ".",
        "Solo compras y ventas de lo comprado; sin dinero real ni órdenes en ningún broker.",
        "",
        "| Perfil | Valor (USD) | Resultado | Operaciones cerradas | Posición abierta | "
        "Próxima orden |",
        "|---|---:|---:|---:|---|---|",
    ]
    for r in results:
        closed = sum(s.closed_trades for s in r.sleeves)
        held = "; ".join(s.open_position for s in r.sleeves if s.open_position) or "en efectivo"
        nxt = "; ".join(f"{'comprar' if s.pending == 'buy' else 'vender'} {s.sleeve.symbol}"
                        for s in r.sleeves if s.pending) or "—"  # fmt: skip
        lines.append(f"| {r.profile.name} | {r.value:,.2f} | {r.return_pct:+.1f} % | {closed} | "
                     f"{held} | {nxt} |")  # fmt: skip
    best = max(results, key=lambda r: r.return_pct)
    worst = min(results, key=lambda r: r.return_pct)
    total = sum(r.value for r in results)
    lines += [
        "",
        f"Mejor: {best.profile.name} ({best.return_pct:+.1f} %). "
        f"Peor: {worst.profile.name} ({worst.return_pct:+.1f} %). "
        f"Conjunto: {total:,.2f} de {BUDGET * len(results):,.0f} USD.",
        "Comprar y mantener en el mismo periodo: "
        + ", ".join(
            f"{s.sleeve.symbol} {s.buy_and_hold_pct:+.1f} %"
            for s in results[0].sleeves
            if s.buy_and_hold_pct is not None
        )
        + ".",
        "Resultados de simulación: no garantizan lo que ocurriría con dinero real ni son "
        "asesoramiento financiero.",
    ]
    return "\n".join(lines)


# -- state ----------------------------------------------------------------------------------


def load_start(path: Path) -> datetime | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(str(data["start"]))
    except (OSError, ValueError, KeyError):
        return None


def save_start(path: Path, start: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"start": start.isoformat(), "budget": BUDGET}), encoding="utf-8")
