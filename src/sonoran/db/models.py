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
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# The modem preset columns (#313) are `deferred=True`: a SELECT of a whole
# row does not name them, so every query written before them runs the
# same SQL as before. A reader that wants one names the column. See
# `tests/unit/test_preset_param_legacy.py` and `ingest/presets.py`.


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
    # How many bits of precision the last position carried. NULL means
    # the node did not say, which is the common case for a node heard
    # over the radio and means full precision. See
    # `sonoran/positions.py`.
    last_position_precision_bits: Mapped[int | None] = mapped_column(Integer)
    position_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heard: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_mqtt_gateway: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_mqtt_topic: Mapped[str | None] = mapped_column(Text)
    last_channel: Mapped[str | None] = mapped_column(Text)
    # The modem preset of the newest packet from this node whose preset
    # is known, and that packet's receive time. NULL until ingest has
    # tagged one (#313). This is what keeps a quiet node on its mesh
    # when its last packet was on a topic channel such as `azmsh`.
    last_preset: Mapped[str | None] = mapped_column(Text, deferred=True)
    last_preset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), deferred=True)
    # The modem preset this node uploads on as an MQTT gateway: the one
    # its newest preset-named topic named. Ingest reads it back at start.
    uplink_preset: Mapped[str | None] = mapped_column(Text, deferred=True)
    uplink_preset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), deferred=True
    )
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
    # Why the payload could or could not be read: one of
    # `sonoran.decode.payload_state.PayloadState`, or NULL for a row
    # written before this was recorded. NULL is not a fourth state --
    # see that module, and do not fold it into the commonest value.
    payload_state: Mapped[str | None] = mapped_column(Text)
    # The modem preset that carried the packet: the majority of its
    # observations' presets (#313). NULL on rows written before that,
    # and on a packet no gateway with a known preset uploaded.
    modem_preset: Mapped[str | None] = mapped_column(Text, deferred=True)

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


