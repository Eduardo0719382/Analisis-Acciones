"""Paper portfolios: persistence, price lookup and valuation (no real money involved)."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

import pandas as pd

from analisis_acciones.models.errors import AppError, InternalError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.portfolio.engine import (
    BUY,
    DIVIDEND,
    SELL,
    SPLIT,
    AppliedEvent,
    ClosedTrade,
    CorporateEvent,
    PaperTrade,
    Valuation,
    adjust_for_splits,
    daily_values,
    replay,
    split_factor_after,
    value,
)
from analisis_acciones.portfolio.rebalance import RebalancePlan, plan_rebalance
from analisis_acciones.providers.base import normalize_symbol
from analisis_acciones.services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

DEFAULT_NAME = "Mi cartera"
DEFAULT_CASH = 10_000.0
MAX_NAME = 40


MAX_TEXT = 500
REBALANCE_NOTE = "Rebalanceo hacia los pesos objetivo"
QUANTITY_DECIMALS = 6


@dataclass(frozen=True)
class Portfolio:
    id: int
    name: str
    initial_cash: float
    commission_fixed: float = 0.0  # per trade, in dollars
    commission_pct: float = 0.0  # percent of the traded value
    commission_min: float = 0.0  # minimum per trade, in dollars
    apply_dividends: bool = True
    dividend_withholding_pct: float = 0.0  # withheld from each dividend
    capital_gains_tax_pct: float = 0.0  # estimate on each year's net realised gains

    def commission_for(self, value: float) -> float:
        """Commission of a trade of ``value`` dollars under this portfolio's schedule."""
        fee = self.commission_fixed + value * self.commission_pct / 100
        return round(max(fee, self.commission_min), 2) if fee or self.commission_min else 0.0


@dataclass(frozen=True)
class PortfolioReport:
    portfolio: Portfolio
    trades: list[PaperTrade]  # as entered (real prices and quantities)
    valuation: Valuation
    equity: pd.Series  # daily total value
    benchmark: pd.Series  # benchmark rebased to the initial cash, same days (may be empty)
    benchmark_symbol: str
    problems: list[str]
    # Sales with their result (quantities and prices in the units of their day), oldest first.
    closed: list[ClosedTrade] = field(default_factory=list)
    # Market value per symbol per day (same days as ``equity``).
    position_values: pd.DataFrame = field(default_factory=pd.DataFrame)
    # (year, net realised result, estimated tax) for years with sales.
    taxes: list[tuple[int, float, float]] = field(default_factory=list)
    # Dividends and splits that affected the portfolio, in the share units of their day
    # (``shares`` is the count after the event for a split).
    events: list[AppliedEvent] = field(default_factory=list)


