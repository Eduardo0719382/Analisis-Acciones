"""Performance statistics computed from a BacktestResult (no simulation here)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from analisis_acciones.backtesting.engine import BacktestResult


@dataclass(frozen=True)
class Statistics:
    initial_capital: float
    final_equity: float
    total_return_pct: float
    trades: int
    winning: int
    losing: int
    win_rate_pct: float | None
    max_drawdown_pct: float
    #: Gross profit / gross loss; None when undefined (no losing trades).
    profit_factor: float | None
    buy_and_hold_pct: float
    exposure_pct: float
    commissions: float
    open_trade_pnl: float | None


def max_drawdown_pct(equity: pd.Series) -> float:
    """Largest peak-to-trough decline, as a negative percentage (0 if none)."""
    values = equity.to_numpy(dtype=float)
    if values.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(values)
    drawdowns = values / peaks - 1.0
    return float(drawdowns.min() * 100.0)


def compute_statistics(result: BacktestResult, bars: pd.DataFrame) -> Statistics:
    initial = result.config.initial_capital
    final = float(result.equity.iloc[-1])
    pnls = [t.pnl() for t in result.trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit, gross_loss = sum(wins), -sum(losses)
    positions = {pd.Timestamp(t): i for i, t in enumerate(bars.index)}
    in_market = 0
    for trade in [*result.trades, *([result.open_trade] if result.open_trade else [])]:
        start = positions[pd.Timestamp(trade.entry_date)]
        end = positions[pd.Timestamp(trade.exit_date)] if trade.exit_date else len(bars)
        in_market += max(0, end - start)
    commissions = sum(t.entry_commission + t.exit_commission for t in result.trades)
    if result.open_trade:
        commissions += result.open_trade.entry_commission
    first_open, last_close = float(bars["open"].iloc[0]), float(bars["close"].iloc[-1])
    return Statistics(
        initial_capital=initial,
        final_equity=final,
        total_return_pct=(final / initial - 1.0) * 100.0,
        trades=len(pnls),
        winning=len(wins),
        losing=len(losses),
        win_rate_pct=len(wins) / len(pnls) * 100.0 if pnls else None,
        max_drawdown_pct=max_drawdown_pct(result.equity),
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else None,
        buy_and_hold_pct=(last_close / first_open - 1.0) * 100.0,
        exposure_pct=in_market / len(bars) * 100.0,
        commissions=commissions,
        open_trade_pnl=(
            result.open_trade.pnl(float(bars["close"].iloc[-1])) if result.open_trade else None
        ),
    )
