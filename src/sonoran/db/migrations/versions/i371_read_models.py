"""Read models for the long-window views, and packets per sender and port (#371).

Views that cover hours or days were computed from raw rows when somebody
asked, in the API's one event loop: the longest-link board took 11.6 s
over 30 days, the graph 1.5 s over 7 days. While one of them ran, every
other request waited. The jobs service now builds them ahead of time and
the API reads the stored answer.

**Read model tables.** Each holds the latest build only. The job
deletes a run and inserts the new one in one transaction, and the child
rows go with the run (`ON DELETE CASCADE`). Like the #351 tables they
hold node numbers and numbers, never a name or a position: the API joins
`node` when it reads, so a renamed or moved node reads correctly at once.

- `link_evidence_run`, `link_evidence_link`, `link_evidence_node`: the
  links that traceroutes and neighbour reports show on one channel ('' is
  every channel) over one window, and each node's packet count. The graph
  and the longest-link board both read them.
- `broadcast_run`, `broadcast_node`: each node's broadcast rates over a
  rolling window, in the order the report ranks them.
- `channel_nodes_run`, `channel_node`: the nodes that sent traffic seen on
  a channel inside a window (the coverage page's node list).

**`packet_sender_port_hourly`.** A continuous aggregate made and read like
those of revisions i366 and i368: packets first seen, per hour, sender
and port. The broadcast rates count from it.

**Grants.** `azmsh_jobs` gets SELECT, INSERT and DELETE on the read model
tables, and SELECT on `packet_hourly` and the new aggregate, which it now
reads. `azmsh_api` gets SELECT on all of them.

Revision ID: i371
Revises: i368
Create Date: 2026-10-13
"""

import os
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "i371"
down_revision: str | None = "i368"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out rather than imported, so this revision keeps meaning what
# it meant when the models change later. Parents before children.
TABLES = (
    "link_evidence_run",
    "link_evidence_link",
    "link_evidence_node",
    "broadcast_run",
    "broadcast_node",
    "channel_nodes_run",
    "channel_node",
)

# How much longer than the raw rows the hourly totals are kept, in days.
KEEP_LONGER_DAYS = 14

VIEWS = {
    "packet_sender_port_hourly": """
        SELECT time_bucket(INTERVAL '1 hour', first_seen_at) AS bucket,
               from_node_num,
               portnum,
               count(*) AS packets
        FROM packet
        GROUP BY bucket, from_node_num, portnum
    """,
}


# The jobs role reads the hourly totals per sender for each node's packet
# count. A list, so the integration tests can grant it again after they
# rebuild `packet_hourly` from revision i366.
JOB_GRANTS = ("GRANT SELECT ON packet_hourly TO azmsh_jobs",)


def _retention_days() -> int:
    """The packet retention of this deployment, as revision 0005 reads it."""
    try:
        value = int(os.environ.get("RETENTION_DAYS_PACKET", "30"))
    except ValueError as exc:
        raise ValueError("RETENTION_DAYS_PACKET must be a positive integer") from exc
    if value < 1:
        raise ValueError("RETENTION_DAYS_PACKET must be a positive integer")
    return value


def create_statements(keep_days: int) -> list[str]:
    """The statements that create the aggregate with no data.

    One list, so the integration tests can put the aggregate back
    exactly as this revision makes it.
    """
    statements: list[str] = []
    for name, query in VIEWS.items():
        statements += [
            f"CREATE MATERIALIZED VIEW {name} "
            "WITH (timescaledb.continuous, timescaledb.materialized_only = false) "
            f"AS {query} WITH NO DATA",
            f"SELECT add_continuous_aggregate_policy('{name}', "
            "start_offset => NULL, end_offset => INTERVAL '1 hour', "
            "schedule_interval => INTERVAL '30 minutes')",
            f"SELECT add_retention_policy('{name}', drop_after => INTERVAL '{keep_days} days')",
            f"GRANT SELECT ON {name} TO azmsh_api",
            f"GRANT SELECT ON {name} TO azmsh_jobs",
        ]
    return statements


def _run_key(*names: str) -> list[sa.Column[Any]]:
    columns: dict[str, sa.Column[Any]] = {
        "channel": sa.Column("channel", sa.Text(), nullable=False),
        "hours": sa.Column("hours", sa.Integer(), nullable=False),
    }
    return [columns[name] for name in names]


def upgrade() -> None:
    """Create the aggregate, the read model tables and their grants."""
    for statement in create_statements(_retention_days() + KEEP_LONGER_DAYS):
        op.execute(statement)
    # The graph job counts each node's packets from the hourly totals.
    for statement in JOB_GRANTS:
        op.execute(statement)

    op.create_table(
        "link_evidence_run",
        *_run_key("channel", "hours"),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("channel", "hours"),
    )
    op.create_table(
        "link_evidence_link",
        *_run_key("channel", "hours"),
        sa.Column("source", sa.BigInteger(), nullable=False),
        sa.Column("target", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("kinds", ARRAY(sa.Text()), nullable=False),
        sa.Column("snr", sa.Double(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("forward", sa.Integer(), nullable=False),
        sa.Column("backward", sa.Integer(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("channel", "hours", "source", "target"),
        sa.ForeignKeyConstraint(
            ["channel", "hours"],
            ["link_evidence_run.channel", "link_evidence_run.hours"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "link_evidence_node",
        *_run_key("channel", "hours"),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("packet_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("channel", "hours", "node_num"),
        sa.ForeignKeyConstraint(
            ["channel", "hours"],
            ["link_evidence_run.channel", "link_evidence_run.hours"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "broadcast_run",
        *_run_key("hours"),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notable_count", sa.Integer(), nullable=False),
        sa.Column("power_loop_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hours"),
    )
    op.create_table(
        "broadcast_node",
        *_run_key("hours"),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("packet_count", sa.Integer(), nullable=False),
        sa.Column("notable", ARRAY(sa.Text()), nullable=False),
        sa.Column("faster_than_default", ARRAY(sa.Text()), nullable=False),
        sa.Column("families", JSONB(), nullable=False),
        sa.Column("health", JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("hours", "node_num"),
        sa.ForeignKeyConstraint(["hours"], ["broadcast_run.hours"], ondelete="CASCADE"),
    )
    op.create_index("ix_broadcast_node_rank", "broadcast_node", ["hours", "rank"])
    op.create_table(
        "channel_nodes_run",
        *_run_key("channel", "hours"),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("channel", "hours"),
    )
    op.create_table(
        "channel_node",
        *_run_key("channel", "hours"),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("channel", "hours", "node_num"),
        sa.ForeignKeyConstraint(
            ["channel", "hours"],
            ["channel_nodes_run.channel", "channel_nodes_run.hours"],
            ondelete="CASCADE",
        ),
    )
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, DELETE ON {table} TO azmsh_jobs")
        op.execute(f"GRANT SELECT ON {table} TO azmsh_api")


def downgrade() -> None:
    """Drop the tables and the aggregate. Their grants and policies go with them."""
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("REVOKE SELECT ON packet_hourly FROM azmsh_jobs")
    for name in reversed(VIEWS):
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name}")
