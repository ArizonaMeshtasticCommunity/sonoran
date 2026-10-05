"""Add the hourly rollup of the 900 MHz band.

The waterfall reads every minute in its window, bin by bin. A week of
one station at 25 kHz bins is about 10 million values per page view,
which is too much for a small box once a minute. The jobs process rolls
each finished hour up once, with the same per-bin rules as a waterfall
row, and the 3 and 7 day windows read these rows instead. Each hour
also keeps every bin's loudest moment and the minute it happened, so a
short transmission is never averaged away and can be found again.

It keeps 14 days, like `rf_spectrum`, which it is built from.
`azmsh_jobs` writes it; `azmsh_api` reads it.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table, the hypertable, its retention and the grants."""
    op.create_table(
        "rf_spectrum_hour",
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("t", sa.DateTime(timezone=True), nullable=False),
        sa.Column("f_start_hz", sa.BigInteger(), nullable=False),
        sa.Column("bin_hz", sa.Integer(), nullable=False),
        sa.Column("bins", sa.Integer(), nullable=False),
        sa.Column("gain_db", sa.REAL(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("p50", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("p95", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("busy", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("peak", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("peak_min", ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("station_id", "t", "f_start_hz", "bin_hz", "bins"),
    )
    op.execute(
        "SELECT create_hypertable('rf_spectrum_hour', by_range('t', INTERVAL '7 days'), "
        "if_not_exists => TRUE)"
    )
    op.execute(
        "SELECT add_retention_policy('rf_spectrum_hour', drop_after => INTERVAL '14 days', "
        "if_not_exists => TRUE)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON rf_spectrum_hour TO azmsh_jobs")
    op.execute("GRANT SELECT ON rf_spectrum_hour TO azmsh_api")


def downgrade() -> None:
    """Drop the table. Its grants and its policy go with it."""
    op.drop_table("rf_spectrum_hour")
