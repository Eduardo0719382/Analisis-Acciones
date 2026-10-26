"""Trading costs charged to a profile's virtual book.

Rates were looked up on 2026-10-26, not assumed (sources in DECISIONS.md, D-080):

* Crypto (Alpaca, tier 1, 0-100k USD of 30-day volume): taker 0.25 %, maker 0.15 %. A buy
  pays in the coin received (the position shrinks), a sell pays in dollars. Seen on this
  account: buys charged 0.25 % of the quantity, rounded up to 9 decimals and taken from the
  position at once; each sell was rounded up to the cent. Alpaca posts them the next day as
  ``CFEE`` activities, without an order id, so the book charges them at the fill and
  ``reconcile`` compares the totals with the posted fees.
* Stocks: no commission. Sells pay the SEC fee (Section 31) on the principal and FINRA's
  TAF per share sold (capped); every trade pays the CAT fee per share. The paper account
  does not charge them, so the book does, to stay honest.
* Spread and slippage are not a fee line: the book uses the real fill price, which already
  contains them. ``spread_pct`` measures the spread from a quote so a profile can tell, before
  buying, whether the expected move pays for the round trip.
"""

from __future__ import annotations

import math
from datetime import date

CRYPTO_TAKER = 0.0025
CRYPTO_MAKER = 0.0015

#: (first day it applies, USD per million of principal sold). Section 31.
SEC_RATES: tuple[tuple[date, float], ...] = (
    (date(2025, 5, 14), 0.0),
    (date(2026, 4, 4), 20.60),
)
#: (first day it applies, USD per share sold, maximum per trade). FINRA TAF; paused for Q4 2026
#: (SR-FINRA-2026-021), back on 2027-01-01.
TAF_RATES: tuple[tuple[date, float, float], ...] = (
    (date(2026, 1, 1), 0.000195, 9.79),
    (date(2026, 10, 1), 0.0, 0.0),
    (date(2027, 1, 1), 0.000195, 9.79),
)
#: USD per share, buys and sells (effective rate given in Alpaca's regulatory-fee docs).
CAT_PER_SHARE = 0.000046


def _dated(table: tuple[tuple[date, float], ...] | tuple[tuple[date, float, float], ...],
           day: date) -> tuple[float, ...]:  # fmt: skip
    current: tuple[float, ...] = (0.0,) * (len(table[0]) - 1)
    for row in table:
        if row[0] <= day:
            current = tuple(row[1:])
    return current


def ceil_cent(value: float) -> float:
    return math.ceil(round(value * 100, 6)) / 100


def crypto_fee(
    side: str, qty: float, price: float, rate: float = CRYPTO_TAKER
) -> tuple[float, float]:
    """(fee in coin, fee in USD) of a crypto fill. Exactly one of them is non-zero."""
    if side == "buy":  # rounded up to the coin's 9 decimals, as Alpaca does
        return math.ceil(round(qty * rate * 1e9, 3)) / 1e9, 0.0
    return 0.0, ceil_cent(qty * price * rate)


def stock_fees(side: str, qty: float, price: float, day: date) -> float:
    """SEC + TAF (sells) and CAT (both sides) in USD for one stock fill."""
    cat = qty * CAT_PER_SHARE
    if side != "sell":
        return cat
    (sec_per_million,) = _dated(SEC_RATES, day)
    taf_per_share, taf_max = _dated(TAF_RATES, day)
    sec = qty * price * sec_per_million / 1_000_000
    taf = min(qty * taf_per_share, taf_max)
    return sec + taf + cat


def spread_pct(bid: float | None, ask: float | None) -> float | None:
    if not bid or not ask or bid <= 0 or ask < bid:
        return None
    return (ask - bid) / ((ask + bid) / 2) * 100


#: Stock quotes come from IEX (the free feed: one exchange), whose spread can be far wider
#: than the market's, and is meaningless outside the session. Above this it is not trusted.
STOCK_SPREAD_TRUSTED_MAX = 0.5
#: Used instead for a stock whose IEX spread is missing or not trusted (an assumption,
#: checked against real fills in the weekly review).
STOCK_SPREAD_FALLBACK = 0.10


def effective_spread(
    crypto: bool, bid: float | None, ask: float | None
) -> tuple[float | None, bool]:
    """(spread % to use in the cost check, whether it was measured)."""
    measured = spread_pct(bid, ask)
    if crypto:
        return measured, measured is not None
    if measured is None or measured > STOCK_SPREAD_TRUSTED_MAX:
        return STOCK_SPREAD_FALLBACK, False
    return measured, True


def round_trip_cost_pct(crypto: bool, price: float, spread: float | None, day: date) -> float:
    """Estimated cost, in % of the amount, of buying now and selling later at the same price.

    Crypto sells are rounded up to the cent, which is ignored here (it matters only for
    amounts of a few dollars).
    """
    if crypto:
        fees = 2 * CRYPTO_TAKER * 100
    else:
        fees = (
            (stock_fees("buy", 1.0, price, day) + stock_fees("sell", 1.0, price, day)) / price * 100
        )
    return fees + (spread or 0.0)
