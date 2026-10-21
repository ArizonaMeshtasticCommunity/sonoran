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
from sonoran.jobs import (
    activity_heatmap,
    calibrate,
    coverage,
    gaps,
    gaps_siting,
    legacy_import,
    read_models,
    rf_rollup,
    snapshots,
    supervisor,
)
from sonoran.logging import configure_logging, get_logger

logger = get_logger(__name__)

# How long to wait before trying a task that failed.
#
# Short enough that a run lost to a restarting database comes back
# quickly. Long enough that a task failing every time does not fill the
# log.
RETRY_SECONDS = 300.0

# How often finished hours of the 900 MHz band are rolled up.
RF_ROLLUP_SECONDS = 600.0


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
    fit it stores. The siting half of the coverage gaps feature runs
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
        # After it succeeded, not before: a calibration that failed is
        # tried again with the next coverage run, not a day later.
        _record_attempt(settings, "calibration")
    await coverage.run_once(session, settings)
    if settings.gaps_enabled and settings.gaps_siting_enabled:
        # It reads the coverage run above and the gaps assessment, and
        # stores its answer (#351).
        await gaps_siting.run_once(session, settings)


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
        except supervisor.OverLimit as stopped:
            # Not the short retry: a job that cannot fit would be tried
            # again and again, the livelock of 2026-09-21. It waits its
            # normal interval, and its ceiling can be raised meanwhile.
            logger.error("%s; next try in %.0fs", stopped, task.next_delay())
            await asyncio.sleep(task.next_delay())
            continue
        except Exception:
            logger.exception("the %s job failed", task.name)
            await asyncio.sleep(RETRY_SECONDS)
            continue
        took = (datetime.now(UTC) - started).total_seconds()
        delay = task.next_delay()
        logger.info("the %s job took %.1fs, next in %.0fs", task.name, took, delay)
        await asyncio.sleep(delay)


# --- the jobs, one body each ------------------------------------------
#
# Each body runs one job once. The supervisor runs it in a child process
# (`sonoran/jobs/run_task.py`), so nothing here may keep state in memory
# between runs: what must last goes in the attempt files or the database.


def _calibration_due(settings: Settings) -> bool:
    """True when the calibration should run before this coverage run."""
    if not settings.calibration_enabled:
        return False
    last = _read_last_attempt(settings, "calibration")
    interval = max(settings.calibration_interval_hours, 1) * 3600.0
    return last is None or datetime.now(UTC).timestamp() - last >= interval


async def _job_snapshot(settings: Settings) -> None:
    await snapshots.main()


async def _job_coverage(settings: Settings) -> None:
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await _coverage_cycle(session, settings, _calibration_due(settings))
    finally:
        await engine.dispose()


async def _job_calibration(settings: Settings) -> None:
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await calibrate.run_once(session, settings)
    finally:
        await engine.dispose()


async def _job_gaps(settings: Settings) -> None:
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await gaps.run_once(session, settings)
    finally:
        await engine.dispose()


async def _job_rf_rollup(settings: Settings) -> None:
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await rf_rollup.run_once(session)
    finally:
        await engine.dispose()


async def _job_activity_heatmap(settings: Settings) -> None:
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await activity_heatmap.run_once(session, settings)
    finally:
        await engine.dispose()


async def _job_read_models(settings: Settings) -> None:
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await read_models.run_once(session, settings)
    finally:
        await engine.dispose()


#: Every job by name: what `run_task` and the in-process runner call.
JOB_BODIES: dict[str, Callable[[Settings], Awaitable[None]]] = {
    "snapshot": _job_snapshot,
    "coverage": _job_coverage,
    "calibration": _job_calibration,
    "gaps": _job_gaps,
    "rf-rollup": _job_rf_rollup,
    "read-models": _job_read_models,
    "activity_heatmap": _job_activity_heatmap,
}


async def run_body(name: str, settings: Settings) -> None:
    """Run one job once, in this process."""
    await JOB_BODIES[name](settings)


