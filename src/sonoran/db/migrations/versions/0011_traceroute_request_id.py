"""Store the traceroute request ID.

A traceroute reply carries `request_id` in its Data payload. That field
holds the packet ID of the request it answers, so a request and its
reply share one identity.

mesh-graph keys a trace the same way. Its ingest reads:

    trace_id = decoded.get("requestId", packet.id)

Storing the field lets a traceroute link straight to the matching
mesh-graph page, and lets a request and its reply be grouped.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the request ID column and its lookup index."""
    op.add_column("traceroute", sa.Column("request_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_traceroute_request", "traceroute", ["request_id"])


def downgrade() -> None:
    """Remove the request ID column and its index."""
    op.drop_index("ix_traceroute_request", table_name="traceroute")
    op.drop_column("traceroute", "request_id")
