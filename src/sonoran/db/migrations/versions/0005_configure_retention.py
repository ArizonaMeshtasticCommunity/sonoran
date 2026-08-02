"""Configure retention policies from deployment settings.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-01

The initial policy values are safe defaults. This revision replaces them
with the values set for this deployment. The migration service reads the
same `.env` file as the application services.
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICIES = (
    ("packet", "RETENTION_DAYS_PACKET", 30),
    ("packet_seen", "RETENTION_DAYS_PACKET", 30),
    ("traceroute", "RETENTION_DAYS_TRACEROUTE", 90),
    ("text_message", "RETENTION_DAYS_TEXT", 30),
    ("position_metrics", "RETENTION_DAYS_POSITION", 30),
    ("device_metrics", "RETENTION_DAYS_METRIC", 90),
    ("environment_metrics", "RETENTION_DAYS_METRIC", 90),
    ("air_quality_metrics", "RETENTION_DAYS_METRIC", 90),
    ("power_metrics", "RETENTION_DAYS_METRIC", 90),
    ("pax_metrics", "RETENTION_DAYS_METRIC", 90),
    ("mesh_packet_metrics", "RETENTION_DAYS_METRIC", 90),
    ("neighbor_metrics", "RETENTION_DAYS_METRIC", 90),
)


def _days(variable: str, default: int) -> int:
    """Read and validate one positive retention setting."""
    try:
        value = int(os.environ.get(variable, str(default)))
    except ValueError as exc:
        raise ValueError(f"{variable} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{variable} must be a positive integer")
    return value


def _set_policy(table: str, days: int) -> None:
    """Replace a table retention policy with one configured period."""
    op.execute(f"SELECT remove_retention_policy('{table}', if_exists => TRUE)")
    op.execute(
        f"SELECT add_retention_policy('{table}', "
        f"drop_after => INTERVAL '{days} days', if_not_exists => TRUE)"
    )


def upgrade() -> None:
    """Apply deployment retention settings to every hypertable."""
    for table, variable, default in POLICIES:
        _set_policy(table, _days(variable, default))


def downgrade() -> None:
    """Restore the documented default retention periods."""
    for table, _, default in POLICIES:
        _set_policy(table, default)
