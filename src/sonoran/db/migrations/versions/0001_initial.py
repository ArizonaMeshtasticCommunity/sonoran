"""Initial schema: roles, tables, hypertables, retention policies.

Revision ID: 0001
Revises: none
Create Date: 2026-08-01

This migration does four things:

1. It enables the TimescaleDB extension.
2. It creates the process roles with least-privilege grants.
3. It creates all tables from the SQLAlchemy models.
4. It converts the high-volume tables to hypertables with retention policies.

Role passwords come from environment variables:
AZMSH_INGEST_PASSWORD, AZMSH_API_PASSWORD, AZMSH_JOBS_PASSWORD.
The default for each is "change_me". Change them before deploy.
"""

import os
from collections.abc import Sequence

from alembic import op

from sonoran.db.migrations.initial_schema import metadata

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ["azmsh_ingest", "azmsh_api", "azmsh_jobs"]

# Keep this revision independent from models added by later revisions.
INITIAL_TABLES = (
    "node",
    "packet",
    "packet_seen",
    "traceroute",
    "text_message",
    "device_metrics",
    "environment_metrics",
    "air_quality_metrics",
    "power_metrics",
    "pax_metrics",
    "position_metrics",
    "neighbor_metrics",
    "node_config",
    "daily_snapshot",
)

INITIAL_HYPERTABLES = (
    ("packet", "first_seen_at", 30),
    ("packet_seen", "seen_at", 30),
    ("traceroute", "seen_at", 90),
    ("text_message", "seen_at", 30),
    ("position_metrics", "time", 30),
    ("device_metrics", "time", 90),
    ("environment_metrics", "time", 90),
    ("air_quality_metrics", "time", 90),
    ("power_metrics", "time", 90),
    ("pax_metrics", "time", 90),
    ("neighbor_metrics", "time", 90),
)


def _password(env_var: str) -> str:
    return os.environ.get(env_var, "change_me")


def upgrade() -> None:
    # 1. TimescaleDB extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # 2. Roles with least-privilege grants.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'azmsh_ingest') THEN
                CREATE ROLE azmsh_ingest LOGIN PASSWORD '{_password("AZMSH_INGEST_PASSWORD")}';
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'azmsh_api') THEN
                CREATE ROLE azmsh_api LOGIN PASSWORD '{_password("AZMSH_API_PASSWORD")}';
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'azmsh_jobs') THEN
                CREATE ROLE azmsh_jobs LOGIN PASSWORD '{_password("AZMSH_JOBS_PASSWORD")}';
            END IF;
        END
        $$;
        """
    )

    # 3. Tables.
    metadata.create_all(
        bind=op.get_bind(),
        tables=[metadata.tables[table_name] for table_name in INITIAL_TABLES],
    )

    # 4. Grants.
    for table in INITIAL_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO azmsh_ingest")
        op.execute(f"GRANT SELECT ON {table} TO azmsh_api")
        op.execute(f"GRANT SELECT ON {table} TO azmsh_jobs")
    op.execute("GRANT INSERT, UPDATE ON daily_snapshot TO azmsh_jobs")
    # The ingest role needs sequence usage for the identity columns.
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO azmsh_ingest")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO azmsh_jobs")

    # 5. Hypertables and retention policies.
    for table, time_column, retention_days in INITIAL_HYPERTABLES:
        op.execute(
            f"SELECT create_hypertable('{table}', by_range('{time_column}'), if_not_exists => TRUE)"
        )
        op.execute(
            f"SELECT add_retention_policy('{table}', "
            f"drop_after => INTERVAL '{retention_days} days', if_not_exists => TRUE)"
        )


def downgrade() -> None:
    for role in ROLES:
        op.execute(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {role}")
        op.execute(f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {role}")
    metadata.drop_all(bind=op.get_bind())
    for role in ROLES:
        op.execute(f"DROP ROLE IF EXISTS {role}")
    # The extension stays. Other databases on the server may use it.
