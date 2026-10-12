"""Ingest tags each packet with its modem preset, as the ingest role (#313).

Every write here runs through `process_message` on a connection made as
`azmsh_ingest`. That role has no table-level SELECT on `packet` and no
right to `ON CONFLICT DO UPDATE` (AGENTS.md 9.1, 9.2), so a pass proves
that the tagging needs neither. The reads that check the result use the
owner connection, and the API checks use `azmsh_api`.

The traffic is built here rather than recorded: a recorded packet has
one gateway and one topic, and these tests need one packet uploaded by
several gateways on several presets.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.ingest.pipeline import process_message
from sonoran.ingest.preset_writes import load_gateway_presets, store_last_preset
from sonoran.ingest.presets import PresetTracker
from sonoran.meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2
from sonoran.mqtt.client import RawMqttMessage
from sonoran.mqtt.topics import parse_topic
from tests.integration.conftest import role_url

SENDER = 0x31300001
QUIET = 0x31300002
GW_LONG = 0x31300A01
GW_MED_1 = 0x31300B01
GW_MED_2 = 0x31300B02
GW_BOTH = 0x31300C01
NODES = (SENDER, QUIET, GW_LONG, GW_MED_1, GW_MED_2, GW_BOTH)
NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)


def _message(
    sender: int, packet_id: int, gateway: int, channel: str, at: datetime, body: str = "hi"
) -> RawMqttMessage:
    """One unencrypted text packet, as one gateway uploaded it."""
    data = mesh_pb2.Data()
    data.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    data.payload = body.encode()
    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", sender)
    packet.to = 0xFFFFFFFF
    packet.id = packet_id
    packet.hop_limit = 3
    packet.hop_start = 3
    packet.decoded.CopyFrom(data)
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.packet.CopyFrom(packet)
    envelope.channel_id = channel
    envelope.gateway_id = f"!{gateway:08x}"
    return RawMqttMessage(
        topic=parse_topic(f"msh/US/AZ/Phoenix/2/e/{channel}/!{gateway:08x}"),
        payload=envelope.SerializeToString(),
        received_at=at,
    )


def _clean(engine: Any) -> None:
    with engine.begin() as connection:
        for table in ("text_message", "packet_key", "packet_seen", "packet"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE from_node_num = ANY(:nodes)"),
                {"nodes": list(NODES)},
            )
        for table in ("mesh_packet_metrics",):
            connection.execute(
                text(f"DELETE FROM {table} WHERE from_node_num = ANY(:nodes)"),
                {"nodes": list(NODES)},
            )
        connection.execute(
            text("DELETE FROM node WHERE node_num = ANY(:nodes)"), {"nodes": list(NODES)}
        )


async def _ingest(url: str, tracker: PresetTracker, messages: list[RawMqttMessage]) -> None:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        for message in messages:
            # One transaction per message, as `pipeline.main` does.
            async with factory() as session:
                await process_message(
                    session, message, [], store_text_messages=True, presets=tracker
                )
                await session.commit()
    finally:
        await engine.dispose()


def _scalar(engine: Any, sql: str, **params: object) -> Any:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar()


def _tracker() -> PresetTracker:
    return PresetTracker(conflict_window=timedelta(minutes=60))


def _announce(gateway: int, channel: str, at: datetime, packet_id: int) -> RawMqttMessage:
    """A packet a gateway uploads on a preset-named topic, which names its preset."""
    return _message(QUIET, packet_id, gateway, channel, at)


@pytest.fixture
def ingest_url(timescale_url: str, migrated_engine: Any) -> str:
    _clean(migrated_engine)
    return role_url(timescale_url, "azmsh_ingest")


def test_a_packet_takes_the_majority_of_its_gateways(ingest_url: str, migrated_engine: Any) -> None:
    tracker = _tracker()
    messages = [
        _announce(GW_LONG, "LongFast", NOW, 1),
        _announce(GW_MED_1, "MediumFast", NOW + timedelta(seconds=1), 2),
        _announce(GW_MED_2, "MediumFast", NOW + timedelta(seconds=2), 3),
        # The packet under test, first through the LongFast gateway.
        _message(SENDER, 100, GW_LONG, "azmsh", NOW + timedelta(seconds=10)),
    ]
    asyncio.run(_ingest(ingest_url, tracker, messages))

    def packet_preset() -> Any:
        return _scalar(
            migrated_engine,
            "SELECT modem_preset FROM packet WHERE from_node_num = :s AND packet_id = 100",
            s=SENDER,
        )

    assert packet_preset() == "LongFast", "the first vote is written with the packet"
    assert (
        _scalar(migrated_engine, "SELECT last_preset FROM node WHERE node_num = :s", s=SENDER)
        == "LongFast"
    )

    # One MediumFast vote ties, and a tie keeps the stored value.
    asyncio.run(
        _ingest(
            ingest_url,
            tracker,
            [_message(SENDER, 100, GW_MED_1, "azmsh", NOW + timedelta(seconds=11))],
        )
    )
    assert packet_preset() == "LongFast"

    # The second one is a majority, and the UPDATE runs as the ingest role.
    asyncio.run(
        _ingest(
            ingest_url,
            tracker,
            [_message(SENDER, 100, GW_MED_2, "azmsh", NOW + timedelta(seconds=12))],
        )
    )
    assert packet_preset() == "MediumFast"
    assert (
        _scalar(migrated_engine, "SELECT last_preset FROM node WHERE node_num = :s", s=SENDER)
        == "MediumFast"
    )

    with migrated_engine.connect() as connection:
        seen = connection.execute(
            text(
                "SELECT gateway_node_num, modem_preset FROM packet_seen "
                "WHERE from_node_num = :s AND packet_id = 100"
            ),
            {"s": SENDER},
        ).all()
    assert dict(seen) == {GW_LONG: "LongFast", GW_MED_1: "MediumFast", GW_MED_2: "MediumFast"}
    assert (
        _scalar(migrated_engine, "SELECT uplink_preset FROM node WHERE node_num = :g", g=GW_LONG)
        == "LongFast"
    )


def test_an_ambiguous_gateway_casts_no_vote(ingest_url: str, migrated_engine: Any) -> None:
    messages = [
        _announce(GW_BOTH, "LongFast", NOW, 11),
        _announce(GW_BOTH, "MediumFast", NOW + timedelta(minutes=5), 12),
        _message(SENDER, 200, GW_BOTH, "azmsh", NOW + timedelta(minutes=6)),
    ]
    asyncio.run(_ingest(ingest_url, _tracker(), messages))
    assert (
        _scalar(
            migrated_engine,
            "SELECT count(*) FROM packet_seen WHERE from_node_num = :s AND packet_id = 200 "
            "AND modem_preset IS NULL",
            s=SENDER,
        )
        == 1
    )
    assert (
        _scalar(
            migrated_engine,
            "SELECT modem_preset FROM packet WHERE from_node_num = :s AND packet_id = 200",
            s=SENDER,
        )
        is None
    )
    # Its preset-named uploads still name their own preset.
    assert (
        _scalar(
            migrated_engine,
            "SELECT modem_preset FROM packet WHERE from_node_num = :q AND packet_id = 12",
            q=QUIET,
        )
        == "MediumFast"
    )


def test_a_restart_remembers_each_gateway(ingest_url: str, migrated_engine: Any) -> None:
    asyncio.run(_ingest(ingest_url, _tracker(), [_announce(GW_LONG, "LongFast", NOW, 21)]))

    async def restart() -> PresetTracker:
        tracker = _tracker()
        engine = create_async_engine(ingest_url)
        try:
            async with async_sessionmaker(engine)() as session:
                assert await load_gateway_presets(session, tracker) >= 1
        finally:
            await engine.dispose()
        return tracker

    fresh = asyncio.run(restart())
    asyncio.run(
        _ingest(
            ingest_url,
            fresh,
            [_message(SENDER, 300, GW_LONG, "azmsh", NOW + timedelta(minutes=1))],
        )
    )
    assert (
        _scalar(
            migrated_engine,
            "SELECT modem_preset FROM packet WHERE from_node_num = :s AND packet_id = 300",
            s=SENDER,
        )
        == "LongFast"
    )


def test_a_repeat_after_a_restart_updates_the_packet(ingest_url: str, migrated_engine: Any) -> None:
    """The window update runs as the ingest role, with no read of `packet.id`.

    After a restart the tally is gone, so a repeat of a packet stored
    before it updates by a window of `first_seen_at`, not by its exact
    time. An ORM `update()` with a BETWEEN syncs its session by reading
    `packet.id` first, which this role may not do, and on the first
    deploy of #313 every such message was refused and lost.
    """
    asyncio.run(
        _ingest(ingest_url, _tracker(), [_message(SENDER, 400, GW_MED_1, "MediumFast", NOW)])
    )
    asyncio.run(
        _ingest(
            ingest_url,
            _tracker(),
            [_message(SENDER, 400, GW_LONG, "LongFast", NOW + timedelta(seconds=30))],
        )
    )
    assert (
        _scalar(
            migrated_engine,
            "SELECT modem_preset FROM packet WHERE from_node_num = :s AND packet_id = 400",
            s=SENDER,
        )
        == "LongFast"
    )


def test_last_preset_only_moves_forward(ingest_url: str, migrated_engine: Any) -> None:
    asyncio.run(_ingest(ingest_url, _tracker(), [_announce(GW_LONG, "LongFast", NOW, 31)]))

    async def older() -> None:
        engine = create_async_engine(ingest_url)
        try:
            async with async_sessionmaker(engine)() as session:
                await store_last_preset(session, QUIET, "MediumFast", NOW - timedelta(hours=1))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(older())
    assert (
        _scalar(migrated_engine, "SELECT last_preset FROM node WHERE node_num = :q", q=QUIET)
        == "LongFast"
    )


def test_the_ingest_role_still_cannot_read_a_packet(ingest_url: str) -> None:
    async def attempt(sql: str) -> None:
        engine = create_async_engine(ingest_url)
        try:
            async with engine.connect() as connection:
                await connection.execute(text(sql))
        finally:
            await engine.dispose()

    for sql in (
        "SELECT modem_preset FROM packet LIMIT 1",
        "SELECT raw_bytes FROM packet LIMIT 1",
        "SELECT * FROM packet LIMIT 1",
        "SELECT modem_preset FROM packet_seen LIMIT 1",
        "SELECT last_preset FROM node LIMIT 1",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            asyncio.run(attempt(sql))


def test_the_list_pages_read_the_tag_and_keep_untagged_rows(
    ingest_url: str, migrated_engine: Any, timescale_url: str
) -> None:
    tracker = _tracker()
    asyncio.run(
        _ingest(
            ingest_url,
            tracker,
            [
                _announce(GW_LONG, "LongFast", NOW, 41),
                _announce(GW_MED_1, "MediumFast", NOW, 42),
                _message(SENDER, 400, GW_LONG, "azmsh", NOW + timedelta(seconds=5), "on long"),
                _message(SENDER, 401, GW_MED_1, "azmsh", NOW + timedelta(seconds=6), "on medium"),
            ],
        )
    )
    # A row from before the tag: NULL preset, on the LongFast topic.
    old = NOW - timedelta(minutes=1)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, channel, first_seen_at) "
                "VALUES (:s, 402, 1, 'LongFast', :t)"
            ),
            {"s": QUIET, "t": old},
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, packet_id, to_node_num, channel, "
                "body, seen_at) VALUES (:s, 402, 0, 'LongFast', 'from before', :t)"
            ),
            {"s": QUIET, "t": old},
        )

    app = create_app(
        Settings(
            _env_file=None,
            database_url_api=role_url(timescale_url, "azmsh_api"),
            stats_cache_seconds=0,
        )
    )
    with TestClient(app) as client:
        _check_pages(client)


def _check_pages(client: TestClient) -> None:
    def bodies(path: str) -> set[str]:
        response = client.get(path)
        assert response.status_code == 200, response.text
        return {row["body"] for row in response.json()}

    long_chat = bodies("/api/chat?preset=LongFast&limit=500")
    assert {"on long", "from before"} <= long_chat
    assert "on medium" not in long_chat
    assert "on medium" in bodies("/api/chat?preset=MediumFast&limit=500")
    # The channel page on one preset: azmsh, on LongFast only.
    assert bodies("/api/chat?channel=azmsh&preset=LongFast&limit=500") >= {"on long"}
    assert "on medium" not in bodies("/api/chat?channel=azmsh&preset=LongFast&limit=500")
    # The old form is unchanged: azmsh on every preset.
    assert {"on long", "on medium"} <= bodies("/api/chat?channel=azmsh&limit=500")

    overview = client.get("/api/chat/overview?hours=2&preset=LongFast").json()
    azmsh = [s for s in overview["sections"] if s["channel"] == "azmsh"]
    assert azmsh and {m["body"] for m in azmsh[0]["messages"]} >= {"on long"}
    assert "on medium" not in {m["body"] for m in azmsh[0]["messages"]}

    keys = {
        row["packet_key"] for row in client.get("/api/packets?preset=LongFast&limit=500").json()
    }
    assert f"{SENDER}:400" in keys and f"{QUIET}:402" in keys
    assert f"{SENDER}:401" not in keys

    long_nodes = {row["node_id"] for row in client.get("/api/nodes?preset=LongFast").json()}
    medium_nodes = {row["node_id"] for row in client.get("/api/nodes?preset=MediumFast").json()}
    # The sender's newest tagged packet was on MediumFast.
    assert f"!{SENDER:08x}" in medium_nodes and f"!{SENDER:08x}" not in long_nodes
    facets = client.get("/api/nodes/facets?preset=MediumFast")
    assert facets.status_code == 200


def _preset_schema(engine: Any) -> tuple[set[tuple[str, str]], dict[str, bool]]:
    with engine.connect() as connection:
        columns = {
            (table, column)
            for table, column in connection.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name IN "
                    "('modem_preset', 'last_preset', 'last_preset_at', "
                    "'uplink_preset', 'uplink_preset_at')"
                )
            ).all()
        }
        reads = {
            name: bool(
                connection.execute(
                    text("SELECT has_column_privilege('azmsh_ingest', :t, :c, 'SELECT')"),
                    {"t": name.split(".")[0], "c": name.split(".")[1]},
                ).scalar()
            )
            for name in ("packet.first_seen_at", "packet.packet_id", "node.node_num")
        }
    return columns, reads


def test_the_preset_revision_downgrades_and_upgrades(
    timescale_url: str, migrated_engine: Any
) -> None:
    os.environ["DATABASE_URL_MIGRATE"] = timescale_url
    config = Config("alembic.ini")
    expected = {
        ("packet", "modem_preset"),
        ("packet_seen", "modem_preset"),
        ("node", "last_preset"),
        ("node", "last_preset_at"),
        ("node", "uplink_preset"),
        ("node", "uplink_preset_at"),
    }
    columns, reads = _preset_schema(migrated_engine)
    assert columns == expected
    assert all(reads.values())

    command.downgrade(config, "0021")
    columns, reads = _preset_schema(migrated_engine)
    assert columns == set()
    assert reads == {
        "packet.first_seen_at": False,
        "packet.packet_id": False,
        # Revision 0006 still holds this one.
        "node.node_num": True,
    }

    command.upgrade(config, "head")
    columns, reads = _preset_schema(migrated_engine)
    assert columns == expected
    assert all(reads.values())
