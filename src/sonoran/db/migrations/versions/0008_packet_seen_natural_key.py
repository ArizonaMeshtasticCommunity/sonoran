"""Index the observation deduplication key.

The API joins `packet_seen` to `packet` by (`from_node_num`,
`packet_id`). The ingest role has no SELECT right, so it cannot read
back the generated `packet.id` to store on the observation.

Without this index the join reads the whole table.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the natural-key index to the observation table."""
    op.create_index(
        "ix_packet_seen_natural_key",
        "packet_seen",
        ["from_node_num", "packet_id", sa.text("seen_at DESC")],
    )


def downgrade() -> None:
    """Remove the natural-key index."""
    op.drop_index("ix_packet_seen_natural_key", table_name="packet_seen")
