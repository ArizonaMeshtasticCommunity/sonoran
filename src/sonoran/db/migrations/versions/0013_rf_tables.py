"""Add the RF map tables.

What the community's own receivers hear beyond Meshtastic, aircraft
first. See `docs/design/rf-map.md` sections 5.2 and 5.4.

`rf_track` and `rf_heard` are hypertables with retention, because
ADS-B is the largest stream this database will hold: about 1.3 million
points a day at one point per aircraft per 20 s. The retention here is
load bearing and matches the capacity arithmetic in the design.

`sonoran-rf-ingest` runs as `azmsh_ingest`. It gets INSERT and UPDATE on
these tables and, as revision 0006 does for `node`, SELECT on only the
columns an `ON CONFLICT DO NOTHING` target or an `UPDATE ... WHERE`
reads. It still cannot read the tables. `azmsh_api` and `azmsh_jobs`
read them.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("rf_station", "rf_track", "rf_heard", "rf_latest")

# How long each hypertable keeps rows. See the design, 5.2 and 5.4.
RETENTION = (("rf_track", "bucket", "2 days"), ("rf_heard", "bucket", "14 days"))

# The columns the ingest role must be able to read, and nothing more.
INGEST_COLUMNS = {
    "rf_station": ("station_id",),
    "rf_track": ("kind", "thing_id", "bucket", "rssi_db"),
    "rf_heard": ("station_id", "kind", "thing_id", "bucket", "heard", "best_rssi_db"),
    "rf_latest": ("kind", "thing_id", "t"),
}


def _position_columns() -> list[sa.Column]:
    return [
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lon", sa.Double(), nullable=False),
        sa.Column("alt_m", sa.REAL()),
        sa.Column("alt_ref", sa.Text()),
        sa.Column("gs_kn", sa.REAL()),
        sa.Column("track_deg", sa.REAL()),
        sa.Column("rssi_db", sa.REAL()),
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("meta", JSONB()),
    ]


def upgrade() -> None:
    """Create the tables, the hypertables, their retention and the grants."""
    op.create_table(
        "rf_station",
        sa.Column("station_id", sa.Text(), primary_key=True),
        sa.Column("lat", sa.Double()),
        sa.Column("lon", sa.Double()),
        sa.Column("precision_m", sa.Integer()),
        sa.Column("kinds", ARRAY(sa.Text())),
        sa.Column("agent_version", sa.Text()),
        sa.Column("heard", sa.Integer()),
        sa.Column("sent", sa.Integer()),
        sa.Column("dropped", sa.Integer()),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "rf_track",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("thing_id", sa.Text(), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("t", sa.DateTime(timezone=True), nullable=False),
        *_position_columns(),
        sa.PrimaryKeyConstraint("kind", "thing_id", "bucket"),
    )
    op.create_index("ix_rf_track_bucket", "rf_track", [sa.text("bucket DESC")])
    op.create_table(
        "rf_heard",
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("thing_id", sa.Text(), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heard", sa.Integer(), nullable=False),
        sa.Column("best_rssi_db", sa.REAL()),
        sa.Column("lat", sa.Double()),
        sa.Column("lon", sa.Double()),
        sa.PrimaryKeyConstraint("station_id", "kind", "thing_id", "bucket"),
    )
    op.create_index(
        "ix_rf_heard_station_bucket", "rf_heard", ["station_id", sa.text("bucket DESC")]
    )
    op.create_table(
        "rf_latest",
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("thing_id", sa.Text(), primary_key=True),
        sa.Column("t", sa.DateTime(timezone=True), nullable=False),
        *_position_columns(),
    )
    op.create_index("ix_rf_latest_t", "rf_latest", ["t"])

    for table, column, keep in RETENTION:
        op.execute(
            f"SELECT create_hypertable('{table}', by_range('{column}'), if_not_exists => TRUE)"
        )
        op.execute(
            f"SELECT add_retention_policy('{table}', drop_after => INTERVAL '{keep}', "
            "if_not_exists => TRUE)"
        )

    for table in TABLES:
        op.execute(f"GRANT INSERT, UPDATE ON {table} TO azmsh_ingest")
        op.execute(f"GRANT SELECT ({', '.join(INGEST_COLUMNS[table])}) ON {table} TO azmsh_ingest")
        op.execute(f"GRANT SELECT ON {table} TO azmsh_api")
        op.execute(f"GRANT SELECT ON {table} TO azmsh_jobs")


def downgrade() -> None:
    """Drop the tables. Their grants and policies go with them."""
    for table in reversed(TABLES):
        op.drop_table(table)
