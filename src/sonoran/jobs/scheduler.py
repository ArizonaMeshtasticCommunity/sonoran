"""The scheduled work of the jobs process.

The process holds work that runs on different clocks. The daily
snapshot takes a moment once a day. The coverage run takes minutes and
wants to run several times a day.

The snapshot keeps its own clock. Calibration and coverage share one
clock because coverage depends on calibration. A due calibration runs
first. Coverage then reads the file it just wrote.

The gap assessment keeps its own clock as well, because it runs no
engine and wants to be fresher than a coverage run. **A task that does
use the engine must join `_coverage_cycle` instead of being added here:
tasks added here run beside each other under `asyncio.gather`, so a
second engine user is free to start during a coverage build and take the
last core of a small box.** The siting half of the coverage gaps feature
is exactly that case, and it runs inside `_coverage_cycle`.

A task that raises is logged and tried again at its next turn. One bad
run must never stop the process: a jobs container that exits stops
every other task with it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings, get_settings
from sonoran.db.session import make_engine, make_session_factory
from sonoran.jobs import calibrate, coverage, gaps, gaps_siting, snapshots
from sonoran.logging import configure_logging, get_logger

logger = get_logger(__name__)

# How long to wait before trying a task that failed.
#
# Short enough that a run lost to a restarting database comes back
# quickly. Long enough that a task failing every time does not fill the
# log.
RETRY_SECONDS = 300.0


@dataclass
class Task:
    """One piece of scheduled work."""

    name: str
    run: Callable[[], Awaitable[None]]
    # Seconds until this task should run again, from the moment it
    # finished. It is a function so a task can follow the clock rather
    # than a fixed period.
    next_delay: Callable[[], float]
    # True runs the task once as soon as the process starts.
    at_start: bool = True


def _delay_to_next_utc_day() -> float:
    """Return seconds until shortly after the next UTC day begins."""
    now = datetime.now(UTC)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)
    return max((tomorrow - now).total_seconds() + 5, 1.0)


async def _coverage_cycle(session: AsyncSession, settings: Settings, run_calibration: bool) -> None:
    """Run one clock's worth of engine work, in order.

    A due calibration runs first, because the coverage run consumes the
    file it writes. The siting half of the coverage gaps feature runs
    last, because it reads the run that coverage just published.

    **Everything that uses the engine belongs on this one clock.** The
    tasks in `build_tasks` run beside each other under `asyncio.gather`,
    so a second engine user registered there would be free to start
    during a coverage build. The engine has no IO to yield on, so a
    worker holds its core until it finishes, and on a three core box
    that also serves a public dashboard that is the last core.
    """
    if run_calibration:
        await calibrate.run_once(session, settings)
    await coverage.run_once(session, settings)
    if settings.gaps_enabled and settings.gaps_siting_enabled:
        # It reads the artefacts the two jobs above wrote and asks the
        # database nothing, so it takes no session.
        await gaps_siting.run_once(settings)


def _attempt_file(settings: Settings, name: str) -> Path:
    """Where the last attempt at one task is recorded."""
    return Path(settings.coverage_cache_dir) / "attempts" / f"{name}.txt"


def _read_last_attempt(settings: Settings, name: str) -> float | None:
    """Return when this task was last tried, across process restarts."""
    try:
        return float(_attempt_file(settings, name).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        # No file, an unreadable one, or something that is not a number.
        # All three mean the same thing -- nothing is known about a
        # previous attempt -- and none of them may stop the process.
        return None


def _record_attempt(settings: Settings, name: str) -> None:
    """Record that this task is being tried, BEFORE it is tried.

    Before, not after, and that ordering is the whole point. A task
    killed part-way through never reaches an "after". The coverage job
    is killed part-way through on this deployment every time -- the
    kernel OOM killer takes it, exit 137 -- so a success-only record
    would stay empty for ever and the backoff would never engage.

    A failure to write is logged and ignored. A read-only cache volume
    must not stop the jobs process; it only costs the backoff.
    """
    path = _attempt_file(settings, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(datetime.now(UTC).timestamp()), encoding="utf-8")
    except OSError:
        logger.warning("could not record an attempt at the %s job at %s", name, path)


def _startup_delay(task: Task, settings: Settings) -> float:
    """Seconds to wait before the first run after the process starts.

    `at_start` exists so a fresh box produces a coverage map without
    waiting hours for the first timer. It also means that **every**
    restart re-runs the job immediately, and that turned a job the
    kernel kills into a livelock:

        21:16:39  coverage starts
        21:20:01  removed a coverage run that never finished
        21:24:51  jobs running: ... (restart)
        21:24:56  removed a coverage run that never finished

    Eleven restarts, each one re-running a prediction that cannot
    finish, on a box with one core. Coverage never completed once, and
    the API -- sharing that core -- went from 0.32 s to 2.06 s on its
    heaviest endpoint.

    So `at_start` now means "if it is actually due". A task tried
    recently waits out the rest of its interval instead of starting
    again, which turns a tight loop into one attempt per interval and
    leaves the core to the thing people are looking at.
    """
    if not task.at_start:
        return task.next_delay()
    last = _read_last_attempt(settings, task.name)
    if last is None:
        return 0.0
    interval = task.next_delay()
    remaining = interval - (datetime.now(UTC).timestamp() - last)
    if remaining <= 0:
        return 0.0
    logger.info(
        "the %s job was tried %.0fs ago, so it is not due for another %.0fs",
        task.name,
        interval - remaining,
        remaining,
    )
    return remaining


async def _run_forever(task: Task, settings: Settings) -> None:
    """Run one task on its own clock, for as long as the process lives."""
    delay = _startup_delay(task, settings)
    if delay > 0:
        await asyncio.sleep(delay)
    while True:
        started = datetime.now(UTC)
        _record_attempt(settings, task.name)
        try:
            await task.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("the %s job failed", task.name)
            await asyncio.sleep(RETRY_SECONDS)
            continue
        took = (datetime.now(UTC) - started).total_seconds()
        delay = task.next_delay()
        logger.info("the %s job took %.1fs, next in %.0fs", task.name, took, delay)
        await asyncio.sleep(delay)


def build_tasks(settings: Settings) -> list[Task]:
    """Return the tasks this deployment runs."""
    tasks = [
        Task(
            name="snapshot",
            run=snapshots.main,
            next_delay=_delay_to_next_utc_day,
        )
    ]

    if settings.coverage_enabled:
        last_calibration: float | None = None

        async def coverage_run() -> None:
            nonlocal last_calibration
            engine = make_engine(settings.database_url_jobs)
            factory = make_session_factory(engine)
            try:
                async with factory() as session:
                    now = asyncio.get_running_loop().time()
                    interval = max(settings.calibration_interval_hours, 1) * 3600.0
                    calibration_due = settings.calibration_enabled and (
                        last_calibration is None or now - last_calibration >= interval
                    )
                    await _coverage_cycle(session, settings, calibration_due)
                    if calibration_due:
                        last_calibration = asyncio.get_running_loop().time()
            finally:
                await engine.dispose()

        tasks.append(
            Task(
                name="coverage",
                run=coverage_run,
                next_delay=lambda: max(settings.coverage_interval_hours, 1) * 3600.0,
            )
        )
    else:
        logger.info("the coverage job is turned off")
        if settings.calibration_enabled:

            async def calibration_run() -> None:
                engine = make_engine(settings.database_url_jobs)
                factory = make_session_factory(engine)
                try:
                    async with factory() as session:
                        await calibrate.run_once(session, settings)
                finally:
                    await engine.dispose()

            tasks.append(
                Task(
                    name="calibration",
                    run=calibration_run,
                    next_delay=lambda: max(settings.calibration_interval_hours, 1) * 3600.0,
                )
            )

    if settings.gaps_enabled:
        # Its own clock, on purpose. This job runs no engine: it is SQL
        # and a few thousand dictionary operations, so it cannot take a
        # core away from a coverage build. It also wants to run every
        # half hour rather than every six hours.
        #
        # The engine work of the siting half is the opposite case and
        # must join `_coverage_cycle` instead of standing beside it. A
        # task registered here is free to run during a coverage build,
        # and on a three core box that is the last core.
        async def gaps_run() -> None:
            engine = make_engine(settings.database_url_jobs)
            factory = make_session_factory(engine)
            try:
                async with factory() as session:
                    await gaps.run_once(session, settings)
            finally:
                await engine.dispose()

        tasks.append(
            Task(
                name="gaps",
                run=gaps_run,
                next_delay=lambda: max(settings.gaps_interval_minutes, 1) * 60.0,
            )
        )
    else:
        logger.info("the coverage gaps job is turned off")

    return tasks


async def service() -> None:
    """Run every task until the process is stopped."""
    settings = get_settings()
    tasks = build_tasks(settings)
    logger.info("jobs running: %s", ", ".join(task.name for task in tasks))
    await asyncio.gather(*(_run_forever(task, settings) for task in tasks))


def run() -> None:
    """Console script entry point."""
    configure_logging(get_settings().log_level)
    asyncio.run(service())