# What the node page reads from a sighting, carried in both time
# indexes of `packet_seen` so it never visits the heap (#304).
SIGHTING_INCLUDE = [
    "from_node_num",
    "packet_id",
    "gateway_node_num",
    "rx_snr",
    "rx_rssi",
    "hop_limit",
    "hop_start",
]


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
    # The same header's hop start, so "direct" needs no join (#304).
    # NULL on rows written before revision 0017. See `api/sightings.py`.
    hop_start: Mapped[int | None] = mapped_column(Integer)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The modem preset of this one upload (#313): the topic's own preset
    # when the topic is preset-named, else the gateway's current preset,
    # else NULL. See `ingest/presets.py`.
    modem_preset: Mapped[str | None] = mapped_column(Text, deferred=True)

    __table_args__ = (
        PrimaryKeyConstraint("id", "seen_at"),
        UniqueConstraint(
            "from_node_num",
            "packet_id",
            "gateway_node_num",
            "seen_at",
            name="uq_packet_seen_observation",
        ),
        # Covering (#304): a node's sightings are scattered over the
        # whole heap, and reading them there took 5 s on a busy gateway.
        # The INCLUDE columns let the node page read the index alone.
        # See revision 0017 and `api/sightings.py`.
        Index(
            "ix_packet_seen_from_time",
            "from_node_num",
            seen_at.desc(),
            postgresql_include=SIGHTING_INCLUDE,
        ),
        Index(
            "ix_packet_seen_gateway_time",
            "gateway_node_num",
            seen_at.desc(),
            postgresql_include=SIGHTING_INCLUDE,
        ),
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
    location_source: Mapped[str | None] = mapped_column(Text)
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


# --- The RF map (docs/design/rf-map.md) --------------------------------
#
# What the community's own receivers hear beyond Meshtastic: aircraft
# first. Written by `sonoran-rf-ingest` from the messages `rf-agent`
# publishes, and read by `/api/rf`.


class RfStation(Base):
    """One row per receiving station, from its heartbeat."""

    __tablename__ = "rf_station"

    station_id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Rounded by the agent before it was sent. `precision_m` says by how much.
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    precision_m: Mapped[int | None] = mapped_column(Integer)
    kinds: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    agent_version: Mapped[str | None] = mapped_column(Text)
    # The counts since the heartbeat before this one. A thinned picture
    # must say it is thinned (design 4.2).
    heard: Mapped[int | None] = mapped_column(Integer)
    sent: Mapped[int | None] = mapped_column(Integer)
    dropped: Mapped[int | None] = mapped_column(Integer)
    # The newest heartbeat of any source. None for a location that is in
    # the registry and has sent no heartbeat yet.
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # From the registry (#305). None when the location is not in it.
    display_name: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    # The sources that hold a broker login now.
    registered_sources: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    registry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RfSource(Base):
    """One row per source of a location, from that source's heartbeat (#305).

    A source is one Pi or decoder with its own broker login. An agent
    that sends no source is stored as `NO_SOURCE`.
    """

    __tablename__ = "rf_source"

    station_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    kinds: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    agent_version: Mapped[str | None] = mapped_column(Text)
    heard: Mapped[int | None] = mapped_column(Integer)
    sent: Mapped[int | None] = mapped_column(Integer)
    dropped: Mapped[int | None] = mapped_column(Integer)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # What the source's sweepers run, as its heartbeat reports it (#324).
    # A claim, shown as one. None when the agent reports nothing.
    sweeps: Mapped[list | None] = mapped_column(JSONB)


class RfSpectrumHour(Base):
    """One hour of one swept range from one station, rolled up from its minutes.

    Built by the jobs process (`jobs/rf_rollup.py`) with the same per-bin
    rules as a waterfall row (`rf/spectrum_sql.py`), so the 3 and 7 day
    windows read a few hundred rows instead of every minute. One row per
    station, source, hour and range (#324).
    """

    __tablename__ = "rf_spectrum_hour"

    station_id: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    # The start of the hour.
    t: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    f_start_hz: Mapped[int] = mapped_column(BigInteger)
    bin_hz: Mapped[int] = mapped_column(Integer)
    bins: Mapped[int] = mapped_column(Integer)
    gain_db: Mapped[float] = mapped_column(REAL)
    # How many minutes the hour holds. Fewer than 60 is a gap in the data.
    minutes: Mapped[int] = mapped_column(Integer)
    p50: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    p95: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    busy: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    # The loudest single moment of each bin in the hour, and the minute
    # of the hour (0 to 59) it happened in, so a short transmission can
    # be found again at full resolution.
    peak: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    peak_min: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("station_id", "source", "t", "f_start_hz", "bin_hz", "bins"),
    )


class RfTrack(Base):
    """One point per thing heard, per time bucket, across every station.

    Two stations that hear the same aircraft make one point, not two:
    the identity is (`kind`, `thing_id`, `bucket`), the way (`from_node_num`,
    `packet_id`) is for Meshtastic. The point kept is the first one
    received, unless a station of a higher trust level sends one. The
    level a station reports is never what decides (#324). Which stations
    heard it lives in `rf_heard`.
    """

    __tablename__ = "rf_track"

    kind: Mapped[str] = mapped_column(Text)
    thing_id: Mapped[str] = mapped_column(Text)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    t: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    alt_m: Mapped[float | None] = mapped_column(REAL)
    alt_ref: Mapped[str | None] = mapped_column(Text)
    gs_kn: Mapped[float | None] = mapped_column(REAL)
    track_deg: Mapped[float | None] = mapped_column(REAL)
    rssi_db: Mapped[float | None] = mapped_column(REAL)
    station_id: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB)
    # Which login sent the point kept, its trust when it was kept, and
    # when Sonoran received it (#324). See `rf/store.py`.
    source: Mapped[str | None] = mapped_column(Text)
    trust: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("kind", "thing_id", "bucket"),
        Index("ix_rf_track_bucket", bucket.desc()),
    )


class RfHeard(Base):
    """Per station, per thing, per five minutes: how well it was heard.

    The receiver layer is drawn from this: where a station has actually
    heard aircraft, measured and not modelled.
    """

    __tablename__ = "rf_heard"

    station_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    thing_id: Mapped[str] = mapped_column(Text)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heard: Mapped[int] = mapped_column(Integer)
    best_rssi_db: Mapped[float | None] = mapped_column(REAL)
    # Where the thing was when this station heard it loudest.
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)

    __table_args__ = (
        PrimaryKeyConstraint("station_id", "kind", "thing_id", "bucket"),
        Index("ix_rf_heard_station_bucket", "station_id", bucket.desc()),
    )


