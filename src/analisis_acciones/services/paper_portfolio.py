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

from analisis_acciones.data.trades_import import ImportedTrade
from analisis_acciones.models.errors import AppError, InternalError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.portfolio.alerts import AlertThresholds, conditions
from analisis_acciones.portfolio.engine import (
    BUY,
    CASH_DIVIDEND,
    DIVIDEND,
    MOVEMENT_KINDS,
    SELL,
    SPLIT,
    AppliedEvent,
    CashMovement,
    ClosedTrade,
    CorporateEvent,
    PaperTrade,
    Valuation,
    adjust_for_splits,
    cash_needed,
    daily_values,
    flows_by_day,
    in_dollars,
    replay,
    split_factor_after,
    time_weighted,
    value,
    with_flows,
)
from analisis_acciones.portfolio.rebalance import RebalancePlan, plan_rebalance
from analisis_acciones.providers.base import normalize_symbol
from analisis_acciones.services.fx import FxConverter
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.storage.database import transaction

logger = logging.getLogger(__name__)

DEFAULT_NAME = "Mi cartera"
DEFAULT_CASH = 10_000.0
MAX_NAME = 40


MAX_TEXT = 500
MAX_BENCHMARKS = 3
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
    alerts: AlertThresholds = field(default_factory=AlertThresholds)

    def commission_for(self, value: float) -> float:
        """Commission of a trade of ``value`` dollars under this portfolio's schedule."""
        fee = self.commission_fixed + value * self.commission_pct / 100
        return round(max(fee, self.commission_min), 2) if fee or self.commission_min else 0.0


@dataclass(frozen=True)
class PortfolioNotice:
    portfolio: str
    symbol: str  # "" for the whole portfolio
    message: str


