"""How long a Statistics or graph answer is held grows with its window (#371).

A window of 30 days moves by a few packets in five minutes; a window of
an hour moves visibly. So the hold is a share of the window, between
`STATS_CACHE_SECONDS` and `STATS_CACHE_MAX_SECONDS`.
"""

from datetime import UTC, datetime, timedelta

from sonoran.api.window import Window, cache_seconds
from sonoran.config import Settings


def _settings(**extra: object) -> Settings:
    return Settings(_env_file=None, **extra)  # type: ignore[arg-type]


def _rolling(hours: int) -> Window:
    now = datetime.now(UTC)
    return Window(now - timedelta(hours=hours), now, key=f"h{hours}")


def test_a_rolling_window_is_held_for_a_share_of_its_length() -> None:
    settings = _settings()
    assert cache_seconds(settings, _rolling(1)) == 30.0, "an hour keeps the shortest hold"
    assert cache_seconds(settings, _rolling(24)) == 120.0, "a day is held 2 minutes"
    assert cache_seconds(settings, _rolling(72)) == 300.0
    assert cache_seconds(settings, _rolling(720)) == 300.0, "30 days stop at the ceiling"
    assert cache_seconds(settings, 24) == 120.0, "a length in hours reads the same"


def test_a_range_that_is_over_is_held_the_longest() -> None:
    end = datetime.now(UTC) - timedelta(days=2)
    past = Window(end - timedelta(hours=1), end, key="fixed")
    assert cache_seconds(_settings(), past) == 300.0


def test_no_window_is_held_two_minutes() -> None:
    assert cache_seconds(_settings(), None) == 120.0


def test_zero_still_turns_every_hold_off() -> None:
    settings = _settings(stats_cache_seconds=0)
    for window in (None, 24, _rolling(720)):
        assert cache_seconds(settings, window) == 0.0


def test_the_ceiling_and_the_floor_are_settings() -> None:
    settings = _settings(stats_cache_seconds=10, stats_cache_max_seconds=60)
    assert cache_seconds(settings, _rolling(1)) == 10.0
    assert cache_seconds(settings, _rolling(720)) == 60.0
