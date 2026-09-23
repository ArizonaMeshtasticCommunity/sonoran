"""Record why a packet's payload could not be read (#157).

`portnum = 0` is both the sentinel for "could not read it" and the real
port `UNKNOWN_APP`, and nothing on the row told them apart. A census
over a 168 h production window measured what those rows actually were:

    pki_to_one_recipient   8342   91.7%
    opaque_no_key_opened    743    8.2%
    decoded_with_payload      7    0.1%
    decoded_empty_payload     1    0.0%

The chart calling all of them `UNKNOWN_APP` was therefore about 99.9%
wrong, and it is read by operators deciding what their mesh is doing.

The column is text, not an integer or an enum type. Text because these
values get read by people in `psql`; not a Postgres `ENUM` because
adding a value to one takes a lock on every table that uses it, and a
future firmware that needs a fourth state should not need an outage.

**No backfill, on purpose.** The answer for an existing row is inside
`raw_bytes` and takes a decryption attempt per row against the current
channel keys. A migration does not have those keys, would be writing
today's key configuration onto packets ingested under a different one,
and would be doing it row by row across a hypertable holding hundreds
of thousands of rows a week. `tools/portnum_zero_census.py` is the
thing that answers it for a window, and it is read-only. Old rows keep
NULL, which readers must show as unknown rather than fold into the
commonest value.

`azmsh_ingest` already holds INSERT on `packet`, and a table grant
covers a column added later, so this needs no grant revision.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column. Nullable, because every existing row is unknown."""
    op.add_column("packet", sa.Column("payload_state", sa.Text()))


def downgrade() -> None:
    """Drop the column.

    The values are not recoverable afterwards without re-running the
    census, which is stated here because a downgrade on this table is
    otherwise an easy thing to treat as free.
    """
    op.drop_column("packet", "payload_state")
