"""Store the Meshtastic packet ID on every payload table.

The payload tables carried `packet_pk`, which points at the generated
`packet.id` surrogate key. Ingest can never fill it: the role has no
SELECT right, so it cannot read a generated key back. Every one of those
columns is NULL, and nothing can be traced to its packet.

The protocol already gives a packet ID. Ingest holds it before it writes
anything, and `packet`, `packet_seen`, and `mesh_packet_metrics` already
store it. This revision gives the same column to the rest, so every
stored value can be joined to the packet that carried it with
(`node`, `packet_id`).

Rows written before this revision keep a NULL packet ID. They cannot be
traced, because the link was never recorded.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Each table with the node column that pairs with the packet ID.
TABLES: tuple[tuple[str, str], ...] = (
    ("traceroute", "from_node_num"),
    ("text_message", "from_node_num"),
    ("neighbor_metrics", "node_num"),
    ("device_metrics", "node_num"),
    ("environment_metrics", "node_num"),
    ("air_quality_metrics", "node_num"),
    ("power_metrics", "node_num"),
    ("pax_metrics", "node_num"),
    ("position_metrics", "node_num"),
)


def upgrade() -> None:
    """Add the packet ID column and a lookup index to each table."""
    for table, node_column in TABLES:
        op.add_column(table, sa.Column("packet_id", sa.BigInteger(), nullable=True))
        op.create_index(
            f"ix_{table}_packet",
            table,
            [node_column, "packet_id"],
        )


def downgrade() -> None:
    """Remove the packet ID column and its index from each table."""
    for table, _ in TABLES:
        op.drop_index(f"ix_{table}_packet", table_name=table)
        op.drop_column(table, "packet_id")
