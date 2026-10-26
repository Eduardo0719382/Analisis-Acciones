"""Ready-made long-only profiles: a time horizon crossed with a risk style.

A profile is a registered strategy with fixed parameters on a fixed bar interval. They are
starting points for studying and for simulated orders; none is a recommendation, and a
profile that did well in the past can do badly next. Short selling is not offered anywhere:
every profile buys, holds and sells what it bought.

The horizon sets the bar (hours: 1h; days: daily; weeks: weekly; months: monthly). The
style sets how early it buys and how quickly it gives up:

* aggressive: buys breakouts or early crosses, tolerates deeper drops, trades more often;
* balanced: follows the trend with a medium average;
* conservative: only buys inside a long up-trend, sells at the first sign of weakness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analisis_acciones.models.errors import UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.strategies.registry import STRATEGY_REGISTRY, validate_strategy_params

HORIZON_NAMES = {"hours": "Horas", "days": "Días", "weeks": "Semanas", "months": "Meses"}
STYLE_NAMES = {"aggressive": "Agresivo", "balanced": "Equilibrado", "conservative": "Conservador"}


@dataclass(frozen=True)
class Profile:
    id: str
    horizon: str  # key of HORIZON_NAMES
    style: str  # key of STYLE_NAMES
    interval: Interval
    strategy_id: str
    params: dict[str, Any]
    summary: str

    @property
    def name(self) -> str:
        return f"{HORIZON_NAMES[self.horizon]} · {STYLE_NAMES[self.style]}"

    def validated_params(self) -> dict[str, int | float]:
        return validate_strategy_params(STRATEGY_REGISTRY[self.strategy_id], self.params)


PROFILES: tuple[Profile, ...] = (
    # Hours (1h bars: Yahoo keeps about two years of them).
    Profile("hours_aggressive", "hours", "aggressive", Interval.H1, "breakout",
            {"entry_n": 24, "exit_n": 8},
            "Compra al romper el máximo de las últimas 24 horas; sale al perder el mínimo de 8."),
    Profile("hours_balanced", "hours", "balanced", Interval.H1, "ema_cross",
            {"fast": 20, "slow": 50},
            "Cruce de medias exponenciales de 20 y 50 horas."),
    Profile("hours_conservative", "hours", "conservative", Interval.H1, "pullback",
            {"trend": 200, "period": 14, "low": 35, "high": 60},
            "Solo compra retrocesos cuando el precio está sobre su media de 200 horas."),
    # Days.
    Profile("days_aggressive", "days", "aggressive", Interval.D1, "breakout",
            {"entry_n": 20, "exit_n": 10},
            "Compra al romper el máximo de 20 días; sale al perder el mínimo de 10."),
    Profile("days_balanced", "days", "balanced", Interval.D1, "ema_cross",
            {"fast": 20, "slow": 50},
            "Cruce de medias exponenciales de 20 y 50 días."),
    Profile("days_conservative", "days", "conservative", Interval.D1, "pullback",
            {"trend": 200, "period": 14, "low": 40, "high": 65},
            "Compra retrocesos solo con el precio sobre su media de 200 días; vende al "
            "recuperarse o al perder la media."),
    # Weeks.
    Profile("weeks_aggressive", "weeks", "aggressive", Interval.W1, "breakout",
            {"entry_n": 13, "exit_n": 6},
            "Compra al romper el máximo de 13 semanas; sale al perder el mínimo de 6."),
    Profile("weeks_balanced", "weeks", "balanced", Interval.W1, "ema_cross",
            {"fast": 10, "slow": 30},
            "Cruce de medias exponenciales de 10 y 30 semanas."),
    Profile("weeks_conservative", "weeks", "conservative", Interval.W1, "trend_exhaustion",
            {"period": 40, "conditions": 3, "rsi_high": 70},
            "Tendencia sobre la media de 40 semanas; sale antes si la subida se agota."),
    # Months.
    Profile("months_aggressive", "months", "aggressive", Interval.MN1, "ema_cross",
            {"fast": 3, "slow": 10},
            "Cruce de medias de 3 y 10 meses: entra pronto en las tendencias largas."),
    Profile("months_balanced", "months", "balanced", Interval.MN1, "trend_exhaustion",
            {"period": 10, "conditions": 3, "rsi_high": 70},
            "Tendencia sobre la media de 10 meses; sale antes si la subida se agota."),
    Profile("months_conservative", "months", "conservative", Interval.MN1, "trend_exhaustion",
            {"period": 12, "conditions": 2, "rsi_high": 65},
            "Tendencia sobre la media de 12 meses; sale con solo 2 señales de agotamiento."),
)  # fmt: skip
PROFILE_BY_ID = {p.id: p for p in PROFILES}


def profile(profile_id: str) -> Profile:
    try:
        return PROFILE_BY_ID[profile_id]
    except KeyError:
        raise UserError(f"unknown profile {profile_id!r}",
                        user_message="Perfil de estrategia desconocido.") from None  # fmt: skip
