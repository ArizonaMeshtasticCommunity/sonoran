"""Contributors against a real database, as the jobs role (#178, #181).

The rules are unit tested in tests/unit/test_contrib.py. This file holds
the SQL: the grants, the heard list, a round from job to reading, and a
reassignment after a job expires.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.contrib import store
from sonoran.contrib.dispatch import JOB_WAIT, refuse_result
from sonoran.contrib.schema import Contributor, Result, Status
from sonoran.db.session import make_engine, make_session_factory
from tests.integration.conftest import role_url

# Node numbers no other test uses.
ROUTER, BASE, CLIENT = 0x0C0B_0001, 0x0C0B_0002, 0x0C0B_0003
A = Contributor("contrib-a", "pi")
B = Contributor("contrib-b", "pi")
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _id(num: int) -> str:
    return f"!{num:08x}"


@pytest.fixture
def clean(migrated_engine) -> Iterator[None]:  # type: ignore[no-untyped-def]
    def wipe() -> None:
        with migrated_engine.begin() as connection:
            connection.execute(text("DELETE FROM local_stats"))
            connection.execute(text("DELETE FROM contrib_job"))
            connection.execute(text("DELETE FROM contrib_source"))
            connection.execute(
                text("DELETE FROM node WHERE node_num = ANY(:n)"), {"n": [ROUTER, BASE, CLIENT]}
            )

    wipe()
    with migrated_engine.begin() as connection:
        for num, role in ((ROUTER, "ROUTER"), (BASE, "CLIENT_BASE"), (CLIENT, None)):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, role, first_seen, updated_at,"
                    " is_mqtt_gateway) VALUES (:n, :i, :r, now(), now(), false)"
                ),
                {"n": num, "i": _id(num), "r": role},
            )
    yield
    wipe()


def _as_jobs[T](timescale_url: str, func: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run `func` in one committed transaction as `azmsh_jobs`."""

    async def go() -> T:
        engine = make_engine(role_url(timescale_url, "azmsh_jobs"))
        try:
            async with make_session_factory(engine)() as session:
                value = await func(session)
                await session.commit()
                return value
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _status(who: Contributor, heard: list[tuple[int, int | None]], at: datetime) -> Status:
    return Status.model_validate(
        {
            "v": 1,
            "location": who.location,
            "source": who.source,
            "sent": at.isoformat(),
            "kinds": ["local_stats"],
            "heard": [
                {"node": _id(num), "hops": hops, "last_heard": at.isoformat()}
                for num, hops in heard
            ],
        }
    )


def _result(job: str, who: Contributor, target: int, **changes: Any) -> Result:
    body: dict[str, Any] = {
        "v": 1,
        "job": job,
        "location": who.location,
        "source": who.source,
        "kind": "local_stats",
        "target": _id(target),
        "outcome": "ok",
        "sent": NOW.isoformat(),
        "received": NOW.isoformat(),
        "local_stats": {"noise_floor": -104, "channel_utilization": 9.5, "num_tx_relay": 7},
    }
    body.update(changes)
    return Result.model_validate(body)


def test_only_the_roles_in_178_get_jobs_and_the_fewest_hops_wins(  # type: ignore[no-untyped-def]
    timescale_url, clean
) -> None:
    heard_a = [(ROUTER, 3), (BASE, 1), (CLIENT, 0)]
    heard_b = [(ROUTER, 1)]
    _as_jobs(timescale_url, lambda s: store.store_status(s, A, _status(A, heard_a, NOW), NOW))
    _as_jobs(timescale_url, lambda s: store.store_status(s, B, _status(B, heard_b, NOW), NOW))
    planned = _as_jobs(timescale_url, lambda s: store.plan_jobs(s, NOW))
    assert {(job.target, job.contributor) for job in planned} == {(ROUTER, B), (BASE, A)}
    assert all(job.expires - job.issued == JOB_WAIT for job in planned)


