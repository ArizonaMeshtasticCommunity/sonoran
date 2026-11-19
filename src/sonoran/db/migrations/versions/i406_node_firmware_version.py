"""Keep each node's firmware version, and the stable release (#406).

`node.firmware_version` and `node.firmware_version_at` hold the version
from a node's newest map report. Nullable columns with no default:
PostgreSQL adds them without rewriting the table. `azmsh_ingest`
already holds UPDATE on `node`, which covers new columns. Rows written
before this stay NULL until the node sends a map report.

`firmware_release` is a job output (AGENTS.md 4): `azmsh_jobs` replaces
it with DELETE and INSERT, and `azmsh_api` reads it.

Revision ID: i406
Revises: pr344
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i406"
down_revision: str | None = "pr344"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("node", sa.Column("firmware_version", sa.Text(), nullable=True))
    op.add_column(
        "node", sa.Column("firmware_version_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "firmware_release",
        sa.Column("channel", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON firmware_release TO azmsh_jobs")
    op.execute("GRANT SELECT ON firmware_release TO azmsh_api")


def downgrade() -> None:
    op.drop_table("firmware_release")
    op.drop_column("node", "firmware_version_at")
    op.drop_column("node", "firmware_version")
