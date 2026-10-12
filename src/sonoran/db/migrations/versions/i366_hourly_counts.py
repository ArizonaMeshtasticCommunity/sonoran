"""Hourly totals of packets and uploads, kept by TimescaleDB (#366).

Statistics counted raw rows: about 7.8 million uploads for a 30 day
window, twice (the window and the one before it), in 12.7 s. These two
continuous aggregates hold the same counts by hour, so a 30 day count
is a sum over 720 rows. `docs/DATABASE.md` 8 planned them.

- `packet_hourly`: packets first seen, per hour and per sender. Per
  sender, because "distinct nodes per day" cannot be added up from
  plain hourly totals, but it can from these rows.
- `packet_seen_hourly`: uploads, per hour.

**Exact, and live.** A reader sums whole hours from here and counts the
partial hour at each end of its window from the raw rows. With
`materialized_only = false`, TimescaleDB also adds the hours after the
last refresh from the raw rows. So an answer is exact to the second.

**Refresh.** A policy refreshes every 30 minutes. `start_offset` NULL
means every invalidated hour is refreshed, whatever its age, so the
first run fills the whole history and later runs touch only what
changed. Rows arrive with our own receive time (AGENTS.md 9.4), so an
old hour almost never changes.

**Retention.** The raw tables drop whole chunks, so they can hold rows a
few days older than `RETENTION_DAYS_PACKET`. These totals are kept 14
days longer than that, so they always cover every hour the raw tables
still hold. Readers never ask for an hour older than the raw rows.

**Grants.** `azmsh_api` gets SELECT. Nothing writes these views but
TimescaleDB.

Revision ID: i366
Revises: i351
Create Date: 2026-10-12
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "i366"
down_revision: str | None = "i351"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# How much longer than the raw rows the hourly totals are kept, in days.
KEEP_LONGER_DAYS = 14

VIEWS = {
    "packet_hourly": """
        SELECT time_bucket(INTERVAL '1 hour', first_seen_at) AS bucket,
               from_node_num,
               count(*) AS packets
        FROM packet
        GROUP BY bucket, from_node_num
    """,
    "packet_seen_hourly": """
        SELECT time_bucket(INTERVAL '1 hour', seen_at) AS bucket,
               count(*) AS uploads
        FROM packet_seen
        GROUP BY bucket
    """,
}


def _retention_days() -> int:
    """The packet retention of this deployment, as revision 0005 reads it."""
    try:
        value = int(os.environ.get("RETENTION_DAYS_PACKET", "30"))
    except ValueError as exc:
        raise ValueError("RETENTION_DAYS_PACKET must be a positive integer") from exc
    if value < 1:
        raise ValueError("RETENTION_DAYS_PACKET must be a positive integer")
    return value


def create_statements(keep_days: int) -> list[str]:
    """The statements that create both aggregates with no data.

    One list, so `tests/integration/test_hourly_counts.py` can put the
    aggregates back exactly as this revision makes them.
    """
    statements: list[str] = []
    for name, query in VIEWS.items():
        statements += [
            f"CREATE MATERIALIZED VIEW {name} "
            "WITH (timescaledb.continuous, timescaledb.materialized_only = false) "
            f"AS {query} WITH NO DATA",
            f"SELECT add_continuous_aggregate_policy('{name}', "
            "start_offset => NULL, end_offset => INTERVAL '1 hour', "
            "schedule_interval => INTERVAL '30 minutes')",
            f"SELECT add_retention_policy('{name}', drop_after => INTERVAL '{keep_days} days')",
            f"GRANT SELECT ON {name} TO azmsh_api",
        ]
    return statements


def upgrade() -> None:
    """Create the two aggregates, their policies and their grant."""
    for statement in create_statements(_retention_days() + KEEP_LONGER_DAYS):
        op.execute(statement)


def downgrade() -> None:
    """Drop the aggregates. Their policies go with them."""
    for name in reversed(VIEWS):
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name}")
