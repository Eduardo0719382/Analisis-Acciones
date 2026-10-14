"""Paper portfolios: persistence, price lookup and valuation (no real money involved)."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from analisis_acciones.models.errors import AppError, InternalError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.portfolio.engine import (
    BUY,
    SELL,
    PaperTrade,
    Valuation,
    equity_curve,
    replay,
    value,
)
from analisis_acciones.providers.base import normalize_symbol
from analisis_acciones.services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

DEFAULT_NAME = "Mi cartera"
DEFAULT_CASH = 10_000.0
MAX_NAME = 40


@dataclass(frozen=True)
class Portfolio:
    id: int
    name: str
    initial_cash: float


@dataclass(frozen=True)
class PortfolioReport:
    portfolio: Portfolio
    trades: list[PaperTrade]
    valuation: Valuation
    equity: pd.Series  # daily total value
    benchmark: pd.Series  # benchmark rebased to the initial cash, same days (may be empty)
    benchmark_symbol: str
    problems: list[str]


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
            rows = db.execute("SELECT id, name, initial_cash FROM paper_portfolios ORDER BY id")
            found = [Portfolio(r["id"], r["name"], r["initial_cash"]) for r in rows.fetchall()]
        return found or [self.create(DEFAULT_NAME, DEFAULT_CASH)]

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
            db.execute("DELETE FROM paper_portfolios WHERE id = ?", (portfolio_id,))

    def _portfolio(self, portfolio_id: int) -> Portfolio:
        for p in self.portfolios():
            if p.id == portfolio_id:
                return p
        raise InternalError(f"unknown portfolio {portfolio_id}")

    # Trades ----------------------------------------------------------------------
    def trades(self, portfolio_id: int) -> list[PaperTrade]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM paper_trades WHERE portfolio_id = ? ORDER BY trade_date, id",
                (portfolio_id,),
            ).fetchall()
        return [PaperTrade(r["symbol"], r["side"], r["quantity"], r["price"],
                           date.fromisoformat(r["trade_date"]), r["commission"], r["note"],
                           r["id"]) for r in rows]  # fmt: skip

    def close_on(self, symbol: str, day: date) -> tuple[float, date]:
        """Close of ``symbol`` on ``day`` or the last session before it."""
        bars = self._market.load(symbol, Interval.D1).series.bars
        before = bars[bars.index <= pd.Timestamp(day)]
        if before.empty:
            raise UserError(
                f"no price for {symbol} on {day}",
                user_message=f"No hay cotización de {symbol} en esa fecha o antes.",
            )
        return float(before["close"].iloc[-1]), pd.Timestamp(before.index[-1]).date()

    def add_trade(self, portfolio_id: int, symbol: str, side: str, quantity: float,
                  price: float | None = None, trade_date: date | None = None,
                  commission: float = 0.0, note: str = "") -> PaperTrade:  # fmt: skip
        """Record a trade; ``price`` None uses that day's close. Refuses impossible trades."""
        if side not in (BUY, SELL):
            raise UserError(f"bad side {side!r}", user_message="Operación no válida.")
        symbol = normalize_symbol(symbol)
        if not quantity > 0:
            raise UserError("quantity <= 0", user_message="La cantidad debe ser positiva.")
        if commission < 0:
            raise UserError("commission < 0", user_message="La comisión no puede ser negativa.")
        today = self._clock().date()
        day = trade_date or today
        if day > today:
            raise UserError("future trade", user_message="La fecha no puede ser futura.")
        if price is None:
            price, _session = self.close_on(symbol, day)
        if not price > 0:
            raise UserError("price <= 0", user_message="El precio debe ser positivo.")
        trade = PaperTrade(symbol, side, float(quantity), float(price), day, float(commission),
                           " ".join(note.split())[:120])  # fmt: skip
        portfolio = self._portfolio(portfolio_id)
        # Validate against every trade, including later ones (a back-dated sale may make a
        # later sale impossible).
        replay([*self.trades(portfolio_id), trade], portfolio.initial_cash)
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
        replay(remaining, self._portfolio(portfolio_id).initial_cash)
        with self._db() as db:
            db.execute("DELETE FROM paper_trades WHERE id = ? AND portfolio_id = ?",
                       (trade_id, portfolio_id))  # fmt: skip

    # Report ----------------------------------------------------------------------
    def report(self, portfolio_id: int, benchmark: str = "SPY") -> PortfolioReport:
        """Current valuation, daily value curve and benchmark (cache-first loads)."""
        portfolio = self._portfolio(portfolio_id)
        trades = self.trades(portfolio_id)
        problems: list[str] = []
        closes: dict[str, pd.Series] = {}
        for symbol in sorted({t.symbol for t in trades}):
            try:
                closes[symbol] = self._market.load(symbol, Interval.D1).series.bars["close"]
            except AppError as exc:
                problems.append(f"{symbol}: {exc.user_message}")
        state = replay(trades, portfolio.initial_cash)
        end = self._clock().date()
        prices: dict[str, float | None] = {}
        for symbol, series in closes.items():
            known = series[series.index <= pd.Timestamp(end)]  # same day as the value curve
            prices[symbol] = float(known.iloc[-1]) if len(known) else None
        valuation = value(state, portfolio.initial_cash, prices)
        equity = equity_curve(trades, portfolio.initial_cash, closes, end)
        bench = pd.Series(dtype=float)
        if not equity.empty:
            try:
                b = self._market.load(benchmark, Interval.D1).series.bars["close"]
                aligned = b.reindex(equity.index, method="ffill").dropna()
                if not aligned.empty:
                    bench = aligned / float(aligned.iloc[0]) * portfolio.initial_cash
            except AppError as exc:
                problems.append(f"{benchmark}: {exc.user_message}")
        return PortfolioReport(portfolio, trades, valuation, equity, bench, benchmark, problems)
