"""Add the 900 MHz band table.

One row per station per minute: the median, 95th percentile, peak and
busy share of every bin a station's sweeper covered in that minute. See
`docs/design/rf-map.md` sections 3.5, 4.2 and 5.2.

About 520 bins of four small integers is a few kilobytes a row, and a
station sends 1,440 rows a day. The table is a hypertable kept 14 days.
The hourly summary the design keeps for 180 days is left for later.

`sonoran-rf-ingest` runs as `azmsh_ingest`. As revision 0013 does, it
gets INSERT and SELECT on only the columns an `ON CONFLICT DO NOTHING`
target reads, so it still cannot read the table. `azmsh_api` and
`azmsh_jobs` read it.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table, the hypertable, its retention and the grants."""
    op.create_table(
        "rf_spectrum",
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("t", sa.DateTime(timezone=True), nullable=False),
        sa.Column("f_start_hz", sa.BigInteger(), nullable=False),
        sa.Column("bin_hz", sa.Integer(), nullable=False),
        sa.Column("sweeps", sa.Integer(), nullable=False),
        sa.Column("gain_db", sa.REAL(), nullable=False),
        sa.Column("p50", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("p95", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("peak", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("busy", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("station_id", "t"),
    )
    op.execute(
        "SELECT create_hypertable('rf_spectrum', by_range('t', INTERVAL '1 day'), "
        "if_not_exists => TRUE)"
    )
    op.execute(
        "SELECT add_retention_policy('rf_spectrum', drop_after => INTERVAL '14 days', "
        "if_not_exists => TRUE)"
    )
    op.execute("GRANT INSERT ON rf_spectrum TO azmsh_ingest")
    op.execute("GRANT SELECT (station_id, t) ON rf_spectrum TO azmsh_ingest")
    op.execute("GRANT SELECT ON rf_spectrum TO azmsh_api")
    op.execute("GRANT SELECT ON rf_spectrum TO azmsh_jobs")


def downgrade() -> None:
    """Drop the table. Its grants and its policy go with it."""
    op.drop_table("rf_spectrum")
