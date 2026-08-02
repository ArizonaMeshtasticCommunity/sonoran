"""Alembic environment.

The database URL comes from the DATABASE_URL_MIGRATE environment variable.
Use a sync driver (psycopg) for migrations.
"""

import os

from alembic import context
from sqlalchemy import create_engine

from sonoran.db.models import Base

config = context.config
target_metadata = Base.metadata

DEFAULT_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/sonoran"


def get_url() -> str:
    """Return the migration database URL."""
    url = os.environ.get("DATABASE_URL_MIGRATE", DEFAULT_URL)
    # Accept async URLs and convert them to the sync psycopg driver.
    return url.replace("+asyncpg", "+psycopg")


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""
    engine = create_engine(get_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
