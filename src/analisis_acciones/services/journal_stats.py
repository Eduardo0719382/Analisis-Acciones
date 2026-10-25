"""Statistics of the trading journal: how the closed (sold) trades went.

Computed only from the sales of a paper portfolio (each against the average
cost of the shares sold). They describe the past simulation; with few trades
they are not representative, and the report says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from analisis_acciones.portfolio.engine import ClosedTrade, PaperTrade

SMALL_SAMPLE = 10


@dataclass(frozen=True)
class SymbolStats:
    symbol: str
    sales: int
    winners: int
    result: float


@dataclass(frozen=True)
class JournalStats:
    sales: int
    winners: int
    losers: int
    total_result: float
    gross_gain: float
    gross_loss: float  # negative or 0
    average_gain: float | None
    average_loss: float | None  # negative
    best: ClosedTrade | None
    worst: ClosedTrade | None
    average_days_held: float | None
    by_symbol: list[SymbolStats]
    with_reason_pct: float | None  # trades (buys and sales) with a written reason
    with_review_pct: float | None  # trades with a written review

    @property
    def win_rate(self) -> float | None:
        return self.winners / self.sales * 100 if self.sales else None

    @property
    def profit_factor(self) -> float | None:
        return self.gross_gain / -self.gross_loss if self.gross_loss < 0 else None

    @property
    def payoff_ratio(self) -> float | None:
        if self.average_gain is None or not self.average_loss:
            return None
        return self.average_gain / -self.average_loss

    @property
    def small_sample(self) -> bool:
        return self.sales < SMALL_SAMPLE


def journal_stats(closed: Sequence[ClosedTrade], trades: Sequence[PaperTrade]) -> JournalStats:
    gains = [c.result for c in closed if c.result > 0]
    losses = [c.result for c in closed if c.result < 0]
    held = [(c.trade.trade_date - c.opened_on).days for c in closed if c.opened_on is not None]
    symbols: dict[str, list[ClosedTrade]] = {}
    for c in closed:
        symbols.setdefault(c.trade.symbol, []).append(c)
    by_symbol = sorted(
        (
            SymbolStats(s, len(cs), sum(1 for c in cs if c.result > 0), sum(c.result for c in cs))
            for s, cs in symbols.items()
        ),
        key=lambda x: -x.result,
    )

    def share(flags: list[bool]) -> float | None:
        return sum(flags) / len(flags) * 100 if flags else None

    return JournalStats(
        sales=len(closed),
        winners=len(gains),
        losers=len(losses),
        total_result=sum(c.result for c in closed),
        gross_gain=sum(gains),
        gross_loss=sum(losses),
        average_gain=sum(gains) / len(gains) if gains else None,
        average_loss=sum(losses) / len(losses) if losses else None,
        best=max(closed, key=lambda c: c.result) if closed else None,
        worst=min(closed, key=lambda c: c.result) if closed else None,
        average_days_held=sum(held) / len(held) if held else None,
        by_symbol=by_symbol,
        with_reason_pct=share([bool(t.note.strip()) for t in trades]),
        with_review_pct=share([bool(t.review.strip()) for t in trades]),
    )
