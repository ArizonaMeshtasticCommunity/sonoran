"""Give spectrum minutes stored before 0020 the source that sent them.

Revision 0020 put the source in the key of `rf_spectrum` and
`rf_spectrum_hour`, and filled it with `-` (`NO_SOURCE`) for every row
already stored. But the ingest before 0020 did not record the source at
all, so `-` there meant "not recorded", not "an agent that sends no
source". On the live deployment the one station's agent had sent
`source: pi5` the whole time. After the deploy its history sat under `-`,
its new minutes under `pi5`, and the waterfall opened on a range one
minute long (2026-10-07).

This gives those rows the station's source where that is certain: the
station has exactly one row in `rf_source`, and it is not `-`. An agent
that sends no source makes a `-` row there with its first heartbeat, so a
station without one never had such an agent. Any other station is left
as it is. Where a row of the real source already holds the same minute or
hour, the `-` copy is the repeat and is deleted.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Stations whose only source is known, and that source.
ONLY_SOURCE = """
    SELECT station_id, min(source) AS source
    FROM rf_source
    GROUP BY station_id
    HAVING count(*) = 1 AND min(source) <> '-'
"""


def upgrade() -> None:
    """Move the unrecorded rows to the station's one source."""
    for table in ("rf_spectrum", "rf_spectrum_hour"):
        op.execute(
            f"""
            DELETE FROM {table} a
            USING ({ONLY_SOURCE}) s, {table} b
            WHERE a.station_id = s.station_id AND a.source = '-'
              AND b.station_id = a.station_id AND b.source = s.source
              AND b.t = a.t AND b.f_start_hz = a.f_start_hz
              AND b.bin_hz = a.bin_hz AND b.bins = a.bins
            """
        )
        op.execute(
            f"""
            UPDATE {table} a SET source = s.source
            FROM ({ONLY_SOURCE}) s
            WHERE a.station_id = s.station_id AND a.source = '-'
            """
        )


def downgrade() -> None:
    """Nothing to undo: the rows keep the source that sent them."""