class RfLatest(Base):
    """The newest point of each thing heard. Updated in place.

    "Newest" is by a time no later than when Sonoran received the point,
    so a station whose clock runs ahead cannot hold it (#324).
    """

    __tablename__ = "rf_latest"

    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    thing_id: Mapped[str] = mapped_column(Text, primary_key=True)
    t: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    alt_m: Mapped[float | None] = mapped_column(REAL)
    alt_ref: Mapped[str | None] = mapped_column(Text)
    gs_kn: Mapped[float | None] = mapped_column(REAL)
    track_deg: Mapped[float | None] = mapped_column(REAL)
    rssi_db: Mapped[float | None] = mapped_column(REAL)
    station_id: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[str | None] = mapped_column(Text)
    trust: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RfSpectrum(Base):
    """One minute of one swept range from one station.

    A range is (`source`, `f_start_hz`, `bin_hz`, `bins`). A station may
    send several in the same minute: two dongles, or one taking turns
    (#324). `name` is the station's own label for the range, if any.

    Bin `i` covers `f_start_hz + i * bin_hz`. Levels are tenths of a dB
    relative to the dongle's full scale: they compare one station with
    itself over time and never two stations (design 3.5). `busy` is the
    share of sweeps, in percent, in which a bin stood more than 6 dB above
    its own median. A bin no sweep reached is NULL, never a made-up level.
    """

    __tablename__ = "rf_spectrum"

    station_id: Mapped[str] = mapped_column(Text)
    # `NO_SOURCE` for an agent that sends none.
    source: Mapped[str] = mapped_column(Text, server_default="-")
    # The start of the minute summarised.
    t: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    f_start_hz: Mapped[int] = mapped_column(BigInteger)
    bin_hz: Mapped[int] = mapped_column(Integer)
    bins: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(Text)
    sweeps: Mapped[int] = mapped_column(Integer)
    gain_db: Mapped[float] = mapped_column(REAL)
    p50: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    p95: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    peak: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    busy: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("station_id", "source", "f_start_hz", "bin_hz", "bins", "t"),
        Index("ix_rf_spectrum_station_t", "station_id", t.desc()),
    )


class RfCustom(Base):
    """One point from a member's own mod (#324, section 6).

    Kept per station and never merged across stations: a mod's data is
    its station's claim, and no shared layer takes it. `thing_id` is the
    mod's own id. `placement` says where it may be drawn: `reported` (its
    own position, unverified), `heard_here` (the station's rounded
    position), or `none` (the table only).
    """

    __tablename__ = "rf_custom"

    station_id: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    mod: Mapped[str] = mapped_column(Text)
    thing_id: Mapped[str] = mapped_column(Text)
    # The mod's own time, after the clock guard (design 5.3).
    t: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The time the mod sent, as it sent it, so a wrong clock shows.
    sent_t: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    placement: Mapped[str] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    meta: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        PrimaryKeyConstraint("station_id", "mod", "thing_id", "t"),
        Index("ix_rf_custom_station_t", "station_id", t.desc()),
    )


class RfTrust(Base):
    """An operator's trust level for a station or one of its sources (#324).

    Set with `sonoran-rf-trust`, never by a message. A station with no
    row is `new`. `source` is `*` for every source of the station.
    """

    __tablename__ = "rf_trust"

    station_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    trust: Mapped[int] = mapped_column(SmallInteger)
    note: Mapped[str | None] = mapped_column(Text)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RfHiddenMod(Base):
    """A member's mod an operator has hidden from every viewer (#324)."""

    __tablename__ = "rf_hidden_mod"

    station_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mod: Mapped[str] = mapped_column(Text, primary_key=True)
    note: Mapped[str | None] = mapped_column(Text)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RfOperatorLog(Base):
    """Every change an operator makes to a station: trust, hiding, purging.

    Written by the operator commands, as the database owner. No
    application role can read or change it.
    """

    __tablename__ = "rf_operator_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    station_id: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)


# --- What the background jobs computed (#351) --------------------------
#
# The gaps job, the siting half and the calibration fit used to write
# JSON files beside the coverage tiles. They now write these tables.
# `azmsh_jobs` replaces a whole run in one transaction (DELETE, then
# INSERT), so a reader never sees half of one. `azmsh_api` only reads.
#
# None of these is a hypertable. Each holds the latest run only, so its
# size is about nodes x windows x presets and does not grow with time.
#
# A gaps run is keyed by its preset, its scope and the window the page
# asked for. `scope` is `assessment` for the full per node assessment
# (`asked_hours` 0, because its window is `GAPS_WINDOW_HOURS`), or
# `board` for the leaderboard counts of one more Statistics window
# (`asked_hours` 24 or 720, see `gaps/boards.py`).

