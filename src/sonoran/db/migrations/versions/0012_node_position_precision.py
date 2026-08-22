"""Carry the position precision onto the node.

A Meshtastic node can send a position with fewer bits than it measured.
The public broker at mqtt.meshtastic.org limits what it relays to
between 10 and 16 bits, and map reporting defaults to 14, which is
about 1459 m of deviation.

`position_metrics` already records `precision_bits` for each report.
The node row did not carry it, so anything reading `node.last_lat` saw
a fuzzed position and an exact one as the same thing. The coverage map
then drew a footprint around a place that may have no radio on it.

The column is denormalised beside `last_lat` and `last_lon`, and for
the same reason they are. `position_metrics` is a hypertable with a
retention policy, and `node.last_lat` outlives the row it came from. A
join at read time would report an unknown precision for exactly the
nodes whose position is oldest.

The backfill takes the newest report of each node, inside the retention
window, so the first coverage run after this revision is already right
instead of waiting a week for every node to report again.

The newest report, not the newest one that carried a precision. A node
that reported through the public broker last week and directly over the
radio an hour ago has an exact position now, and picking the older
value would call it coarse and drop a good site.

A node with no report inside the window keeps NULL, which
`is_precise_enough` reads as full precision. The migration therefore
fails open, not shut: a deployment with short retention predicts from
everything until each node reports again.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# How far back the backfill reads.
#
# The retention policy drops metric rows after this, so nothing older
# can describe a node that is still on the map.
BACKFILL_DAYS = 30


def upgrade() -> None:
    """Add the column and fill it from the newest report of each node.

    `azmsh_ingest` already holds UPDATE on `node`, and a table grant
    covers a column added later, so this needs no grant revision.
    """
    op.add_column("node", sa.Column("last_position_precision_bits", sa.Integer()))
    op.execute(
        f"""
        UPDATE node
        SET last_position_precision_bits = newest.precision_bits
        FROM (
            SELECT DISTINCT ON (node_num) node_num, precision_bits
            FROM position_metrics
            WHERE time >= now() - INTERVAL '{BACKFILL_DAYS} days'
            ORDER BY node_num, time DESC
        ) AS newest
        WHERE node.node_num = newest.node_num
        """
    )


def downgrade() -> None:
    """Drop the column."""
    op.drop_column("node", "last_position_precision_bits")
