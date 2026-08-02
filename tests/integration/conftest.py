"""Integration test fixtures.

These tests start a real TimescaleDB container.
They skip when Docker is not available.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from testcontainers.postgres import PostgresContainer

TIMESCALE_IMAGE = "timescale/timescaledb-ha:pg17"


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
