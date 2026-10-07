"""Roll each finished hour of every swept range up into `rf_spectrum_hour`.

The 3 and 7 day waterfalls read these rows instead of every minute
(revision 0019). Each hour is built with the same per-bin rules as a
waterfall row (`rf/spectrum_sql.py`): the median of the minute medians,
the highest 95th percentile, the mean busy share, and the loudest moment
with the minute it happened.

Each run:

- finds the finished hours that have minutes and no rollup yet, from the
  key columns only, so finding them never reads the arrays;
- adds the last `RECENT_HOURS` again, because an agent that was cut off
  from the broker sends its queued minutes late;
- builds at most `MAX_HOURS_PER_RUN` of them, newest first. The first
  run after a deploy has 14 days to fill and spreads that over a few
  runs instead of one long one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import RfSpectrum, RfSpectrumHour
from sonoran.logging import get_logger
from sonoran.rf.spectrum_sql import bin_rows

logger = get_logger(__name__)

HOUR = timedelta(hours=1)
KEEP = timedelta(days=14)
RECENT_HOURS = 3
MAX_HOURS_PER_RUN = 48


@dataclass(frozen=True, order=True)
class HourKey:
    """One hour of one range of one station (#324)."""

    t: datetime
    station_id: str
    source: str
    f_start_hz: int
    bin_hz: int
    bins: int


def floor_hour(when: datetime) -> datetime:
    return when.replace(minute=0, second=0, microsecond=0)


async def hours_to_build(
    session: AsyncSession, now: datetime, limit: int = MAX_HOURS_PER_RUN
) -> list[HourKey]:
    """Return the hours to build this run, newest first."""
    current = floor_hour(now)
    since = current - KEEP
    hour = func.time_bucket(HOUR, RfSpectrum.t)
    raw = {
        HourKey(t, station, source, f_start, bin_hz, bins)
        for station, t, source, f_start, bin_hz, bins in (
            await session.execute(
                select(
                    RfSpectrum.station_id,
                    hour,
                    RfSpectrum.source,
                    RfSpectrum.f_start_hz,
                    RfSpectrum.bin_hz,
                    RfSpectrum.bins,
                )
                .where(RfSpectrum.t >= since, RfSpectrum.t < current)
                .distinct()
            )
        ).all()
    }
    done = {
        HourKey(t, station, source, f_start, bin_hz, bins)
        for station, t, source, f_start, bin_hz, bins in (
            await session.execute(
                select(
                    RfSpectrumHour.station_id,
                    RfSpectrumHour.t,
                    RfSpectrumHour.source,
                    RfSpectrumHour.f_start_hz,
                    RfSpectrumHour.bin_hz,
                    RfSpectrumHour.bins,
                ).where(RfSpectrumHour.t >= since)
            )
        ).all()
    }
    recent = current - RECENT_HOURS * HOUR
    todo = [key for key in raw if key not in done or key.t >= recent]
    return sorted(todo, reverse=True)[:limit]


async def build_hour(session: AsyncSession, key: HourKey, now: datetime) -> bool:
    """Build one hour. True when it had minutes to build from."""
    in_hour = (
        RfSpectrum.station_id == key.station_id,
        RfSpectrum.source == key.source,
        RfSpectrum.t >= key.t,
        RfSpectrum.t < key.t + HOUR,
        RfSpectrum.f_start_hz == key.f_start_hz,
        RfSpectrum.bin_hz == key.bin_hz,
        RfSpectrum.bins == key.bins,
    )
    gain_db = await session.scalar(
        select(RfSpectrum.gain_db).where(*in_hour).order_by(RfSpectrum.t.desc()).limit(1)
    )
    if gain_db is None:
        return False
    row = (await session.execute(bin_rows(func.time_bucket(HOUR, RfSpectrum.t), *in_hour))).first()
    if row is None:
        return False
    _, p50, p95, busy, minutes, peak, peak_min = row

    def ints(values: list[object]) -> list[int | None]:
        return [None if v is None else int(v) for v in values]  # type: ignore[call-overload]

    values = {
        "gain_db": gain_db,
        "minutes": int(minutes),
        "p50": ints(p50),
        "p95": ints(p95),
        "busy": ints(busy),
        "peak": ints(peak),
        "peak_min": ints(peak_min),
        "computed_at": now,
    }
    statement = insert(RfSpectrumHour).values(
        station_id=key.station_id,
        source=key.source,
        t=key.t,
        f_start_hz=key.f_start_hz,
        bin_hz=key.bin_hz,
        bins=key.bins,
        **values,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["station_id", "source", "t", "f_start_hz", "bin_hz", "bins"],
            set_=values,
        )
    )
    return True


async def run_once(session: AsyncSession, now: datetime | None = None) -> int:
    """Build the hours that are due. Returns how many were built."""
    now = now or datetime.now(UTC)
    built = 0
    for key in await hours_to_build(session, now):
        if await build_hour(session, key, now):
            built += 1
        # One hour per transaction: a failure loses one hour, not the run.
        await session.commit()
    if built:
        logger.info("rolled up %d hours of swept ranges", built)
    return built
