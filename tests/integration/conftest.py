"""Integration test fixtures.

These tests start a real TimescaleDB container.
They skip when Docker is not available.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

TIMESCALE_IMAGE = "timescale/timescaledb-ha:pg17"

# The password the three least-privilege roles are created with.
#
# Revision 0001 has no default for these and stops when one is missing,
# so a deployment cannot come up on a password published in this
# repository. A test run is a deployment like any other: it sets real
# values and builds its DSNs from this same constant, so the tests
# cannot drift from the migration that made the roles.
#
# Plain characters on purpose. It goes into a URL as well as into SQL,
# and awkward characters are covered where they belong, by
# `test_migrations.py` and `tests/unit/test_role_passwords.py`.
ROLE_PASSWORD = "sonoran-test-role-pw"

ROLE_PASSWORD_VARS = (
    "AZMSH_INGEST_PASSWORD",
    "AZMSH_API_PASSWORD",
    "AZMSH_JOBS_PASSWORD",
)


def role_url(timescale_url: str, role: str) -> str:
    """Return the async DSN of one migration-created role.

    One place builds these. Four test modules each held their own copy
    with the password written into the string, so changing how the
    roles are made meant finding all four.
    """
    _, address = timescale_url.split("@", maxsplit=1)
    return f"postgresql+asyncpg://{role}:{ROLE_PASSWORD}@{address}"


@pytest.fixture(scope="session", autouse=True)
def role_passwords() -> Iterator[None]:
    """Give the migration the role passwords it now insists on."""
    previous = {name: os.environ.get(name) for name in ROLE_PASSWORD_VARS}
    for name in ROLE_PASSWORD_VARS:
        os.environ[name] = ROLE_PASSWORD
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(scope="session")
def timescale_url() -> Iterator[str]:
    """Return a TimescaleDB URL, starting a container unless given one.

    `SONORAN_TEST_DATABASE_URL` lets a developer point the suite at a
    database they already have. It is an escape hatch, not the ordinary
    path: the container starts here on its own.

    It did not always. On a Mac running Colima every database-backed
    test SKIPPED, with "error while creating mount source path ...
    operation not supported", and a skip looks exactly like a pass in
    pytest's summary line. That is how a genuine failure in
    `/api/chat/overview` reached CI unnoticed: 167 tests skipped locally
    and nobody saw it.

    The cause was diagnosed correctly at the time -- testcontainers'
    reaper sidecar bind-mounts the Docker socket, and Colima's socket
    lives on a virtiofs mount that cannot be bind-mounted -- and then
    worked around with the manual container below rather than fixed.
    Turning the reaper off is the fix, and `_disable_ryuk` does it.

        docker run --rm -d --name pg -e POSTGRES_PASSWORD=x \
          -e POSTGRES_DB=azmsh_test -p 55432:5432 \
          timescale/timescaledb-ha:pg17 -c timescaledb.max_background_workers=0
        SONORAN_TEST_DATABASE_URL=postgresql+psycopg://postgres:x@127.0.0.1:55432/azmsh_test \
          uv run pytest tests/integration
    """
    given = os.environ.get("SONORAN_TEST_DATABASE_URL")
    if given:
        _stop_background_workers(given)
        yield given
        return

    container = PostgresContainer(
        image=TIMESCALE_IMAGE,
        username="postgres",
        password="postgres",
        dbname="azmsh_test",
    )
    # No TimescaleDB background workers at all, for the life of the
    # container. `_stop_background_workers` below stops the scheduler that
    # is running at start, but `test_migrations.py` downgrades to base and
    # back, which recreates the extension and starts a new scheduler. Its
    # retention jobs then ran against `packet` while a later downgrade
    # altered it, and CI saw "deadlock detected" on
    # `ALTER TABLE packet ALTER COLUMN want_ack DROP DEFAULT`. A setting
    # read at server start cannot be undone by the schema under test.
    container.with_command("postgres -c timescaledb.max_background_workers=0")
    _disable_ryuk()
    try:
        container.start()
    except Exception as exc:  # Docker not available or image pull failed.
        _no_container(exc)
    url = container.get_connection_url()
    # testcontainers returns a psycopg2 URL. We use psycopg (v3).
    url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
    _stop_background_workers(url)
    yield url
    container.stop()


# Environment variable testcontainers reads to skip its reaper sidecar.
RYUK_DISABLED = "TESTCONTAINERS_RYUK_DISABLED"


def _disable_ryuk() -> None:
    """Turn off testcontainers' reaper, which this suite does not need.

    Ryuk is a sidecar that removes leftover containers after the test
    process exits. It gets the Docker socket by bind-mounting it, and on
    Colima that socket sits on a virtiofs mount where a bind mount is
    "operation not supported" -- so the *database* container never
    starts and every test that needs it skips.

    The trade is small and worth naming. Without Ryuk, a test run that
    is killed outright (SIGKILL, a closed laptop) can leave one
    `timescale/timescaledb-ha:pg17` container behind, to be removed by
    hand. Every ordinary exit still stops it, because `timescale_url`
    stops the container itself rather than relying on the reaper -- so
    on this suite Ryuk was only ever insurance against the abnormal
    exit, and it was costing every local run instead.

    An explicit setting always wins: someone who has set this variable,
    either way, has said what they want.
    """
    os.environ.setdefault(RYUK_DISABLED, "true")


# Set this where a skipped integration suite would be a false green --
# CI, or a local run you intend to trust. It turns "no container" from a
# skip into a failure.
REQUIRE_INTEGRATION = "SONORAN_REQUIRE_INTEGRATION"


def _no_container(exc: Exception) -> None:
    """Skip, or fail, when the database container will not start.

    A skip is the right default: somebody without Docker should still be
    able to run the unit tests. But a skip is reported in the same line
    as a pass, and this suite has already shipped a real bug behind one
    -- so anywhere the result is going to be trusted, say so with
    `SONORAN_REQUIRE_INTEGRATION=1` and a missing container becomes red
    instead of quiet.
    """
    message = f"cannot start TimescaleDB container: {exc}"
    if os.environ.get(REQUIRE_INTEGRATION, "").strip().lower() in {"1", "true", "yes"}:
        pytest.fail(f"{REQUIRE_INTEGRATION} is set, so this is a failure. {message}")
    pytest.skip(message)


def _stop_background_workers(url: str) -> None:
    """Stop TimescaleDB's background jobs for the life of this container.

    `test_migrations.py` drops and recreates every table and hypertable.
    The background scheduler runs retention and other jobs against those
    same objects, and a chunk that disappears between a statement being
    planned and executed produces failures that look like anything but
    their cause:

        tuple concurrently updated
        could not open relation with OID 23397
        relation "_timescaledb_internal._hyper_1_8_chunk" does not exist
          ... while running REVOKE SELECT ON ALL TABLES IN SCHEMA public

    That last one is the clearest: `ON ALL TABLES` expands to every
    chunk, and one of them was taken away underneath it.

    These fail in CI and not here, because the interleaving depends on
    timing. Over one evening the migration test failed 8 of 21 CI runs,
    on pull requests that changed a single markdown file and a single
    JavaScript file. Disposing the other pooled connection removed one
    of two competing backends; this removes the other.

    Nothing under test uses a background job. The API reads, the ingest
    writes, and retention in production is a deployment concern, not a
    property any of these tests assert.
    """
    from sqlalchemy import create_engine

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            # The function moved schema between TimescaleDB versions.
            for schema in ("_timescaledb_functions", "_timescaledb_internal"):
                try:
                    connection.execute(text(f"SELECT {schema}.stop_background_workers()"))
                    return
                except Exception:
                    continue
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def migrated_engine(timescale_url: str):  # type: ignore[no-untyped-def]
    """Run all migrations and yield a sync engine."""
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", timescale_url)
    import os

    os.environ["DATABASE_URL_MIGRATE"] = timescale_url
    command.upgrade(config, "head")
    engine = create_engine(timescale_url)
    yield engine
    engine.dispose()


# The tables the background jobs write (#351), children first.
JOB_OUTPUT_TABLES = (
    "gaps_trace_answer",
    "gaps_node",
    "gaps_run",
    "gaps_index",
    "gaps_siting_candidate",
    "gaps_siting",
    "coverage_calibration_node",
    "coverage_calibration",
)


def wipe_job_outputs(engine) -> None:  # type: ignore[no-untyped-def]
    """Delete every row the background jobs wrote. They hold no test's own data."""
    with engine.begin() as connection:
        for table in JOB_OUTPUT_TABLES:
            connection.execute(text(f"DELETE FROM {table}"))


def run_store(settings, func, *args):  # type: ignore[no-untyped-def]
    """Run one `gaps.store` or calibration function as the jobs role.

    The stores take a session since #351. A test that used to read a
    file calls this instead, with the function and its other arguments.
    """
    import asyncio

    from sonoran.db.session import make_engine, make_session_factory

    async def go():  # type: ignore[no-untyped-def]
        engine = make_engine(settings.database_url_jobs)
        try:
            async with make_session_factory(engine)() as session:
                return await func(session, *args)
        finally:
            await engine.dispose()

    return asyncio.run(go())
