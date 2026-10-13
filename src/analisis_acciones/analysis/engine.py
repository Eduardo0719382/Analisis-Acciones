"""Runs analysis rules over a bar series."""

from __future__ import annotations

import logging

import pandas as pd

from analisis_acciones.analysis.model import AnalysisReport, NumberFormat, Signal, default_format
from analisis_acciones.analysis.rules import DEFAULT_RULES, Rule

logger = logging.getLogger(__name__)


def analyze(
    symbol: str,
    bars: pd.DataFrame,
    *,
    session_in_progress: bool = False,
    rules: tuple[Rule, ...] = DEFAULT_RULES,
    fmt: NumberFormat = default_format,
) -> AnalysisReport:
    """Evaluate ``rules`` on completed bars.

    An in-progress session bar is excluded so signals never depend on a bar
    whose values can still change.
    """
    data = bars.iloc[:-1] if session_in_progress and len(bars) > 0 else bars
    signals: list[Signal] = []
    skipped: list[str] = []
    for rule in rules:
        if len(data) < rule.min_bars:
            skipped.append(
                f"{rule.name}: datos insuficientes (requiere {rule.min_bars} barras, "
                f"hay {len(data)})"
            )
            continue
        try:
            signals.extend(rule.evaluate(data, fmt))
        except (ValueError, ArithmeticError, KeyError):
            logger.exception("Analysis rule %s failed for %s", rule.id, symbol)
            skipped.append(f"{rule.name}: no se pudo evaluar")
    as_of = pd.Timestamp(data.index[-1]).date() if len(data) else None
    return AnalysisReport(
        symbol=symbol,
        as_of=as_of,
        bars_used=len(data),
        signals=tuple(signals),
        skipped=tuple(skipped),
        excluded_partial_bar=session_in_progress and len(bars) > 0,
    )
