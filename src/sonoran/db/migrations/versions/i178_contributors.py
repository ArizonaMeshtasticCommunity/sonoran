"""Contributors, their jobs, and the readings they bring back (#178).

See `docs/design/contributors.md` section 5.4.

- `contrib_source`: the last heartbeat of each contributor.
- `contrib_heard`: the nodes each contributor's node hears. Replaced
  with each heartbeat.
- `contrib_job`: every job and its outcome.
- `local_stats`: a hypertable of readings. Retention is
  `RETENTION_DAYS_METRIC`, as for `device_metrics`.

**Grants.** `sonoran-contrib` runs as `azmsh_jobs`, which already reads
every table: it needs `node.role` to choose targets. It gets SELECT,
INSERT, UPDATE and DELETE on the three `contrib_` tables, and SELECT and
INSERT on `local_stats`; it never edits a reading. `azmsh_api` gets
SELECT on `local_stats` and `contrib_source`. `azmsh_ingest` gets
nothing.

Revision ID: i178
Revises: i371
Create Date: 2026-10-14
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "i178"
down_revision: str | None = "i371"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTRIB_TABLES = ("contrib_source", "contrib_heard", "contrib_job")


def _retention_days() -> int:
    """`RETENTION_DAYS_METRIC`, read as revision 0005 reads it."""
    value = int(os.environ.get("RETENTION_DAYS_METRIC", "90"))
    if value < 1:
        raise ValueError("RETENTION_DAYS_METRIC must be a positive integer")
    return value


def _contributor() -> list[sa.Column]:
    return [
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
    ]


def upgrade() -> None:
    """Create the tables, the hypertable and the grants."""
    op.create_table(
        "contrib_source",
        *_contributor(),
        sa.Column("sent", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Text()),
        sa.Column("mesh_node", sa.BigInteger()),
        sa.Column("kinds", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("location", "source"),
    )
    op.create_table(
        "contrib_heard",
        *_contributor(),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("hops", sa.SmallInteger()),
        sa.Column("last_heard", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("location", "source", "node_num"),
        sa.ForeignKeyConstraint(
            ["location", "source"],
            ["contrib_source.location", "contrib_source.source"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_contrib_heard_node", "contrib_heard", ["node_num"])
    op.create_table(
        "contrib_job",
        sa.Column("job", sa.Text(), primary_key=True),
        *_contributor(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target", sa.BigInteger(), nullable=False),
        # Every job of one round carries the time the round started.
        sa.Column("round_started", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires", sa.DateTime(timezone=True), nullable=False),
        # None while open. Then a Result outcome, or `expired`.
        sa.Column("outcome", sa.Text()),
        sa.Column("finished", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.Text()),
        # True once the outbox message is cleared.
        sa.Column("cleared", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_contrib_job_target_round", "contrib_job", ["target", sa.text("round_started DESC")]
    )
    op.create_index(
        "ix_contrib_job_open",
        "contrib_job",
        ["location", "source"],
        postgresql_where=sa.text("outcome IS NULL"),
    )
    op.create_table(
        "local_stats",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("job", sa.Text(), nullable=False),
        *_contributor(),
        sa.Column("hops", sa.SmallInteger()),
        sa.Column("rx_snr", sa.REAL()),
        sa.Column("rx_rssi", sa.Integer()),
        sa.Column("uptime_seconds", sa.BigInteger()),
        sa.Column("channel_utilization", sa.REAL()),
        sa.Column("air_util_tx", sa.REAL()),
        sa.Column("num_packets_tx", sa.BigInteger()),
        sa.Column("num_packets_rx", sa.BigInteger()),
        sa.Column("num_packets_rx_bad", sa.BigInteger()),
        sa.Column("num_online_nodes", sa.BigInteger()),
        sa.Column("num_total_nodes", sa.BigInteger()),
        sa.Column("num_rx_dupe", sa.BigInteger()),
        sa.Column("num_tx_relay", sa.BigInteger()),
        sa.Column("num_tx_relay_canceled", sa.BigInteger()),
        sa.Column("heap_total_bytes", sa.BigInteger()),
        sa.Column("heap_free_bytes", sa.BigInteger()),
        sa.Column("num_tx_dropped", sa.BigInteger()),
        sa.Column("noise_floor", sa.Integer()),
        sa.PrimaryKeyConstraint("job", "time"),
    )
    op.create_index("ix_local_stats_node_time", "local_stats", ["node_num", sa.text("time DESC")])
    op.execute("SELECT create_hypertable('local_stats', by_range('time'), if_not_exists => TRUE)")
    op.execute(
        "SELECT add_retention_policy('local_stats', "
        f"drop_after => INTERVAL '{_retention_days()} days', if_not_exists => TRUE)"
    )

    for table in CONTRIB_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO azmsh_jobs")
    op.execute("GRANT SELECT, INSERT ON local_stats TO azmsh_jobs")
    op.execute("GRANT SELECT ON local_stats TO azmsh_api")
    op.execute("GRANT SELECT ON contrib_source TO azmsh_api")


def downgrade() -> None:
    """Drop the tables. Their grants and policies go with them."""
    op.drop_table("local_stats")
    for table in reversed(CONTRIB_TABLES):
        op.drop_table(table)
