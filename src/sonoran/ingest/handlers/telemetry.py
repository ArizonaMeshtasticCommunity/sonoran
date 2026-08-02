"""Telemetry packet storage."""

from datetime import UTC, datetime
from typing import Any

from google.protobuf.message import Message
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import AirQualityMetrics, DeviceMetrics, EnvironmentMetrics, PowerMetrics
from sonoran.ingest.handlers.context import HandlerContext


def _time(telemetry: Any, fallback: datetime) -> datetime:
    """Use the telemetry timestamp when available."""
    if telemetry.time:
        return datetime.fromtimestamp(telemetry.time, UTC)
    return fallback


async def store_telemetry(session: AsyncSession, message: Message, context: HandlerContext) -> None:
    """Store each telemetry variant in its matching metric table."""
    telemetry: Any = message
    time = _time(telemetry, context.seen_at)
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
                battery_level=value.battery_level,
                voltage=value.voltage,
                channel_utilization=value.channel_utilization,
                air_util_tx=value.air_util_tx,
                uptime_seconds=value.uptime_seconds,
            )
        )
    if telemetry.HasField("environment_metrics"):
        value = telemetry.environment_metrics
        session.add(
            EnvironmentMetrics(
                **shared,
                temperature=value.temperature,
                relative_humidity=value.relative_humidity,
                barometric_pressure=value.barometric_pressure,
                gas_resistance=value.gas_resistance,
                iaq=value.iaq,
                lux=value.lux,
                uv_lux=value.uv_lux,
                wind_direction=value.wind_direction,
                wind_speed=value.wind_speed,
                rainfall=value.rainfall_1h,
            )
        )
    if telemetry.HasField("air_quality_metrics"):
        value = telemetry.air_quality_metrics
        session.add(
            AirQualityMetrics(
                **shared,
                pm10_standard=value.pm10_standard,
                pm25_standard=value.pm25_standard,
                pm100_standard=value.pm100_standard,
                pm10_environmental=value.pm10_environmental,
                pm25_environmental=value.pm25_environmental,
                pm100_environmental=value.pm100_environmental,
            )
        )
    if telemetry.HasField("power_metrics"):
        value = telemetry.power_metrics
        session.add(
            PowerMetrics(
                **shared,
                ch1_voltage=value.ch1_voltage,
                ch1_current=value.ch1_current,
                ch2_voltage=value.ch2_voltage,
                ch2_current=value.ch2_current,
                ch3_voltage=value.ch3_voltage,
                ch3_current=value.ch3_current,
            )
        )