def _runner(
    name: str, settings: Settings, budget: supervisor.Budget | None
) -> Callable[[], Awaitable[None]]:
    """What a task calls to run once: in a child process, or in this one."""
    if budget is None:
        return lambda: run_body(name, settings)
    return lambda: supervisor.run_job(name, settings, budget)


def build_tasks(settings: Settings, budget: supervisor.Budget | None = None) -> list[Task]:
    """Return the tasks this deployment runs.

    With a `budget`, each run is a child process inside it (the
    supervisor, #371); without one, each runs in this process.
    """

    def task(name: str, next_delay: Callable[[], float]) -> Task:
        return Task(name=name, run=_runner(name, settings, budget), next_delay=next_delay)

    tasks = [task("snapshot", _delay_to_next_utc_day)]

    # SQL and numpy, no engine. Once a day, in its own child like the
    # others, so its memory has a ceiling and the supervisor plans it.
    tasks.append(task("activity_heatmap", _delay_to_next_utc_day))

    if settings.coverage_enabled:
        # Calibration, coverage and the siting half share one clock and
        # one child: `_coverage_cycle`. They all run the engine.
        tasks.append(task("coverage", lambda: max(settings.coverage_interval_hours, 1) * 3600.0))
    else:
        logger.info("the coverage job is turned off")
        if settings.calibration_enabled:
            tasks.append(
                task("calibration", lambda: max(settings.calibration_interval_hours, 1) * 3600.0)
            )

    if settings.gaps_enabled:
        # Its own clock: SQL and dictionaries, no engine, and it wants to
        # be fresher than a coverage run. The engine work of the siting
        # half joins `_coverage_cycle` instead.
        tasks.append(task("gaps", lambda: max(settings.gaps_interval_minutes, 1) * 60.0))
    else:
        logger.info("the coverage gaps job is turned off")

    # Plain SQL over a few hours a run, no engine.
    tasks.append(task("rf-rollup", lambda: RF_ROLLUP_SECONDS))

    if settings.read_models_enabled:
        # SQL and Python, no engine. Beside coverage when the memory
        # allows it; the supervisor decides.
        tasks.append(
            task("read-models", lambda: max(settings.read_models_interval_minutes, 1) * 60.0)
        )
    else:
        logger.info("the read models are turned off")

    return tasks


async def _import_old_files(settings: Settings) -> None:
    """Import the JSON files from before #351 into empty tables, once.

    See `sonoran/jobs/legacy_import.py`. Before any task starts, so a
    coverage run never predicts without the calibration it had.

    Nothing here may stop the jobs process: every task writes its tables
    anyway on its next run. So the engine is made inside the `try` too.
    It uses the jobs role's URL, as every task does. The first deploy of
    #351 used `database_url`, which the jobs container does not set, and
    the process stopped at start.
    """
    engine = None
    try:
        engine = make_engine(settings.database_url_jobs)
        async with make_session_factory(engine)() as session:
            await legacy_import.run_once(session, settings)
    except Exception:
        logger.exception("could not import the files from before #351")
    finally:
        if engine is not None:
            await engine.dispose()


async def service() -> None:
    """Run every task until the process is stopped."""
    settings = get_settings()
    await _import_old_files(settings)
    budget = supervisor.budget_for(settings) if settings.jobs_isolate else None
    tasks = build_tasks(settings, budget)
    logger.info("jobs running: %s", ", ".join(task.name for task in tasks))
    if budget is not None:
        limits = supervisor.limits_for(settings)
        logger.info(
            "each job runs in its own process; memory for all: %s; ceilings: %s",
            "no limit" if budget.total_mb is None else f"{budget.total_mb:.0f} MB",
            ", ".join(f"{task.name} {limits.get(task.name, 0):.0f} MB" for task in tasks),
        )
    await asyncio.gather(*(_run_forever(task, settings) for task in tasks))


def run() -> None:
    """Console script entry point."""
    configure_logging(get_settings().log_level)
    asyncio.run(service())