class PaperPortfolioService:
    def __init__(self, conn: sqlite3.Connection, market: MarketDataService,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:  # fmt: skip
        self._conn = conn
        self._market = market
        self._clock = clock
        self._lock = threading.RLock()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    # Portfolios ------------------------------------------------------------------
    def portfolios(self) -> list[Portfolio]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM paper_portfolios ORDER BY id")
            found = [Portfolio(r["id"], r["name"], r["initial_cash"], r["commission_fixed"],
                               r["commission_pct"], r["commission_min"],
                               bool(r["apply_dividends"]), r["dividend_withholding_pct"],
                               r["capital_gains_tax_pct"]) for r in rows.fetchall()]  # fmt: skip
        return found or [self.create(DEFAULT_NAME, DEFAULT_CASH)]

    def set_costs(self, portfolio_id: int, fixed: float, pct: float, minimum: float,
                  apply_dividends: bool = True) -> Portfolio:  # fmt: skip
        """Commission schedule for new trades (existing trades keep theirs)."""
        if fixed < 0 or minimum < 0 or not 0 <= pct < 10:
            raise UserError(
                "bad commission schedule",
                user_message="Comisión no válida: importes ≥ 0 y porcentaje < 10 %.",
            )
        with self._db() as db:
            db.execute(
                "UPDATE paper_portfolios SET commission_fixed = ?, commission_pct = ?, "
                "commission_min = ?, apply_dividends = ? WHERE id = ?",
                (float(fixed), float(pct), float(minimum), int(apply_dividends), portfolio_id),
            )
        return self._portfolio(portfolio_id)

    def set_taxes(self, portfolio_id: int, dividend_withholding_pct: float,
                  capital_gains_tax_pct: float) -> Portfolio:  # fmt: skip
        """Tax rates of the simulation (applied to the whole history when it is recalculated)."""
        rates = (dividend_withholding_pct, capital_gains_tax_pct)
        if not all(0 <= r <= 60 for r in rates):
            raise UserError(
                "bad tax rate",
                user_message="Los porcentajes de impuestos deben estar entre 0 y 60.",
            )
        portfolio = self._portfolio(portfolio_id)
        trades = self.trades(portfolio_id)
        updated = replace(portfolio, dividend_withholding_pct=float(rates[0]),
                          capital_gains_tax_pct=float(rates[1]))  # fmt: skip
        self._check(updated, trades)  # a higher withholding can leave too little cash later
        with self._db() as db:
            db.execute(
                "UPDATE paper_portfolios SET dividend_withholding_pct = ?, "
                "capital_gains_tax_pct = ? WHERE id = ?",
                (float(rates[0]), float(rates[1]), portfolio_id),
            )
        return updated

    def create(self, name: str, initial_cash: float) -> Portfolio:
        clean = " ".join(str(name).split())
        if not clean or len(clean) > MAX_NAME:
            raise UserError(
                "bad portfolio name",
                user_message=f"El nombre debe tener entre 1 y {MAX_NAME} caracteres.",
            )
        if not 0 < initial_cash <= 1e12:
            raise UserError("bad cash", user_message="El capital inicial debe ser positivo.")
        with self._db() as db:
            try:
                cursor = db.execute(
                    "INSERT INTO paper_portfolios (name, initial_cash, created_at) "
                    "VALUES (?, ?, ?)",
                    (clean, float(initial_cash), self._clock().isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise UserError(
                    "duplicate portfolio", user_message=f"Ya existe una cartera llamada «{clean}»."
                ) from exc
        return Portfolio(int(cursor.lastrowid or 0), clean, float(initial_cash))

    def delete(self, portfolio_id: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM paper_trades WHERE portfolio_id = ?", (portfolio_id,))
            db.execute("DELETE FROM paper_targets WHERE portfolio_id = ?", (portfolio_id,))
            db.execute("DELETE FROM paper_portfolios WHERE id = ?", (portfolio_id,))

    def _portfolio(self, portfolio_id: int) -> Portfolio:
        for p in self.portfolios():
            if p.id == portfolio_id:
                return p
        raise InternalError(f"unknown portfolio {portfolio_id}")

    # Target weights and rebalancing --------------------------------------------------
    def targets(self, portfolio_id: int) -> dict[str, float]:
        with self._db() as db:
            rows = db.execute(
                "SELECT symbol, weight_pct FROM paper_targets WHERE portfolio_id = ? "
                "ORDER BY symbol",
                (portfolio_id,),
            ).fetchall()
        return {r["symbol"]: float(r["weight_pct"]) for r in rows}

    def set_targets(self, portfolio_id: int, targets: dict[str, float]) -> dict[str, float]:
        """Replace the target weights (percent of total value; the rest stays in cash)."""
        clean: dict[str, float] = {}
        for raw, weight in targets.items():
            symbol = normalize_symbol(raw)
            if not 0 < weight <= 100:
                raise UserError(
                    f"bad weight {weight}",
                    user_message=f"El peso de {symbol} debe estar entre 0 y 100 %.",
                )
            clean[symbol] = clean.get(symbol, 0.0) + float(weight)
        if sum(clean.values()) > 100 + 1e-9:
            raise UserError(
                "weights > 100", user_message="Los pesos objetivo no pueden sumar más del 100 %."
            )
        with self._db() as db:
            db.execute("DELETE FROM paper_targets WHERE portfolio_id = ?", (portfolio_id,))
            db.executemany(
                "INSERT INTO paper_targets (portfolio_id, symbol, weight_pct) VALUES (?, ?, ?)",
                [(portfolio_id, s, w) for s, w in clean.items()],
            )
        return clean

    def rebalance_plan(self, report: PortfolioReport) -> RebalancePlan:
        """Orders that bring ``report``'s portfolio to its target weights (not recorded)."""
        targets = self.targets(report.portfolio.id)
        if not targets:
            return RebalancePlan(problems=["Defina primero los pesos objetivo."])
        held = {h.symbol for h in report.valuation.holdings}
        prices: dict[str, float | None] = {}
        today = self._clock().date()
        for symbol in targets:
            if symbol not in held:
                try:
                    prices[symbol] = self.close_on(symbol, today)[0]
                except AppError as exc:
                    logger.info("No price for target %s: %s", symbol, exc)
                    prices[symbol] = None
        return plan_rebalance(report.valuation, targets, report.portfolio.commission_for, prices)

    def apply_rebalance(self, portfolio_id: int, plan: RebalancePlan) -> list[PaperTrade]:
        """Record the plan's orders today at the plan's prices (sales first)."""
        day = self._clock().date()
        done = []
        for order in plan.orders:
            done.append(self.add_trade(portfolio_id, order.symbol, order.side, order.quantity,
                                       order.price, day, note=REBALANCE_NOTE))  # fmt: skip
        return done

    # Trades ----------------------------------------------------------------------
    def trades(self, portfolio_id: int) -> list[PaperTrade]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM paper_trades WHERE portfolio_id = ? ORDER BY trade_date, id",
                (portfolio_id,),
            ).fetchall()
        return [PaperTrade(r["symbol"], r["side"], r["quantity"], r["price"],
                           date.fromisoformat(r["trade_date"]), r["commission"], r["note"],
                           r["id"], r["review"]) for r in rows]  # fmt: skip

    def set_review(self, portfolio_id: int, trade_id: int, text: str) -> None:
        """Journal: what the trade taught, written after the fact."""
        clean = text.strip()[:MAX_TEXT]
        with self._db() as db:
            db.execute("UPDATE paper_trades SET review = ? WHERE id = ? AND portfolio_id = ?",
                       (clean, trade_id, portfolio_id))  # fmt: skip

    # Market data and corporate events -------------------------------------------------
    def _bars(self, symbols: set[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
        bars: dict[str, pd.DataFrame] = {}
        problems: list[str] = []
        for symbol in sorted(symbols):
            try:
                bars[symbol] = self._market.load(symbol, Interval.D1).series.bars
            except AppError as exc:
                problems.append(f"{symbol}: {exc.user_message}")
        return bars, problems

    @staticmethod
    def _events(trades: list[PaperTrade], bars: dict[str, pd.DataFrame],
                dividends: bool) -> list[CorporateEvent]:  # fmt: skip
        """Dividends and splits after each symbol's first trade."""
        events: list[CorporateEvent] = []
        for symbol, frame in bars.items():
            first = min((t.trade_date for t in trades if t.symbol == symbol), default=None)
            if first is None:
                continue
            after = frame[frame.index > pd.Timestamp(first)]
            for column, kind in (("dividends", DIVIDEND), ("splits", SPLIT)):
                if kind == DIVIDEND and not dividends:
                    continue
                paid = after[column][after[column] > 0]
                for ts, v in zip(pd.DatetimeIndex(paid.index), paid, strict=True):
                    events.append(CorporateEvent(symbol, ts.date(), kind, float(v)))
        return events

    def _check(self, portfolio: Portfolio, trades: list[PaperTrade]) -> None:
        """Raise UserError if the history (with corporate events) is impossible."""
        bars, _problems = self._bars({t.symbol for t in trades})
        splits = {s: b["splits"] for s, b in bars.items()}
        replay(adjust_for_splits(trades, splits), portfolio.initial_cash,
               events=self._events(trades, bars, portfolio.apply_dividends),
               withholding_pct=portfolio.dividend_withholding_pct)  # fmt: skip

    def close_on(self, symbol: str, day: date) -> tuple[float, date]:
        """Real close of ``symbol`` on ``day`` or the session before it.

        The price history is split-adjusted; the close is scaled back by the splits
        that came later so it is the price that was actually quoted that day.
        """
        bars = self._market.load(symbol, Interval.D1).series.bars
        before = bars[bars.index <= pd.Timestamp(day)]
        if before.empty:
            raise UserError(
                f"no price for {symbol} on {day}",
                user_message=f"No hay cotización de {symbol} en esa fecha o antes.",
            )
        session = pd.Timestamp(before.index[-1]).date()
        factor = split_factor_after(bars["splits"], session)
        return float(before["close"].iloc[-1]) * factor, session

    def add_trade(self, portfolio_id: int, symbol: str, side: str,
                  quantity: float | None = None, price: float | None = None,
                  trade_date: date | None = None, commission: float | None = None,
                  note: str = "", amount: float | None = None) -> PaperTrade:  # fmt: skip
        """Record a trade and refuse impossible ones.

        Give either ``quantity`` (fractions allowed) or ``amount`` in dollars, which
        buys or sells that value at the price. ``price`` None uses that day's close;
        ``commission`` None applies the portfolio's commission schedule.
        """
        if side not in (BUY, SELL):
            raise UserError(f"bad side {side!r}", user_message="Operación no válida.")
        symbol = normalize_symbol(symbol)
        if (quantity is None) == (amount is None):
            raise UserError(
                "quantity xor amount",
                user_message="Indique la cantidad de acciones o el importe en $.",
            )
        if amount is not None and not amount > 0:
            raise UserError("amount <= 0", user_message="El importe debe ser positivo.")
        if quantity is not None and not quantity > 0:
            raise UserError("quantity <= 0", user_message="La cantidad debe ser positiva.")
        if commission is not None and commission < 0:
            raise UserError("commission < 0", user_message="La comisión no puede ser negativa.")
        today = self._clock().date()
        day = trade_date or today
        if day > today:
            raise UserError("future trade", user_message="La fecha no puede ser futura.")
        if price is None:
            price, _session = self.close_on(symbol, day)
        if not price > 0:
            raise UserError("price <= 0", user_message="El precio debe ser positivo.")
        if quantity is None:
            assert amount is not None
            quantity = round(amount / price, QUANTITY_DECIMALS)
            if quantity <= 0:
                raise UserError("amount too small", user_message="Importe demasiado pequeño.")
        portfolio = self._portfolio(portfolio_id)
        fee = portfolio.commission_for(quantity * price) if commission is None else commission
        trade = PaperTrade(symbol, side, float(quantity), float(price), day, float(fee),
                           " ".join(note.split())[:MAX_TEXT])  # fmt: skip
        # Validate against every trade, including later ones (a back-dated sale may make a
        # later sale impossible), with dividends and splits applied.
        self._check(portfolio, [*self.trades(portfolio_id), trade])
        with self._db() as db:
            cursor = db.execute(
                "INSERT INTO paper_trades (portfolio_id, symbol, side, quantity, price, "
                "commission, trade_date, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (portfolio_id, trade.symbol, trade.side, trade.quantity, trade.price,
                 trade.commission, trade.trade_date.isoformat(), trade.note,
                 self._clock().isoformat()),
            )  # fmt: skip
        return PaperTrade(trade.symbol, trade.side, trade.quantity, trade.price, trade.trade_date,
                          trade.commission, trade.note, int(cursor.lastrowid or 0))  # fmt: skip

    def delete_trade(self, portfolio_id: int, trade_id: int) -> None:
        """Delete a trade unless the remaining history becomes impossible."""
        remaining = [t for t in self.trades(portfolio_id) if t.id != trade_id]
        self._check(self._portfolio(portfolio_id), remaining)
        with self._db() as db:
            db.execute("DELETE FROM paper_trades WHERE id = ? AND portfolio_id = ?",
                       (trade_id, portfolio_id))  # fmt: skip

    # Report ----------------------------------------------------------------------
    def report(self, portfolio_id: int, benchmark: str = "SPY") -> PortfolioReport:
        """Current valuation, events, daily value curve and benchmark (cache-first loads)."""
        portfolio = self._portfolio(portfolio_id)
        trades = self.trades(portfolio_id)
        bars, problems = self._bars({t.symbol for t in trades})
        closes = {s: b["close"] for s, b in bars.items()}
        adjusted = adjust_for_splits(trades, {s: b["splits"] for s, b in bars.items()})
        events = self._events(trades, bars, portfolio.apply_dividends)
        withholding = portfolio.dividend_withholding_pct
        state = replay(adjusted, portfolio.initial_cash, events=events,
                       withholding_pct=withholding)  # fmt: skip
        end = self._clock().date()
        prices: dict[str, float | None] = {}
        for symbol, series in closes.items():
            known = series[series.index <= pd.Timestamp(end)]  # same day as the value curve
            prices[symbol] = float(known.iloc[-1]) if len(known) else None
        valuation = value(state, portfolio.initial_cash, prices)
        equity, per_symbol = daily_values(adjusted, portfolio.initial_cash, closes, end, events,
                                          withholding)  # fmt: skip
        bench = pd.Series(dtype=float)
        if not equity.empty:
            try:
                b = self._market.load(benchmark, Interval.D1).series.bars["close"]
                aligned = b.reindex(equity.index, method="ffill").dropna()
                if not aligned.empty:
                    bench = aligned / float(aligned.iloc[0]) * portfolio.initial_cash
            except AppError as exc:
                problems.append(f"{benchmark}: {exc.user_message}")
        splits = {s: b["splits"] for s, b in bars.items()}
        closed = [self._closed_as_quoted(c) for c in state.closed]
        taxes = gains_tax(closed, portfolio.capital_gains_tax_pct)
        return PortfolioReport(portfolio, trades, valuation, equity, bench, benchmark, problems,
                               closed, per_symbol, taxes,
                               [self._as_quoted(e, splits) for e in state.applied])  # fmt: skip

    @staticmethod
    def _closed_as_quoted(closed: ClosedTrade) -> ClosedTrade:
        t = closed.trade
        f = t.split_factor
        if f == 1.0:
            return closed
        real = replace(t, quantity=t.quantity / f, price=t.price * f, split_factor=1.0)
        return ClosedTrade(real, closed.cost, closed.proceeds, closed.opened_on)

    @staticmethod
    def _as_quoted(applied: AppliedEvent, splits: dict[str, pd.Series]) -> AppliedEvent:
        """An applied event with shares and per-share amount as they were on that day.

        The replay counts shares in today's units; later splits are undone here so the
        report shows the numbers the holder saw then (the cash is unchanged).
        """
        e = applied.event
        factor = split_factor_after(splits[e.symbol], e.day) if e.symbol in splits else 1.0
        if factor == 1.0:
            return applied
        amount = e.value * factor if e.kind == DIVIDEND else e.value
        return AppliedEvent(CorporateEvent(e.symbol, e.day, e.kind, amount),
                            applied.shares / factor, applied.cash, applied.withheld)  # fmt: skip


def gains_tax(closed: list[ClosedTrade], rate_pct: float) -> list[tuple[int, float, float]]:
    """Per year: net realised result of the sales and the estimated tax on it.

    Losses offset gains within the same year only; a net loss pays no tax (losses are
    not carried to other years in this simplified estimate).
    """
    by_year: dict[int, float] = {}
    for c in closed:
        year = c.trade.trade_date.year
        by_year[year] = by_year.get(year, 0.0) + c.result
    return [(y, net, max(net, 0.0) * rate_pct / 100) for y, net in sorted(by_year.items())]
