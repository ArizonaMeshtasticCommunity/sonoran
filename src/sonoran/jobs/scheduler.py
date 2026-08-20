"""The scheduled work of the jobs process.

The process held one task for a long time, and one task needs no
scheduler. It now holds two, and they run on very different clocks: the
daily snapshot takes a moment once a day, and the coverage run takes
minutes and wants to run several times a day.

Running them in one loop would make the snapshot wait for the coverage
run. So each task keeps its own clock, and a task that is slow or that
fails holds up nothing but itself.

A task that raises is logged and tried again at its next turn. One bad
run must never stop the process: a jobs container that exits stops
every other task with it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sonoran.config import Settings, get_settings
from sonoran.db.session import make_engine, make_session_factory
from sonoran.jobs import coverage, snapshots
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


async def _run_forever(task: Task) -> None:
    """Run one task on its own clock, for as long as the process lives."""
    if not task.at_start:
        await asyncio.sleep(task.next_delay())
    while True:
        started = datetime.now(UTC)
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

        async def coverage_run() -> None:
            engine = make_engine(settings.database_url_jobs)
            factory = make_session_factory(engine)
            try:
                async with factory() as session:
                    await coverage.run_once(session, settings)
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

    return tasks


async def service() -> None:
    """Run every task until the process is stopped."""
    settings = get_settings()
    tasks = build_tasks(settings)
    logger.info("jobs running: %s", ", ".join(task.name for task in tasks))
    await asyncio.gather(*(_run_forever(task) for task in tasks))


def run() -> None:
    """Console script entry point."""
    configure_logging(get_settings().log_level)
    asyncio.run(service())
