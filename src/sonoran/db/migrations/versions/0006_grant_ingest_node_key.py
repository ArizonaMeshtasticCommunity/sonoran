"""Grant the ingest role access to the node update key.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-01

PostgreSQL requires SELECT privilege on a column used in an UPDATE predicate.
The ingest role gets access to the node primary key only. It still has no
table-wide SELECT privilege.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Grant the node key needed by position updates."""
    op.execute("GRANT SELECT (node_num) ON node TO azmsh_ingest")


def downgrade() -> None:
    """Remove the node-key read privilege."""
    op.execute("REVOKE SELECT (node_num) ON node FROM azmsh_ingest")
