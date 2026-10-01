"""Add RF locations and their sources (#305).

A location is what the map shows as one station. It may have several
sources: one Pi with an ADS-B decoder and one with the 900 MHz sweep,
for example. Each source has its own broker login and its own heartbeat.

- `rf_source` holds one row per source, from its heartbeat.
- `rf_station` gets the registry fields: the display name, the owner,
  and the sources that hold a login now.
- `rf_station.last_seen` may be NULL. A location can be in the registry
  before any of its sources sends a heartbeat.

`azmsh_ingest` gets INSERT and UPDATE on `rf_source` and SELECT on its
key only, as for the other RF tables (`AGENTS.md` 9.2). The new
`rf_station` columns are written by `UPDATE ... WHERE station_id`, which
the 0013 grant already covers.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create `rf_source`, add the registry columns, and grant."""
    op.create_table(
        "rf_source",
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("kinds", ARRAY(sa.Text())),
        sa.Column("agent_version", sa.Text()),
        sa.Column("heard", sa.Integer()),
        sa.Column("sent", sa.Integer()),
        sa.Column("dropped", sa.Integer()),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("station_id", "source"),
    )
    op.add_column("rf_station", sa.Column("display_name", sa.Text()))
    op.add_column("rf_station", sa.Column("owner", sa.Text()))
    op.add_column("rf_station", sa.Column("registered_sources", ARRAY(sa.Text())))
    op.add_column("rf_station", sa.Column("registry_at", sa.DateTime(timezone=True)))
    op.alter_column("rf_station", "last_seen", nullable=True)

    op.execute("GRANT INSERT, UPDATE ON rf_source TO azmsh_ingest")
    op.execute("GRANT SELECT (station_id, source) ON rf_source TO azmsh_ingest")
    op.execute("GRANT SELECT ON rf_source TO azmsh_api")
    op.execute("GRANT SELECT ON rf_source TO azmsh_jobs")


def downgrade() -> None:
    """Remove them again.

    A location that is in the registry and has sent no heartbeat has no
    `last_seen`. It is removed, because the column becomes NOT NULL
    again. Its first heartbeat adds it back.
    """
    op.execute("DELETE FROM rf_station WHERE last_seen IS NULL")
    op.alter_column("rf_station", "last_seen", nullable=False)
    op.drop_column("rf_station", "registry_at")
    op.drop_column("rf_station", "registered_sources")
    op.drop_column("rf_station", "owner")
    op.drop_column("rf_station", "display_name")
    op.drop_table("rf_source")
