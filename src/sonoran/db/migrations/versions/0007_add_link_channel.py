"""Add the channel to the mesh link tables.

A LoRa modem preset is a different radio configuration. Nodes on
LongFast cannot hear nodes on MediumFast. The mesh graph must draw one
graph for each preset. To do that, each link must know its channel.

The `packet_seen` and `text_message` tables already hold the channel.
This revision does the same for `neighbor_metrics` and `traceroute`.

Rows that exist before this revision keep a NULL channel. The API
reports them under an unknown channel.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the channel column and its lookup index to both tables."""
    op.add_column("neighbor_metrics", sa.Column("channel", sa.Text(), nullable=True))
    op.add_column("traceroute", sa.Column("channel", sa.Text(), nullable=True))
    op.create_index(
        "ix_neighbor_metrics_channel_time",
        "neighbor_metrics",
        ["channel", sa.text("time DESC")],
    )
    op.create_index(
        "ix_traceroute_channel_time",
        "traceroute",
        ["channel", sa.text("seen_at DESC")],
    )


def downgrade() -> None:
    """Remove the channel column and its index from both tables."""
    op.drop_index("ix_traceroute_channel_time", table_name="traceroute")
    op.drop_index("ix_neighbor_metrics_channel_time", table_name="neighbor_metrics")
    op.drop_column("traceroute", "channel")
    op.drop_column("neighbor_metrics", "channel")
