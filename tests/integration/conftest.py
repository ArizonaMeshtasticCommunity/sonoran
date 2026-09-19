"""Integration test fixtures.

These tests start a real TimescaleDB container.
They skip when Docker is not available.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
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
    """Start a TimescaleDB container and return its sync database URL."""
    container = PostgresContainer(
        image=TIMESCALE_IMAGE,
        username="postgres",
        password="postgres",
        dbname="azmsh_test",
    )
    try:
        container.start()
    except Exception as exc:  # Docker not available or image pull failed.
        pytest.skip(f"cannot start TimescaleDB container: {exc}")
    url = container.get_connection_url()
    # testcontainers returns a psycopg2 URL. We use psycopg (v3).
    url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
    yield url
    container.stop()


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
