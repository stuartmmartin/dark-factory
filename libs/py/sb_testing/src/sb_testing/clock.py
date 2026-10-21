"""FakeClock for tests (T8): time moves only when the test says so.

Like `sb_kernel.clock.FixedClock`, it normalises to UTC, so `now()` always returns a UTC
datetime whatever zone the test passed in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _utc(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("FakeClock needs a timezone-aware datetime")
    return at.astimezone(UTC)


class FakeClock:
    def __init__(self, at: datetime) -> None:
        self._at = _utc(at)

    def now(self) -> datetime:
        return self._at

    def advance(self, delta: timedelta) -> None:
        self._at += delta

    def set(self, at: datetime) -> None:
        self._at = _utc(at)
