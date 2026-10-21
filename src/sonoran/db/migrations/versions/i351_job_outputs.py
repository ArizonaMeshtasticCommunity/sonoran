"""Keep what the background jobs compute in tables, not JSON files (#351).

The gaps job, the siting half of the gaps feature and the calibration
fit wrote JSON files beside the coverage tiles, and the API read them.
These tables replace those files. The coverage tiles stay on disk.

- `gaps_index`, `gaps_run`, `gaps_node`, `gaps_signal` and
  `gaps_trace_answer`: the per node assessment of each preset, and the
  leaderboard counts of the other Statistics windows.
- `gaps_siting`, `gaps_siting_area`, `gaps_siting_point` and
  `gaps_siting_candidate`: the siting answer.
- `coverage_calibration` and `coverage_calibration_node`: the fit.

**Each table holds the latest run only.** The job deletes a run's rows
and inserts the new ones in one transaction, so a reader never sees
half of a run, and nothing grows with time. None is a hypertable.

**Foreign keys.** Every child row belongs to its run and is deleted
with it (`ON DELETE CASCADE`). A node row of a gaps run names a real
node (`gaps_node.node_num` references `node`); the job leaves out a row
whose node has no record yet, so that key can never fail a run. A
traceroute count does not reference `node`: a node can be traced and
never send anything, and then it has no record.

**Grants.** `azmsh_jobs` gets SELECT, INSERT and DELETE on these tables
and nothing else new. It reads them back: the siting half reads the
assessment, and the coverage job reads the calibration. It needs no
UPDATE, because a run is replaced, never edited. `azmsh_api` gets
SELECT. `azmsh_ingest` gets nothing.

**No data is moved here.** The old files are in a Docker volume, not in
the database. The jobs process imports them once at start when a table
is empty (`sonoran/jobs/legacy_import.py`), so no page is blank between
the deploy and the first run.

Revision ID: i351
Revises: i313
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "i351"
down_revision: str | None = "i313"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out rather than imported, so this revision keeps meaning what
# it meant when the models change later.
TABLES = (
    "gaps_index",
    "gaps_run",
    "gaps_node",
    "gaps_signal",
    "gaps_trace_answer",
    "gaps_siting",
    "gaps_siting_area",
    "gaps_siting_point",
    "gaps_siting_candidate",
    "coverage_calibration",
    "coverage_calibration_node",
)

RUN_KEY = ["preset", "scope", "asked_hours"]


def _run_key() -> list[sa.Column]:
    return [
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("asked_hours", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    """Create the tables and their grants."""
    op.create_table(
        "gaps_index",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_gaps_index_one_row"),
    )
    op.create_table(
        "gaps_run",
        *_run_key(),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=True),
        sa.Column("summary", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("preset", "scope", "asked_hours"),
        sa.CheckConstraint("scope IN ('assessment', 'board')", name="ck_gaps_run_scope"),
    )
    op.create_table(
        "gaps_node",
        *_run_key(),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("packets", sa.Integer(), nullable=True),
        sa.Column("rf_packets", sa.Integer(), nullable=True),
        sa.Column("ambiguous_packets", sa.Integer(), nullable=True),
        sa.Column("active_hours", sa.Integer(), nullable=True),
        sa.Column("rf_hours", sa.Integer(), nullable=True),
        sa.Column("direct_gateways", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("position_confidence", sa.Text(), nullable=True),
        sa.Column("position_deviation_m", sa.Double(), nullable=True),
        sa.Column("position_spread_km", sa.Double(), nullable=True),
        sa.Column("is_mqtt_gateway", sa.Boolean(), nullable=True),
        sa.Column("mobile", sa.Boolean(), nullable=True),
        sa.Column("worst_state", sa.Text(), nullable=True),
        sa.Column("bad_count", sa.Integer(), nullable=True),
        sa.Column("unknown_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("preset", "scope", "asked_hours", "node_num"),
        sa.ForeignKeyConstraint(RUN_KEY, [f"gaps_run.{c}" for c in RUN_KEY], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_num"], ["node.node_num"]),
    )
    op.create_index("ix_gaps_node_rank", "gaps_node", ["preset", "scope", "asked_hours", "rank"])
    op.create_index(
        "ix_gaps_node_worst", "gaps_node", ["preset", "scope", "asked_hours", "worst_state"]
    )
    op.create_table(
        "gaps_signal",
        *_run_key(),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("signal", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("value", sa.Double(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("preset", "scope", "asked_hours", "node_num", "signal"),
        sa.ForeignKeyConstraint(
            [*RUN_KEY, "node_num"],
            [f"gaps_node.{c}" for c in (*RUN_KEY, "node_num")],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_gaps_signal_state", "gaps_signal", [*RUN_KEY, "signal", "state", "node_num"]
    )
    op.create_table(
        "gaps_trace_answer",
        *_run_key(),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("answered", sa.Integer(), nullable=False),
        sa.Column("senders", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("preset", "scope", "asked_hours", "node_num"),
        sa.ForeignKeyConstraint(RUN_KEY, [f"gaps_run.{c}" for c in RUN_KEY], ondelete="CASCADE"),
    )
    op.create_table(
        "gaps_siting",
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("preset"),
    )
    op.create_table(
        "gaps_siting_area",
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("area", sa.Integer(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("node_nums", ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("centroid_lat", sa.Double(), nullable=False),
        sa.Column("centroid_lon", sa.Double(), nullable=False),
        sa.Column("south", sa.Double(), nullable=False),
        sa.Column("west", sa.Double(), nullable=False),
        sa.Column("north", sa.Double(), nullable=False),
        sa.Column("east", sa.Double(), nullable=False),
        sa.Column("width_km", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("preset", "area"),
        sa.ForeignKeyConstraint(["preset"], ["gaps_siting.preset"], ondelete="CASCADE"),
    )
    op.create_table(
        "gaps_siting_point",
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("area", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("node_nums", ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("names", ARRAY(sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("preset", "area", "position"),
        sa.ForeignKeyConstraint(
            ["preset", "area"],
            ["gaps_siting_area.preset", "gaps_siting_area.area"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "gaps_siting_candidate",
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("area", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("elevation_m", sa.Integer(), nullable=True),
        sa.Column("prominence_m", sa.Integer(), nullable=True),
        sa.Column("node_num", sa.BigInteger(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("screen_score", sa.Integer(), nullable=False),
        sa.Column("screen_unknown", sa.Integer(), nullable=False),
        sa.Column("newly_usable", sa.Integer(), nullable=True),
        sa.Column("newly_usable_nodes", ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("already_usable", sa.Integer(), nullable=False),
        sa.Column("baseline_unknown", sa.Integer(), nullable=False),
        sa.Column("run_stamp", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("preset", "position"),
        sa.ForeignKeyConstraint(["preset"], ["gaps_siting.preset"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_gaps_siting_candidate_area", "gaps_siting_candidate", ["preset", "area", "position"]
    )
    op.create_table(
        "coverage_calibration",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_bias_db", sa.Double(), nullable=False),
        sa.Column("residual_spread_db", sa.Double(), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=False),
        sa.Column("summary", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_coverage_calibration_one_row"),
    )
    op.create_table(
        "coverage_calibration_node",
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("offset_db", sa.Double(), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("counterparties", sa.Integer(), nullable=False),
        sa.Column("censored", sa.Integer(), nullable=False),
        sa.Column("reported", sa.Integer(), nullable=False),
        sa.Column("residual_spread_db", sa.Double(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("node_num"),
    )
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, DELETE ON {table} TO azmsh_jobs")
        op.execute(f"GRANT SELECT ON {table} TO azmsh_api")


def downgrade() -> None:
    """Drop the tables. Their grants go with them."""
    for table in reversed(TABLES):
        op.drop_table(table)
