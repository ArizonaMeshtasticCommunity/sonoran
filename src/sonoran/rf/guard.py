"""What the ingest checks before a station's data reaches a shared layer (#324).

A member's Pi is theirs. Anyone can change their copy of the agent, or
send messages by hand with their login, and nothing the Pi says about
itself can prove otherwise. So every message is a claim, attributed to
one station and source, and the checks that matter run here, where we
control them. The agent's own checks are a convenience, never a defence.

`Guard` keeps, in memory and bounded:

- each station's rounded position, from its heartbeats, for the reach
  check;
- the recent points of each thing, per station, for the motion and
  corroboration checks;
- the trust level an operator set for each station or source;
- the quotas: how much each station sent in the last minute.

None of it is read from the RF tables: the ingest role cannot read them
(`AGENTS.md` 9.2). It reads `rf_trust`, which only operators write.
Everything here is lost on a restart and rebuilt within minutes, because
the broker replays every station's retained heartbeat on connect.
"""

from __future__ import annotations

import logging
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import RfTrust

logger = logging.getLogger(__name__)

# Trust levels, set by an operator with `sonoran-rf-trust`, never by a
# message. A higher level wins a shared point. A quarantined station
# keeps its own data and adds nothing to the shared layers.
QUARANTINED = 0
NEW = 1
TRUSTED = 2
TRUST_NAMES = {QUARANTINED: "quarantined", NEW: "new", TRUSTED: "trusted"}
TRUST_LEVELS = {name: level for level, name in TRUST_NAMES.items()}
ANY_SOURCE = "*"

# How far each kind can be heard, in km, from the station's own rounded
# position. Generous on purpose: a point past this is not a long-range
# record, it is a claim nothing could receive. An aircraft at 12 km is
# above the horizon to about 450 km. A sonde at 35 km to about 670 km.
# APRS positions are the sender's own report, and a packet can arrive
# through a chain of digipeaters. A weather sensor is drawn where it was
# heard, so its reach is the station's rounding and a little more.
REACH_KM: dict[str, float] = {
    "adsb": 550.0,
    "uat": 550.0,
    "aprs": 1000.0,
    "sonde": 800.0,
    "ism": 120.0,
}
# The fastest each kind can move, in m/s. Aircraft get room for fast
# military jets, APRS for a tracker on an aircraft, sondes for the jet
# stream. A weather sensor does not move.
SPEED_MS: dict[str, float] = {
    "adsb": 700.0,
    "uat": 700.0,
    "aprs": 350.0,
    "sonde": 200.0,
}
# Room for rounding, blurring and GNSS error, beside what speed allows.
SLACK_KM = 3.0
# How long a station's last point of a thing is kept for the checks.
RECENT = timedelta(minutes=10)
# Points of other stations closer in time than this corroborate.
CORROBORATE = timedelta(seconds=60)
# A point that disagrees with this many other stations is doubtful.
CORROBORATORS = 2
# Things remembered at once. A busy sky over Arizona is a few hundred.
MAX_THINGS = 50_000
# How long minute counts are kept: an agent sends what it queued while
# the broker was away, up to two hours of spectrum minutes.
MINUTES_KEPT = timedelta(hours=3)
# Over-quota is logged once an hour per station and limit.
QUOTA_LOG_EVERY = timedelta(hours=1)


def parse_refused(spec: str) -> tuple[int, int]:
    """Parse `start:end` in Hz. Raises ValueError."""
    try:
        start, end = (int(part) for part in spec.strip().split(":"))
    except ValueError as exc:
        raise ValueError(f"{spec!r} is not start:end in Hz") from exc
    if not 0 <= start < end:
        raise ValueError(f"{spec!r}: start must be below end")
    return start, end


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The great-circle distance between two points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class Bucket:
    """A token bucket: `rate` a minute, up to `burst` at once."""

    rate: float
    burst: float
    tokens: float = -1.0
    at: datetime | None = None

    def take(self, wanted: int, now: datetime) -> int:
        """Take up to `wanted` tokens. Returns how many were given."""
        if self.at is None:
            self.tokens = self.burst
        else:
            elapsed = max(0.0, (now - self.at).total_seconds())
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate / 60.0)
        self.at = now
        given = min(wanted, int(self.tokens))
        self.tokens -= given
        return max(0, given)


