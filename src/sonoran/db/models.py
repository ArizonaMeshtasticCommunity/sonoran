"""SQLAlchemy models for Sonoran.

The full schema description lives in docs/DATABASE.md.

TimescaleDB rules shape this file:

- Every unique constraint on a hypertable includes the partition column.
- There are no foreign key constraints between hypertables.
  The application keeps referential integrity.

Packet identity comes from the protocol, not from the database. Every
child table stores the Meshtastic `packet_id` beside the node it came
from. That pair joins to `packet` and to `packet_seen`.

The older `packet_pk` column pointed at the generated `packet.id`.
Ingest can never fill it, because the role has no SELECT right and so
cannot read a generated key back. It is NULL everywhere. Use
`packet_id` instead.
"""

from datetime import date, datetime

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""


class Node(Base):
    """One row per node. Latest known state."""

    __tablename__ = "node"

    node_num: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    node_id: Mapped[str] = mapped_column(Text)
    long_name: Mapped[str | None] = mapped_column(Text)
    short_name: Mapped[str | None] = mapped_column(Text)
    hw_model: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    is_licensed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    last_lat: Mapped[float | None] = mapped_column(Double)
    last_lon: Mapped[float | None] = mapped_column(Double)
    last_altitude: Mapped[int | None] = mapped_column(Integer)
    position_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heard: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_mqtt_gateway: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_mqtt_topic: Mapped[str | None] = mapped_column(Text)
    last_channel: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_node_short_name", "short_name"),)


class PacketKey(Base):
    """The deduplication key of a packet. One row per unique packet.

    This is a plain table, not a hypertable, so the primary key holds
    the true packet key with no time column. The `packet` hypertable
    cannot do that: TimescaleDB requires the partition column in every
    unique constraint, and each gateway stamps its own `rx_time`.

    Ingest inserts here with ON CONFLICT DO NOTHING. The affected row
    count says whether the packet is new, so ingest needs no SELECT.
    """

    __tablename__ = "packet_key"

    from_node_num: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    packet_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Packet(Base):
    """One row per unique packet. Hypertable on first_seen_at."""

    __tablename__ = "packet"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    from_node_num: Mapped[int] = mapped_column(BigInteger)
    packet_id: Mapped[int] = mapped_column(BigInteger)
    to_node_num: Mapped[int | None] = mapped_column(BigInteger)
    portnum: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str | None] = mapped_column(Text)
    hop_start: Mapped[int | None] = mapped_column(Integer)
    hop_limit: Mapped[int | None] = mapped_column(Integer)
    want_ack: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    priority: Mapped[int | None] = mapped_column(Integer)
    rx_time: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    payload_json: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        PrimaryKeyConstraint("id", "first_seen_at"),
        UniqueConstraint(
            "from_node_num",
            "packet_id",
            "first_seen_at",
            name="uq_packet_dedup",
        ),
        Index("ix_packet_from_time", "from_node_num", first_seen_at.desc()),
    )


class PacketSeen(Base):
    """One row per observation of a packet. Hypertable on seen_at."""

    __tablename__ = "packet_seen"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    from_node_num: Mapped[int] = mapped_column(BigInteger)
    packet_id: Mapped[int] = mapped_column(BigInteger)
    gateway_node_num: Mapped[int] = mapped_column(BigInteger)
    mqtt_topic: Mapped[str] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    rx_rssi: Mapped[int | None] = mapped_column(Integer)
    rx_snr: Mapped[float | None] = mapped_column(Double)
    hop_limit: Mapped[int | None] = mapped_column(Integer)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "seen_at"),
        UniqueConstraint(
            "from_node_num",
            "packet_id",
            "gateway_node_num",
            "seen_at",
            name="uq_packet_seen_observation",
        ),
        Index("ix_packet_seen_from_time", "from_node_num", seen_at.desc()),
        Index("ix_packet_seen_gateway_time", "gateway_node_num", seen_at.desc()),
        # The API joins observations to packets by the deduplication key.
        Index("ix_packet_seen_natural_key", "from_node_num", "packet_id", seen_at.desc()),
    )


