"""Keep the relay byte of every upload in `packet_seen` (PR #378).

`MeshPacket.relay_node` is the last byte of the node that sent a copy to
the gateway (AGENTS.md 9.20). It was kept once per packet, from the
first upload, in `mesh_packet_metrics`. Each gateway hears its own
relay, so each upload now keeps it.

A nullable column with no default: PostgreSQL adds it without rewriting
the table. `azmsh_ingest` already holds INSERT on the table, which covers
a new column. Rows written before this stay NULL.

Revision ID: pr378
Revises: i178
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "pr378"
down_revision: str | None = "i178"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("packet_seen", sa.Column("relay_node", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("packet_seen", "relay_node")
