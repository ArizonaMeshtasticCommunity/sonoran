"""The time window a statistics request covers (#294).

The Statistics page has one range control, and every widget on it reads
the same window. A window is either rolling (`hours`, which ends now) or
fixed (`since` and optionally `until`). This module is the one place
that turns those query parameters into two instants, so the widgets
cannot disagree about what "the last 7 days" means.

Rules, each one a way this could go wrong:

- **Receive time, bounded at both ends.** The window ends at now at the
  latest. A row dated in the future by a gateway clock written before
  the AGENTS.md 9.4 fix must not count in any window.
- **A date without a time zone is a local date.** The page sends
  `since=2026-09-01`, which the reader means as midnight in the mesh's
  own zone (`DISPLAY_TIMEZONE`), not in UTC. Arizona is seven hours from
  UTC, so reading it as UTC would move every day boundary to 5 pm.
- **At most `MAX_HOURS`.** That is 30 days, the default packet
  retention. A longer window over `packet` would read ground that has
  already been deleted and call it quiet.
- **A window can still start before what is kept.** A fixed range can
  begin 40 days ago. The answer then carries `retained_from`, so the page
  can say the widget counts from there, rather than pretend it counted
  the whole range.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query, Request

from sonoran.config import Settings

#: The longest window any statistics widget reads: 30 days.
MAX_HOURS = 720

# The three query parameters, made once. A call in an argument default
# would be made once anyway; naming them says so.
_HOURS = Query(default=None, ge=1, le=MAX_HOURS)
_SINCE = Query(default=None)
_UNTIL = Query(default=None)


@dataclass(frozen=True)
class Window:
    """Two instants in UTC, and the words the request used for them."""

    start: datetime
    end: datetime
    #: A key for a cache: the request's own words, not the instants, so a
    #: rolling window does not become a new key every second.
    key: str

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    def describe(self, settings: Settings) -> dict[str, object]:
        """The window, as each answer states it."""
        return {
            "window_hours": round(self.hours, 2),
            "window_start": self.start.isoformat(),
            "window_end": self.end.isoformat(),
            # The oldest packet the database still holds, by retention.
            "retained_from": retained_from(settings).isoformat(),
        }


def retained_from(settings: Settings) -> datetime:
    """Return the oldest receive time the `packet` table still covers."""
    return datetime.now(UTC) - timedelta(days=settings.retention_days_packet)


def _aware(value: datetime, zone: ZoneInfo) -> datetime:
    """Read a time with no zone as the mesh's local time."""
    return value.replace(tzinfo=zone) if value.tzinfo is None else value


def _refuse(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def resolve(
    settings: Settings,
    hours: int | None,
    since: datetime | None,
    until: datetime | None,
    default_hours: int | None,
    now: datetime | None = None,
) -> Window | None:
    """Turn the three query parameters into a window, or None for all time."""
    now = now or datetime.now(UTC)
    if since is None and until is None:
        chosen = hours if hours is not None else default_hours
        if chosen is None:
            return None
        return Window(now - timedelta(hours=chosen), now, key=f"h{chosen}")
    if hours is not None:
        raise _refuse("Give hours, or since and until, not both.")
    if since is None:
        raise _refuse("A window with an end needs a start as well.")
    zone = ZoneInfo(settings.display_timezone)
    start = _aware(since, zone).astimezone(UTC)
    # Never past now: the future holds only rows with a wrong clock.
    end = min(_aware(until, zone).astimezone(UTC), now) if until is not None else now
    if start >= end:
        raise _refuse("The window must start before it ends, and before now.")
    if end - start > timedelta(hours=MAX_HOURS):
        raise _refuse(f"A window can be at most {MAX_HOURS // 24} days.")
    until_key = until.isoformat() if until is not None else "now"
    return Window(start, end, key=f"{since.isoformat()}~{until_key}")


def optional_window(
    request: Request,
    hours: int | None = _HOURS,
    since: datetime | None = _SINCE,
    until: datetime | None = _UNTIL,
) -> Window | None:
    """A FastAPI dependency: the window asked for, or None for all time."""
    settings: Settings = request.app.state.settings
    return resolve(settings, hours, since, until, None)


def window_query(default_hours: int) -> Callable[..., Window]:
    """Make a FastAPI dependency that reads a window, with a default.

    `default_hours` is what the endpoint answered before it took a
    window, so a caller that sends nothing gets the same answer as before.
    """

    def dependency(
        request: Request,
        hours: int | None = _HOURS,
        since: datetime | None = _SINCE,
        until: datetime | None = _UNTIL,
    ) -> Window:
        settings: Settings = request.app.state.settings
        window = resolve(settings, hours, since, until, default_hours)
        assert window is not None, "a default window always resolves"
        return window

    return dependency


#: A rolling window is held for this share of its length (#371): 1/720,
#: so a day is held 2 minutes and 30 days hit the ceiling.
CACHE_WINDOW_SHARE = 720

#: An answer with no window (all-time totals) is held this long: its
#: numbers move by a few packets a minute out of hundreds of thousands.
UNWINDOWED_CACHE_SECONDS = 120.0


def cache_seconds(settings: Settings, window: "Window | float | None") -> float:
    """How long to hold an answer about `window`, in seconds.

    `window` is a `Window`, a length in hours, or None for no window.

    - Rolling: 1/`CACHE_WINDOW_SHARE` of its length, between
      `STATS_CACHE_SECONDS` and `STATS_CACHE_MAX_SECONDS`. New packets
      enter at the newest edge; a longer window is moved less by them.
    - Fixed and over: `STATS_CACHE_MAX_SECONDS`. Nothing new can enter.
    - No window: `UNWINDOWED_CACHE_SECONDS`, within the same bounds.

    `STATS_CACHE_SECONDS=0` turns every hold off, as it always did.
    """
    shortest = settings.stats_cache_seconds
    if shortest <= 0:
        return 0.0
    longest = max(shortest, settings.stats_cache_max_seconds)
    if window is None:
        return min(max(shortest, UNWINDOWED_CACHE_SECONDS), longest)
    if isinstance(window, Window):
        if window.end < datetime.now(UTC) - timedelta(seconds=longest):
            return longest
        hours = window.hours
    else:
        hours = float(window)
    return min(max(shortest, hours * 3600 / CACHE_WINDOW_SHARE), longest)
