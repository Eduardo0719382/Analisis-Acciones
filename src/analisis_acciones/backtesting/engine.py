"""Event-driven, long-only backtest.

Timing (no look-ahead):

* signals are computed at the **close** of bar t from data up to bar t;
* the resulting order is filled at the **open** of bar t+1;
* a signal on the last bar cannot be executed and is reported as pending.

Costs: slippage moves each fill against the trader by ``slippage_pct``; the
commission is ``commission_pct`` of the traded value plus ``commission_fixed``
per order. Position size: all available cash, whole shares only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from analisis_acciones.models.errors import UserError


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    commission_pct: float = 0.1  # percent of traded value
    commission_fixed: float = 0.0  # per order, in account currency
    slippage_pct: float = 0.05  # percent

    def validate(self) -> None:
        if not self.initial_capital > 0:
            raise UserError("capital <= 0", user_message="El capital inicial debe ser positivo.")
        if not 0 <= self.commission_pct < 10 or self.commission_fixed < 0:
            raise UserError("bad commission", user_message="La comisión no es válida.")
        if not 0 <= self.slippage_pct < 10:
            raise UserError("bad slippage", user_message="El deslizamiento no es válido.")


@dataclass(frozen=True)
class Trade:
    entry_date: date
    entry_price: float
    shares: int
    entry_commission: float
    exit_date: date | None = None
    exit_price: float | None = None
    exit_commission: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.exit_date is None

    def pnl(self, mark_price: float | None = None) -> float:
        price = self.exit_price if self.exit_price is not None else mark_price
        if price is None:
            return 0.0
        gross = (price - self.entry_price) * self.shares
        return gross - self.entry_commission - self.exit_commission

    @property
    def return_pct(self) -> float | None:
        if self.exit_price is None:
            return None
        invested = self.entry_price * self.shares + self.entry_commission
        return self.pnl() / invested * 100.0


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    trades: tuple[Trade, ...]  # closed trades
    open_trade: Trade | None
    equity: pd.Series
    pending_signal: str | None = None
    notes: tuple[str, ...] = field(default=())


def run_backtest(
    bars: pd.DataFrame, signals: pd.DataFrame, config: BacktestConfig
) -> BacktestResult:
    config.validate()
    if len(bars) < 2:
        raise UserError("not enough bars", user_message="Se necesitan al menos 2 barras.")
    if not signals.index.equals(bars.index):
        raise ValueError("signals must be aligned to bars")

    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    dates = [pd.Timestamp(t).date() for t in bars.index]
    entries = signals["entry"].to_numpy(dtype=bool)
    exits = signals["exit"].to_numpy(dtype=bool)
    slip = config.slippage_pct / 100.0
    comm = config.commission_pct / 100.0

    cash = config.initial_capital
    position: Trade | None = None
    pending: str | None = None
    closed: list[Trade] = []
    notes: list[str] = []
    equity = []

    for i in range(len(bars)):
        # 1) Execute the order decided at the previous close, at this bar's open.
        if pending == "buy" and position is None:
            price = float(opens[i] * (1 + slip))
            shares = math.floor((cash - config.commission_fixed) / (price * (1 + comm)))
            if shares > 0:
                commission = float(price * shares * comm + config.commission_fixed)
                cash -= price * shares + commission
                position = Trade(dates[i], price, shares, commission)
            else:
                notes.append(f"{dates[i]:%d/%m/%Y}: capital insuficiente para comprar 1 acción")
        elif pending == "sell" and position is not None:
            price = float(opens[i] * (1 - slip))
            commission = float(price * position.shares * comm + config.commission_fixed)
            cash += price * position.shares - commission
            closed.append(
                Trade(position.entry_date, position.entry_price, position.shares,
                      position.entry_commission, dates[i], price, commission)
            )  # fmt: skip
            position = None
        pending = None

        # 2) Decide at this bar's close (only data up to i is used).
        if position is None and entries[i]:
            pending = "buy"
        elif position is not None and exits[i]:
            pending = "sell"

        # 3) Mark to market at the close.
        equity.append(float(cash + (position.shares * closes[i] if position else 0.0)))

    if pending is not None:
        notes.append(
            f"Señal de {'entrada' if pending == 'buy' else 'salida'} en la última barra "
            f"({dates[-1]:%d/%m/%Y}): no hay barra siguiente para ejecutarla."
        )
    return BacktestResult(
        config=config,
        trades=tuple(closed),
        open_trade=position,
        equity=pd.Series(equity, index=bars.index, name="equity"),
        pending_signal=pending,
        notes=tuple(notes),
    )
