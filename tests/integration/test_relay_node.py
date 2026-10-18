"""Each upload keeps its relay byte, and the packet API names the candidates.

Unit rules are in tests/unit/test_relay_node.py. This file holds the SQL:
the migration's column, ingest's role writing it, and the API reading it.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from sonoran.api.app import create_app
from sonoran.config import Settings
from tests.integration.conftest import role_url

SENDER, GW_A, GW_B = 0x0E1A_0001, 0x0E1A_0002, 0x0E1A_0003
RELAY_1, RELAY_2, STALE = 0x0E1A_114F, 0x0E1A_224F, 0x0E1A_334F
PACKET_ID = 990001


def _seed_nodes(engine, now: datetime) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as c:
        for num, name, heard in (
            (SENDER, "Sender", now),
            (GW_A, "Gateway A", now),
            (GW_B, "Gateway B", now),
            (RELAY_1, "Relay one", now - timedelta(minutes=5)),
            (RELAY_2, "Relay two", now - timedelta(hours=3)),
            (STALE, "Gone", now - timedelta(days=3)),
        ):
            c.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen,"
                    " updated_at, last_heard) VALUES (:n, :i, :s, :h, :h, :h)"
                    " ON CONFLICT (node_num) DO UPDATE SET last_heard = :h"
                ),
                {"n": num, "i": f"!{num:08x}", "s": name, "h": heard},
            )
        c.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, first_seen_at)"
                " VALUES (:f, :p, 1, 3, :now) ON CONFLICT DO NOTHING"
            ),
            {"f": SENDER, "p": PACKET_ID, "now": now},
        )


def test_each_upload_keeps_its_relay_and_the_api_names_candidates(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url
) -> None:
    now = datetime.now(UTC)
    _seed_nodes(migrated_engine, now)
    # Ingest's own role writes the column: its table-level INSERT covers it.
    ingest_url = role_url(timescale_url, "azmsh_ingest").replace("+asyncpg", "+psycopg")
    as_ingest = create_engine(ingest_url)
    try:
        with as_ingest.begin() as c:
            for gateway, relay in ((GW_A, 0x4F), (GW_B, None)):
                c.execute(
                    text(
                        "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num,"
                        " mqtt_topic, hop_limit, seen_at, relay_node)"
                        " VALUES (:f, :p, :g, 'msh/US/AZ/test', 2, :now, :r)"
                    ),
                    {"f": SENDER, "p": PACKET_ID, "g": gateway, "now": now, "r": relay},
                )
    finally:
        as_ingest.dispose()

    settings = Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api"))
    with TestClient(create_app(settings)) as client:
        body = client.get(f"/api/packets/!{SENDER:08x}/{PACKET_ID}").json()
    by_gateway = {row["gateway"]: row["relayed_by"] for row in body["observations"]}
    relay = by_gateway[f"!{GW_A:08x}"]
    assert relay["byte"] == "4f"
    # Newest first; the node not heard in a day is left out.
    assert [c["node_id"] for c in relay["candidates"]] == [f"!{RELAY_1:08x}", f"!{RELAY_2:08x}"]
    assert by_gateway[f"!{GW_B:08x}"] is None
