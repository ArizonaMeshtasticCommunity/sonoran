"""Each job runs in its own process, with its own memory ceiling (#371)."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from sonoran.config import Settings
from sonoran.jobs import run_task, scheduler, supervisor


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


def test_a_stopped_job_waits_its_interval_not_the_short_retry() -> None:
    import inspect

    source = inspect.getsource(scheduler._run_forever)
    stopped = source.index("except supervisor.OverLimit")
    other = source.index("except Exception")
    assert stopped < other, "the general handler would catch a stop first"
    assert "task.next_delay()" in source[stopped:other]
