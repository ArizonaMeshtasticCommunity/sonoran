"""Tests for the order of the scheduled jobs."""

import asyncio
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings
from sonoran.jobs import scheduler


def test_calibration_finishes_before_coverage(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Coverage must read the calibration made in the same cycle."""
    calls: list[str] = []

    async def calibrated(session: AsyncSession, settings: Settings) -> None:
        calls.append("calibration")

    async def covered(session: AsyncSession, settings: Settings) -> None:
        calls.append("coverage")

    async def sited(session: AsyncSession, settings: Settings) -> list[str]:
        calls.append("siting")
        return []

    monkeypatch.setattr(scheduler.calibrate, "run_once", calibrated)
    monkeypatch.setattr(scheduler.coverage, "run_once", covered)
    monkeypatch.setattr(scheduler.gaps_siting, "run_once", sited)

    asyncio.run(
        scheduler._coverage_cycle(
            cast(AsyncSession, object()), Settings(_env_file=None), run_calibration=True
        )
    )

    assert calls == ["calibration", "coverage", "siting"]


def test_coverage_does_not_get_a_competing_calibration_task() -> None:
    """One task owns both jobs when coverage consumes calibration."""
    tasks = scheduler.build_tasks(
        Settings(_env_file=None, calibration_enabled=True, coverage_enabled=True)
    )

    # The gaps task is here as well, and it is not a competitor: it runs
    # no engine, so it cannot take a core from a coverage build. Anything
    # that DOES use the engine must join `_coverage_cycle` instead.
    assert [task.name for task in tasks] == [
        "snapshot",
        "activity_heatmap",
        "coverage",
        "gaps",
        "rf-rollup",
    ]


def test_calibration_keeps_its_task_when_coverage_is_off() -> None:
    tasks = scheduler.build_tasks(
        Settings(_env_file=None, calibration_enabled=True, coverage_enabled=False)
    )

    assert [task.name for task in tasks] == [
        "snapshot",
        "activity_heatmap",
        "calibration",
        "gaps",
        "rf-rollup",
    ]
