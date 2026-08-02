"""Integration tests for packet-family storage handlers."""

import asyncio
import base64
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonoran.config import DEFAULT_CHANNEL_KEY
from sonoran.crypto.decrypt import decode_key
from sonoran.db.models import DeviceMetrics, NeighborMetrics, Node, PositionMetrics, Traceroute
from sonoran.ingest.pipeline import process_message
from sonoran.mqtt.client import RawMqttMessage
from sonoran.mqtt.topics import parse_topic

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"


def _message(filename: str) -> RawMqttMessage:
    """Load one recorded sonoran MQTT packet."""
    fixture = json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return RawMqttMessage(
        topic=parse_topic(fixture["topic"]),
        payload=base64.b64decode(fixture["payload_base64"]),
        received_at=datetime.fromisoformat(fixture["recorded_at"]),
    )


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("recorded_azmsh_nodeinfo.json", Node),
        ("recorded_azmsh_position.json", PositionMetrics),
        ("recorded_azmsh_telemetry.json", DeviceMetrics),
        ("recorded_azmsh_neighbor.json", NeighborMetrics),
        ("recorded_azmsh_traceroute.json", Traceroute),
    ],
)
def test_recorded_packet_stores_family_row(
    filename: str,
    model: type[Node | PositionMetrics | DeviceMetrics | NeighborMetrics | Traceroute],
    timescale_url: str,
    migrated_engine: object,
) -> None:
    """Each recorded packet writes a row in its matching family table."""
    asyncio.run(_store_and_count(filename, model, timescale_url))


async def _store_and_count(
    filename: str,
    model: type[Node | PositionMetrics | DeviceMetrics | NeighborMetrics | Traceroute],
    timescale_url: str,
) -> None:
    """Store a packet and confirm its handler wrote at least one row."""
    engine = create_async_engine(timescale_url.replace("+psycopg", "+asyncpg"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            stored = await process_message(
                session, _message(filename), [decode_key(DEFAULT_CHANNEL_KEY)]
            )
            await session.commit()
            assert stored is not None
        async with factory() as session:
            count = await session.scalar(select(func.count()).select_from(model))
        assert count and count > 0
    finally:
        await engine.dispose()