GAPS_SCOPE_ASSESSMENT = "assessment"
GAPS_SCOPE_BOARD = "board"


class GapsIndex(Base):
    """When the gaps job last ran. One row, or none before the first run."""

    __tablename__ = "gaps_index"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_hours: Mapped[int] = mapped_column(Integer)

    __table_args__ = (CheckConstraint("id = 1", name="ck_gaps_index_one_row"),)


class GapsRun(Base):
    """One assessment, or one window of leaderboard counts, of one preset.

    `summary` holds every top-level field of the old JSON document except
    the node rows and the traceroute counts, which have their own tables.
    """

    __tablename__ = "gaps_run"

    preset: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    asked_hours: Mapped[int] = mapped_column(Integer, primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_hours: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("scope IN ('assessment', 'board')", name="ck_gaps_run_scope"),
    )


class GapsNode(Base):
    """One node of one gaps run.

    The name, the short name and the role are not stored. A reader joins
    `node` for them, so a renamed node reads with its new name at once.
    `rank` is the order the job set (worst first), so no reader holds a
    copy of the ranking rule. A board row fills the counts only.
    """

    __tablename__ = "gaps_node"

    preset: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    asked_hours: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_num: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)
    packets: Mapped[int | None] = mapped_column(Integer)
    rf_packets: Mapped[int | None] = mapped_column(Integer)
    ambiguous_packets: Mapped[int | None] = mapped_column(Integer)
    active_hours: Mapped[int | None] = mapped_column(Integer)
    rf_hours: Mapped[int | None] = mapped_column(Integer)
    direct_gateways: Mapped[int | None] = mapped_column(Integer)
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    position_confidence: Mapped[str | None] = mapped_column(Text)
    position_deviation_m: Mapped[float | None] = mapped_column(Double)
    position_spread_km: Mapped[float | None] = mapped_column(Double)
    is_mqtt_gateway: Mapped[bool | None] = mapped_column(Boolean)
    mobile: Mapped[bool | None] = mapped_column(Boolean)
    worst_state: Mapped[str | None] = mapped_column(Text)
    bad_count: Mapped[int | None] = mapped_column(Integer)
    unknown_count: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["preset", "scope", "asked_hours"],
            ["gaps_run.preset", "gaps_run.scope", "gaps_run.asked_hours"],
            ondelete="CASCADE",
        ),
        # The job leaves out a row whose node has no record yet, so this
        # key can never fail a run. See `gaps/store.py`.
        ForeignKeyConstraint(["node_num"], ["node.node_num"]),
        Index("ix_gaps_node_rank", "preset", "scope", "asked_hours", "rank"),
        Index("ix_gaps_node_worst", "preset", "scope", "asked_hours", "worst_state"),
    )


class GapsSignal(Base):
    """One signal of one node in one gaps assessment (`gaps/signals.py`).

    `evidence` stays `jsonb`: its shape is the signal's own, and the page
    reads it whole. Everything a reader filters on is a column. The
    sentence is not stored; it is made from the reason when it is read,
    so a change of wording reaches every run at once.
    """

    __tablename__ = "gaps_signal"

    preset: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    asked_hours: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_num: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger)
    state: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Double)
    unit: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)

    __table_args__ = (
        ForeignKeyConstraint(
            ["preset", "scope", "asked_hours", "node_num"],
            ["gaps_node.preset", "gaps_node.scope", "gaps_node.asked_hours", "gaps_node.node_num"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_gaps_signal_state",
            "preset",
            "scope",
            "asked_hours",
            "signal",
            "state",
            "node_num",
        ),
    )


class GapsTraceAnswer(Base):
    """How often one node was traced in one gaps run, and answered (#293)."""

    __tablename__ = "gaps_trace_answer"

    preset: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    asked_hours: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_num: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer)
    answered: Mapped[int] = mapped_column(Integer)
    senders: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["preset", "scope", "asked_hours"],
            ["gaps_run.preset", "gaps_run.scope", "gaps_run.asked_hours"],
            ondelete="CASCADE",
        ),
    )


