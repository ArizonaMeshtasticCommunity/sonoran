"""Let the ingest role read `rf_heard.lat`.

A hearing of an APRS digipeater named in a path has no position of its
own (design 5.1), so its `rf_heard` row stores none. When the same
station later hears that digipeater's own beacon in the same bucket,
the ingest fills the position in, but only where the row has none:

    UPDATE rf_heard SET lat = ..., lon = ... WHERE ... AND lat IS NULL

Reading `lat` in the `WHERE` needs SELECT on it, and revision 0013 gave
`azmsh_ingest` SELECT on only the columns it needed then (`AGENTS.md`
9.2). Without this grant every repeat hearing in a bucket, aircraft
included, fails with "permission denied for table rf_heard".

`lon` is written, never read, so it needs no grant.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Grant SELECT on the one column the ingest now reads."""
    op.execute("GRANT SELECT (lat) ON rf_heard TO azmsh_ingest")


def downgrade() -> None:
    """Take the grant back. The ingest from before 0016 never reads it."""
    op.execute("REVOKE SELECT (lat) ON rf_heard FROM azmsh_ingest")
