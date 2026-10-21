"""The hourly totals give the raw counts, exactly (#366, #368, #371).

Every count here is checked against the same count read from the raw
rows, for windows that start and end inside an hour. Each check runs
twice: before the aggregates hold anything, when TimescaleDB answers
from the raw rows in real time, and after a full refresh, when it
answers from the materialised hours.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from sonoran.api import hourly
from sonoran.db.session import make_engine, make_session_factory
from tests.integration.conftest import role_url
from tests.integration.test_gaps import _packet

SENDERS = (0x0DC0_0001, 0x0DC0_0002, 0x0DC0_0003)
ZONE = "America/Phoenix"
VIEWS = (
    "packet_hourly",
    "packet_seen_hourly",
    "packet_family_hourly",
    "packet_sender_port_hourly",
)
REVISIONS = ("i366_hourly_counts", "i368_family_hourly", "i371_read_models")
BASE = (datetime.now(UTC) - timedelta(days=3)).replace(minute=0, second=0, microsecond=0)


@pytest.fixture
def traffic(migrated_engine: Any) -> Iterator[None]:
    """About 56 hours of packets from three senders, one every 17 minutes."""

    def wipe() -> None:
        with migrated_engine.begin() as connection:
            for table in ("packet_seen", "packet"):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE from_node_num = ANY(:s)"),
                    {"s": list(SENDERS)},
                )

    wipe()
    with migrated_engine.begin() as connection:
        for k in range(200):
            sender = SENDERS[k % len(SENDERS)]
            gateways = [(0x0DC0_0100 + g, 3, 5.0) for g in range(1 + k % 3)]
            _packet(
                connection,
                sender,
                700_000 + k,
                gateways,
                seen_at=BASE + timedelta(minutes=17 * k, seconds=k % 7),
            )
        # Several families, so the activity counts have more than one
        # group per hour. Port 0 in two states is two families.
        connection.execute(
            text(
                "UPDATE packet SET portnum = packet_id % 4, payload_state = "
                "CASE packet_id % 3 WHEN 0 THEN NULL WHEN 1 THEN 'readable' ELSE 'pki' END "
                "WHERE from_node_num = ANY(:s)"
            ),
            {"s": list(SENDERS)},
        )
    yield
    wipe()


def _refresh(timescale_url: str) -> None:
    engine = create_engine(timescale_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            for view in VIEWS:
                connection.execute(text(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)"))
    finally:
        engine.dispose()


def _raw(engine: Any, sql: str, **params: Any) -> Any:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).all()


async def _counts(url: str, start: datetime, end: datetime) -> tuple[Any, ...]:
    engine = make_engine(url)
    try:
        async with make_session_factory(engine)() as session:
            return (
                await hourly.count_packets(session, start, end),
                await hourly.count_uploads(session, start, end),
                await hourly.daily_counts(session, ZONE, start, end),
                await hourly.counts_by_sender(session, start, end),
                await hourly.family_counts(session, ZONE, start, end, by_day=False),
                await hourly.family_counts(session, ZONE, start, end, by_day=True),
                await hourly.top_senders(session, start, end, 2),
                set((await session.execute(hourly.senders_heard(start, end))).scalars()),
                await hourly.family_totals(session, start, end),
                await hourly.sender_port_counts(session, start, end, [0, 1, 2, 3]),
            )
    finally:
        await engine.dispose()


WINDOWS = [
    (timedelta(minutes=7), timedelta(hours=50, minutes=13)),  # both ends inside an hour
    (timedelta(hours=2), timedelta(hours=30)),  # both ends on an hour
    (timedelta(minutes=10), timedelta(minutes=55)),  # no whole hour at all
    (timedelta(hours=-5), timedelta(hours=60)),  # wider than the traffic
]


def _check(timescale_url: str, migrated_engine: Any) -> None:
    for begin, finish in WINDOWS:
        start, end = BASE + begin, BASE + finish
        (
            packets,
            uploads,
            (days, upload_days),
            senders,
            families_by_hour,
            families_by_day,
            top,
            heard,
            totals,
            sender_ports,
        ) = asyncio.run(_counts(role_url(timescale_url, "azmsh_api"), start, end))
        [(raw_packets,)] = _raw(
            migrated_engine,
            "SELECT count(*) FROM packet WHERE first_seen_at >= :a AND first_seen_at < :b",
            a=start,
            b=end,
        )
        [(raw_uploads,)] = _raw(
            migrated_engine,
            "SELECT count(*) FROM packet_seen WHERE seen_at >= :a AND seen_at < :b",
            a=start,
            b=end,
        )
        assert (packets, uploads) == (raw_packets, raw_uploads), (begin, finish)

        by_day = _raw(
            migrated_engine,
            "SELECT timezone(:z, date_trunc('day', timezone(:z, first_seen_at))) AS day, "
            "count(*), count(DISTINCT from_node_num) FROM packet "
            "WHERE first_seen_at >= :a AND first_seen_at < :b GROUP BY 1",
            z=ZONE,
            a=start,
            b=end,
        )
        assert days == {day: (count, nodes) for day, count, nodes in by_day}, (begin, finish)
        uploads_by_day = _raw(
            migrated_engine,
            "SELECT timezone(:z, date_trunc('day', timezone(:z, seen_at))) AS day, count(*) "
            "FROM packet_seen WHERE seen_at >= :a AND seen_at < :b GROUP BY 1",
            z=ZONE,
            a=start,
            b=end,
        )
        assert upload_days == dict(uploads_by_day), (begin, finish)

        per_sender = _raw(
            migrated_engine,
            "SELECT from_node_num, count(*) FROM packet "
            "WHERE first_seen_at >= :a AND first_seen_at < :b GROUP BY 1",
            a=start,
            b=end,
        )
        assert senders == dict(per_sender), (begin, finish)
        busiest = sorted(per_sender, key=lambda row: (-row[1], row[0]))[:2]
        assert top == [tuple(row) for row in busiest], (begin, finish)
        assert heard == {row[0] for row in per_sender}, (begin, finish)

        raw_totals = _raw(
            migrated_engine,
            "SELECT portnum, payload_state, count(*) FROM packet "
            "WHERE first_seen_at >= :a AND first_seen_at < :b GROUP BY 1, 2",
            a=start,
            b=end,
        )
        assert sorted(totals, key=repr) == sorted(map(tuple, raw_totals), key=repr), (
            begin,
            finish,
        )
        raw_ports = _raw(
            migrated_engine,
            "SELECT from_node_num, portnum, count(*) FROM packet "
            "WHERE first_seen_at >= :a AND first_seen_at < :b AND portnum IN (0, 1, 2, 3) "
            "GROUP BY 1, 2",
            a=start,
            b=end,
        )
        assert sorted(sender_ports) == sorted(map(tuple, raw_ports)), (begin, finish)

        for bucket, got in (
            ("date_trunc('hour', first_seen_at)", families_by_hour),
            ("timezone(:z, date_trunc('day', timezone(:z, first_seen_at)))", families_by_day),
        ):
            families = _raw(
                migrated_engine,
                f"SELECT {bucket}, portnum, payload_state, count(*) FROM packet "
                "WHERE first_seen_at >= :a AND first_seen_at < :b GROUP BY 1, 2, 3",
                z=ZONE,
                a=start,
                b=end,
            )
            assert sorted(got, key=repr) == sorted(map(tuple, families), key=repr), (
                begin,
                finish,
                bucket,
            )


def test_the_hourly_counts_equal_the_raw_counts_before_any_refresh(
    timescale_url: str, migrated_engine: Any, traffic: None
) -> None:
    _check(timescale_url, migrated_engine)


@pytest.fixture
def refreshed(timescale_url: str) -> Iterator[None]:
    """Materialise the aggregates, then leave them as the migration does: empty.

    The test database stops TimescaleDB's background jobs, so nothing
    would refresh an hour a later test changes. Left materialised, a
    later test that writes rows into an old hour would read a stale
    total. Emptying them puts every later read on the raw rows again.
    """
    _refresh(timescale_url)
    yield
    _empty(timescale_url)


def _empty(timescale_url: str) -> None:
    """Recreate the aggregates with no data, as revisions i366, i368 and i371 create them."""
    import importlib.util
    from pathlib import Path

    import sonoran

    engine = create_engine(timescale_url, isolation_level="AUTOCOMMIT")
    grants: list[str] = []
    try:
        for module in REVISIONS:
            path = Path(sonoran.__file__).parent / "db" / "migrations" / "versions" / f"{module}.py"
            spec = importlib.util.spec_from_file_location(module, path)
            assert spec is not None and spec.loader is not None
            revision = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(revision)
            keep = revision._retention_days() + revision.KEEP_LONGER_DAYS
            grants += list(getattr(revision, "JOB_GRANTS", ()))
            with engine.connect() as connection:
                for name in revision.VIEWS:
                    connection.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS {name}"))
                for statement in revision.create_statements(keep):
                    connection.execute(text(statement))
        # Rebuilding `packet_hourly` from i366 drops the grant i371 gave
        # the jobs role. Later tests run the read model job as that role.
        with engine.connect() as connection:
            for statement in grants:
                connection.execute(text(statement))
    finally:
        engine.dispose()


def test_the_hourly_counts_equal_the_raw_counts_after_a_full_refresh(
    timescale_url: str, migrated_engine: Any, traffic: None, refreshed: None
) -> None:
    _check(timescale_url, migrated_engine)


def test_the_api_role_reads_the_totals_and_cannot_write_them(
    timescale_url: str, migrated_engine: Any
) -> None:
    engine = create_engine(role_url(timescale_url, "azmsh_api").replace("+asyncpg", "+psycopg"))
    try:
        with engine.connect() as connection:
            for view in VIEWS:
                connection.execute(text(f"SELECT count(*) FROM {view}"))
    finally:
        engine.dispose()
