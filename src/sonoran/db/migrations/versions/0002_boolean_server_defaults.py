"""Add server defaults to required Boolean columns.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-01

ORM defaults do not apply to SQL that does not use the ORM.
These server defaults let all insert methods omit a required Boolean value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add false defaults for required Boolean columns."""
    for table_name, column_name in (
        ("node", "is_licensed"),
        ("node", "is_mqtt_gateway"),
        ("packet", "want_ack"),
        ("text_message", "emoji"),
    ):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Boolean(),
            server_default=sa.false(),
        )


def downgrade() -> None:
    """Remove the server defaults."""
    for table_name, column_name in (
        ("text_message", "emoji"),
        ("packet", "want_ack"),
        ("node", "is_mqtt_gateway"),
        ("node", "is_licensed"),
    ):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Boolean(),
            server_default=None,
        )
