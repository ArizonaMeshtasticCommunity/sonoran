"""Any swept range, member mods, and trust for the shared layers (#324).

- `rf_spectrum` is keyed by range as well as station and minute: (`station_id`,
  `source`, `f_start_hz`, `bin_hz`, `bins`, `t`). A station that sweeps
  two ranges, with two dongles or one taking turns, keeps both. `bins` was
  the length of the arrays; it is now a column, so it can be in the key.
  `name` is the station's own label for a range.
- `rf_spectrum_hour` gets `source` in its key, for the same reason.
- `rf_source.sweeps` holds what a source reports it sweeps, and how.
- `rf_track` and `rf_latest` record the source, the trust level and the
  receive time of the point they keep. The winner is no longer the point
  that claims the loudest level or the newest time (`rf/store.py`).
- `rf_custom` holds what members' mods send, per station, 14 days.
- `rf_trust`, `rf_hidden_mod` and `rf_operator_log` are the operators'
  tools. Only the database owner writes them.

Grants, as revision 0013 does them: `azmsh_ingest` reads only the columns
a conflict target or an `UPDATE ... WHERE` needs. It also reads
`rf_trust`, which is settings an operator writes, never data a station
sends (`AGENTS.md` 9.2).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SPECTRUM_KEY = ("station_id", "source", "f_start_hz", "bin_hz", "bins", "t")
HOUR_KEY = ("station_id", "source", "t", "f_start_hz", "bin_hz", "bins")


def upgrade() -> None:
    """Add the columns and tables, change the keys, and grant."""
    # The minutes: a range in the key.
    op.add_column("rf_spectrum", sa.Column("source", sa.Text(), nullable=False, server_default="-"))
    op.add_column("rf_spectrum", sa.Column("bins", sa.Integer()))
    op.add_column("rf_spectrum", sa.Column("name", sa.Text()))
    op.execute("UPDATE rf_spectrum SET bins = cardinality(p95)")
    op.alter_column("rf_spectrum", "bins", nullable=False)
    op.drop_constraint("rf_spectrum_pkey", "rf_spectrum", type_="primary")
    op.create_primary_key("rf_spectrum_pkey", "rf_spectrum", list(SPECTRUM_KEY))
    op.create_index("ix_rf_spectrum_station_t", "rf_spectrum", ["station_id", sa.text("t DESC")])
    op.execute("GRANT SELECT (source, f_start_hz, bin_hz, bins) ON rf_spectrum TO azmsh_ingest")

    # The hours: the source in the key.
    op.add_column(
        "rf_spectrum_hour", sa.Column("source", sa.Text(), nullable=False, server_default="-")
    )
    op.drop_constraint("rf_spectrum_hour_pkey", "rf_spectrum_hour", type_="primary")
    op.create_primary_key("rf_spectrum_hour_pkey", "rf_spectrum_hour", list(HOUR_KEY))

    # What a source reports it sweeps.
    op.add_column("rf_source", sa.Column("sweeps", JSONB()))

    # Who holds a shared point, and at what trust.
    for table in ("rf_track", "rf_latest"):
        op.add_column(table, sa.Column("source", sa.Text()))
        op.add_column(
            table, sa.Column("trust", sa.SmallInteger(), nullable=False, server_default="1")
        )
        op.add_column(table, sa.Column("received_at", sa.DateTime(timezone=True)))
        op.execute(f"GRANT SELECT (trust) ON {table} TO azmsh_ingest")

    # Members' mods.
    op.create_table(
        "rf_custom",
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("mod", sa.Text(), nullable=False),
        sa.Column("thing_id", sa.Text(), nullable=False),
        sa.Column("t", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_t", sa.DateTime(timezone=True), nullable=False),
        sa.Column("placement", sa.Text(), nullable=False),
        sa.Column("lat", sa.Double()),
        sa.Column("lon", sa.Double()),
        sa.Column("meta", JSONB()),
        sa.PrimaryKeyConstraint("station_id", "mod", "thing_id", "t"),
    )
    op.create_index("ix_rf_custom_station_t", "rf_custom", ["station_id", sa.text("t DESC")])
    op.execute(
        "SELECT create_hypertable('rf_custom', by_range('t', INTERVAL '1 day'), "
        "if_not_exists => TRUE)"
    )
    op.execute(
        "SELECT add_retention_policy('rf_custom', drop_after => INTERVAL '14 days', "
        "if_not_exists => TRUE)"
    )
    op.execute("GRANT INSERT ON rf_custom TO azmsh_ingest")
    op.execute("GRANT SELECT (station_id, mod, thing_id, t) ON rf_custom TO azmsh_ingest")
    op.execute("GRANT SELECT ON rf_custom TO azmsh_api")
    op.execute("GRANT SELECT ON rf_custom TO azmsh_jobs")

    # The operators' tools.
    op.create_table(
        "rf_trust",
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("trust", sa.SmallInteger(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("station_id", "source"),
    )
    op.create_table(
        "rf_hidden_mod",
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("mod", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("station_id", "mod"),
    )
    op.create_table(
        "rf_operator_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("station_id", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("GRANT SELECT ON rf_trust TO azmsh_ingest")
    op.execute("GRANT SELECT ON rf_trust TO azmsh_api")
    op.execute("GRANT SELECT ON rf_hidden_mod TO azmsh_api")


def downgrade() -> None:
    """Remove them again.

    The old keys hold one range per station and minute (or hour). Where
    a station sent more than one, all but one are deleted first, and the
    one kept is the first by source and range.
    """
    op.drop_table("rf_operator_log")
    op.drop_table("rf_hidden_mod")
    op.drop_table("rf_trust")
    op.drop_table("rf_custom")
    for table in ("rf_latest", "rf_track"):
        op.drop_column(table, "received_at")
        op.drop_column(table, "trust")
        op.drop_column(table, "source")
    op.drop_column("rf_source", "sweeps")

    op.execute(
        "DELETE FROM rf_spectrum_hour a USING rf_spectrum_hour b "
        "WHERE a.station_id = b.station_id AND a.t = b.t AND a.f_start_hz = b.f_start_hz "
        "AND a.bin_hz = b.bin_hz AND a.bins = b.bins AND a.source > b.source"
    )
    op.drop_constraint("rf_spectrum_hour_pkey", "rf_spectrum_hour", type_="primary")
    op.create_primary_key(
        "rf_spectrum_hour_pkey",
        "rf_spectrum_hour",
        ["station_id", "t", "f_start_hz", "bin_hz", "bins"],
    )
    op.drop_column("rf_spectrum_hour", "source")

    op.execute(
        "DELETE FROM rf_spectrum a USING rf_spectrum b "
        "WHERE a.station_id = b.station_id AND a.t = b.t "
        "AND (a.source, a.f_start_hz, a.bin_hz, a.bins) "
        "> (b.source, b.f_start_hz, b.bin_hz, b.bins)"
    )
    op.drop_index("ix_rf_spectrum_station_t", table_name="rf_spectrum")
    op.drop_constraint("rf_spectrum_pkey", "rf_spectrum", type_="primary")
    op.create_primary_key("rf_spectrum_pkey", "rf_spectrum", ["station_id", "t"])
    op.drop_column("rf_spectrum", "name")
    op.drop_column("rf_spectrum", "bins")
    op.drop_column("rf_spectrum", "source")
