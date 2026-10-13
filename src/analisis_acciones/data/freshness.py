"""When does cached end-of-day data need refreshing?

US regular sessions close at 16:00 America/New_York. Cached daily data is
considered current if it was fetched after the most recent session close
(plus a settling buffer). Exchange holidays are not modelled: on a holiday the
"expected" session simply yields no new bar, and because the fetch time is
recorded, the provider is asked at most once per session close.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SESSION_CLOSE = time(16, 0)
SETTLE = timedelta(minutes=30)


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


def needs_refresh(fetched_at: datetime, now: datetime) -> bool:
    return fetched_at < last_session_close(now)


def session_in_progress(last_bar: date | None, now: datetime) -> bool:
    """True when the last bar belongs to today's session that has not closed yet."""
    if last_bar is None:
        return False
    local = now.astimezone(NEW_YORK)
    close = datetime.combine(local.date(), SESSION_CLOSE, tzinfo=NEW_YORK)
    return last_bar == local.date() and local < close + SETTLE
