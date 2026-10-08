"""Tag each packet with the modem preset that carried it (#313).

The revision ID names the issue, not a number in sequence, so two
branches that add a migration at the same time cannot claim one ID
(the convention proposed in #348).

A topic channel such as `azmsh` is not a modem preset. This mesh runs
`azmsh` on MediumFast and on LongFast, so a filter on the topic channel
cannot tell the two meshes apart. Ingest now decides the preset of each
upload and stores it. See `sonoran/ingest/presets.py`.

Columns, all nullable:

- `packet_seen.modem_preset`: the preset of one upload.
- `packet.modem_preset`: the majority of its uploads' presets.
- `node.last_preset`, `node.last_preset_at`: the preset of the newest
  packet from the node whose preset is known.
- `node.uplink_preset`, `node.uplink_preset_at`: the preset the node
  uploads on as a gateway.

**No backfill, and no rewrite.** A nullable column with no default is a
catalogue change on a hypertable, so this is quick at deploy and takes
no long lock. Old rows keep NULL, and the API reads a NULL row by its
topic channel, exactly as before. That fallback fades as retention
expires the old rows.

**No new index.** The list pages read these rows newest first through
the time index they already use, and filter as they go. An index on
`(modem_preset, first_seen_at)` could not serve the NULL fallback, and
each new index on `packet_seen` costs every insert. See the PR.

**Grants.** `azmsh_ingest` holds INSERT and UPDATE on all three tables,
and a table grant covers a column added later (see 0015). PostgreSQL
also needs SELECT on every column an UPDATE names in its WHERE clause,
which is why revision 0006 grants `node.node_num`. So ingest gets
SELECT on these columns alone, never on the table:

- `packet (from_node_num, packet_id, first_seen_at)`: the natural key
  and the partition column, to find the one row to update. Nothing
  else in `packet` becomes readable.
- `node (uplink_preset, uplink_preset_at)`: read once at start, so a
  restart remembers each gateway's preset.
- `node (last_preset_at)`: so `last_preset` only moves forward in time.

Revision ID: i313
Revises: 0021
Create Date: 2026-10-08
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "i313"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out rather than imported from the models, so this revision
# keeps meaning what it meant when the models change later.
COLUMNS: list[tuple[str, str, Any]] = [
    ("packet_seen", "modem_preset", sa.Text()),
    ("packet", "modem_preset", sa.Text()),
    ("node", "last_preset", sa.Text()),
    ("node", "last_preset_at", sa.DateTime(timezone=True)),
    ("node", "uplink_preset", sa.Text()),
    ("node", "uplink_preset_at", sa.DateTime(timezone=True)),
]

INGEST_READS = {
    "packet": "from_node_num, packet_id, first_seen_at",
    "node": "uplink_preset, uplink_preset_at, last_preset_at",
}


def upgrade() -> None:
    """Add the nullable columns, then the narrow column grants."""
    for table, column, kind in COLUMNS:
        op.add_column(table, sa.Column(column, kind, nullable=True))
    for table, columns in INGEST_READS.items():
        op.execute(f"GRANT SELECT ({columns}) ON {table} TO azmsh_ingest")


def downgrade() -> None:
    """Remove the grants, then the columns.

    The tags are lost. They cannot be rebuilt afterwards, because the
    gateway state that decided them lived in the ingest process.
    """
    for table, columns in INGEST_READS.items():
        op.execute(f"REVOKE SELECT ({columns}) ON {table} FROM azmsh_ingest")
    for table, column, _kind in reversed(COLUMNS):
        op.drop_column(table, column)
