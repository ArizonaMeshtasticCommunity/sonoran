"""Telemetry packet storage."""

from datetime import UTC, datetime, timedelta
from typing import Any

from google.protobuf.message import Message
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import AirQualityMetrics, DeviceMetrics, EnvironmentMetrics, PowerMetrics
from sonoran.ingest.handlers.clocks import device_time
from sonoran.ingest.handlers.context import HandlerContext


def _time(telemetry: Any, context: HandlerContext) -> datetime:
    """Use the telemetry timestamp when it is possible.

    A device that claims a time ahead of when we heard it is refused
    and the receipt time is used, because it names a moment that had
    not happened. See `clocks.device_time`.
    """
    if not telemetry.time:
        return context.seen_at
    return device_time(
        datetime.fromtimestamp(telemetry.time, UTC),
        context.seen_at,
        timedelta(seconds=context.mesh_future_slack_seconds),
        kind="telemetry",
        node_num=context.from_node_num,
    )


def _reported(value: Any, **columns: str) -> dict[str, Any]:
    """Return only the fields the node actually sent (#190).

    Meshtastic marks its telemetry fields `optional`, so the protobuf
    tracks presence per field. Reading an absent one gives the type's
    default, and this handler used to copy that default straight into
    the database:

        barometric_pressure=value.barometric_pressure

    A node with a temperature-and-humidity sensor and nothing else was
    therefore stored as reporting a barometric pressure of 0 hPa, which
    is not a low reading -- it is not a pressure at all. The Weather
    panel drew it, the device panel read a missing battery as 0 %, and
    `node_page` averaged the false zeros into everyone else's numbers.

    Measured on the live database over seven days before this fix:
    2,642 of 5,811 environment rows (45%) held a pressure of exactly
    zero, and **not one row in either table held NULL**. That second
    number is the proof: with per-field presence working, some node
    somewhere would have to be missing something.

    `columns` maps a database column to its protobuf field, because two
    of them differ (`rainfall` is `rainfall_1h`).

    `HasField` raises for a field with no presence to ask about -- a
    repeated one, such as `one_wire_temperature` in the vendored
    schema, where empty already *is* the absent state. Those keep their
    value. None of them are stored today; the branch is here so that
    adding one cannot take the ingest down with a ValueError.
    """
    stored: dict[str, Any] = {}
    for column, field in columns.items():
        try:
            present = value.HasField(field)
        except ValueError:
            present = True
        stored[column] = getattr(value, field) if present else None
    return stored


async def store_telemetry(session: AsyncSession, message: Message, context: HandlerContext) -> None:
    """Store each telemetry variant in its matching metric table."""
    telemetry: Any = message
    time = _time(telemetry, context)
    shared = {
        "node_num": context.from_node_num,
        "packet_pk": context.packet_pk,
        "packet_id": context.packet_id,
        "time": time,
    }
    if telemetry.HasField("device_metrics"):
        value = telemetry.device_metrics
        session.add(
            DeviceMetrics(
                **shared,
                **_reported(
                    value,
                    battery_level="battery_level",
                    voltage="voltage",
                    channel_utilization="channel_utilization",
                    air_util_tx="air_util_tx",
                    uptime_seconds="uptime_seconds",
                ),
            )
        )
    if telemetry.HasField("environment_metrics"):
        value = telemetry.environment_metrics
        session.add(
            EnvironmentMetrics(
                **shared,
                **_reported(
                    value,
                    temperature="temperature",
                    relative_humidity="relative_humidity",
                    barometric_pressure="barometric_pressure",
                    gas_resistance="gas_resistance",
                    iaq="iaq",
                    lux="lux",
                    uv_lux="uv_lux",
                    wind_direction="wind_direction",
                    wind_speed="wind_speed",
                    # The column is `rainfall`; the field is `rainfall_1h`.
                    rainfall="rainfall_1h",
                ),
            )
        )
    if telemetry.HasField("air_quality_metrics"):
        value = telemetry.air_quality_metrics
        session.add(
            AirQualityMetrics(
                **shared,
                **_reported(
                    value,
                    pm10_standard="pm10_standard",
                    pm25_standard="pm25_standard",
                    pm100_standard="pm100_standard",
                    pm10_environmental="pm10_environmental",
                    pm25_environmental="pm25_environmental",
                    pm100_environmental="pm100_environmental",
                ),
            )
        )
    if telemetry.HasField("power_metrics"):
        value = telemetry.power_metrics
        session.add(
            PowerMetrics(
                **shared,
                **_reported(
                    value,
                    ch1_voltage="ch1_voltage",
                    ch1_current="ch1_current",
                    ch2_voltage="ch2_voltage",
                    ch2_current="ch2_current",
                    ch3_voltage="ch3_voltage",
                    ch3_current="ch3_current",
                ),
            )
        )