class Traceroute(Base):
    """Parsed traceroute data. Hypertable on seen_at."""

    __tablename__ = "traceroute"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    # The request this reply answers. mesh-graph keys a trace on it.
    request_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    from_node_num: Mapped[int] = mapped_column(BigInteger)
    to_node_num: Mapped[int] = mapped_column(BigInteger)
    channel: Mapped[str | None] = mapped_column(Text)
    route: Mapped[list | None] = mapped_column(JSONB)
    route_back: Mapped[list | None] = mapped_column(JSONB)
    snr_towards: Mapped[list | None] = mapped_column(JSONB)
    snr_back: Mapped[list | None] = mapped_column(JSONB)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "seen_at"),
        Index("ix_traceroute_from_time", "from_node_num", seen_at.desc()),
        Index("ix_traceroute_to_time", "to_node_num", seen_at.desc()),
        Index("ix_traceroute_channel_time", "channel", seen_at.desc()),
        Index("ix_traceroute_packet", "from_node_num", "packet_id"),
    )


class TextMessage(Base):
    """Decrypted text bodies. Hypertable on seen_at."""

    __tablename__ = "text_message"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    from_node_num: Mapped[int] = mapped_column(BigInteger)
    to_node_num: Mapped[int] = mapped_column(BigInteger)
    channel: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    reply_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    emoji: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "seen_at"),
        Index("ix_text_message_channel_time", "channel", seen_at.desc()),
        Index("ix_text_message_packet", "from_node_num", "packet_id"),
    )


class DeviceMetrics(Base):
    """Device telemetry. Hypertable on time."""

    __tablename__ = "device_metrics"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    node_num: Mapped[int] = mapped_column(BigInteger)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    battery_level: Mapped[float | None] = mapped_column(REAL)
    voltage: Mapped[float | None] = mapped_column(REAL)
    channel_utilization: Mapped[float | None] = mapped_column(REAL)
    air_util_tx: Mapped[float | None] = mapped_column(REAL)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "time"),
        Index("ix_device_metrics_node_time", "node_num", time.desc()),
        Index("ix_device_metrics_packet", "node_num", "packet_id"),
    )


class EnvironmentMetrics(Base):
    """Environment telemetry. Hypertable on time."""

    __tablename__ = "environment_metrics"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    node_num: Mapped[int] = mapped_column(BigInteger)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    temperature: Mapped[float | None] = mapped_column(REAL)
    relative_humidity: Mapped[float | None] = mapped_column(REAL)
    barometric_pressure: Mapped[float | None] = mapped_column(REAL)
    gas_resistance: Mapped[float | None] = mapped_column(REAL)
    iaq: Mapped[int | None] = mapped_column(Integer)
    lux: Mapped[float | None] = mapped_column(REAL)
    uv_lux: Mapped[float | None] = mapped_column(REAL)
    wind_direction: Mapped[int | None] = mapped_column(Integer)
    wind_speed: Mapped[float | None] = mapped_column(REAL)
    rainfall: Mapped[float | None] = mapped_column(REAL)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "time"),
        Index("ix_environment_metrics_node_time", "node_num", time.desc()),
        Index("ix_environment_metrics_packet", "node_num", "packet_id"),
    )


class AirQualityMetrics(Base):
    """Air quality telemetry. Hypertable on time."""

    __tablename__ = "air_quality_metrics"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    node_num: Mapped[int] = mapped_column(BigInteger)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    pm10_standard: Mapped[int | None] = mapped_column(Integer)
    pm25_standard: Mapped[int | None] = mapped_column(Integer)
    pm100_standard: Mapped[int | None] = mapped_column(Integer)
    pm10_environmental: Mapped[int | None] = mapped_column(Integer)
    pm25_environmental: Mapped[int | None] = mapped_column(Integer)
    pm100_environmental: Mapped[int | None] = mapped_column(Integer)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "time"),
        Index("ix_air_quality_metrics_node_time", "node_num", time.desc()),
        Index("ix_air_quality_metrics_packet", "node_num", "packet_id"),
    )


class PowerMetrics(Base):
    """Power telemetry. Hypertable on time."""

    __tablename__ = "power_metrics"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    node_num: Mapped[int] = mapped_column(BigInteger)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    ch1_voltage: Mapped[float | None] = mapped_column(REAL)
    ch1_current: Mapped[float | None] = mapped_column(REAL)
    ch2_voltage: Mapped[float | None] = mapped_column(REAL)
    ch2_current: Mapped[float | None] = mapped_column(REAL)
    ch3_voltage: Mapped[float | None] = mapped_column(REAL)
    ch3_current: Mapped[float | None] = mapped_column(REAL)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "time"),
        Index("ix_power_metrics_node_time", "node_num", time.desc()),
        Index("ix_power_metrics_packet", "node_num", "packet_id"),
    )