@dataclass(frozen=True)
class Limits:
    """The per-station limits, from the settings."""

    messages_per_minute: int = 240
    messages_burst: int = 2400
    points_per_minute: int = 3000
    points_burst: int = 30000
    spectrum_max_ranges: int = 4
    spectrum_max_bins: int = 8192
    refused: tuple[tuple[int, int], ...] = ()
    custom_per_minute: int = 600
    custom_burst: int = 6000
    custom_max_ids: int = 1000


@dataclass
class _Seen:
    lat: float
    lon: float
    when: datetime


@dataclass
class _Station:
    position: tuple[float, float, float] | None = None  # lat, lon, precision in metres
    messages: Bucket | None = None
    points: Bucket | None = None
    custom: Bucket | None = None
    # (minute) -> ranges and bins stored in that minute
    spectrum: dict[datetime, tuple[set[tuple[object, ...]], int]] = field(default_factory=dict)
    # (day) -> custom ids seen that day
    custom_ids: dict[datetime, set[tuple[str, str]]] = field(default_factory=dict)
    quota_logged: dict[str, datetime] = field(default_factory=dict)


class Guard:
    """The ingest's checks on what each station sends. See the module text."""

    def __init__(self, limits: Limits | None = None) -> None:
        self.limits = limits or Limits()
        self._stations: dict[str, _Station] = {}
        self._things: OrderedDict[tuple[str, str], dict[str, _Seen]] = OrderedDict()
        self._trust: dict[tuple[str, str], int] = {}
        # Over-quota and refused counts since the last report.
        self.dropped: dict[str, int] = {}

    # --- Trust -------------------------------------------------------

    def set_trust(self, levels: dict[tuple[str, str], int]) -> None:
        """Replace the trust levels: (station, source or `*`) -> level."""
        self._trust = dict(levels)

    async def refresh(self, session: AsyncSession) -> None:
        """Read the operators' trust levels again."""
        query = select(RfTrust.station_id, RfTrust.source, RfTrust.trust)
        rows = (await session.execute(query)).all()
        self.set_trust({(station, source): int(level) for station, source, level in rows})

    def trust_of(self, station: str, source: str | None) -> int:
        """The level of a source: its own, else its station's, else `NEW`."""
        if source is not None and (station, source) in self._trust:
            return self._trust[(station, source)]
        return self._trust.get((station, ANY_SOURCE), NEW)

    # --- Positions and plausibility ----------------------------------

    def _station(self, station: str) -> _Station:
        found = self._stations.get(station)
        if found is None:
            found = self._stations[station] = _Station()
        return found

    def note_position(
        self, station: str, lat: float | None, lon: float | None, precision_m: float | None
    ) -> None:
        """Remember where a station is, from its heartbeat."""
        if lat is None or lon is None:
            return
        self._station(station).position = (lat, lon, float(precision_m or 0))

    def doubtful(
        self, kind: str, station: str, thing: str, lat: float, lon: float, when: datetime
    ) -> str | None:
        """Why a point is not plausible, or None when it is.

        A doubtful point stays in the station's own view and never takes
        a shared point. The checks:

        - **Reach:** further from the station than its kind can be heard.
        - **Motion:** further from the station's own last point of the
          same thing than the thing could have moved.
        - **Corroboration:** where at least `CORROBORATORS` other stations
          placed the same thing lately, a point that none of them could
          have seen is doubtful.

        A station that sent no position is not checked for reach. The
        motion and corroboration checks still hold.
        """
        reach = REACH_KM.get(kind)
        own = self._station(station).position
        if reach is not None and own is not None:
            away = distance_km(own[0], own[1], lat, lon) - own[2] / 1000.0
            if away > reach:
                return f"{away:.0f} km from the station; {kind} reaches {reach:.0f} km"
        speed = SPEED_MS.get(kind)
        if speed is None:
            return None
        recent = self._things.get((kind, thing), {})
        mine = recent.get(station)
        if mine is not None and not self._could_move(mine, lat, lon, when, speed):
            return "moved faster than it can since this station's last point"
        others = [
            seen
            for name, seen in recent.items()
            if name != station and abs(when - seen.when) <= CORROBORATE
        ]
        if len(others) >= CORROBORATORS and not any(
            self._could_move(seen, lat, lon, when, speed) for seen in others
        ):
            return f"disagrees with {len(others)} other stations"
        return None

    @staticmethod
    def _could_move(seen: _Seen, lat: float, lon: float, when: datetime, speed: float) -> bool:
        seconds = abs((when - seen.when).total_seconds())
        return distance_km(seen.lat, seen.lon, lat, lon) <= speed * seconds / 1000.0 + SLACK_KM

    def remember(
        self, kind: str, station: str, thing: str, lat: float, lon: float, when: datetime
    ) -> None:
        """Keep a plausible point for the checks of the next ones."""
        key = (kind, thing)
        recent = self._things.pop(key, None) or {}
        recent[station] = _Seen(lat, lon, when)
        for name in [n for n, seen in recent.items() if when - seen.when > RECENT]:
            del recent[name]
        self._things[key] = recent
        while len(self._things) > MAX_THINGS:
            self._things.popitem(last=False)

    # --- Quotas ------------------------------------------------------

    def _over(self, station: str, what: str, count: int, now: datetime) -> None:
        if count <= 0:
            return
        self.dropped[what] = self.dropped.get(what, 0) + count
        state = self._station(station)
        last = state.quota_logged.get(what)
        if last is None or now - last >= QUOTA_LOG_EVERY:
            state.quota_logged[what] = now
            logger.warning(
                "RF station %s is over its %s limit: %d dropped (logged once an hour per station)",
                station,
                what,
                count,
            )

    def allow_message(self, station: str, now: datetime) -> bool:
        """Count one message against the station. False when over its limit."""
        state = self._station(station)
        if state.messages is None:
            state.messages = Bucket(self.limits.messages_per_minute, self.limits.messages_burst)
        if state.messages.take(1, now):
            return True
        self._over(station, "messages", 1, now)
        return False

    def allow_points(self, station: str, wanted: int, now: datetime) -> int:
        """How many of `wanted` observations the station may store now."""
        state = self._station(station)
        if state.points is None:
            state.points = Bucket(self.limits.points_per_minute, self.limits.points_burst)
        given = state.points.take(wanted, now)
        self._over(station, "points", wanted - given, now)
        return given

    def allow_spectrum(
        self,
        station: str,
        range_key: tuple[object, ...],
        f_start_hz: int,
        bins: int,
        bin_hz: int,
        minute: datetime,
        now: datetime,
    ) -> str | None:
        """Why one minute of one range is refused, or None to store it.

        The limits are on the minute the station measured, not when it
        arrived, so a backlog sent after an outage is not refused for
        arriving at once, and a station can never store more than
        `spectrum_max_ranges` ranges for one minute however it sends them.
        """
        end = f_start_hz + bins * bin_hz
        for low, high in self.limits.refused:
            if f_start_hz < high and end > low:
                self._over(station, "refused range", 1, now)
                return "a range this sonoran does not store"
        state = self._station(station)
        for old in [m for m in state.spectrum if now - m > MINUTES_KEPT]:
            del state.spectrum[old]
        ranges, total = state.spectrum.get(minute, (set(), 0))
        if range_key in ranges:
            return None  # a repeat: the database ignores it
        if len(ranges) >= self.limits.spectrum_max_ranges:
            self._over(station, "spectrum ranges", 1, now)
            return f"more than {self.limits.spectrum_max_ranges} ranges in one minute"
        if total + bins > self.limits.spectrum_max_bins:
            self._over(station, "spectrum bins", 1, now)
            return f"more than {self.limits.spectrum_max_bins} bins in one minute"
        state.spectrum[minute] = (ranges | {range_key}, total + bins)
        return None

    def allow_custom(self, station: str, mod: str, ids: list[str], now: datetime) -> list[bool]:
        """Which of a mod's points the station may store now."""
        state = self._station(station)
        if state.custom is None:
            state.custom = Bucket(self.limits.custom_per_minute, self.limits.custom_burst)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for old in [d for d in state.custom_ids if d != day]:
            del state.custom_ids[old]
        seen = state.custom_ids.setdefault(day, set())
        given = state.custom.take(len(ids), now)
        out: list[bool] = []
        for index, thing in enumerate(ids):
            ok = index < given
            key = (mod, thing)
            if ok and key not in seen:
                if len(seen) >= self.limits.custom_max_ids:
                    ok = False
                else:
                    seen.add(key)
            out.append(ok)
        self._over(station, "custom points", out.count(False), now)
        return out
