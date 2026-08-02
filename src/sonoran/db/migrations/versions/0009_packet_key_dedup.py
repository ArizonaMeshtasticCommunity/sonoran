"""Add the packet deduplication key table.

`packet` is a hypertable. TimescaleDB requires the partition column in
every unique constraint, so the packet key had to include
`first_seen_at`. That time comes from the packet `rx_time`, and every
gateway stamps its own value. The key therefore never matched a repeat,
and one packet was stored once per gateway.

This table holds the true key only. It is a plain table, so the primary
key is (`from_node_num`, `packet_id`) with no time column. Ingest writes
it with ON CONFLICT DO NOTHING and reads the affected row count to learn
whether a packet is new. That needs no SELECT right.

Observations are unaffected. Every gateway still writes its own
`packet_seen` row with its own signal reading.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the deduplication key table and its grants."""
    op.create_table(
        "packet_key",
        sa.Column("from_node_num", sa.BigInteger(), nullable=False),
        sa.Column("packet_id", sa.BigInteger(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("from_node_num", "packet_id", name="pk_packet_key"),
    )
    # The jobs process prunes old keys by time.
    op.create_index("ix_packet_key_first_seen", "packet_key", ["first_seen_at"])
    op.execute("GRANT INSERT ON packet_key TO azmsh_ingest")
    # ON CONFLICT must read the key columns to match a conflict. This is
    # the same narrow grant that revision 0006 gives on `node.node_num`.
    op.execute("GRANT SELECT (from_node_num, packet_id) ON packet_key TO azmsh_ingest")
    op.execute("GRANT SELECT ON packet_key TO azmsh_api")
    op.execute("GRANT SELECT, DELETE ON packet_key TO azmsh_jobs")


def downgrade() -> None:
    """Drop the deduplication key table."""
    op.drop_index("ix_packet_key_first_seen", table_name="packet_key")
    op.drop_table("packet_key")
