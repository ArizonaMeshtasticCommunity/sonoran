"""Let the node page read a node's sightings from the index alone (#304).

`/api/nodes/{id}/routes` took 5 to 8 seconds on a busy gateway. For
`!576b1bbe` over 720 hours, 5.1 s of 8.3 s was one query over its
156,000 sightings as a gateway. Measured on s.azmsh.dev:

- **The time was the heap, not the join.** Without the join to
  `packet` the same query still took 5.7 s. A node's sightings are
  written in time order among everybody else's, so they sit on about
  100,000 different pages (111,000 buffers per query), and this host
  cannot keep 870 MB of `packet_seen` in memory.
- **A covering index answered it in 44 ms** (1,478 pages, no heap
  fetch), measured on a copy of that node's rows.

So this revision does two things:

1. **`packet_seen.hop_start`.** A sighting is direct when `hop_start =
   hop_limit` (AGENTS.md 9.5), and `hop_start` was on `packet` only.
   The sender sets it and a relay does not change it, so each upload's
   header carries the value `packet` holds. Ingest writes it now.
2. **Both time indexes become covering.** `ix_packet_seen_from_time`
   and `ix_packet_seen_gateway_time` keep their keys and INCLUDE the
   columns the node page reads (`models.SIGHTING_INCLUDE`). They are
   replaced, not added beside, so ingest maintains the same number of
   indexes as before.

**No backfill, on purpose.** Rewriting several gigabytes of
`packet_seen` is too much for this host. Old rows keep NULL, and
`api/sightings.py` joins only those to `packet`, still from the index.
Retention expires them within 30 days.

**Cost at deploy.** Adding the column is a catalogue change. Building
the two indexes reads the whole table, and `CREATE INDEX` blocks
inserts into `packet_seen` while it runs, so ingest waits for it. Run
it when the mesh is quiet, and time it first on a copy if you can.

`azmsh_ingest` holds INSERT on the table, and a table grant covers a
column added later (see 0015).

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out rather than imported from the models, so this revision
# keeps meaning what it meant when the models change later.
INCLUDE = [
    "from_node_num",
    "packet_id",
    "gateway_node_num",
    "rx_snr",
    "rx_rssi",
    "hop_limit",
    "hop_start",
]
INDEXES = {
    "ix_packet_seen_from_time": "from_node_num",
    "ix_packet_seen_gateway_time": "gateway_node_num",
}


def upgrade() -> None:
    """Add the column, then rebuild both time indexes as covering."""
    op.add_column("packet_seen", sa.Column("hop_start", sa.Integer()))
    for name, key in INDEXES.items():
        op.drop_index(name, table_name="packet_seen")
        op.create_index(
            name,
            "packet_seen",
            [key, sa.text("seen_at DESC")],
            postgresql_include=INCLUDE,
        )


def downgrade() -> None:
    """Put the plain indexes back and drop the column.

    Readers then join every sighting to `packet` again, and the node
    page is as slow as before this revision.
    """
    for name, key in INDEXES.items():
        op.drop_index(name, table_name="packet_seen")
        op.create_index(name, "packet_seen", [key, sa.text("seen_at DESC")])
    op.drop_column("packet_seen", "hop_start")
