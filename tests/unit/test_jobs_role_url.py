"""Every job connects as the jobs role (#351).

The first deploy of #351 stopped the jobs process at start: the import
of the old files made its engine from `database_url`, which the jobs
container does not set. Unit tests and CI never noticed, because there
both URLs reach a database.
"""

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from sonoran.config import Settings
from sonoran.jobs import scheduler

JOBS = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "jobs"


def test_no_job_makes_an_engine_from_another_roles_url() -> None:
    for path in sorted(JOBS.glob("*.py")):
        calls = re.findall(r"make_engine\(([^)]*)\)", path.read_text(encoding="utf-8"))
        for argument in calls:
            assert argument.strip() == "settings.database_url_jobs", f"{path.name}: {argument}"


def test_the_import_of_the_old_files_can_never_stop_the_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even an engine that cannot be made is logged, not raised."""
    asked: list[str] = []

    def broken(url: str) -> Any:
        asked.append(url)
        raise ValueError("Could not parse SQLAlchemy URL")

    monkeypatch.setattr(scheduler, "make_engine", broken)
    settings = Settings(_env_file=None, database_url_jobs="postgresql+asyncpg://jobs@x/y")
    asyncio.run(scheduler._import_old_files(settings))
    assert asked == ["postgresql+asyncpg://jobs@x/y"]
