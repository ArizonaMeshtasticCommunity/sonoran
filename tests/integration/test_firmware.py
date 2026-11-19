"""A node's firmware version, and whether it is behind stable (#406).

Unit rules are in tests/unit/test_firmware_status.py. This file holds
the SQL: ingest's role writing the version from a map report, the jobs
role replacing the stable release, and the API reading both.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.db.session import make_engine, make_session_factory
from sonoran.ingest.pipeline import process_map_report
from sonoran.jobs import firmware_releases
from sonoran.meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2
from sonoran.mqtt.client import RawMqttMessage
from sonoran.mqtt.topics import parse_topic
from tests.integration.conftest import role_url

NODE = 0x0F1A_0001
OTHER = 0x0F1A_0002
NOW = datetime(2026, 11, 19, 5, 0, tzinfo=UTC)
LIST_BODY = {
    "releases": {
        "stable": [
            {"id": "v2.7.26.54e0d8d", "title": "Meshtastic Firmware 2.7.26.54e0d8d Beta"},
            {"id": "v2.7.15.567b8ea", "title": "Meshtastic Firmware 2.7.15.567b8ea Beta"},
        ],
        "alpha": [{"id": "v2.8.2.d5f1619", "title": "Meshtastic Firmware 2.8.2.d5f1619 Alpha"}],
    }
}


def _map_message(
    from_num: int,
    version: str,
    *,
    gateway: int | None = None,
    encrypted: bool = False,
    at: datetime = NOW,
    topic: str = "msh/US/AZ/Phoenix/2/map/",
) -> RawMqttMessage:
    """A map report as firmware builds it (MQTT.cpp perhapsReportToMap)."""
    report: Any = mqtt_pb2.MapReport(  # type: ignore[attr-defined]
        long_name="Ridge", short_name="RDG", firmware_version=version
    )
    packet: Any = mesh_pb2.MeshPacket(id=0x1234, to=0xFFFFFFFF)  # type: ignore[attr-defined]
    setattr(packet, "from", from_num)
    if encrypted:
        packet.encrypted = b"\x01\x02\x03\x04"
    else:
        packet.decoded.portnum = portnums_pb2.MAP_REPORT_APP  # type: ignore[attr-defined]
        packet.decoded.payload = report.SerializeToString()
    envelope: Any = mqtt_pb2.ServiceEnvelope(  # type: ignore[attr-defined]
        packet=packet,
        channel_id="LongFast",
        gateway_id=f"!{(gateway if gateway is not None else from_num):08x}",
    )
    return RawMqttMessage(
        topic=parse_topic(topic), payload=envelope.SerializeToString(), received_at=at
    )


@pytest.fixture
def clean(migrated_engine):  # type: ignore[no-untyped-def]
    def wipe() -> None:
        with migrated_engine.begin() as c:
            c.execute(text("DELETE FROM node WHERE node_num = ANY(:n)"), {"n": [NODE, OTHER]})
            c.execute(text("DELETE FROM firmware_release"))

    wipe()
    yield
    wipe()


def _ingest(timescale_url: str, *messages: RawMqttMessage) -> None:
    """Run the messages through ingest as the write-only ingest role."""

    async def go() -> None:
        engine = make_engine(role_url(timescale_url, "azmsh_ingest"))
        try:
            factory = make_session_factory(engine)
            for message in messages:
                async with factory() as session:
                    await process_map_report(session, message)
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(go())


def _firmware_row(engine: Any, node_num: int) -> Any:
    with engine.begin() as c:
        return c.execute(
            text("SELECT firmware_version, firmware_version_at FROM node WHERE node_num = :n"),
            {"n": node_num},
        ).one_or_none()


def test_a_map_report_stores_the_version_with_the_ingest_role(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    _ingest(timescale_url, _map_message(NODE, "2.6.4.b89355f"))
    row = _firmware_row(migrated_engine, NODE)
    assert row is not None
    assert row.firmware_version == "2.6.4.b89355f"
    assert row.firmware_version_at == NOW


def test_a_newer_report_replaces_the_version(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    """An upgrade shows on the next report."""
    later = NOW + timedelta(hours=1)
    _ingest(
        timescale_url,
        _map_message(NODE, "2.6.4.b89355f"),
        _map_message(NODE, "2.7.26.54e0d8d", at=later),
    )
    row = _firmware_row(migrated_engine, NODE)
    assert row.firmware_version == "2.7.26.54e0d8d"
    assert row.firmware_version_at == later


def test_a_report_about_another_node_is_ignored(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    """Firmware only reports its own node (`mp->from = nodeDB->getNodeNum()`)."""
    _ingest(timescale_url, _map_message(NODE, "2.6.4.b89355f", gateway=OTHER))
    assert _firmware_row(migrated_engine, NODE) is None
    assert _firmware_row(migrated_engine, OTHER) is None


def test_an_encrypted_map_packet_is_ignored(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    _ingest(timescale_url, _map_message(NODE, "", encrypted=True))
    assert _firmware_row(migrated_engine, NODE) is None


def test_a_report_with_no_usable_version_keeps_the_old_one(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    _ingest(
        timescale_url,
        _map_message(NODE, "2.7.26.54e0d8d"),
        _map_message(NODE, "", at=NOW + timedelta(hours=1)),
        _map_message(NODE, "x" * 200, at=NOW + timedelta(hours=2)),
    )
    row = _firmware_row(migrated_engine, NODE)
    assert row.firmware_version == "2.7.26.54e0d8d"
    assert row.firmware_version_at == NOW


def test_a_report_never_touches_the_names_nodeinfo_gave(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    """NodeInfo owns the identity. A map report only adds the version."""
    with migrated_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO node (node_num, node_id, long_name, first_seen, updated_at)"
                " VALUES (:n, :i, 'From NodeInfo', :t, :t)"
            ),
            {"n": NODE, "i": f"!{NODE:08x}", "t": NOW - timedelta(days=1)},
        )
    _ingest(timescale_url, _map_message(NODE, "2.7.26.54e0d8d"))
    with migrated_engine.begin() as c:
        name = c.execute(
            text("SELECT long_name FROM node WHERE node_num = :n"), {"n": NODE}
        ).scalar_one()
    assert name == "From NodeInfo"


def _settings(timescale_url: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url_jobs=role_url(timescale_url, "azmsh_jobs"),
        database_url_api=role_url(timescale_url, "azmsh_api"),
    )


def _run_job(timescale_url: str, transport: httpx.MockTransport) -> None:
    settings = _settings(timescale_url)

    async def go() -> None:
        engine = make_engine(settings.database_url_jobs)
        try:
            async with make_session_factory(engine)() as session:
                await firmware_releases.refresh(session, settings, transport=transport)
        finally:
            await engine.dispose()

    asyncio.run(go())


def _stable(engine: Any) -> list[Any]:
    with engine.begin() as c:
        return list(c.execute(text("SELECT channel, version, page_url FROM firmware_release")))


def test_the_job_stores_the_stable_release(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    _run_job(timescale_url, httpx.MockTransport(lambda r: httpx.Response(200, json=LIST_BODY)))
    rows = _stable(migrated_engine)
    assert [(r.channel, r.version) for r in rows] == [("stable", "2.7.26.54e0d8d")]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="down"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"releases": {"stable": []}}),
    ],
)
def test_a_failed_fetch_keeps_the_last_good_release(
    timescale_url: str, migrated_engine: Any, clean: None, response: httpx.Response
) -> None:
    _run_job(timescale_url, httpx.MockTransport(lambda r: httpx.Response(200, json=LIST_BODY)))
    _run_job(timescale_url, httpx.MockTransport(lambda r: response))
    assert [r.version for r in _stable(migrated_engine)] == ["2.7.26.54e0d8d"]


def test_a_network_error_keeps_the_last_good_release(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    _run_job(timescale_url, httpx.MockTransport(lambda r: httpx.Response(200, json=LIST_BODY)))
    _run_job(timescale_url, httpx.MockTransport(fail))
    assert [r.version for r in _stable(migrated_engine)] == ["2.7.26.54e0d8d"]


def _detail(timescale_url: str, node_num: int) -> dict[str, Any]:
    with TestClient(create_app(_settings(timescale_url))) as client:
        response = client.get(f"/api/nodes/!{node_num:08x}/detail")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_the_node_page_says_the_node_is_behind(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    _run_job(timescale_url, httpx.MockTransport(lambda r: httpx.Response(200, json=LIST_BODY)))
    _ingest(timescale_url, _map_message(NODE, "2.6.4.b89355f"))
    firmware = _detail(timescale_url, NODE)["node"]["firmware"]
    assert firmware["version"] == "2.6.4.b89355f"
    assert firmware["status"] == "behind"
    assert firmware["stable_version"] == "2.7.26.54e0d8d"
    assert firmware["stable_url"].endswith("/v2.7.26.54e0d8d")
    assert firmware["reported_at"].startswith("2026-11-19T05:00:00")


def test_a_node_with_no_report_is_unknown(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    _run_job(timescale_url, httpx.MockTransport(lambda r: httpx.Response(200, json=LIST_BODY)))
    with migrated_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO node (node_num, node_id, first_seen, updated_at)"
                " VALUES (:n, :i, :t, :t)"
            ),
            {"n": OTHER, "i": f"!{OTHER:08x}", "t": NOW},
        )
    firmware = _detail(timescale_url, OTHER)["node"]["firmware"]
    assert firmware["version"] is None
    assert firmware["status"] == "unknown"
    assert firmware["stable_version"] == "2.7.26.54e0d8d"


def test_no_stable_release_yet_is_unknown_not_behind(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    _ingest(timescale_url, _map_message(NODE, "2.6.4.b89355f"))
    firmware = _detail(timescale_url, NODE)["node"]["firmware"]
    assert firmware["version"] == "2.6.4.b89355f"
    assert firmware["status"] == "unknown"
    assert firmware["stable_version"] is None
