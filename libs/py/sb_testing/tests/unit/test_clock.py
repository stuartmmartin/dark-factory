from datetime import UTC, datetime, timedelta, timezone

import pytest

from sb_testing.clock import FakeClock


def test_fake_clock_fixture_starts_at_fixed_instant(fake_clock: FakeClock) -> None:
    assert fake_clock.now() == datetime(2026, 1, 1, 9, tzinfo=UTC)
    fake_clock.advance(timedelta(hours=1))
    assert fake_clock.now().hour == 10


def test_fake_clock_normalises_to_utc_like_fixed_clock() -> None:
    plus_two = timezone(timedelta(hours=2))
    clock = FakeClock(datetime(2026, 1, 1, 11, tzinfo=plus_two))
    assert clock.now() == datetime(2026, 1, 1, 9, tzinfo=UTC)
    assert clock.now().tzinfo is UTC
    clock.set(datetime(2026, 1, 2, 12, tzinfo=plus_two))
    assert clock.now().tzinfo is UTC
    assert clock.now().hour == 10


def test_fake_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 1, 1))  # noqa: DTZ001 - deliberately naive
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(datetime(2026, 1, 1))  # noqa: DTZ001 - deliberately naive
