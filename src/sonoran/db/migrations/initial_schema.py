"""Frozen metadata for the initial database schema.

This module is used only by revision 0001.
It must not import the application models.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

node = sa.Table(
    "node",
    metadata,
    sa.Column("node_num", sa.BigInteger(), primary_key=True),
    sa.Column("node_id", sa.Text(), nullable=False),
    sa.Column("long_name", sa.Text()),
    sa.Column("short_name", sa.Text()),
    sa.Column("hw_model", sa.Text()),
    sa.Column("role", sa.Text()),
    sa.Column("is_licensed", sa.Boolean(), nullable=False),
    sa.Column("public_key", sa.LargeBinary()),
    sa.Column("last_lat", sa.Double()),
    sa.Column("last_lon", sa.Double()),
    sa.Column("last_altitude", sa.Integer()),
    sa.Column("position_time", sa.DateTime(timezone=True)),
    sa.Column("last_heard", sa.DateTime(timezone=True)),
    sa.Column("is_mqtt_gateway", sa.Boolean(), nullable=False),
    sa.Column("last_mqtt_topic", sa.Text()),
    sa.Column("last_channel", sa.Text()),
    sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index("ix_node_last_heard", node.c.last_heard)
sa.Index("ix_node_short_name", node.c.short_name)

packet = sa.Table(
    "packet",
    metadata,
    sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column("from_node_num", sa.BigInteger(), nullable=False),
    sa.Column("packet_id", sa.BigInteger(), nullable=False),
    sa.Column("to_node_num", sa.BigInteger()),
    sa.Column("portnum", sa.Integer(), nullable=False),
    sa.Column("channel", sa.Text()),
    sa.Column("hop_start", sa.Integer()),
    sa.Column("hop_limit", sa.Integer()),
    sa.Column("want_ack", sa.Boolean(), nullable=False),
    sa.Column("priority", sa.Integer()),
    sa.Column("rx_time", sa.Integer()),
    sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("raw_bytes", sa.LargeBinary()),
    sa.Column("payload_json", JSONB()),
    sa.PrimaryKeyConstraint("id", "first_seen_at"),
    sa.UniqueConstraint("from_node_num", "packet_id", "first_seen_at", name="uq_packet_dedup"),
)
sa.Index("ix_packet_from_time", packet.c.from_node_num, packet.c.first_seen_at.desc())

packet_seen = sa.Table(
    "packet_seen",
    metadata,
    sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column("packet_pk", sa.BigInteger()),
    sa.Column("from_node_num", sa.BigInteger(), nullable=False),
    sa.Column("packet_id", sa.BigInteger(), nullable=False),
    sa.Column("gateway_node_num", sa.BigInteger(), nullable=False),
    sa.Column("mqtt_topic", sa.Text(), nullable=False),
    sa.Column("channel", sa.Text()),
    sa.Column("rx_rssi", sa.Integer()),
    sa.Column("rx_snr", sa.Double()),
    sa.Column("hop_limit", sa.Integer()),
    sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("id", "seen_at"),
    sa.UniqueConstraint(
        "from_node_num",
        "packet_id",
        "gateway_node_num",
        "seen_at",
        name="uq_packet_seen_observation",
    ),
)
sa.Index("ix_packet_seen_from_time", packet_seen.c.from_node_num, packet_seen.c.seen_at.desc())
sa.Index(
    "ix_packet_seen_gateway_time",
    packet_seen.c.gateway_node_num,
    packet_seen.c.seen_at.desc(),
)

traceroute = sa.Table(
    "traceroute",
    metadata,
    sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column("packet_pk", sa.BigInteger()),
    sa.Column("from_node_num", sa.BigInteger(), nullable=False),
    sa.Column("to_node_num", sa.BigInteger(), nullable=False),
    sa.Column("route", JSONB()),
    sa.Column("route_back", JSONB()),
    sa.Column("snr_towards", JSONB()),
    sa.Column("snr_back", JSONB()),
    sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("id", "seen_at"),
)
sa.Index("ix_traceroute_from_time", traceroute.c.from_node_num, traceroute.c.seen_at.desc())
sa.Index("ix_traceroute_to_time", traceroute.c.to_node_num, traceroute.c.seen_at.desc())

text_message = sa.Table(
    "text_message",
    metadata,
    sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column("packet_pk", sa.BigInteger()),
    sa.Column("from_node_num", sa.BigInteger(), nullable=False),
    sa.Column("to_node_num", sa.BigInteger(), nullable=False),
    sa.Column("channel", sa.Text()),
    sa.Column("body", sa.Text(), nullable=False),
    sa.Column("reply_id", sa.BigInteger()),
    sa.Column("emoji", sa.Boolean(), nullable=False),
    sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("id", "seen_at"),
)
sa.Index("ix_text_message_reply_id", text_message.c.reply_id)
sa.Index("ix_text_message_channel_time", text_message.c.channel, text_message.c.seen_at.desc())


def metric_table(name: str, *columns: sa.Column) -> sa.Table:
    """Build one initial metric table."""
    table = sa.Table(
        name,
        metadata,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("node_num", sa.BigInteger(), nullable=False),
        sa.Column("packet_pk", sa.BigInteger()),
        *columns,
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "time"),
    )
    sa.Index(f"ix_{name}_node_time", table.c.node_num, table.c.time.desc())
    return table


metric_table(
    "device_metrics",
    sa.Column("battery_level", sa.REAL()),
    sa.Column("voltage", sa.REAL()),
    sa.Column("channel_utilization", sa.REAL()),
    sa.Column("air_util_tx", sa.REAL()),
    sa.Column("uptime_seconds", sa.BigInteger()),
)
metric_table(
    "environment_metrics",
    sa.Column("temperature", sa.REAL()),
    sa.Column("relative_humidity", sa.REAL()),
    sa.Column("barometric_pressure", sa.REAL()),
    sa.Column("gas_resistance", sa.REAL()),
    sa.Column("iaq", sa.Integer()),
    sa.Column("lux", sa.REAL()),
    sa.Column("uv_lux", sa.REAL()),
    sa.Column("wind_direction", sa.Integer()),
    sa.Column("wind_speed", sa.REAL()),
    sa.Column("rainfall", sa.REAL()),
)
metric_table(
    "air_quality_metrics",
    sa.Column("pm10_standard", sa.Integer()),
    sa.Column("pm25_standard", sa.Integer()),
    sa.Column("pm100_standard", sa.Integer()),
    sa.Column("pm10_environmental", sa.Integer()),
    sa.Column("pm25_environmental", sa.Integer()),
    sa.Column("pm100_environmental", sa.Integer()),
)
metric_table(
    "power_metrics",
    sa.Column("ch1_voltage", sa.REAL()),
    sa.Column("ch1_current", sa.REAL()),
    sa.Column("ch2_voltage", sa.REAL()),
    sa.Column("ch2_current", sa.REAL()),
    sa.Column("ch3_voltage", sa.REAL()),
    sa.Column("ch3_current", sa.REAL()),
)
metric_table(
    "pax_metrics",
    sa.Column("wifi_count", sa.Integer()),
    sa.Column("ble_count", sa.Integer()),
    sa.Column("uptime_seconds", sa.BigInteger()),
)
metric_table(
    "position_metrics",
    sa.Column("latitude", sa.Double()),
    sa.Column("longitude", sa.Double()),
    sa.Column("altitude", sa.Integer()),
    sa.Column("ground_speed", sa.Integer()),
    sa.Column("ground_track", sa.Integer()),
    sa.Column("precision_bits", sa.Integer()),
    sa.Column("sats_in_view", sa.Integer()),
)
metric_table(
    "neighbor_metrics",
    sa.Column("neighbor_node_num", sa.BigInteger(), nullable=False),
    sa.Column("snr", sa.REAL()),
    sa.Column("last_rx_time", sa.DateTime(timezone=True)),
    sa.Column("node_broadcast_interval_secs", sa.Integer()),
)

sa.Table(
    "node_config",
    metadata,
    sa.Column("node_num", sa.BigInteger(), primary_key=True),
    sa.Column("config_type", sa.Text(), primary_key=True),
    sa.Column("config_json", JSONB(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Table(
    "daily_snapshot",
    metadata,
    sa.Column("day", sa.Date(), primary_key=True),
    sa.Column("node_count", sa.Integer()),
    sa.Column("packet_count", sa.Integer()),
    sa.Column("observation_count", sa.Integer()),
    sa.Column("gateway_count", sa.Integer()),
    sa.Column("text_count", sa.Integer()),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
