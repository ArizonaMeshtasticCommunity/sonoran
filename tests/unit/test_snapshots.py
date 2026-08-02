"""Tests for the daily snapshot schedule."""

from datetime import UTC, datetime

from sonoran.jobs.snapshots import _delay_to_next_utc_day


def test_delay_is_to_the_next_utc_day() -> None:
    """The snapshot service waits until shortly after UTC midnight."""
    now = datetime(2026, 8, 1, 23, 59, 50, tzinfo=UTC)
    assert _delay_to_next_utc_day(now) == 15
