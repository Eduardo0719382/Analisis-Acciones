"""When does cached end-of-day data need refreshing?

US regular sessions close at 16:00 America/New_York. Cached daily data is
considered current if it was fetched after the most recent session close
(plus a settling buffer). Exchange holidays are not modelled: on a holiday the
"expected" session simply yields no new bar, and because the fetch time is
recorded, the provider is asked at most once per session close.

Cryptocurrencies (Yahoo pairs such as ``BTC-USD``) trade every day around the
clock; Yahoo closes their daily bar at 00:00 UTC. For them the "session" is the
UTC calendar day and cached data is refreshed at most every ``CRYPTO_REFRESH``.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SESSION_CLOSE = time(16, 0)
SETTLE = timedelta(minutes=30)
CRYPTO_SETTLE = timedelta(minutes=10)
CRYPTO_REFRESH = timedelta(hours=1)

# Base asset, a dash and a known quote currency: BTC-USD, ETH-EUR, SOL-USDT...
# Share classes (BRK-B) and warrants never end in one of these currencies.
_QUOTES = ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "KRW", "INR", "BRL",
           "MXN", "USDT", "USDC", "BTC", "ETH")  # fmt: skip
_CRYPTO = re.compile(rf"^[A-Z0-9]{{2,12}}-(?:{'|'.join(_QUOTES)})$")


def is_crypto(symbol: str) -> bool:
    """Is ``symbol`` a Yahoo cryptocurrency pair (``BTC-USD``)? Decided by its form only."""
    return bool(_CRYPTO.match(symbol.strip().upper()))


def last_session_close(now: datetime) -> datetime:
    """Most recent weekday close (+ buffer) at or before ``now`` (aware datetime)."""
    local = now.astimezone(NEW_YORK)
    day = local.date()
    while True:
        if day.weekday() < 5:
            close = datetime.combine(day, SESSION_CLOSE, tzinfo=NEW_YORK) + SETTLE
            if close <= local:
                return close
        day -= timedelta(days=1)


def last_utc_close(now: datetime) -> datetime:
    """Most recent 00:00 UTC (+ buffer) at or before ``now``: the end of a crypto daily bar."""
    local = now.astimezone(UTC)
    close = datetime.combine(local.date(), time(0), tzinfo=UTC) + CRYPTO_SETTLE
    return close if close <= local else close - timedelta(days=1)


def needs_refresh(fetched_at: datetime, now: datetime, crypto: bool = False) -> bool:
    if crypto:
        return fetched_at < last_utc_close(now) or now - fetched_at >= CRYPTO_REFRESH
    return fetched_at < last_session_close(now)


def session_in_progress(last_bar: date | None, now: datetime, crypto: bool = False) -> bool:
    """True when the last bar belongs to today's session that has not closed yet.

    For crypto the bar of the current UTC day is always still forming.
    """
    if last_bar is None:
        return False
    if crypto:
        return last_bar >= now.astimezone(UTC).date()
    local = now.astimezone(NEW_YORK)
    close = datetime.combine(local.date(), SESSION_CLOSE, tzinfo=NEW_YORK)
    return last_bar == local.date() and local < close + SETTLE


SESSION_OPEN = time(9, 30)


def market_open(now: datetime) -> bool:
    """Regular US session hours on a weekday (holidays are not modelled)."""
    local = now.astimezone(NEW_YORK)
    return local.weekday() < 5 and SESSION_OPEN <= local.time() < SESSION_CLOSE
