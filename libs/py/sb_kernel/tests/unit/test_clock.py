from datetime import UTC, datetime, timedelta, timezone

import pytest

from sb_kernel.clock import FixedClock, SystemClock


def test_system_clock_is_aware_utc() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_fixed_clock_advances() -> None:
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    clock.advance(timedelta(days=1))
    assert clock.now() == datetime(2026, 1, 2, tzinfo=UTC)


def test_fixed_clock_rejects_naive() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 1, 1))  # noqa: DTZ001 - asserting the rejection


def test_fixed_clock_normalizes_to_utc() -> None:
    plus2 = timezone(timedelta(hours=2))
    clock = FixedClock(datetime(2026, 1, 1, 2, tzinfo=plus2))
    assert clock.now().tzinfo is UTC
    assert clock.now() == datetime(2026, 1, 1, tzinfo=UTC)
    clock.advance(timedelta(hours=1))
    assert clock.now().tzinfo is UTC
