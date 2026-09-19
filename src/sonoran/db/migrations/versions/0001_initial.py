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

There is no default, and this migration stops if one is missing, empty
or still the placeholder from `.env.example`. It used to default each
of them to "change_me", so an operator who followed the documented
first run — `cp .env.example .env`, per `tools/db_restore.sh` — got a
working deployment whose three least-privilege roles all had a password
published in this repository, and nothing anywhere said so.

The values must match the passwords in DATABASE_URL, DATABASE_URL_API
and DATABASE_URL_JOBS, which is why all six are named together in
`.env.example`.
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


# The passwords this migration refuses, by name.
#
# `change_me` was the default, and `.env.example` shipped it inside all
# three role DSNs while never naming the variables that set the real
# thing. `tools/db_restore.sh` tells an operator to copy that file.
# Follow the documentation and you got a deployment that worked, so
# nothing ever told you the three least-privilege roles were reachable
# with a password printed in a public repository.
#
# `CHANGE_ME` is the placeholder `.env.example` carries now. It is
# refused for the same reason: a file meant to be edited is a file
# somebody will copy unedited, and the value has to stop working rather
# than quietly become the password.
PLACEHOLDER_PASSWORDS = frozenset({"change_me", "CHANGE_ME"})


class MissingRolePassword(RuntimeError):
    """A database role password was not supplied, or was the placeholder.

    Raised rather than defaulted. A default that works is a default
    nobody changes: the migration succeeds, the stack comes up, the
    dashboard serves, and the only sign of the fault is that somebody
    reads this file.
    """


def _password(env_var: str) -> str:
    """Return a role password from the environment, or refuse to migrate.

    There is no default. An absent, empty or placeholder value stops the
    migration with the variable named, which is the one moment an
    operator is watching and can fix it.
    """
    value = os.environ.get(env_var, "")
    if not value:
        raise MissingRolePassword(
            f"{env_var} is not set. The three database roles are created by this "
            f"migration and each needs its own password. Set AZMSH_INGEST_PASSWORD, "
            f"AZMSH_API_PASSWORD and AZMSH_JOBS_PASSWORD, and use the same values in "
            f"DATABASE_URL, DATABASE_URL_API and DATABASE_URL_JOBS. See .env.example."
        )
    if value in PLACEHOLDER_PASSWORDS:
        raise MissingRolePassword(
            f"{env_var} is still {value!r}, which is a placeholder from .env.example "
            f"and is published in a public repository. Choose a real password and put "
            f"the same value in the matching DATABASE_URL."
        )
    return value


# The tag of the dollar-quoted block the role statements live in.
#
# Not the bare `$$`, so a password that contains `$$` cannot end the
# block early and have the rest of itself read as SQL.
ROLE_BLOCK_TAG = "$azmsh_roles$"


def _sql_literal(value: str) -> str:
    """Return a value as a single-quoted SQL string literal.

    A password is chosen by an operator and may hold any character, so
    it is quoted rather than trusted. `standard_conforming_strings` is
    on by default in PostgreSQL, so a backslash is an ordinary
    character and doubling the quote is the whole of the escape.
    """
    if "\x00" in value:
        raise MissingRolePassword("a role password cannot contain a null byte")
    if ROLE_BLOCK_TAG in value:
        raise MissingRolePassword(f"a role password cannot contain {ROLE_BLOCK_TAG!r}")
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _role_password_literal(env_var: str) -> str:
    """Return the password for a role, ready to place in the statement."""
    return _sql_literal(_password(env_var))


def upgrade() -> None:
    # 1. TimescaleDB extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # 2. Roles with least-privilege grants.
    ingest_password = _role_password_literal("AZMSH_INGEST_PASSWORD")
    api_password = _role_password_literal("AZMSH_API_PASSWORD")
    jobs_password = _role_password_literal("AZMSH_JOBS_PASSWORD")
    op.execute(
        f"""
        DO {ROLE_BLOCK_TAG}
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'azmsh_ingest') THEN
                CREATE ROLE azmsh_ingest LOGIN PASSWORD {ingest_password};
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'azmsh_api') THEN
                CREATE ROLE azmsh_api LOGIN PASSWORD {api_password};
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'azmsh_jobs') THEN
                CREATE ROLE azmsh_jobs LOGIN PASSWORD {jobs_password};
            END IF;
        END
        {ROLE_BLOCK_TAG};
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