def test_a_result_becomes_a_reading_the_api_can_read(  # type: ignore[no-untyped-def]
    timescale_url, migrated_engine, clean
) -> None:
    _as_jobs(timescale_url, lambda s: store.store_status(s, A, _status(A, [(ROUTER, 1)], NOW), NOW))
    (job,) = _as_jobs(timescale_url, lambda s: store.plan_jobs(s, NOW))
    result = _result(job.job, A, ROUTER)

    async def accept(session: AsyncSession) -> bool:
        facts = await store.job_facts(session, job.job)
        assert refuse_result(facts, A, result) is None
        return await store.store_result(session, result, NOW + timedelta(seconds=20))

    assert _as_jobs(timescale_url, accept) is True
    api = create_engine(role_url(timescale_url, "azmsh_api").replace("+asyncpg", "+psycopg"))
    try:
        with api.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT noise_floor, num_tx_relay, location FROM local_stats"
                    " WHERE node_num = :n"
                ),
                {"n": ROUTER},
            ).one()
    finally:
        api.dispose()
    assert tuple(row) == (-104, 7, "contrib-a")

    # The round is done: no new job inside the router's 12 hours.
    later = NOW + timedelta(hours=1)
    assert _as_jobs(timescale_url, lambda s: store.plan_jobs(s, later)) == []
    # And a second result for the same job is refused.
    facts = _as_jobs(timescale_url, lambda s: store.job_facts(s, job.job))
    assert refuse_result(facts, A, result) is not None


def test_an_expired_job_moves_to_the_next_contributor(  # type: ignore[no-untyped-def]
    timescale_url, clean
) -> None:
    _as_jobs(timescale_url, lambda s: store.store_status(s, A, _status(A, [(ROUTER, 1)], NOW), NOW))
    _as_jobs(timescale_url, lambda s: store.store_status(s, B, _status(B, [(ROUTER, 2)], NOW), NOW))
    (first,) = _as_jobs(timescale_url, lambda s: store.plan_jobs(s, NOW))
    assert first.contributor == A

    after = first.expires + timedelta(seconds=1)
    assert _as_jobs(timescale_url, lambda s: store.expire_jobs(s, after)) == 1
    (second,) = _as_jobs(timescale_url, lambda s: store.plan_jobs(s, after))
    assert (second.contributor, second.target) == (B, ROUTER)
    # The expired job's outbox message is to be cleared; the open one is not.
    to_clear = _as_jobs(timescale_url, store.to_clear)
    assert [job for job, _ in to_clear] == [first.job]


def test_the_ingest_role_cannot_touch_contributor_tables(  # type: ignore[no-untyped-def]
    timescale_url, clean
) -> None:
    ingest = create_engine(role_url(timescale_url, "azmsh_ingest").replace("+asyncpg", "+psycopg"))
    try:
        with pytest.raises(DBAPIError), ingest.connect() as connection:
            connection.execute(text("SELECT 1 FROM contrib_job"))
    finally:
        ingest.dispose()


def test_the_node_page_and_the_rf_layer_show_the_reading(  # type: ignore[no-untyped-def]
    timescale_url, migrated_engine, clean
) -> None:
    """#182: the measured noise floor on the node page and the RF map."""
    from fastapi.testclient import TestClient

    from sonoran.api.app import create_app
    from sonoran.config import Settings

    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE node SET last_lat = 33.4, last_lon = -112.1 WHERE node_num = :n"),
            {"n": ROUTER},
        )
    _as_jobs(timescale_url, lambda s: store.store_status(s, A, _status(A, [(ROUTER, 1)], now), now))
    (job,) = _as_jobs(timescale_url, lambda s: store.plan_jobs(s, now))
    result = _result(job.job, A, ROUTER, received=now.isoformat(), sent=now.isoformat())
    _as_jobs(timescale_url, lambda s: store.store_result(s, result, now))

    app = create_app(
        Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api"))
    )
    with TestClient(app) as client:
        detail = client.get(f"/api/nodes/{_id(ROUTER)}/detail").json()
        assert detail["local_stats"]["noise_floor"] == -104
        series = client.get(f"/api/nodes/{_id(ROUTER)}/telemetry?family=local_stats").json()
        assert [point["noise_floor"] for point in series] == [-104]
        layer = client.get("/api/rf/noise-floor").json()
    (point,) = [item for item in layer if item["node_id"] == _id(ROUTER)]
    assert point["noise_floor_dbm"] == -104
    assert point["measured_by"]["location"] == "contrib-a"
