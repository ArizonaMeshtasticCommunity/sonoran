"""Counting from the hourly totals: the hour arithmetic (#366).

The SQL is checked against raw counts in
`tests/integration/test_hourly_counts.py`.
"""

import inspect
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sonoran.api import hourly
from sonoran.api.routes import stats


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, 12, hour, minute, second, tzinfo=UTC)


def test_an_hour_boundary_is_its_own_floor_and_ceiling() -> None:
    assert hourly.floor_hour(_at(5)) == _at(5)
    assert hourly.ceil_hour(_at(5)) == _at(5)


def test_a_moment_inside_an_hour_rounds_out_to_whole_hours() -> None:
    assert hourly.floor_hour(_at(5, 59, 59)) == _at(5)
    assert hourly.ceil_hour(_at(5, 0, 1)) == _at(6)


def test_whole_hours_are_split_from_the_two_partial_ends() -> None:
    assert hourly.split(_at(5, 10), _at(9, 20)) == (_at(6), _at(9))
    assert hourly.split(_at(5), _at(9)) == (_at(5), _at(9))


def test_a_window_with_no_whole_hour_is_counted_from_raw_rows() -> None:
    assert hourly.split(_at(5, 10), _at(5, 50)) is None
    assert hourly.split(_at(5, 10), _at(6, 50)) is None, "05:10 to 06:50 holds no whole hour"


def test_hourly_totals_add_up_to_days_only_in_a_whole_hour_zone() -> None:
    moment = _at(12)
    assert hourly.whole_hour_zone(ZoneInfo("America/Phoenix"), moment)
    assert hourly.whole_hour_zone(ZoneInfo("UTC"), moment)
    assert not hourly.whole_hour_zone(ZoneInfo("Asia/Kolkata"), moment), "UTC+5:30"


def test_the_slow_counts_go_through_the_hourly_totals() -> None:
    """The 12.7 s and 8.5 s requests: neither may count raw rows directly again."""
    for function in (stats._window_counts, stats._read_summary, stats._read_daily):
        source = inspect.getsource(function)
        assert "select_from(PacketSeen)" not in source, function.__name__
        assert "hourly." in source or "_kept(" in source, function.__name__
