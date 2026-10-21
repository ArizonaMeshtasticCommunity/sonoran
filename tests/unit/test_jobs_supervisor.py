"""Each job runs in its own process, with its own memory ceiling (#371)."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from sonoran.config import Settings
from sonoran.jobs import run_task, scheduler, supervisor

# The supervisor reads memory from /proc, which only Linux has. The jobs
# run in a Linux container, and CI runs on Linux, so these tests run
# there. On a Mac they are skipped, not failed.
needs_proc = pytest.mark.skipif(
    not Path("/proc/self").exists(), reason="the supervisor reads /proc, which only Linux has"
)


def _settings(tmp_path: Path, **extra: object) -> Settings:
    return Settings(_env_file=None, coverage_cache_dir=str(tmp_path), **extra)  # type: ignore[arg-type]


def test_limits_read_name_equals_megabytes_over_the_defaults(tmp_path: Path) -> None:
    assert supervisor.parse_limits("coverage=700, gaps = 120,broken=x,") == {
        "coverage": 700.0,
        "gaps": 120.0,
    }
    limits = supervisor.limits_for(_settings(tmp_path, jobs_memory_limits="gaps=120"))
    assert limits["gaps"] == 120.0
    assert limits["coverage"] == supervisor.DEFAULT_LIMITS_MB["coverage"]


def test_a_job_is_planned_at_its_last_peak_and_never_above_its_ceiling(tmp_path: Path) -> None:
    settings = _settings(tmp_path, jobs_memory_limits="gaps=300")
    assert supervisor.planned_mb(settings, "gaps") == 300.0, "no peak yet: the ceiling"
    supervisor._record_peak(settings, "gaps", 100.0)
    assert supervisor.planned_mb(settings, "gaps") == pytest.approx(115.0)
    supervisor._record_peak(settings, "gaps", 290.0)
    assert supervisor.planned_mb(settings, "gaps") == 300.0, "the margin stops at the ceiling"


def test_runs_overlap_when_they_fit_and_wait_when_they_do_not() -> None:
    async def scenario() -> list[str]:
        budget = supervisor.Budget(total_mb=1000.0)
        order: list[str] = []

        async def run(name: str, size: float, hold: float) -> None:
            await budget.acquire(name, size)
            order.append(f"+{name}")
            await asyncio.sleep(hold)
            order.append(f"-{name}")
            await budget.release(size)

        await asyncio.gather(
            run("coverage", 700.0, 0.2),
            run("rollup", 200.0, 0.05),  # fits beside coverage
            run("read-models", 400.0, 0.01),  # does not fit until coverage ends
        )
        return order

    order = asyncio.run(scenario())
    assert order.index("+rollup") < order.index("-coverage"), "a run that fits did not overlap"
    assert order.index("+read-models") > order.index("-coverage"), "a run started over budget"


def test_a_run_bigger_than_the_whole_budget_still_runs_alone() -> None:
    budget = supervisor.Budget(total_mb=500.0)
    assert budget.fits(800.0), "nothing running: it must be allowed to run"
    budget.running, budget.used_mb = 1, 100.0
    assert not budget.fits(800.0)


@needs_proc
def test_the_memory_of_a_process_tree_is_read_from_proc() -> None:
    me = os.getpid()
    assert me in supervisor.process_tree(me)
    assert supervisor.tree_rss_mb(me) > 10.0
    assert supervisor.rss_mb(10**9) == 0.0, "a process that is gone uses nothing"


def _child(code: str) -> Any:
    """A stand-in for `python -m sonoran.jobs.run_task NAME`."""
    real = asyncio.create_subprocess_exec

    async def spawn(*_: object, **__: object) -> Any:
        return await real(sys.executable, "-c", code)

    return spawn


@needs_proc
def test_a_job_over_its_ceiling_is_stopped_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, jobs_memory_limits="gaps=60")
    monkeypatch.setattr(
        supervisor.asyncio,
        "create_subprocess_exec",
        _child("import time; block = bytearray(150 * 1024 * 1024); time.sleep(30)"),
    )
    budget = supervisor.Budget(total_mb=None)
    with pytest.raises(supervisor.OverLimit, match="over its limit of 60 MB"):
        asyncio.run(supervisor.run_job("gaps", settings, budget))
    assert budget.running == 0 and budget.used_mb == 0.0, "its share was not given back"
    assert supervisor.read_peak(settings, "gaps") is None, "a stopped run is not a peak"


@needs_proc
def test_a_finished_job_records_its_peak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        supervisor.asyncio,
        "create_subprocess_exec",
        _child("import time; block = bytearray(40 * 1024 * 1024); time.sleep(2.5)"),
    )
    asyncio.run(supervisor.run_job("rf-rollup", settings, supervisor.Budget(total_mb=None)))
    peak = supervisor.read_peak(settings, "rf-rollup")
    assert peak is not None and peak >= 40.0


def test_a_failed_job_is_an_error_not_a_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(supervisor.asyncio, "create_subprocess_exec", _child("raise SystemExit(1)"))
    with pytest.raises(RuntimeError, match="exited with 1"):
        asyncio.run(supervisor.run_job("snapshot", settings, supervisor.Budget(total_mb=None)))


def test_the_child_entry_runs_only_known_jobs() -> None:
    assert run_task.main(["run_task"]) == 2
    assert run_task.main(["run_task", "not-a-job"]) == 2
    assert set(scheduler.JOB_BODIES) == set(supervisor.DEFAULT_LIMITS_MB)


def test_with_a_budget_every_task_runs_in_a_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    async def fake(name: str, *_: object) -> None:
        asked.append(name)

    monkeypatch.setattr(supervisor, "run_job", fake)
    budget = supervisor.Budget(total_mb=None)
    tasks = scheduler.build_tasks(_settings(tmp_path), budget)
    for task in tasks:
        asyncio.run(task.run())  # type: ignore[arg-type]
    assert asked == [task.name for task in tasks]


def test_a_stopped_job_waits_its_interval_not_the_short_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stopped() -> None:
        raise supervisor.OverLimit("the gaps job used 900 MB, over its limit")

    waits: list[float] = []

    class Done(Exception):
        pass

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        raise Done

    monkeypatch.setattr(scheduler.asyncio, "sleep", sleep)
    task = scheduler.Task(name="gaps", run=stopped, next_delay=lambda: 1800.0)
    with pytest.raises(Done):
        asyncio.run(scheduler._run_forever(task, _settings(tmp_path)))
    assert waits == [1800.0], f"waited {waits}, not its interval"


def test_a_failed_run_does_not_record_a_peak_and_a_short_one_lowers_it_slowly(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    supervisor._record_peak(settings, "coverage", 627.0)
    supervisor._record_peak(settings, "coverage", 100.0)  # nothing to plan this time
    assert supervisor.read_peak(settings, "coverage") == pytest.approx(564.3, abs=1)
    assert supervisor.planned_mb(settings, "coverage") > 600.0


@needs_proc
def test_a_failed_run_leaves_the_recorded_peak_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    supervisor._record_peak(settings, "gaps", 200.0)
    monkeypatch.setattr(
        supervisor.asyncio,
        "create_subprocess_exec",
        _child("import time; time.sleep(0.6); raise SystemExit(1)"),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(supervisor.run_job("gaps", settings, supervisor.Budget(total_mb=None)))
    assert supervisor.read_peak(settings, "gaps") == 200.0


@needs_proc
def test_a_short_job_still_records_a_peak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        supervisor.asyncio,
        "create_subprocess_exec",
        _child("import time; time.sleep(0.6)"),
    )
    asyncio.run(supervisor.run_job("snapshot", settings, supervisor.Budget(total_mb=None)))
    assert supervisor.read_peak(settings, "snapshot") is not None


@needs_proc
def test_the_memory_of_a_tree_counts_shared_pages_once() -> None:
    me = os.getpid()
    assert 0 < supervisor.share_mb(me) <= supervisor.rss_mb(me) + 1


def test_calibration_is_due_by_its_last_success(tmp_path: Path) -> None:
    settings = _settings(tmp_path, calibration_interval_hours=24)
    assert scheduler._calibration_due(settings), "never run: due"
    scheduler._record_attempt(settings, "calibration")
    assert not scheduler._calibration_due(settings)
    old = scheduler._attempt_file(settings, "calibration")
    old.write_text(str(float(old.read_text()) - 25 * 3600))
    assert scheduler._calibration_due(settings)
    assert not scheduler._calibration_due(_settings(tmp_path, calibration_enabled=False))


def test_a_failed_calibration_is_tried_again_with_the_next_coverage_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)

    async def broken(*_: object) -> None:
        raise ConnectionError("the database restarted")

    monkeypatch.setattr(scheduler.calibrate, "run_once", broken)
    with pytest.raises(ConnectionError):
        asyncio.run(scheduler._coverage_cycle(object(), settings, True))  # type: ignore[arg-type]
    assert scheduler._calibration_due(settings), "a failed calibration counted as done"

    async def fine(*_: object) -> None:
        return None

    monkeypatch.setattr(scheduler.calibrate, "run_once", fine)
    monkeypatch.setattr(scheduler.coverage, "run_once", fine)
    monkeypatch.setattr(scheduler.gaps_siting, "run_once", fine)
    asyncio.run(scheduler._coverage_cycle(object(), settings, True))  # type: ignore[arg-type]
    assert not scheduler._calibration_due(settings)
