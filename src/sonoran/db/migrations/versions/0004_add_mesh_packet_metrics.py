"""Add mesh packet routing statistics.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the mesh packet routing statistics hypertable."""
    op.create_table(
        "mesh_packet_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("packet_pk", sa.BigInteger(), nullable=True),
        sa.Column("from_node_num", sa.BigInteger(), nullable=False),
        sa.Column("to_node_num", sa.BigInteger(), nullable=False),
        sa.Column("packet_id", sa.BigInteger(), nullable=False),
        sa.Column("reporting_gateway_node_num", sa.BigInteger(), nullable=True),
        sa.Column("via_mqtt", sa.Boolean(), nullable=True),
        sa.Column("message_size_bytes", sa.Integer(), nullable=True),
        sa.Column("relay_node_num", sa.BigInteger(), nullable=True),
        sa.Column("next_hop_node_num", sa.BigInteger(), nullable=True),
        sa.Column("transport_mechanism", sa.Text(), nullable=True),
        sa.Column("pki_encrypted", sa.Boolean(), nullable=True),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "time"),
    )
    op.create_index(
        "ix_mesh_packet_metrics_from_time",
        "mesh_packet_metrics",
        ["from_node_num", sa.text("time DESC")],
    )
    op.create_index(
        "ix_mesh_packet_metrics_to_time",
        "mesh_packet_metrics",
        ["to_node_num", sa.text("time DESC")],
    )
    op.create_index(
        "ix_mesh_packet_metrics_gateway_time",
        "mesh_packet_metrics",
        ["reporting_gateway_node_num", sa.text("time DESC")],
    )
    op.execute(
        "SELECT create_hypertable('mesh_packet_metrics', by_range('time'), if_not_exists => TRUE)"
    )
    op.execute(
        "SELECT add_retention_policy('mesh_packet_metrics', "
        "drop_after => INTERVAL '90 days', if_not_exists => TRUE)"
    )
    op.execute("GRANT INSERT, UPDATE ON mesh_packet_metrics TO azmsh_ingest")
    op.execute("GRANT SELECT ON mesh_packet_metrics TO azmsh_api")
    op.execute("GRANT SELECT ON mesh_packet_metrics TO azmsh_jobs")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO azmsh_ingest")


def downgrade() -> None:
    """Drop the mesh packet routing statistics hypertable."""
    op.drop_table("mesh_packet_metrics")