class PaxMetrics(Base):
    """Pax counter telemetry. Hypertable on time."""

    __tablename__ = "pax_metrics"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    node_num: Mapped[int] = mapped_column(BigInteger)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    wifi_count: Mapped[int | None] = mapped_column(Integer)
    ble_count: Mapped[int | None] = mapped_column(Integer)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "time"),
        Index("ix_pax_metrics_node_time", "node_num", time.desc()),
        Index("ix_pax_metrics_packet", "node_num", "packet_id"),
    )


class MeshPacketMetrics(Base):
    """Packet routing and network statistics. Hypertable on time."""

    __tablename__ = "mesh_packet_metrics"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    from_node_num: Mapped[int] = mapped_column(BigInteger)
    to_node_num: Mapped[int] = mapped_column(BigInteger)
    packet_id: Mapped[int] = mapped_column(BigInteger)
    reporting_gateway_node_num: Mapped[int | None] = mapped_column(BigInteger)
    via_mqtt: Mapped[bool | None] = mapped_column(Boolean)
    message_size_bytes: Mapped[int | None] = mapped_column(Integer)
    relay_node_num: Mapped[int | None] = mapped_column(BigInteger)
    next_hop_node_num: Mapped[int | None] = mapped_column(BigInteger)
    transport_mechanism: Mapped[str | None] = mapped_column(Text)
    pki_encrypted: Mapped[bool | None] = mapped_column(Boolean)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "time"),
        Index("ix_mesh_packet_metrics_from_time", "from_node_num", time.desc()),
        Index("ix_mesh_packet_metrics_to_time", "to_node_num", time.desc()),
        Index(
            "ix_mesh_packet_metrics_gateway_time",
            "reporting_gateway_node_num",
            time.desc(),
        ),
    )


class PositionMetrics(Base):
    """Position history. Hypertable on time."""

    __tablename__ = "position_metrics"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    node_num: Mapped[int] = mapped_column(BigInteger)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    altitude: Mapped[int | None] = mapped_column(Integer)
    ground_speed: Mapped[int | None] = mapped_column(Integer)
    ground_track: Mapped[int | None] = mapped_column(Integer)
    precision_bits: Mapped[int | None] = mapped_column(Integer)
    sats_in_view: Mapped[int | None] = mapped_column(Integer)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "time"),
        Index("ix_position_metrics_node_time", "node_num", time.desc()),
        Index("ix_position_metrics_packet", "node_num", "packet_id"),
    )


class NeighborMetrics(Base):
    """One row per neighbor link per report. Hypertable on time."""

    __tablename__ = "neighbor_metrics"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    node_num: Mapped[int] = mapped_column(BigInteger)
    packet_pk: Mapped[int | None] = mapped_column(BigInteger)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    neighbor_node_num: Mapped[int] = mapped_column(BigInteger)
    channel: Mapped[str | None] = mapped_column(Text)
    snr: Mapped[float | None] = mapped_column(REAL)
    last_rx_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    node_broadcast_interval_secs: Mapped[int | None] = mapped_column(Integer)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", "time"),
        Index("ix_neighbor_metrics_node_time", "node_num", time.desc()),
        Index("ix_neighbor_metrics_channel_time", "channel", time.desc()),
        Index("ix_neighbor_metrics_packet", "node_num", "packet_id"),
    )


class NodeConfig(Base):
    """Latest reported module configuration per node. Regular table."""

    __tablename__ = "node_config"

    node_num: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    config_type: Mapped[str] = mapped_column(Text, primary_key=True)
    config_json: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DailySnapshot(Base):
    """One row per day. Written by the jobs process."""

    __tablename__ = "daily_snapshot"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    node_count: Mapped[int | None] = mapped_column(Integer)
    packet_count: Mapped[int | None] = mapped_column(Integer)
    observation_count: Mapped[int | None] = mapped_column(Integer)
    gateway_count: Mapped[int | None] = mapped_column(Integer)
    text_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# The ingest role has INSERT and UPDATE rights only. Disable PostgreSQL
# implicit RETURNING so ORM inserts do not require SELECT rights.
for _table in Base.metadata.tables.values():
    _table.implicit_returning = False