class GapsSiting(Base):
    """One preset's siting answer, without its areas and candidates.

    `summary` holds the cost, the thresholds, the coverage it used and
    the caveats, as the old JSON document did.
    """

    __tablename__ = "gaps_siting"

    preset: Mapped[str] = mapped_column(Text, primary_key=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSONB)


class GapsSitingArea(Base):
    """One neighbourhood of struggling nodes (`gaps/siting.py`)."""

    __tablename__ = "gaps_siting_area"

    preset: Mapped[str] = mapped_column(Text, primary_key=True)
    area: Mapped[int] = mapped_column(Integer, primary_key=True)
    point_count: Mapped[int] = mapped_column(Integer)
    node_count: Mapped[int] = mapped_column(Integer)
    node_nums: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    centroid_lat: Mapped[float] = mapped_column(Double)
    centroid_lon: Mapped[float] = mapped_column(Double)
    south: Mapped[float] = mapped_column(Double)
    west: Mapped[float] = mapped_column(Double)
    north: Mapped[float] = mapped_column(Double)
    east: Mapped[float] = mapped_column(Double)
    width_km: Mapped[float] = mapped_column(Double)

    __table_args__ = (ForeignKeyConstraint(["preset"], ["gaps_siting.preset"], ondelete="CASCADE"),)


class GapsSitingPoint(Base):
    """One demand point of an area: the place a group of nodes stands."""

    __tablename__ = "gaps_siting_point"

    preset: Mapped[str] = mapped_column(Text, primary_key=True)
    area: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    node_count: Mapped[int] = mapped_column(Integer)
    node_nums: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    names: Mapped[list[str]] = mapped_column(ARRAY(Text))

    __table_args__ = (
        ForeignKeyConstraint(
            ["preset", "area"],
            ["gaps_siting_area.preset", "gaps_siting_area.area"],
            ondelete="CASCADE",
        ),
    )


class GapsSitingCandidate(Base):
    """One place a node could go, in the order the siting job ranked it.

    The fields are those of `gaps.siting.Candidate`. The sentence is made
    from the reason when it is read, and the name of an existing node is
    joined live from `node`.
    """

    __tablename__ = "gaps_siting_candidate"

    preset: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    area: Mapped[int] = mapped_column(Integer)
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    elevation_m: Mapped[int | None] = mapped_column(Integer)
    prominence_m: Mapped[int | None] = mapped_column(Integer)
    node_num: Mapped[int | None] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    screen_score: Mapped[int] = mapped_column(Integer)
    screen_unknown: Mapped[int] = mapped_column(Integer)
    newly_usable: Mapped[int | None] = mapped_column(Integer)
    newly_usable_nodes: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    already_usable: Mapped[int] = mapped_column(Integer)
    baseline_unknown: Mapped[int] = mapped_column(Integer)
    run_stamp: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        ForeignKeyConstraint(["preset"], ["gaps_siting.preset"], ondelete="CASCADE"),
        Index("ix_gaps_siting_candidate_area", "preset", "area", "position"),
    )


class CoverageCalibration(Base):
    """The calibration fit as a whole. One row, or none.

    No row means no fit: a new box, or a window with no neighbour
    reports. The prediction then uses the nameplate figures.
    """

    __tablename__ = "coverage_calibration"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_bias_db: Mapped[float] = mapped_column(Double)
    residual_spread_db: Mapped[float] = mapped_column(Double)
    rounds: Mapped[int] = mapped_column(Integer)
    summary: Mapped[dict] = mapped_column(JSONB)

    __table_args__ = (CheckConstraint("id = 1", name="ck_coverage_calibration_one_row"),)


class CoverageCalibrationNode(Base):
    """What the measurements say about one node. See `coverage/calibrate.py`."""

    __tablename__ = "coverage_calibration_node"

    node_num: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    offset_db: Mapped[float] = mapped_column(Double)
    observations: Mapped[int] = mapped_column(Integer)
    counterparties: Mapped[int] = mapped_column(Integer)
    censored: Mapped[int] = mapped_column(Integer)
    reported: Mapped[int] = mapped_column(Integer)
    residual_spread_db: Mapped[float] = mapped_column(Double)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


# The ingest role has INSERT and UPDATE rights only. Disable PostgreSQL
# implicit RETURNING so ORM inserts do not require SELECT rights.
for _table in Base.metadata.tables.values():
    _table.implicit_returning = False
