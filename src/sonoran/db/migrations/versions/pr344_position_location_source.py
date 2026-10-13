"""Add location_source to position_metrics.

Revision ID: pr344
Revises: i368
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "pr344"
down_revision: str | None = "i368"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add location_source."""
    op.add_column("position_metrics", sa.Column("location_source", sa.Text()))


def downgrade() -> None:
    """Drop location_source."""
    op.drop_column("position_metrics", "location_source")
