"""Hourly packet totals by family, kept by TimescaleDB (#368).

The activity chart grouped every raw packet of its window by hour (or
local day), port and payload state: 525 ms of database time for 30
days, and more as the mesh grows. This continuous aggregate holds the
same counts by hour. About 700,000 packets fold into about 9,600 rows.

- `packet_family_hourly`: packets first seen, per hour, `portnum` and
  `payload_state`. `payload_state` is kept because port 0 is a
  different family in each state (`traffic_label`).

It works as the two aggregates of revision i366 do: real-time
aggregation on, refreshed every 30 minutes over every invalidated hour,
kept `RETENTION_DAYS_PACKET` plus 14 days, SELECT for `azmsh_api`.
`sonoran/api/hourly.py` sums whole hours from it and counts the partial
hour at each end from the raw rows, so each count is exact.

Revision ID: i368
Revises: i366
Create Date: 2026-10-12
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "i368"
down_revision: str | None = "i366"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# How much longer than the raw rows the hourly totals are kept, in days.
KEEP_LONGER_DAYS = 14

VIEWS = {
    "packet_family_hourly": """
        SELECT time_bucket(INTERVAL '1 hour', first_seen_at) AS bucket,
               portnum,
               payload_state,
               count(*) AS packets
        FROM packet
        GROUP BY bucket, portnum, payload_state
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
    """The statements that create the aggregate with no data.

    One list, so the integration tests can put the aggregate back
    exactly as this revision makes it.
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
    """Create the aggregate, its policies and its grant."""
    for statement in create_statements(_retention_days() + KEEP_LONGER_DAYS):
        op.execute(statement)


def downgrade() -> None:
    """Drop the aggregate. Its policies go with it."""
    for name in reversed(VIEWS):
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name}")
