"""Fix process role grants.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-01

The ingest process writes data. It does not read data.
The jobs process can delete data when a retention fallback is needed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the least-privilege process grants."""
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM azmsh_ingest")
    op.execute("GRANT DELETE ON daily_snapshot TO azmsh_jobs")


def downgrade() -> None:
    """Restore the grants from the initial schema."""
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO azmsh_ingest")
    op.execute("REVOKE DELETE ON daily_snapshot FROM azmsh_jobs")