@dataclass(frozen=True)
class ImportPreview:
    trades: list[PaperTrade]  # ready to store, in file order
    cash_needed: float | None  # initial cash the history needs (None: history impossible)
    problems: list[str]
    fx_notes: list[str] = field(default_factory=list)
    cash_needed_alone: float | None = None  # same, for the imported trades only


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
    # How amounts in other currencies were converted to dollars.
    fx_notes: list[str] = field(default_factory=list)
    # Dividends and splits that affected the portfolio, in the share units of their day
    # (``shares`` is the count after the event for a split).
    events: list[AppliedEvent] = field(default_factory=list)
    # Every reference index, rebased to the initial cash on the first day (main one first),
    # receiving the same deposits/withdrawals as the portfolio on the same days.
    benchmarks: dict[str, pd.Series] = field(default_factory=dict)
    movements: list[CashMovement] = field(default_factory=list)
    # The references' price alone, rebased to the initial cash (for return comparisons).
    benchmark_prices: dict[str, pd.Series] = field(default_factory=dict)
    # Time-weighted growth of the initial cash: the curve without deposits/withdrawals.
    growth: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    # Money put in up to each day (initial cash + deposits − withdrawals).
    invested: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    @property
    def time_weighted_pct(self) -> float | None:
        if self.growth.empty or self.portfolio.initial_cash <= 0:
            return None
        return (float(self.growth.iloc[-1]) / self.portfolio.initial_cash - 1) * 100


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
                               r["capital_gains_tax_pct"],
                               AlertThresholds(r["alert_loss_pct"], r["alert_drift_pts"],
                                               r["alert_drawdown_pct"]))
                     for r in rows.fetchall()]  # fmt: skip
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

    def set_alerts(self, portfolio_id: int, limits: AlertThresholds) -> Portfolio:
        values = (limits.loss_pct, limits.drift_pts, limits.drawdown_pct)
        if not all(0 <= v <= 100 for v in values):
            raise UserError("bad alert", user_message="Los umbrales deben estar entre 0 y 100.")
        with self._db() as db:
            db.execute(
                "UPDATE paper_portfolios SET alert_loss_pct = ?, alert_drift_pts = ?, "
                "alert_drawdown_pct = ? WHERE id = ?",
                (*map(float, values), portfolio_id),
            )
        return self._portfolio(portfolio_id)

    def check_alerts(self, benchmark: str = "SPY") -> list[PortfolioNotice]:
        """New notices for every portfolio with alerts on; never raises for data problems.

        A condition is announced once; when it stops being true it is forgotten, so it is
        announced again if it comes back.
        """
        notices: list[PortfolioNotice] = []
        for portfolio in self.portfolios():
            if not portfolio.alerts.active or not self.trades(portfolio.id):
                continue
            try:
                report = self.report(portfolio.id, benchmark)
            except AppError as exc:
                logger.warning("Portfolio alerts for %s skipped: %s", portfolio.name, exc)
                continue
            # With deposits/withdrawals the drawdown is measured on the time-weighted curve,
            # so taking money out is not mistaken for a fall.
            curve = report.growth if report.movements else report.equity
            now = conditions(report.valuation, curve, self.targets(portfolio.id),
                             portfolio.alerts)  # fmt: skip
            with self._db() as db:
                rows = db.execute(
                    "SELECT key FROM paper_alert_state WHERE portfolio_id = ?", (portfolio.id,)
                ).fetchall()
                known = {r["key"] for r in rows}
                with transaction(db):
                    db.execute("DELETE FROM paper_alert_state WHERE portfolio_id = ?",
                               (portfolio.id,))  # fmt: skip
                    db.executemany(
                        "INSERT INTO paper_alert_state (portfolio_id, key) VALUES (?, ?)",
                        [(portfolio.id, k) for k in now],
                    )
            for key, (symbol, message) in now.items():
                if key not in known:
                    notices.append(PortfolioNotice(portfolio.name, symbol, message))
        return notices

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
            db.execute("DELETE FROM paper_alert_state WHERE portfolio_id = ?", (portfolio_id,))
            db.execute("DELETE FROM paper_cash WHERE portfolio_id = ?", (portfolio_id,))
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
        fx = FxConverter(self._market)
        for symbol in targets:
            if symbol not in held:
                try:
                    local = self.close_on(symbol, today)[0]
                    prices[symbol] = local * fx.rate_on(fx.currency_of(symbol), today)
                except AppError as exc:
                    logger.info("No price for target %s: %s", symbol, exc)
                    prices[symbol] = None
        return plan_rebalance(report.valuation, targets, report.portfolio.commission_for, prices)

    def apply_rebalance(self, portfolio_id: int, plan: RebalancePlan) -> list[PaperTrade]:
        """Record the plan's orders today at the plan's prices (sales first).

        Plan prices are in dollars; trades are recorded in each asset's own currency.
        """
        day = self._clock().date()
        fx = FxConverter(self._market)
        done = []
        for order in plan.orders:
            local = order.price / fx.rate_on(fx.currency_of(order.symbol), day)
            done.append(self.add_trade(portfolio_id, order.symbol, order.side, order.quantity,
                                       local, day, note=REBALANCE_NOTE))  # fmt: skip
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
                           r["id"], r["review"], 1.0, r["currency"],
                           r["fx_rate"]) for r in rows]  # fmt: skip

    def set_review(self, portfolio_id: int, trade_id: int, text: str) -> None:
        """Journal: what the trade taught, written after the fact."""
        clean = text.strip()[:MAX_TEXT]
        with self._db() as db:
            db.execute("UPDATE paper_trades SET review = ? WHERE id = ? AND portfolio_id = ?",
                       (clean, trade_id, portfolio_id))  # fmt: skip

    # Market data and corporate events -------------------------------------------------
    def _bars(
        self, symbols: set[str], fx: FxConverter | None = None
    ) -> tuple[dict[str, pd.DataFrame], list[str]]:
        """Daily bars with prices and dividends converted to dollars."""
        fx = fx or FxConverter(self._market)
        bars: dict[str, pd.DataFrame] = {}
        problems: list[str] = []
        for symbol in sorted(symbols):
            try:
                raw = self._market.load(symbol, Interval.D1).series.bars
                bars[symbol] = fx.to_usd(raw, fx.currency_of(symbol))
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

    def _check(self, portfolio: Portfolio, trades: list[PaperTrade],
               movements: list[CashMovement] | None = None) -> None:  # fmt: skip
        """Raise UserError if the history (with corporate events and cash) is impossible."""
        if movements is None:
            movements = self.movements(portfolio.id)
        bars, _problems = self._bars({t.symbol for t in trades})
        splits = {s: b["splits"] for s, b in bars.items()}
        replay(adjust_for_splits(in_dollars(trades), splits), portfolio.initial_cash,
               events=self._events(trades, bars, portfolio.apply_dividends),
               withholding_pct=portfolio.dividend_withholding_pct,
               movements=movements)  # fmt: skip

    # Cash movements ------------------------------------------------------------------
    def movements(self, portfolio_id: int) -> list[CashMovement]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM paper_cash WHERE portfolio_id = ? ORDER BY day, id", (portfolio_id,)
            ).fetchall()
        return [CashMovement(date.fromisoformat(r["day"]), r["kind"], r["amount"], r["symbol"],
                             r["note"], r["id"], r["currency"], r["fx_rate"])
                for r in rows]  # fmt: skip

    def make_movement(self, kind: str, amount: float, day: date, symbol: str = "",
                      note: str = "", currency: str | None = None) -> CashMovement:  # fmt: skip
        """Validated movement (exchange rate of its date); not stored."""
        if kind not in MOVEMENT_KINDS:
            raise UserError(f"bad movement {kind!r}", user_message="Tipo de movimiento no válido.")
        if not amount > 0:
            raise UserError("amount <= 0", user_message="El importe debe ser positivo.")
        if day > self._clock().date():
            raise UserError("future movement", user_message="La fecha no puede ser futura.")
        clean_symbol = normalize_symbol(symbol) if symbol.strip() else ""
        if kind == CASH_DIVIDEND and not clean_symbol:
            raise UserError("dividend without symbol",
                            user_message="Indique el ticker del dividendo.")  # fmt: skip
        fx = FxConverter(self._market)
        cur = currency or "USD"
        return CashMovement(day, kind, float(amount), clean_symbol,
                            " ".join(note.split())[:MAX_TEXT], None, cur,
                            fx.rate_on(cur, day))  # fmt: skip

    def add_movement(self, portfolio_id: int, movement: CashMovement) -> CashMovement:
        portfolio = self._portfolio(portfolio_id)
        self._check(portfolio, self.trades(portfolio_id),
                    [*self.movements(portfolio_id), movement])  # fmt: skip
        with self._db() as db:
            cursor = db.execute(
                "INSERT INTO paper_cash (portfolio_id, day, kind, amount, currency, fx_rate, "
                "symbol, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (portfolio_id, movement.day.isoformat(), movement.kind, movement.amount,
                 movement.currency, movement.fx_rate, movement.symbol, movement.note,
                 self._clock().isoformat()),
            )  # fmt: skip
        return replace(movement, id=int(cursor.lastrowid or 0))

    def delete_movement(self, portfolio_id: int, movement_id: int) -> None:
        remaining = [m for m in self.movements(portfolio_id) if m.id != movement_id]
        self._check(self._portfolio(portfolio_id), self.trades(portfolio_id), remaining)
        with self._db() as db:
            db.execute("DELETE FROM paper_cash WHERE id = ? AND portfolio_id = ?",
                       (movement_id, portfolio_id))  # fmt: skip

    def close_on(self, symbol: str, day: date) -> tuple[float, date]:
        """Real close of ``symbol`` on ``day`` or the session before it, in its own currency.

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
        fx = FxConverter(self._market)
        currency = fx.currency_of(symbol)
        rate = fx.rate_on(currency, day)
        if quantity is None:
            assert amount is not None
            quantity = round(amount / (price * rate), QUANTITY_DECIMALS)  # amount is in $
            if quantity <= 0:
                raise UserError("amount too small", user_message="Importe demasiado pequeño.")
        portfolio = self._portfolio(portfolio_id)
        value_usd = quantity * price * rate
        fee = portfolio.commission_for(value_usd) if commission is None else commission
        trade = PaperTrade(symbol, side, float(quantity), float(price), day, float(fee),
                           " ".join(note.split())[:MAX_TEXT], currency=currency,
                           fx_rate=rate)  # fmt: skip
        # Validate against every trade, including later ones (a back-dated sale may make a
        # later sale impossible), with dividends and splits applied.
        self._check(portfolio, [*self.trades(portfolio_id), trade])
        with self._db() as db:
            cursor = db.execute(
                "INSERT INTO paper_trades (portfolio_id, symbol, side, quantity, price, "
                "commission, trade_date, note, created_at, currency, fx_rate) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (portfolio_id, trade.symbol, trade.side, trade.quantity, trade.price,
                 trade.commission, trade.trade_date.isoformat(), trade.note,
                 self._clock().isoformat(), trade.currency, trade.fx_rate),
            )  # fmt: skip
        return replace(trade, id=int(cursor.lastrowid or 0))

    # Import from a broker's CSV -------------------------------------------------------
    def prepare_import(self, portfolio_id: int,
                       rows: list[ImportedTrade]) -> ImportPreview:  # fmt: skip
        """Turn parsed rows into trades (currency and exchange rate of each date) and work
        out the cash the portfolio would need. Nothing is stored."""
        fx = FxConverter(self._market)
        today = self._clock().date()
        trades: list[PaperTrade] = []
        problems: list[str] = []
        for row in rows:
            if row.day > today:
                problems.append(f"Línea {row.line}: fecha futura.")
                continue
            try:
                symbol = normalize_symbol(row.symbol)
                currency = row.currency or fx.currency_of(symbol)
                rate = fx.rate_on(currency, row.day)
            except UserError as exc:
                problems.append(f"Línea {row.line}: {exc.user_message}")
                continue
            trades.append(PaperTrade(symbol, row.side, row.quantity, row.price, row.day,
                                     round(row.commission, 2), row.note, currency=currency,
                                     fx_rate=rate))  # fmt: skip
        existing = self.trades(portfolio_id)
        start = max((t.id or 0 for t in existing), default=0) + 1
        numbered = [replace(t, id=start + i) for i, t in enumerate(trades)]  # keep file order
        portfolio = self._portfolio(portfolio_id)
        combined = [*existing, *numbered]
        bars, bar_problems = self._bars({t.symbol for t in combined}, fx)
        splits = {s: b["splits"] for s, b in bars.items()}
        adjusted = adjust_for_splits(in_dollars(combined), splits)
        events = self._events(combined, bars, portfolio.apply_dividends)
        withholding = portfolio.dividend_withholding_pct

        def need(history: list[PaperTrade]) -> float | None:
            try:
                return cash_needed(adjust_for_splits(in_dollars(history), splits),
                                   self._events(history, bars, portfolio.apply_dividends),
                                   withholding)  # fmt: skip
            except UserError:
                return None

        alone = need(numbered)
        try:
            needed = cash_needed(adjusted, events, withholding)
        except UserError as exc:  # e.g. selling shares never bought
            return ImportPreview(numbered, None, [*problems, exc.user_message], fx.notes, alone)
        return ImportPreview(numbered, needed, [*problems, *bar_problems], fx.notes, alone)

    def import_trades(self, portfolio_id: int, preview: ImportPreview) -> int:
        """Store the previewed trades in one transaction, after validating the whole history."""
        if not preview.trades:
            return 0
        portfolio = self._portfolio(portfolio_id)
        self._check(portfolio, [*self.trades(portfolio_id), *preview.trades])
        now = self._clock().isoformat()
        with self._db() as db, transaction(db):
            db.executemany(
                "INSERT INTO paper_trades (portfolio_id, symbol, side, quantity, price, "
                "commission, trade_date, note, created_at, currency, fx_rate) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(portfolio_id, t.symbol, t.side, t.quantity, t.price, t.commission,
                  t.trade_date.isoformat(), t.note, now, t.currency, t.fx_rate)
                 for t in preview.trades],
            )  # fmt: skip
        logger.info("Imported %d trades into portfolio %d", len(preview.trades), portfolio_id)
        return len(preview.trades)

    def delete_trade(self, portfolio_id: int, trade_id: int) -> None:
        """Delete a trade unless the remaining history becomes impossible."""
        remaining = [t for t in self.trades(portfolio_id) if t.id != trade_id]
        self._check(self._portfolio(portfolio_id), remaining)
        with self._db() as db:
            db.execute("DELETE FROM paper_trades WHERE id = ? AND portfolio_id = ?",
                       (trade_id, portfolio_id))  # fmt: skip

    # Report ----------------------------------------------------------------------
    def report(self, portfolio_id: int, benchmark: str | list[str] = "SPY") -> PortfolioReport:
        """Current valuation, events, daily value curve and benchmarks (cache-first loads).

        ``benchmark`` may list several symbols (at most MAX_BENCHMARKS); the first one is the
        main reference of the summary.
        """
        names = [benchmark] if isinstance(benchmark, str) else list(benchmark)
        names = list(dict.fromkeys(n.strip().upper() for n in names if n.strip()))
        names = names[:MAX_BENCHMARKS] or ["SPY"]
        portfolio = self._portfolio(portfolio_id)
        trades = self.trades(portfolio_id)
        movements = self.movements(portfolio_id)
        fx = FxConverter(self._market)
        bars, problems = self._bars({t.symbol for t in trades}, fx)
        closes = {s: b["close"] for s, b in bars.items()}
        adjusted = adjust_for_splits(in_dollars(trades), {s: b["splits"] for s, b in bars.items()})
        events = self._events(trades, bars, portfolio.apply_dividends)
        withholding = portfolio.dividend_withholding_pct
        state = replay(adjusted, portfolio.initial_cash, events=events,
                       withholding_pct=withholding, movements=movements)  # fmt: skip
        end = self._clock().date()
        prices: dict[str, float | None] = {}
        for symbol, series in closes.items():
            known = series[series.index <= pd.Timestamp(end)]  # same day as the value curve
            prices[symbol] = float(known.iloc[-1]) if len(known) else None
        valuation = value(state, portfolio.initial_cash, prices)
        equity, per_symbol = daily_values(adjusted, portfolio.initial_cash, closes, end, events,
                                          withholding, movements)  # fmt: skip
        flows = flows_by_day(movements, pd.DatetimeIndex(equity.index))
        has_flows = bool((flows != 0).any())
        growth = time_weighted(equity, flows, portfolio.initial_cash)
        benches: dict[str, pd.Series] = {}
        bench_prices: dict[str, pd.Series] = {}
        if not equity.empty:
            for name in names:
                try:
                    raw = self._market.load(name, Interval.D1).series.bars
                    b = fx.to_usd(raw, fx.currency_of(name))["close"]
                    aligned = b.reindex(equity.index, method="ffill").dropna()
                    if not aligned.empty:
                        rebased = aligned / float(aligned.iloc[0]) * portfolio.initial_cash
                        bench_prices[name] = rebased
                        benches[name] = (with_flows(aligned, flows, portfolio.initial_cash)
                                         if has_flows else rebased)  # fmt: skip
                except AppError as exc:
                    problems.append(f"{name}: {exc.user_message}")
        bench = benches.get(names[0], pd.Series(dtype=float))
        benchmark = names[0]
        splits = {s: b["splits"] for s, b in bars.items()}
        closed = [self._closed_as_quoted(c) for c in state.closed]
        taxes = gains_tax(closed, portfolio.capital_gains_tax_pct)
        return PortfolioReport(portfolio, trades, valuation, equity, bench, benchmark, problems,
                               closed, per_symbol, taxes, fx.notes,
                               [self._as_quoted(e, splits) for e in state.applied],
                               benches, movements, bench_prices,
                               growth * portfolio.initial_cash,
                               portfolio.initial_cash + flows.cumsum())  # fmt: skip

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


def yearly_returns(series: pd.Series, initial: float) -> list[tuple[int, float, bool]]:
    """(year, return %, partial year) of a value curve that starts with ``initial``.

    Each year runs from the last value of the previous year (``initial`` for the first year)
    to its own last value. The first and the current year are marked partial when the curve
    does not cover them fully.
    """
    clean = series.dropna()
    if clean.empty or initial <= 0:
        return []
    index = pd.DatetimeIndex(clean.index)
    out: list[tuple[int, float, bool]] = []
    start = initial
    years = sorted(set(index.year))
    for k, year in enumerate(years):
        values = clean[index.year == year]
        end = float(values.iloc[-1])
        first_day = pd.Timestamp(values.index[0])
        last_day = pd.Timestamp(values.index[-1])
        partial = (k == 0 and (first_day.month, first_day.day) > (1, 7)) or (
            k == len(years) - 1 and (last_day.month, last_day.day) < (12, 24)
        )
        out.append((int(year), (end / start - 1) * 100, partial))
        start = end
    return out
