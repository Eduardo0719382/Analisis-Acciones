from __future__ import annotations

from datetime import UTC, date, datetime

from analisis_acciones.data.freshness import (
    NEW_YORK,
    last_session_close,
    needs_refresh,
    session_in_progress,
)


def ny(*args: int) -> datetime:
    return datetime(*args, tzinfo=NEW_YORK)


def test_last_close_during_session_is_previous_day() -> None:
    # Wednesday 2024-03-13 at 11:00 New York -> Tuesday's close.
    close = last_session_close(ny(2024, 3, 13, 11, 0))
    assert close.date() == date(2024, 3, 12)


def test_last_close_after_settle_is_today() -> None:
    assert last_session_close(ny(2024, 3, 13, 16, 45)).date() == date(2024, 3, 13)


def test_weekend_maps_to_friday() -> None:
    assert last_session_close(ny(2024, 3, 17, 12, 0)).date() == date(2024, 3, 15)
    assert last_session_close(ny(2024, 3, 18, 9, 0)).date() == date(2024, 3, 15)


def test_needs_refresh() -> None:
    fetched = ny(2024, 3, 12, 17, 0)  # after Tuesday close
    assert not needs_refresh(fetched, ny(2024, 3, 13, 15, 0))  # still Wednesday session
    assert needs_refresh(fetched, ny(2024, 3, 13, 17, 0))  # Wednesday closed


def test_needs_refresh_accepts_utc_inputs() -> None:
    fetched = datetime(2024, 3, 12, 21, 0, tzinfo=UTC)  # 17:00 New York (EDT)
    assert not needs_refresh(fetched, datetime(2024, 3, 13, 19, 0, tzinfo=UTC))


def test_session_in_progress() -> None:
    assert session_in_progress(date(2024, 3, 13), ny(2024, 3, 13, 12, 0))
    assert not session_in_progress(date(2024, 3, 13), ny(2024, 3, 13, 17, 0))
    assert not session_in_progress(date(2024, 3, 12), ny(2024, 3, 13, 12, 0))
    assert not session_in_progress(None, ny(2024, 3, 13, 12, 0))
