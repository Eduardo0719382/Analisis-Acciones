"""Figures for the weekly review: per profile, net of costs, against buy-and-hold.

Every number comes from the store (filled orders, equity snapshots, recorded prices); a
figure that cannot be computed is shown as "—", never estimated.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from analisis_acciones.lab import costs
from analisis_acciones.lab.book import Book, max_drawdown
from analisis_acciones.lab.profiles import LabProfile
from analisis_acciones.lab.store import Store

BENCHMARKS = ("SPY", "QQQ", "BTC-USD")


@dataclass(frozen=True)
class ProfileFigures:
    id: str
    nombre: str
    estado: str
    inicio: str
    capital: float
    valor: float
    rentabilidad_pct: float
    caida_max_pct: float
    operaciones: int
    acierto_pct: float | None
    comisiones: float
    realizado: float
    latente: float
    efectivo: float
    referencias: dict[str, float | None]
    decisiones: dict[str, int]

    def row(self) -> str:
        refs = " · ".join(f"{k.replace('-USD', '')} {_pct(v)}" for k, v in self.referencias.items())
        hit = "—" if self.acierto_pct is None else f"{self.acierto_pct:.0f} %"
        return (f"| {self.id} {self.nombre} | {self.estado} | {self.valor:,.2f} | "
                f"{self.rentabilidad_pct:+.2f} % | {self.caida_max_pct:.2f} % | "
                f"{self.operaciones} | {hit} | {self.comisiones:,.2f} | {refs} |")  # fmt: skip


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f} %"


def benchmark_return(
    store: Store, symbol: str, since: str, price_now: float | None
) -> float | None:
    """Buy and hold ``symbol`` with the same money from ``since``, after its buy fee."""
    start = store.price_at_or_after(symbol, since)
    if not start or not price_now:
        return None
    fee = costs.CRYPTO_TAKER if symbol.endswith("-USD") else 0.0
    return ((1 - fee) * price_now / start - 1) * 100


def figures(store: Store, profile: LabProfile, book: Book, prices: Mapping[str, float],
            since: str | None = None) -> ProfileFigures:  # fmt: skip
    started, capital = store.profile_start(profile.id) or ("", profile.capital)
    value = book.value(prices)
    curve = [float(r["equity"]) for r in store.snapshots(profile.id)] + [value]
    kinds = Counter(str(r["kind"]) for r in store.decisions(profile.id, since=since))
    return ProfileFigures(
        id=profile.id, nombre=profile.nombre, estado=profile.estado, inicio=started[:16],
        capital=capital, valor=value, rentabilidad_pct=(value / capital - 1) * 100,
        caida_max_pct=max_drawdown([capital, *curve]), operaciones=book.trades,
        acierto_pct=(book.winning_sells / book.closed_sells * 100) if book.closed_sells else None,
        comisiones=book.fees, realizado=book.realized, latente=book.unrealized(prices),
        efectivo=book.cash,
        referencias={s: benchmark_return(store, s, started, prices.get(s)) for s in BENCHMARKS},
        decisiones=dict(kinds),
    )  # fmt: skip


def render_markdown(rows: list[ProfileFigures], title: str, notes: list[str]) -> str:
    lines = [
        f"## {title}", "",
        "Rentabilidad neta de comisiones y tasas, con precios de ejecución reales. Referencias: "
        "comprar y mantener con los mismos 100 USD desde el inicio de cada perfil.", "",
        "| Perfil | Estado | Valor | Neto | Caída máx. | Operaciones | Acierto | Costes | "
        "SPY · QQQ · BTC |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
        *(r.row() for r in rows),
    ]  # fmt: skip
    if notes:
        lines += ["", "Avisos de reconciliación:", *(f"- {n}" for n in notes)]
    return "\n".join(lines)


def decisions_dump(store: Store, profile_id: str, since: str | None) -> list[dict[str, Any]]:
    """The agent's decisions with what the executor did, oldest first (for the audit)."""
    out = []
    for r in reversed(store.decisions(profile_id, since=since)):
        out.append({"fecha": r["at"], "tipo": r["kind"], "motivo": r["reason"],
                    "propuesta": json.loads(r["payload"] or "{}"),
                    "resultado": json.loads(r["outcome"] or "{}"),
                    "efectivo": r["cash"], "valor": r["equity"]})  # fmt: skip
    return out
