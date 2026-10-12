"""A request without `preset=` runs exactly the SQL it ran before #313.

Something outside this repository may call these endpoints, and a page
cached in somebody's browser still sends `channel=` until it reloads.
So the old form must not move by one byte of SQL.

Each case calls an endpoint through a session that records every
statement instead of running it, compiles each one for PostgreSQL, and
compares a digest of the result with the digest the same request made
on `c926ad0`, before this change. Times are masked, because "now" moves.

A digest is opaque on purpose: it fails on any change at all. When it
fails, do not update the digest to make it pass. Find out what changed
in the path that has no `preset`, and put it back.

The new columns are `deferred` in `db/models.py` for this reason. A
SELECT of a whole `Packet` or `Node` would otherwise name them, and
every one of these digests would move.
"""

import hashlib
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from sonoran.api.app import create_app
from sonoran.api.dependencies import get_session
from sonoran.config import Settings
from tests.unit.job_outputs import JobOutputs


@pytest.fixture(autouse=True)
def _outputs(job_outputs: JobOutputs) -> None:
    """The gaps reads come from memory (#351), so only this page's SQL is recorded."""


class _Result:
    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None

    def scalar(self) -> int:
        return 0

    def __iter__(self) -> Any:
        return iter([])


class RecordingSession:
    """Records each statement it is asked to run, and finds nothing."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def _record(self, statement: Any) -> None:
        compiled = statement.compile(dialect=postgresql.dialect())
        params = {
            key: "<time>" if isinstance(value, datetime) else repr(value)
            for key, value in sorted(compiled.params.items())
        }
        self.statements.append(f"{compiled}\n{params}")

    async def execute(self, statement: Any, *_: Any, **__: Any) -> _Result:
        self._record(statement)
        return _Result()

    async def scalars(self, statement: Any, *_: Any, **__: Any) -> _Result:
        self._record(statement)
        return _Result()

    async def scalar(self, statement: Any, *_: Any, **__: Any) -> int:
        self._record(statement)
        return 0

    async def get(self, *_: Any, **__: Any) -> None:
        return None


def recorded_sql(path: str, tmp_path: Any) -> list[str]:
    """Request one path and return every statement it ran, compiled."""
    session = RecordingSession()
    app = create_app(Settings(_env_file=None, coverage_cache_dir=str(tmp_path)))

    async def _session() -> Any:
        yield session

    app.dependency_overrides[get_session] = _session
    response = TestClient(app).get(path)
    assert response.status_code == 200, response.text
    return session.statements


def _digest(path: str, tmp_path: Any) -> tuple[str, int]:
    statements = recorded_sql(path, tmp_path)
    text = "\n---\n".join(statements)
    return hashlib.sha256(text.encode()).hexdigest()[:16], len(statements)


# Recorded on c926ad0, before #313. See the module docstring before
# touching any of these.
LEGACY = {
    "/api/chat?channel=MediumFast": ("714111cac591bb10", 1),
    "/api/chat?channel=azmsh&limit=5&metrics=true": ("cf8b34cb0545b203", 1),
    "/api/chat?limit=5": ("e6d99f9feacbd0ad", 1),
    "/api/chat/overview?hours=168": ("1b86cab8d1119739", 2),
    "/api/packets?channel=MediumFast&limit=150&summary=true": ("7e227b57b1997406", 1),
    "/api/packets?limit=150": ("a60e04a1277aa3de", 1),
    "/api/stats/portnums?hours=24&channel=MediumFast": ("d1894e97fdd4ab71", 1),
    "/api/stats/portnums": ("688acc845f7f8b1c", 1),
    "/api/nodes?limit=100&active_hours=24&channel=MediumFast": ("07250a02f671795d", 2),
    "/api/nodes?limit=100&channel=Weather": ("523464e5df2c92cd", 2),
    "/api/nodes/facets?active_hours=24&channel=MediumFast": ("f2efcfd416ec0eb6", 6),
    "/api/nodes?limit=100": ("3177d982511f929a", 2),
    "/api/nodes/facets": ("dae2e869fe5bf69c", 6),
}


@pytest.mark.parametrize("path", sorted(LEGACY))
def test_the_legacy_request_runs_the_sql_it_always_ran(path: str, tmp_path: Any) -> None:
    got = _digest(path, tmp_path)
    assert got == LEGACY[path], f"{path} now runs different SQL: {got}"
