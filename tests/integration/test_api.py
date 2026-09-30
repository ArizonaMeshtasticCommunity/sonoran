"""Database-backed tests for the public GET API."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.config import Settings
from tests.integration.conftest import role_url


def _api_url(timescale_url: str) -> str:
    """Make an async URL for the migration-created API role."""
    return role_url(timescale_url, "azmsh_api")


def _seed(migrated_engine) -> int:  # type: ignore[no-untyped-def]
    """Insert one complete public data set with the admin test connection."""
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                "last_heard, last_lat, last_lon) "
                "VALUES (4242, '!00001092', 'API', :now, :now, :now, 33.45, -112.07) "
                "ON CONFLICT (node_num) DO NOTHING"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, first_seen_at) "
                "VALUES (4242, 77, 1, :now) ON CONFLICT DO NOTHING"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                "mqtt_topic, seen_at) "
                "VALUES (4242, 77, 4242, 'msh/US/AZ/test', :now) ON CONFLICT DO NOTHING"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, body, seen_at) "
                "VALUES (4242, 0, 'test', :now) ON CONFLICT DO NOTHING"
            ),
            {"now": now},
        )
        trace_id = connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, seen_at) "
                "VALUES (4242, 1, :now) "
                "RETURNING id"
            ),
            {"now": now},
        ).scalar_one()
    return trace_id


def test_documented_get_endpoints_query_the_api_role(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The main documented endpoints return data through the SELECT-only role."""
    trace_id = _seed(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    paths = (
        "/api/nodes",
        "/api/nodes/!00001092",
        "/api/nodes/!00001092/heard-by",
        "/api/nodes/!00001092/packets",
        "/api/nodes/!00001092/telemetry?family=device",
        "/api/nodes/!00001092/neighbors",
        "/api/nodes/!00001092/graph",
        "/api/nodes/!00001092/detail",
        "/api/nodes/!00001092/signal",
        "/api/graph",
        "/api/packets?portnum=TEXT_MESSAGE_APP",
        "/api/packets/!00001092/77",
        "/api/chat",
        "/api/chat/channels",
        "/api/chat/overview",
        "/api/chat/tagged",
        "/api/map/nodes",
        "/api/map/edges",
        "/api/map/traffic",
        "/api/map/traceroute-paths",
        "/api/map/track/!00001092",
        "/api/stats",
        "/api/stats/top",
        "/api/stats/hardware",
        "/api/stats/portnums",
        "/api/stats/snapshots/daily",
        "/api/stats/reliability/!00001092",
        "/api/traceroutes",
        f"/api/traceroutes/{trace_id}",
    )
    with TestClient(app) as client:
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, path
        edges = client.get("/api/map/edges").json()
        completed = client.get("/api/map/traceroute-paths?minutes=60").json()
        attempts = client.get("/api/map/traceroute-paths?minutes=60&completed_only=false").json()

    # The edges layer draws radio links, so it holds neighbor reports
    # only. It used to add one line for each traceroute, drawn between
    # the two ends of the trace. Those ends can be many hops apart and
    # often have no link at all, so the line meant nothing.
    assert all(edge["kind"] == "neighbor" for edge in edges)

    # The seeded traceroute carries no request ID, so it is a request
    # that nothing answered. Anybody can send one to any node, and most
    # never come back. A request proves no path, so the map must not be
    # given one to draw.
    assert completed["completed_only"] is True
    assert not [item for item in completed["traces"] if item["from"]["node_id"] == "!00001092"]

    # The attempts are still available when they are asked for.
    trace = next(item for item in attempts["traces"] if item["from"]["node_id"] == "!00001092")
    assert trace["is_reply"] is False
    assert trace["hops"], "a traceroute must report at least one hop"
    # The seeded trace carries no intermediate hop, so it is one link
    # from the node that asked to the node that answered.
    assert trace["link_count"] == 1
    assert trace["hops"][0]["from"]["node_id"] == "!00001092"
    assert trace["hops"][0]["to"]["node_id"] == trace["to"]["node_id"]


def _seed_two_presets(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """Insert neighbor links on two different modem presets."""
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for node_num, name in ((7001, "LF-A"), (7002, "LF-B"), (7003, "MF-A"), (7004, "MF-B")):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                    "last_heard) VALUES (:n, :nid, :sn, :now, :now, :now) "
                    "ON CONFLICT (node_num) DO NOTHING"
                ),
                {"n": node_num, "nid": f"!{node_num:08x}", "sn": name, "now": now},
            )
        for node_num, neighbor, channel in (
            (7001, 7002, "LongFast"),
            (7003, 7004, "MediumFast"),
        ):
            connection.execute(
                text(
                    "INSERT INTO neighbor_metrics (node_num, neighbor_node_num, channel, snr, "
                    "time) VALUES (:n, :o, :c, 5.0, :now)"
                ),
                {"n": node_num, "o": neighbor, "c": channel, "now": now},
            )


def test_graph_keeps_each_preset_separate(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A graph holds one preset only.

    Nodes on LongFast cannot hear nodes on MediumFast. A graph that
    mixes them would draw links that cannot exist.
    """
    _seed_two_presets(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        channels = client.get("/api/graph/channels").json()["channels"]
        names = {item["channel"] for item in channels}
        assert {"LongFast", "MediumFast"} <= names

        long_fast = client.get("/api/graph?channel=LongFast").json()
        medium_fast = client.get("/api/graph?channel=MediumFast").json()

    long_ids = {node["node_id"] for node in long_fast["nodes"]}
    medium_ids = {node["node_id"] for node in medium_fast["nodes"]}
    assert "!00001b59" in long_ids  # 7001
    assert "!00001b5b" not in long_ids  # 7003 is on MediumFast
    assert "!00001b5b" in medium_ids
    assert not (long_ids & medium_ids)


def test_graph_channels_are_labelled_by_preset(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Each channel carries its preset group for the page tabs."""
    _seed_two_presets(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        channels = client.get("/api/graph/channels").json()["channels"]
    by_name = {item["channel"]: item for item in channels}
    assert by_name["LongFast"]["group"] == "Presets"
    assert by_name["LongFast"]["preset"] == "LongFast"
    assert by_name["MediumFast"]["preset"] == "MediumFast"


def test_map_edges_filter_by_preset(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The map link layer draws one preset at a time.

    A node on LongFast cannot hear a node on MediumFast, so a mixed
    layer would draw lines that cannot exist.
    """
    _seed_two_presets(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        long_fast = client.get("/api/map/edges?channel=LongFast").json()
        medium_fast = client.get("/api/map/edges?channel=MediumFast").json()
        every = client.get("/api/map/edges").json()

    assert long_fast, "the LongFast layer must have links"
    assert {edge["channel"] for edge in long_fast} == {"LongFast"}
    assert {edge["channel"] for edge in medium_fast} == {"MediumFast"}
    # Without a channel the response still holds every preset together.
    assert {"LongFast", "MediumFast"} <= {edge["channel"] for edge in every}


def test_unknown_channel_sorts_last(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Links with no channel never become the default graph tab.

    They were stored before the channel column existed, so one graph of
    them mixes every preset. The page selects the first tab, so this set
    must sort last however many reports it holds.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        # Many rows with no channel, few with a real preset.
        for index in range(30):
            connection.execute(
                text(
                    "INSERT INTO neighbor_metrics (node_num, neighbor_node_num, channel, snr, "
                    "time) VALUES (:n, :o, NULL, 1.0, :now)"
                ),
                {"n": 8100 + index, "o": 8200 + index, "now": now},
            )
        connection.execute(
            text(
                "INSERT INTO neighbor_metrics (node_num, neighbor_node_num, channel, snr, time) "
                "VALUES (8301, 8302, 'ShortSlow', 1.0, :now)"
            ),
            {"now": now},
        )
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        channels = client.get("/api/graph/channels").json()["channels"]

    assert channels, "the window must hold link reports"
    assert channels[-1]["channel"] == "unknown", "links with no channel sort last"
    assert channels[-1]["mixed_presets"] is True
    assert channels[0]["channel"] != "unknown", "the default tab must be a real channel"


def test_tapbacks_attach_to_the_message_they_react_to(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A tapback is a reaction on a message, not a message of its own.

    The phone apps send a tapback as a text message with the emoji flag
    set and `reply_id` holding the packet ID of the parent.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM text_message WHERE from_node_num BETWEEN 9100 AND 9199")
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                "packet_id, emoji, seen_at) "
                "VALUES (9101, 4294967295, 'LongFast', 'Radio check', 555001, false, :now)"
            ),
            {"now": now},
        )
        # Two nodes send a thumbs up, one sends a wave.
        for node, glyph in (
            (9102, "\N{THUMBS UP SIGN}"),
            (9103, "\N{THUMBS UP SIGN}"),
            (9104, "\N{WAVING HAND SIGN}"),
        ):
            connection.execute(
                text(
                    "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                    "packet_id, reply_id, emoji, seen_at) "
                    "VALUES (:n, 4294967295, 'LongFast', :glyph, :pid, 555001, true, :now)"
                ),
                {"n": node, "glyph": glyph, "pid": 555100 + node, "now": now},
            )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        messages = client.get("/api/chat?limit=200").json()

    parent = next(m for m in messages if m["packet_id"] == 555001)
    assert parent["body"] == "Radio check"
    by_emoji = {r["emoji"]: r for r in parent["reactions"]}
    assert by_emoji["\N{THUMBS UP SIGN}"]["count"] == 2, "identical emoji group into one chip"
    assert by_emoji["\N{WAVING HAND SIGN}"]["count"] == 1
    assert len(by_emoji["\N{THUMBS UP SIGN}"]["from"]) == 2

    # The tapbacks themselves are not listed as messages.
    bodies = [m["body"] for m in messages]
    assert "\N{THUMBS UP SIGN}" not in bodies, "a lone emoji is not a message"


def test_chat_metrics_say_how_a_message_travelled(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """`metrics=true` adds the delivery facts of each message.

    Three gateways matter here, and each one tests a rule:
    the sender uploading its own packet is not a gateway that heard it,
    one gateway uploading twice is still one gateway, and a relayed
    upload's strong reading belongs to the last hop, so it is never the
    best direct signal. See AGENTS.md 9.5 and 9.5.1.
    """
    now = datetime.now(UTC)
    sender, near, far = 7601, 7602, 7603
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM text_message WHERE from_node_num BETWEEN 7600 AND 7699")
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                "packet_id, emoji, seen_at) "
                "VALUES (:s, 4294967295, 'MetricsTest', 'Anyone copy?', 766001, false, :now)"
            ),
            {"s": sender, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, channel, hop_start, "
                "want_ack, first_seen_at) "
                "VALUES (:s, 766001, 1, 'MetricsTest', 3, true, :now) ON CONFLICT DO NOTHING"
            ),
            {"s": sender, "now": now},
        )
        uploads = (
            (sender, 3, 12.0, -20, 0),  # its own voice
            (near, 3, 6.5, -70, 1),  # direct
            (near, 3, 6.5, -70, 4),  # the same gateway again
            (far, 1, 11.0, -40, 2),  # relayed twice, with a strong last hop
        )
        for gateway, hop_limit, snr, rssi, delay in uploads:
            connection.execute(
                text(
                    "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                    "mqtt_topic, channel, hop_limit, rx_snr, rx_rssi, seen_at) "
                    "VALUES (:s, 766001, :g, 'msh/US/AZ/t', 'MetricsTest', :hl, :snr, :rssi, :t) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "s": sender,
                    "g": gateway,
                    "hl": hop_limit,
                    "snr": snr,
                    "rssi": rssi,
                    "t": now + timedelta(seconds=delay),
                },
            )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        plain = client.get("/api/chat?channel=MetricsTest").json()
        rich = client.get("/api/chat?channel=MetricsTest&metrics=true").json()

    assert "metrics" not in plain[0], "metrics are opt in"
    metrics = rich[0]["metrics"]
    assert metrics["gateway_count"] == 2, "gateways, not uploads, and never the sender"
    assert metrics["direct_gateways"] == 1
    assert metrics["fewest_hops"] == 0
    assert metrics["best_direct_snr"] == 6.5, "a relayed reading is not a direct one"
    assert metrics["best_direct_rssi"] == -70
    assert metrics["want_ack"] is True


def test_replies_carry_the_message_they_answer(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A threaded reply shows what it replies to."""
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM text_message WHERE from_node_num BETWEEN 9200 AND 9299")
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                "packet_id, emoji, seen_at) "
                "VALUES (9201, 4294967295, 'LongFast', 'Anyone near Payson?', 556001, false, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                "packet_id, reply_id, emoji, seen_at) "
                "VALUES (9202, 4294967295, 'LongFast', 'I am, on the ridge', 556002, 556001, "
                "false, :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        messages = client.get("/api/chat?limit=200").json()

    reply = next(m for m in messages if m["packet_id"] == 556002)
    assert reply["reply_to"] is not None
    assert reply["reply_to"]["body"] == "Anyone near Payson?"
    assert reply["reply_to"]["packet_id"] == 556001


def test_tapback_names_its_sender_and_packet(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A reaction says who sent it and which packet carried it.

    An emoji with no name behind it tells the reader nothing.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM text_message WHERE from_node_num BETWEEN 9300 AND 9399")
        )
        connection.execute(
            text(
                "INSERT INTO node (node_num, node_id, long_name, first_seen, updated_at) "
                "VALUES (9302, '!00002456', 'Reacting Node', :now, :now) "
                "ON CONFLICT (node_num) DO NOTHING"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                "packet_id, emoji, seen_at) "
                "VALUES (9301, 4294967295, 'LongFast', 'Net starts now', 557001, false, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                "packet_id, reply_id, emoji, seen_at) "
                "VALUES (9302, 4294967295, 'LongFast', :glyph, 557002, 557001, true, :now)"
            ),
            {"glyph": "\N{THUMBS UP SIGN}", "now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        messages = client.get("/api/chat?limit=200").json()

    parent = next(m for m in messages if m["packet_id"] == 557001)
    reaction = parent["reactions"][0]
    sender = reaction["senders"][0]
    assert sender["display_name"] == "Reacting Node", "the reaction names its sender"
    assert sender["node_id"] == "!00002456"
    assert sender["packet_id"] == 557002, "the tapback's own packet can be opened"


def test_node_neighbours_use_the_page_window(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The neighbour list respects the window the page asked for.

    Without a window it would list neighbours the node stopped hearing
    long ago, and disagree with the mesh graph, which always windows.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM neighbor_metrics WHERE node_num = 9401"))
        connection.execute(
            text(
                "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at) "
                "VALUES (9401, '!000024b9', 'NBR', :now, :now) "
                "ON CONFLICT (node_num) DO NOTHING"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO neighbor_metrics (node_num, neighbor_node_num, channel, snr, time) "
                "VALUES (9401, 9402, 'LongFast', 5.0, :recent)"
            ),
            {"recent": now},
        )
        connection.execute(
            text(
                "INSERT INTO neighbor_metrics (node_num, neighbor_node_num, channel, snr, time) "
                "VALUES (9401, 9403, 'LongFast', 5.0, :old)"
            ),
            {"old": now - timedelta(days=5)},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        recent = client.get("/api/nodes/9401/detail?hours=24").json()
        wide = client.get("/api/nodes/9401/detail?hours=720").json()

    assert len(recent["neighbors"]) == 1, "the old neighbour falls outside 24 hours"
    assert len(wide["neighbors"]) == 2, "a wider window brings it back"


def test_a_traceroute_reply_reads_in_request_order(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A reply is shown from the asking node to the answering node.

    A reply travels back, so its packet fields are the wrong way round
    for describing the route. mesh-graph swaps them, and so must we, or
    the two disagree on every reply.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM traceroute WHERE from_node_num = 9501"))
        # The reply comes from 9501, the node that answered. The request
        # was sent by 9502, and travelled through 9503.
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "request_id, route, snr_towards, seen_at) "
                "VALUES (9501, 9502, 'LongFast', 600002, 600001, "
                "CAST('[9503]' AS jsonb), CAST('[20, 24]' AS jsonb), :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        rows = client.get("/api/traceroutes?limit=200").json()

    trace = next(t for t in rows if t["packet_id"] == 600002)
    assert trace["is_reply"] is True
    # Request order: the asking node first, the answering node last.
    assert trace["from_node"] == "!0000251e", "the asking node leads"
    assert trace["to_node"] == "!0000251d", "the answering node is the destination"
    assert trace["packet_from_node"] == "!0000251d", "the packet fields are kept as sent"
    hops = trace["hops"]
    assert [hop["from_node"] for hop in hops] == ["!0000251e", "!0000251f"]
    assert [hop["to_node"] for hop in hops] == ["!0000251f", "!0000251d"]
    assert hops[0]["snr"] == 5.0


def test_a_reply_in_flight_does_not_claim_delivery(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A path is drawn only as far as the report measured.

    The broker sees a reply while it travels, so `snr_back` is one short
    of the full path. The last hop back to the asking node had not
    happened, and must not be drawn as though it had.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM traceroute WHERE from_node_num = 9601"))
        # Reply from 9601 heading back to 9602 through 9603 and 9604.
        # Two readings for what would be three hops.
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "request_id, route, snr_towards, route_back, snr_back, seen_at) "
                "VALUES (9601, 9602, 'LongFast', 601002, 601001, "
                "CAST('[]' AS jsonb), CAST('[20]' AS jsonb), "
                "CAST('[9603, 9604]' AS jsonb), CAST('[12, 16]' AS jsonb), :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        rows = client.get("/api/traceroutes?limit=200").json()

    trace = next(t for t in rows if t["packet_id"] == 601002)
    assert trace["return_delivered"] is False, "delivery back was never observed"
    assert len(trace["return_hops"]) == 2, "only measured hops are drawn"
    assert trace["return_hops"][-1]["to_node"] == "!00002584", "the reply reached 9604"
    assert trace["reply_reached"] is not None


def test_a_traceroute_links_to_the_packet_that_carried_it(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """The packet of a reply belongs to the node that answered.

    The route is shown from the asking node, but a packet is keyed by
    its sender. Linking with the route origin gives a dead link.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM traceroute WHERE from_node_num = 9701"))
        connection.execute(
            text("DELETE FROM packet WHERE from_node_num = 9701 AND packet_id = 602002")
        )
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, channel, first_seen_at) "
                "VALUES (9701, 602002, 70, 'LongFast', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "request_id, route, snr_towards, seen_at) "
                "VALUES (9701, 9702, 'LongFast', 602002, 602001, "
                "CAST('[]' AS jsonb), CAST('[20]' AS jsonb), :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        trace = next(
            t for t in client.get("/api/traceroutes?limit=200").json() if t["packet_id"] == 602002
        )
        # The route reads from the asking node.
        assert trace["from_node"] == "!000025e6"
        # The packet belongs to the answering node, and must resolve.
        assert trace["packet_from_node"] == "!000025e5"
        found = client.get(f"/api/packets/{trace['packet_from_node']}/{trace['packet_id']}")
        assert found.status_code == 200, "the packet link must resolve"
        dead = client.get(f"/api/packets/{trace['from_node']}/{trace['packet_id']}")
        assert dead.status_code == 404, "the route origin is the wrong key"


def test_a_request_names_its_reply_only_when_one_was_stored(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """The trace page says "no reply was seen" only when that is true (#288).

    A request row never holds a return path: the reply is a row of its
    own, sent back by the node that was asked. Three requests here:

    - 9801 asked 9802, and 9802 answered. `reply_id` is that reply.
    - 9801 asked 9803, and nothing came back. `reply_id` is null.
    - 9801 asked 9804, and a reply from a DIFFERENT node carries the same
      request ID. Packet IDs are unique only per sender, so that is not
      a reply to this request, and `reply_id` stays null.

    The reply itself always has a null `reply_id`.
    """
    now = datetime.now(UTC)
    insert = text(
        "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
        "request_id, route, snr_towards, seen_at) "
        "VALUES (:f, :t, 'LongFast', :pid, :rid, CAST('[]' AS jsonb), CAST('[]' AS jsonb), :at)"
    )
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM traceroute WHERE from_node_num IN (9801, 9802, 9805)"))
        rows = [
            (9801, 9802, 603001, None),  # answered
            (9802, 9801, 603002, 603001),  # the answer, sent back by 9802
            (9801, 9803, 603003, None),  # never answered
            (9801, 9804, 603004, None),  # answered only by a stranger's reuse
            (9805, 9801, 603005, 603004),  # 9805 was not asked
        ]
        for f, t, pid, rid in rows:
            connection.execute(insert, {"f": f, "t": t, "pid": pid, "rid": rid, "at": now})

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        listed = {t["packet_id"]: t for t in client.get("/api/traceroutes?limit=500").json()}

        def one(packet_id: int) -> dict[str, object]:
            response = client.get(f"/api/traceroutes/{listed[packet_id]['id']}")
            assert response.status_code == 200
            return response.json()  # type: ignore[no-any-return]

        assert one(603001)["reply_id"] == listed[603002]["id"], "the stored reply is named"
        assert one(603003)["reply_id"] is None, "nothing came back"
        assert one(603004)["reply_id"] is None, "a reply from another node is not this reply"
        assert one(603002)["reply_id"] is None, "a reply has no reply of its own"


def _seed_deep_trace(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """Insert one reply with a long route, behind plenty of newer noise.

    The noise matters. The link page reads a limited number of rows, and
    the fault was that it took the newest ones and hoped. The evidence
    here sits far behind that cut, so a query that still sorts by
    recency alone cannot find it.
    """
    now = datetime.now(UTC)
    old = now - timedelta(hours=6)
    path = [8101, 8102, 8103, 8104]
    with migrated_engine.begin() as connection:
        for node_num in path:
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                    "last_heard) VALUES (:n, :nid, :sn, :now, :now, :now) "
                    "ON CONFLICT (node_num) DO NOTHING"
                ),
                {"n": node_num, "nid": f"!{node_num:08x}", "sn": f"D{node_num}", "now": now},
            )
        # The reply. Stored endpoints run backwards: from the answerer
        # (8104) to the asker (8101), with the outward route between.
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "request_id, route, snr_towards, seen_at) "
                "VALUES (8104, 8101, 'LongFast', 810001, 810000, "
                "CAST('[8102, 8103]' AS jsonb), CAST('[12, 20, 8]' AS jsonb), :old)"
            ),
            {"old": old},
        )
        # Newer traffic that mentions neither end of the link.
        for index in range(700):
            connection.execute(
                text(
                    "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                    "route, snr_towards, seen_at) "
                    "VALUES (9001, 9002, 'LongFast', :pid, CAST('[]' AS jsonb), "
                    "CAST('[]' AS jsonb), :now)"
                ),
                {"pid": 820000 + index, "now": now - timedelta(seconds=index)},
            )


def test_a_drawn_link_always_has_its_evidence(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Every traceroute link on the graph opens a page that explains it.

    The graph and the link page read the same rows through the same
    rules. A link the graph draws must therefore always have at least
    one report behind it, however far back the row sits.
    """
    _seed_deep_trace(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        graph = client.get("/api/graph?hours=24&channel=LongFast").json()
        drawn = {
            (link["source"], link["target"])
            for link in graph["links"]
            if link["kind"] == "traceroute"
        }
        assert ("!00001fa5", "!00001fa6") in drawn, "the first hop of the reply must be drawn"

        for source, target in drawn:
            link = client.get(
                f"/api/graph/link?a={source}&b={target}&hours=24&channel=LongFast"
            ).json()
            assert link["report_count"] > 0, f"{source} to {target} was drawn with no evidence"


def test_a_reply_counts_its_way_back(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A reply's return path is evidence in the other direction (#73).

    A hop that only the way back names must still open a link page that
    explains it, so the graph and the link page keep agreeing.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for node_num in (6401, 6402, 6403):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                    "last_heard) VALUES (:n, :nid, :sn, :now, :now, :now) "
                    "ON CONFLICT (node_num) DO NOTHING"
                ),
                {"n": node_num, "nid": f"!{node_num:08x}", "sn": f"W{node_num}", "now": now},
            )
        # A direct reply: 6401 asked 6402, which answered by way of 6403.
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "request_id, route, route_back, snr_towards, snr_back, seen_at) "
                "VALUES (6402, 6401, 'LongModerate', 640001, 640000, CAST('[]' AS jsonb), "
                "CAST('[6403]' AS jsonb), CAST('[12]' AS jsonb), CAST('[8, 4]' AS jsonb), :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        links = client.get("/api/graph?hours=24&channel=LongModerate").json()["links"]
        by_pair = {frozenset((link["source"], link["target"])): link for link in links}
        back = by_pair[frozenset(("!00001902", "!00001903"))]
        evidence = client.get(
            "/api/graph/link?a=!00001902&b=!00001903&hours=24&channel=LongModerate"
        ).json()

    assert sorted(by_pair[frozenset(("!00001901", "!00001902"))]["each_way"]) == [0, 1]
    assert back["snr"] == 2.0
    # "unknown", not "weak": one report says nothing about the link
    # itself, only about how much of it we have seen (#149).
    assert back["strength"] == "unknown"
    assert evidence["report_count"] == 1, "a hop only the way back names still has evidence"


def test_a_reply_does_not_draw_links_to_its_own_endpoints(
    migrated_engine, timescale_url: str
) -> None:  # type: ignore[no-untyped-def]
    """A reply reads in request order, so its end links are real.

    Read as stored, the reply above would join the answering node to the
    first hop of the outward path, and the last hop to the asking node.
    Neither link exists.
    """
    _seed_deep_trace(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        graph = client.get("/api/graph?hours=24&channel=LongFast").json()
    pairs = {frozenset((link["source"], link["target"])) for link in graph["links"]}
    asker, first, last, answerer = "!00001fa5", "!00001fa6", "!00001fa7", "!00001fa8"
    assert frozenset((asker, first)) in pairs
    assert frozenset((last, answerer)) in pairs
    assert frozenset((answerer, first)) not in pairs, "invented by reading the reply as stored"
    assert frozenset((last, asker)) not in pairs, "invented by reading the reply as stored"


def test_an_unanswered_request_draws_no_link(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A request that nothing answered proves no path.

    Its route is empty, so its intended path is one hop from end to end.
    Drawing that claims the two nodes hear each other directly, which is
    the one thing the trace failed to show.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for node_num in (8301, 8302):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                    "last_heard) VALUES (:n, :nid, :sn, :now, :now, :now) "
                    "ON CONFLICT (node_num) DO NOTHING"
                ),
                {"n": node_num, "nid": f"!{node_num:08x}", "sn": f"U{node_num}", "now": now},
            )
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "route, snr_towards, seen_at) "
                "VALUES (8301, 8302, 'ShortTurbo', 830001, CAST('[]' AS jsonb), NULL, :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        graph = client.get("/api/graph?hours=24&channel=ShortTurbo").json()
    pairs = {frozenset((link["source"], link["target"])) for link in graph["links"]}
    assert frozenset(("!0000206d", "!0000206e")) not in pairs


def test_a_packet_says_which_key_sealed_it(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """`pki_encrypted` comes from `mesh_packet_metrics`, and unknown stays unknown.

    Sender 7501 is used by no other test here. The tables are shared across
    this file, and a reused key makes a second packet row for another test.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for packet_id in (92, 93):
            connection.execute(
                text(
                    "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, "
                    "first_seen_at) VALUES (7501, :p, 1, 3, :now) ON CONFLICT DO NOTHING"
                ),
                {"p": packet_id, "now": now},
            )
        connection.execute(
            text(
                "INSERT INTO mesh_packet_metrics (from_node_num, to_node_num, packet_id, "
                "pki_encrypted, time) VALUES (7501, 7502, 92, true, :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        sealed = client.get("/api/packets/!00001d4d/92").json()
        unknown = client.get("/api/packets/!00001d4d/93").json()

    assert sealed["packet"]["pki_encrypted"] is True
    assert unknown["packet"]["pki_encrypted"] is None, "no row is not the same as false"


def test_a_sender_gatewaying_itself_is_not_a_direct_observation(
    migrated_engine, timescale_url: str
) -> None:  # type: ignore[no-untyped-def]
    """A node that uploads its own packet heard nothing over the radio.

    The sender is often its own MQTT gateway. Such a row always has
    hop_start equal to hop_limit, so the hop rule alone calls it direct
    and then offers its reading as the sender's own link. It measures
    no link at all.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, "
                "first_seen_at) VALUES (8501, 91, 1, 3, :now) ON CONFLICT DO NOTHING"
            ),
            {"now": now},
        )
        for gateway in (8501, 8502):
            connection.execute(
                text(
                    "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                    "mqtt_topic, hop_limit, rx_snr, seen_at) "
                    "VALUES (8501, 91, :g, 'msh/US/AZ/t', 3, 5.0, :now) ON CONFLICT DO NOTHING"
                ),
                {"g": gateway, "now": now},
            )
        # The same gateway uploads the packet a second time.
        connection.execute(
            text(
                "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                "mqtt_topic, hop_limit, rx_snr, seen_at) "
                "VALUES (8501, 91, 8502, 'msh/US/AZ/t', 3, 5.0, :later) ON CONFLICT DO NOTHING"
            ),
            {"later": now + timedelta(seconds=5)},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        body = client.get("/api/packets/!00002135/91").json()

    by_gateway = {row["gateway"]: row for row in body["observations"]}
    own = by_gateway["!00002135"]
    other = by_gateway["!00002136"]

    assert own["self_reported"] is True
    assert own["direct"] is False, "a node does not hear itself over the radio"
    assert other["self_reported"] is False
    assert other["direct"] is True, "a gateway that used no hop did hear the sender"

    # Three uploads arrived, but only two gateways sent them.
    assert len(body["observations"]) == 3
    assert body["gateway_count"] == 2


def test_heard_by_does_not_credit_a_self_upload_with_signal(
    migrated_engine, timescale_url: str
) -> None:  # type: ignore[no-untyped-def]
    """The Heard by table gives a self upload no direct count and no SNR.

    The table splits observations into direct and relayed and shows a
    signal figure for the direct ones. A gateway that is the node itself
    uploads its own voice, which the hop rule alone reads as direct. It
    must carry neither a direct count nor an SNR. See AGENTS.md 9.5.1.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, "
                "first_seen_at) VALUES (8531, 97, 1, 3, :now) ON CONFLICT DO NOTHING"
            ),
            {"now": now},
        )
        # 8531 uploads its own packet; 8532 hears it with no hop. Both
        # rows have the hop limits equal, so only the node tells them
        # apart.
        for gateway in (8531, 8532):
            connection.execute(
                text(
                    "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                    "mqtt_topic, channel, hop_limit, rx_snr, seen_at) "
                    "VALUES (8531, 97, :g, 'msh/US/AZ/t', 'LongFast', 3, 5.0, :now) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"g": gateway, "now": now},
            )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        rows = client.get("/api/nodes/!00002153/heard-by").json()

    by_gateway = {row["node_id"]: row for row in rows}
    own = by_gateway["!00002153"]
    other = by_gateway["!00002154"]

    # The node's own upload is not a direct link to itself and has no
    # signal figure, even though its hop numbers are equal.
    assert own["direct_count"] == 0
    assert own["avg_snr"] is None
    # The other gateway used no hop, so it heard the sender directly.
    assert other["direct_count"] == 1
    assert other["avg_snr"] == 5.0


def test_traffic_events_carry_the_hop_count(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The live map says how far a relayed line is from the truth.

    An ordinary packet carries no route, so which nodes it passed
    through is not recorded and cannot be drawn. The hop count is the
    whole of what is known.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, "
                "first_seen_at) VALUES (8601, 93, 1, 5, :now) ON CONFLICT DO NOTHING"
            ),
            {"now": now},
        )
        for gateway, hop_limit in ((8602, 2), (8603, 5)):
            connection.execute(
                text(
                    "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                    "mqtt_topic, channel, hop_limit, seen_at) "
                    "VALUES (8601, 93, :g, 'msh/US/AZ/t', 'LongFast', :h, :now) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"g": gateway, "h": hop_limit, "now": now},
            )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        events = client.get("/api/map/traffic?minutes=60&limit=400").json()["events"]

    mine = {e["gateway"]["node_id"]: e for e in events if e["packet_id"] == 93}
    relayed = mine["!0000219a"]
    straight = mine["!0000219b"]

    # Five hops were available and two remain, so three were burned.
    assert relayed["hops_taken"] == 3
    assert relayed["direct"] is False
    # Nothing was burned, so this gateway heard the sender itself.
    assert straight["hops_taken"] == 0
    assert straight["direct"] is True


def test_traffic_counts_the_window_not_the_limit(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The summary answers the window the reader picked.

    Counting the rows that came back reported the cap instead: a busy
    mesh fills it in a couple of minutes, so every longer window
    answered with the same number and the picker looked broken.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for offset in range(6):
            # Half of them used no hop, so half are direct.
            hop_limit = 4 if offset % 2 else 3
            connection.execute(
                text(
                    "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, "
                    "first_seen_at) VALUES (8801, :p, 1, 4, :now) ON CONFLICT DO NOTHING"
                ),
                {"p": 9400 + offset, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                    "mqtt_topic, channel, hop_limit, seen_at) "
                    "VALUES (8801, :p, 8802, 'msh/US/AZ/t', 'CountWindow', :h, :now) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"p": 9400 + offset, "h": hop_limit, "now": now},
            )

    # A channel name unique to this test, so the window counts see only
    # its own rows. The database is shared across the session with no
    # cleanup, so a count over a shared preset would move as other tests
    # add rows to it.
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        body = client.get("/api/map/traffic?minutes=60&limit=2&channel=CountWindow").json()

    # The limit holds back the events, and nothing else.
    assert body["returned_count"] == 2
    assert len(body["events"]) == 2
    assert body["truncated"] is True
    assert body["event_count"] == 6
    assert body["direct_count"] == 3


def test_traffic_reads_the_packet_within_the_lookback(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The packet is looked for from a little before the window.

    A packet is first heard slightly before the other gateways upload
    it, so the packet read looks back before the window. A packet first
    heard longer ago than that lookback reads with a null port number
    and no hop count, and cannot be called direct. This pins the edge on
    both sides of it.
    """
    now = datetime.now(UTC)
    within = now - timedelta(minutes=5)
    # Well past the ten minute lookback of a five minute window.
    stale = now - timedelta(minutes=40)
    with migrated_engine.begin() as connection:
        for packet_id, first_seen in ((9500, within), (9501, stale)):
            connection.execute(
                text(
                    "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, "
                    "first_seen_at) VALUES (8811, :p, 1, 3, :seen) ON CONFLICT DO NOTHING"
                ),
                {"p": packet_id, "seen": first_seen},
            )
            # Both observations sit inside the window; only the packet
            # row of one is old enough to fall out of the lookback.
            connection.execute(
                text(
                    "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                    "mqtt_topic, channel, hop_limit, seen_at) "
                    "VALUES (8811, :p, 8812, 'msh/US/AZ/t', 'Lookback', 3, :now) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"p": packet_id, "now": now},
            )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        body = client.get("/api/map/traffic?minutes=5&limit=50&channel=Lookback").json()

    events = {event["packet_id"]: event for event in body["events"]}
    fresh = events[9500]
    old = events[9501]

    # The fresh packet is within the lookback, so it reads in full and
    # its equal hop numbers make it direct.
    assert fresh["hop_start"] == 3
    assert fresh["portnum"] == "TEXT_MESSAGE_APP"
    assert fresh["direct"] is True

    # The old packet fell out of the lookback, so it has no hop start,
    # no port number, and cannot be called direct.
    assert old["hop_start"] is None
    assert old["portnum"] is None
    assert old["direct"] is False

    # Both observations are in the window, so both are counted, but only
    # the one the packet read could reach counts as direct.
    assert body["event_count"] == 2
    assert body["direct_count"] == 1


def test_traffic_does_not_call_a_self_upload_direct(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A node uploading its own packet is not a direct radio link.

    The sender is often its own gateway, so it uploads the packet it just
    sent. Such a row carries hop_start equal to hop_limit, so the hop
    rule alone calls it direct and then offers the reading as the
    sender's own link. It must not count. See AGENTS.md 9.5.1.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, "
                "first_seen_at) VALUES (8821, 96, 1, 3, :now) ON CONFLICT DO NOTHING"
            ),
            {"now": now},
        )
        # 8821 uploads its own packet, and 8822 hears it with no hop. The
        # hop numbers are equal on both rows, so only the node tells them
        # apart: the self upload is not direct, the other gateway is.
        for gateway in (8821, 8822):
            connection.execute(
                text(
                    "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                    "mqtt_topic, channel, hop_limit, seen_at) "
                    "VALUES (8821, 96, :g, 'msh/US/AZ/t', 'SelfUpload', 3, :now) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"g": gateway, "now": now},
            )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        body = client.get("/api/map/traffic?minutes=60&limit=50&channel=SelfUpload").json()

    events = {event["gateway"]["node_id"]: event for event in body["events"]}
    # The sender's own upload used no hop, but a node does not hear itself
    # over the radio, so it is not direct.
    assert events["!00002275"]["direct"] is False
    # Another gateway that used no hop did hear the sender directly.
    assert events["!00002276"]["direct"] is True

    # Two observations, one direct, so the self upload is left out of the
    # count as well as the flag.
    assert body["event_count"] == 2
    assert body["direct_count"] == 1


def test_a_link_says_whether_a_reply_confirmed_it(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A hop known only from an unanswered request is marked one way.

    The broker sees a request in flight, so the hops it has already made
    are real and measured. Nothing came back to confirm the round trip,
    so the evidence runs one way and the page may want to say so.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for node_num in (8701, 8702, 8703, 8704):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                    "last_heard) VALUES (:n, :nid, :sn, :now, :now, :now) "
                    "ON CONFLICT (node_num) DO NOTHING"
                ),
                {"n": node_num, "nid": f"!{node_num:08x}", "sn": f"C{node_num}", "now": now},
            )
        # An unanswered request. It reached 8702 and stopped there.
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "route, snr_towards, seen_at) "
                "VALUES (8701, 8703, 'ShortSlow', 870001, CAST('[8702]' AS jsonb), "
                "CAST('[12]' AS jsonb), :now)"
            ),
            {"now": now},
        )
        # A reply, which proves its whole path.
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "request_id, route, snr_towards, seen_at) "
                "VALUES (8704, 8701, 'ShortSlow', 870003, 870002, CAST('[8702]' AS jsonb), "
                "CAST('[12, 20]' AS jsonb), :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        links = client.get("/api/graph?hours=24&channel=ShortSlow").json()["links"]
    by_pair = {frozenset((link["source"], link["target"])): link for link in links}

    # 8702 to 8703 is the hop the request never made, so it is absent.
    assert frozenset(("!000021fe", "!000021ff")) not in by_pair

    # 8701 to 8702 is evidenced by both, and one of them came back.
    assert by_pair[frozenset(("!000021fd", "!000021fe"))]["confirmed"] is True

    # 8702 to 8704 is the reply's own last hop, so it is confirmed too.
    assert by_pair[frozenset(("!000021fe", "!00002200"))]["confirmed"] is True


def test_a_request_only_link_is_marked_one_way(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Nothing answered, so the link carries one-way evidence only."""
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for node_num in (8801, 8802):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                    "last_heard) VALUES (:n, :nid, :sn, :now, :now, :now) "
                    "ON CONFLICT (node_num) DO NOTHING"
                ),
                {"n": node_num, "nid": f"!{node_num:08x}", "sn": f"O{node_num}", "now": now},
            )
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "route, snr_towards, seen_at) "
                "VALUES (8801, 8899, 'LongSlow', 880001, CAST('[8802]' AS jsonb), "
                "CAST('[12]' AS jsonb), :now)"
            ),
            {"now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        links = client.get("/api/graph?hours=24&channel=LongSlow").json()["links"]
    by_pair = {frozenset((link["source"], link["target"])): link for link in links}
    link = by_pair[frozenset(("!00002261", "!00002262"))]
    assert link["confirmed"] is False, "no reply came back, so the evidence runs one way"
    assert link["snr"] == 3.0, "the hop was still measured"


def test_map_nodes_follow_the_preset(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The dots on the map belong to the preset the lines belong to.

    A node on LongFast cannot hear a node on MediumFast, so drawing both
    sets of dots under one preset's lines invites the reader to join two
    nodes that have no way to reach each other. See AGENTS.md 9.7.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for node_num, lat in ((8901, 33.1), (8902, 33.2), (8903, 33.3)):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                    "last_heard, last_lat, last_lon) "
                    "VALUES (:n, :nid, :sn, :now, :now, :now, :lat, -112.0) "
                    "ON CONFLICT (node_num) DO NOTHING"
                ),
                {
                    "n": node_num,
                    "nid": f"!{node_num:08x}",
                    "sn": f"M{node_num}",
                    "now": now,
                    "lat": lat,
                },
            )
        # 8901 talks on LongFast, 8902 on MediumFast. 8903 talks on both,
        # which a real dual-preset node does.
        for node_num, packet_id, channel in (
            (8901, 890001, "LongFast"),
            (8902, 890002, "MediumFast"),
            (8903, 890003, "LongFast"),
            (8903, 890004, "MediumFast"),
        ):
            connection.execute(
                text(
                    "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                    "mqtt_topic, channel, seen_at) "
                    "VALUES (:n, :p, 8901, 'msh/US/AZ/t', :c, :now) ON CONFLICT DO NOTHING"
                ),
                {"n": node_num, "p": packet_id, "c": channel, "now": now},
            )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        long_fast = {n["node_id"] for n in client.get("/api/map/nodes?channel=LongFast").json()}
        medium = {n["node_id"] for n in client.get("/api/map/nodes?channel=MediumFast").json()}
        every = {n["node_id"] for n in client.get("/api/map/nodes").json()}

    assert "!000022c5" in long_fast  # 8901
    assert "!000022c6" not in long_fast, "a MediumFast node must not sit under LongFast lines"
    assert "!000022c6" in medium  # 8902
    assert "!000022c5" not in medium

    # A node that really runs both presets belongs to both.
    assert "!000022c7" in long_fast and "!000022c7" in medium

    # Without the parameter the map holds every positioned node.
    assert {"!000022c5", "!000022c6", "!000022c7"} <= every


# --- the conversation endpoint -----------------------------------------
#
# It matched on `packet_pk`, which nothing writes, so it could never find
# a message. Nothing in the dashboard called it, so nothing noticed.


def _seed_conversation(engine) -> None:  # type: ignore[no-untyped-def]
    """Two senders reusing one packet ID, plus a reply and a tapback."""
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM text_message WHERE from_node_num BETWEEN 9400 AND 9499")
        )
        # A packet ID is only unique per sender, so both of these are
        # packet 4242 and only the sender tells them apart.
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, "
                "body, packet_id, seen_at, emoji) VALUES "
                "(9401, 0, 'LongFast', 'mine', 4242, :now, false), "
                "(9402, 0, 'LongFast', 'not mine', 4242, :now, false)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, "
                "body, packet_id, reply_id, seen_at, emoji) VALUES "
                "(9403, 0, 'LongFast', 'a reply', 5001, 4242, :later, false), "
                "(9404, 0, 'LongFast', '\U0001f44d', 5002, 4242, :later, true)"
            ),
            {"later": now + timedelta(seconds=30)},
        )


def test_the_conversation_endpoint_finds_a_message(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A message is addressed by its sender and its packet ID."""
    _seed_conversation(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        response = client.get("/api/chat/conversation/!000024b9/4242")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["message"]["body"] == "mine"


def test_the_conversation_endpoint_keeps_two_senders_apart(
    migrated_engine, timescale_url: str
) -> None:  # type: ignore[no-untyped-def]
    """Packet 4242 from one node is not packet 4242 from another."""
    _seed_conversation(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        mine = client.get("/api/chat/conversation/!000024b9/4242").json()
        theirs = client.get("/api/chat/conversation/!000024ba/4242").json()
    assert mine["message"]["body"] == "mine"
    assert theirs["message"]["body"] == "not mine"


def test_the_conversation_endpoint_returns_replies_but_not_tapbacks(
    migrated_engine, timescale_url: str
) -> None:  # type: ignore[no-untyped-def]
    """A tapback is a reply in the wire format and not one to a reader."""
    _seed_conversation(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        body = client.get("/api/chat/conversation/!000024b9/4242").json()
    bodies = [reply["body"] for reply in body["replies"]]
    assert bodies == ["a reply"]


def test_an_unknown_conversation_is_a_404(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    _seed_conversation(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        assert client.get("/api/chat/conversation/!000024b9/999999").status_code == 404


def test_a_malformed_sender_is_a_422_not_a_500(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A bad node ID is a bad request. It used to raise and become a 500."""
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        assert client.get("/api/chat/conversation/nonsense/4242").status_code == 422
        assert client.get("/api/chat?from=nonsense").status_code == 422


# --- user input must not reach the query's grammar ----------------------


def _seed_wildcards(engine) -> None:  # type: ignore[no-untyped-def]
    """Names and bodies that a LIKE pattern would confuse."""
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM node WHERE node_num BETWEEN 9500 AND 9599"))
        connection.execute(
            text("DELETE FROM text_message WHERE from_node_num BETWEEN 9500 AND 9599")
        )
        connection.execute(
            text(
                "INSERT INTO node (node_num, node_id, long_name, short_name, "
                "first_seen, last_heard, updated_at) VALUES "
                "(9501, '!0000251d', 'Ridge Top', 'RT', :now, :now, :now), "
                "(9502, '!0000251e', 'Ridge_Top', 'R_T', :now, :now, :now), "
                "(9503, '!0000251f', 'RidgeXTop', 'RXT', :now, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO text_message (from_node_num, to_node_num, channel, "
                "body, packet_id, seen_at, emoji) VALUES "
                "(9501, 0, 'LongFast', 'plain body', 7001, :now, false), "
                "(9502, 0, 'LongFast', '100% sure', 7002, :now, false)"
            ),
            {"now": now},
        )


def test_a_node_search_treats_an_underscore_as_a_character(
    migrated_engine, timescale_url: str
) -> None:  # type: ignore[no-untyped-def]
    """`Ridge_Top` must not also find `RidgeXTop`."""
    _seed_wildcards(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        found = client.get("/api/nodes?q=Ridge_Top&limit=50").json()
    names = {row["long_name"] for row in found}
    assert "Ridge_Top" in names
    assert "RidgeXTop" not in names


def test_a_bare_percent_does_not_match_every_node(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """`%` used to be a full scan anybody could ask a public endpoint for."""
    _seed_wildcards(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        everything = client.get("/api/nodes?limit=500").json()
        wildcard = client.get("/api/nodes?q=%25&limit=500").json()
    assert len(wildcard) < len(everything)


def test_a_percent_in_a_message_search_is_a_character(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Searching for `100%` finds the message that says 100%."""
    _seed_wildcards(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        hits = client.get("/api/chat?q=100%25&limit=50").json()
    bodies = [row["body"] for row in hits]
    assert "100% sure" in bodies
    assert "plain body" not in bodies


def test_a_malformed_node_id_is_422_on_every_filter(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """It was a 500 on four of these, depending which endpoint you asked."""
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    paths = (
        "/api/packets?from=nonsense",
        "/api/packets?to=nonsense",
        "/api/traceroutes?from=nonsense",
        "/api/traceroutes?to=nonsense",
        "/api/chat?from=nonsense",
        "/api/graph/link?a=nonsense&b=nonsense",
    )
    with TestClient(app) as client:
        for path in paths:
            assert client.get(path).status_code == 422, path


def test_the_daily_snapshot_days_parameter_is_bounded(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """`days=-1` became `LIMIT -1`, which Postgres rejects with a 500."""
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        assert client.get("/api/stats/snapshots/daily?days=-1").status_code == 422
        assert client.get("/api/stats/snapshots/daily?days=0").status_code == 422
        assert client.get("/api/stats/snapshots/daily?days=9999").status_code == 422
        assert client.get("/api/stats/snapshots/daily?days=30").status_code == 200


# --- what the whole-table endpoints cost ---------------------------------
#
# `/api/stats`, `/api/stats/hardware` and `/api/stats/portnums` are the
# only answers in the API with no time window. They count every row ever
# kept, so the work grows with retention and never with what the reader
# asked for, and the dashboard asks for all three on every load.


def test_the_statistics_are_counted_once_and_then_held(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """A second reader inside the hold is answered without a new scan.

    Asserted by changing the database underneath and watching the
    answer not move. That is the behaviour a cache has; a mock of the
    session would only assert that this test knows how the code is
    written.
    """
    _seed(migrated_engine)
    app = create_app(
        Settings(
            _env_file=None,
            database_url_api=_api_url(timescale_url),
            stats_cache_seconds=300.0,
        )
    )
    with TestClient(app) as client:
        first = client.get("/api/stats").json()
        assert first["node_count"] >= 1

        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, "
                    "updated_at, last_heard) "
                    "VALUES (4343, '!000010f7', 'CACHE', now(), now(), now()) "
                    "ON CONFLICT (node_num) DO NOTHING"
                )
            )

        second = client.get("/api/stats").json()
        assert second == first, "the second read counted the table again"

    # And the new row is there, so the hold is what held it back and not
    # a write that never landed.
    with migrated_engine.connect() as connection:
        total = connection.execute(text("SELECT count(*) FROM node")).scalar_one()
    assert total > first["node_count"]


def test_a_hold_of_zero_counts_every_time(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """`STATS_CACHE_SECONDS=0` is how a deployment asks for live figures.

    The guard has to be seen in both states. A cache only ever observed
    holding is a cache nobody has watched let go.
    """
    _seed(migrated_engine)
    app = create_app(
        Settings(
            _env_file=None,
            database_url_api=_api_url(timescale_url),
            stats_cache_seconds=0.0,
        )
    )
    with TestClient(app) as client:
        first = client.get("/api/stats").json()
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, "
                    "updated_at, last_heard) "
                    "VALUES (4344, '!000010f8', 'LIVE', now(), now(), now()) "
                    "ON CONFLICT (node_num) DO NOTHING"
                )
            )
        second = client.get("/api/stats").json()

    assert second["node_count"] > first["node_count"]


def test_the_grouped_statistics_are_held_too(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """`/hardware` and `/portnums` are ungrouped full scans of their table."""
    _seed(migrated_engine)
    app = create_app(
        Settings(
            _env_file=None,
            database_url_api=_api_url(timescale_url),
            stats_cache_seconds=300.0,
        )
    )
    with TestClient(app) as client:
        hardware = client.get("/api/stats/hardware").json()
        portnums = client.get("/api/stats/portnums").json()

        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, hw_model, "
                    "first_seen, updated_at, last_heard) "
                    "VALUES (4345, '!000010f9', 'HW', 'A_NEW_MODEL', now(), now(), now()) "
                    "ON CONFLICT (node_num) DO NOTHING"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO packet (from_node_num, packet_id, portnum, first_seen_at) "
                    "VALUES (4242, 991, 67, now()) ON CONFLICT DO NOTHING"
                )
            )

        assert client.get("/api/stats/hardware").json() == hardware
        assert client.get("/api/stats/portnums").json() == portnums


# --- the public node list, against a real table --------------------------
#
# `/api/embed/nodes` used to be `select(Node)`: every row and every
# column into Python, then filtered. The filters are in the query now.
# The rule that decides who is public did not move — `public_nodes` in
# `embed/sanitise.py` still applies it to every row that arrives — so
# these tests exist to prove the narrowing did not change the answer.


def _seed_public_and_private(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """Insert one node of each kind the public rule has to sort out."""
    rows = [
        # (node_num, short, role, lat, lon, gateway)
        (5001, "RTR", "ROUTER", 33.45, -112.07, False),
        (5002, "RPT", "REPEATER", 33.50, -112.10, False),
        (5003, "RLT", "ROUTER_LATE", 33.55, -112.15, False),
        # A client is a person's house. Never public, whatever else.
        (5004, "CLI", "CLIENT", 33.60, -112.20, False),
        # A NULL role is a client, not an unknown. See AGENTS.md 9.22.
        (5005, "NUL", None, 33.65, -112.25, False),
        # A gateway is not evidence of infrastructure by itself.
        (5006, "GWC", "CLIENT", 33.70, -112.30, True),
        # A router with no position cannot be drawn.
        (5007, "NOP", "ROUTER", None, None, False),
        # A router at Null Island never had a fix.
        (5008, "NIL", "ROUTER", 0.0, 0.0, False),
        # Lower case in the column must still match the role table.
        (5009, "LOW", "router", 33.75, -112.35, False),
    ]
    with migrated_engine.begin() as connection:
        for node_num, short, role, lat, lon, gateway in rows:
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, role, last_lat, "
                    "last_lon, is_mqtt_gateway, first_seen, updated_at, last_heard) "
                    "VALUES (:n, :i, :s, :r, :lat, :lon, :g, now(), now(), now()) "
                    "ON CONFLICT (node_num) DO UPDATE SET role = :r, last_lat = :lat, "
                    "last_lon = :lon, is_mqtt_gateway = :g"
                ),
                {
                    "n": node_num,
                    "i": f"!{node_num:08x}",
                    "s": short,
                    "r": role,
                    "lat": lat,
                    "lon": lon,
                    "g": gateway,
                },
            )


def _embed_app(timescale_url: str):  # type: ignore[no-untyped-def]
    """An app with the embed switched on, reading the SELECT-only role."""
    return create_app(
        Settings(
            _env_file=None,
            database_url_api=_api_url(timescale_url),
            embed_enabled=True,
            embed_position_step=0.01,
        )
    )


def test_the_public_node_list_shows_infrastructure_only(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """The filters moved into SQL. The answer must not have moved."""
    _seed_public_and_private(migrated_engine)
    with TestClient(_embed_app(timescale_url)) as client:
        response = client.get("/api/embed/nodes")
    assert response.status_code == 200
    names = {node["short_name"] for node in response.json()}

    # Infrastructure with a usable position, including the lower case
    # role, which `upper()` in the query has to fold.
    assert {"RTR", "RPT", "RLT", "LOW"} <= names
    # And nothing else. Each of these was a way in.
    for absent in ("CLI", "NUL", "GWC", "NOP", "NIL"):
        assert absent not in names, f"{absent} reached the public list"


def test_the_public_node_list_sends_no_long_name_or_exact_position(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """The columns that are not read are the ones the embed keeps back.

    `select(Node)` carried the long name, the public key and the raw
    position out of the database only to throw them away in Python.
    They are not selected at all now, so they never cross the wire.
    """
    _seed_public_and_private(migrated_engine)
    with TestClient(_embed_app(timescale_url)) as client:
        nodes = client.get("/api/embed/nodes").json()

    assert nodes
    for node in nodes:
        assert set(node) == {"short_name", "lat", "lon", "role", "is_gateway"}

    # The position is snapped, so it names a hill and not a building.
    router = next(node for node in nodes if node["short_name"] == "RTR")
    assert router["lat"] != 33.45
    assert abs(router["lat"] - 33.45) < 0.02


# --- the traffic window count ------------------------------------------
#
# It read the packet behind each observation with a correlated subquery,
# one index probe per row, on a public endpoint the map polls every
# fifteen seconds (ISSUES.md 2.9). It is now a join against the window's
# distinct packet keys, deduplicated first. These pin the two cases that
# make such a join wrong if it is written carelessly.


def _seed_traffic_counts(engine) -> None:  # type: ignore[no-untyped-def]
    """One packet duplicated, one observation whose packet is missing."""
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM packet_seen WHERE from_node_num BETWEEN 9600 AND 9699")
        )
        connection.execute(text("DELETE FROM packet WHERE from_node_num BETWEEN 9600 AND 9699"))
        # The canonical row is the EARLIEST. Its hop_start matches the
        # observation's hop_limit, so the observation is direct. The
        # duplicate, written later, says otherwise and must not be read.
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, want_ack, "
                "first_seen_at, hop_start, hop_limit, channel) VALUES "
                "(9601, 5100, 3, false, :early, 3, 3, 'LongFast'), "
                "(9601, 5100, 3, false, :late,  9, 3, 'LongFast'), "
                "(9601, 5101, 3, false, :early, 3, 3, 'LongFast')"
            ),
            {"early": now - timedelta(minutes=2), "late": now - timedelta(minutes=1)},
        )
        connection.execute(
            text(
                "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                "mqtt_topic, seen_at, hop_limit, channel) VALUES "
                # direct: canonical hop_start 3 == hop_limit 3, and the
                # gateway is not the sender
                "(9601, 5100, 9602, 'test', :now, 3, 'LongFast'), "
                # a self-upload is never a radio link (AGENTS.md 9.5.1)
                "(9601, 5101, 9601, 'test', :now, 3, 'LongFast'), "
                # no packet row at all: unknown, so not direct
                "(9601, 5199, 9603, 'test', :now, 3, 'LongFast')"
            ),
            {"now": now - timedelta(seconds=30)},
        )


def test_the_traffic_count_reads_the_canonical_duplicate(
    migrated_engine, timescale_url: str
) -> None:  # type: ignore[no-untyped-def]
    """A duplicated packet must be counted once, from its earliest row."""
    _seed_traffic_counts(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        body = client.get("/api/map/traffic?minutes=15&channel=LongFast&limit=2000").json()
    # Other tests seed this channel too, so assert on these rows rather
    # than on the window totals. That is also the sharper question: the
    # duplicate packet row must not multiply the one observation that
    # points at it.
    mine = [event for event in body["events"] if event["packet_id"] == 5100]
    assert len(mine) == 1, mine
    assert mine[0]["direct"] is True, mine[0]

    # A node uploading its own packet is never a radio link.
    own = [event for event in body["events"] if event["packet_id"] == 5101]
    assert len(own) == 1, own
    assert own[0]["direct"] is False, own[0]


def test_an_observation_with_no_packet_is_not_direct(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Unknown is not the same as direct. A left join must not invent one."""
    _seed_traffic_counts(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        body = client.get("/api/map/traffic?minutes=15&channel=LongFast").json()
    orphan = [e for e in body["events"] if e["packet_id"] == 5199]
    assert orphan, "the orphan observation was dropped from the events"
    assert orphan[0]["direct"] is False


# --- the nodes list: ordering, paging, and an honest total -------------
#
# The list is capped, so the page cannot count the rows it received and
# call that the answer, and it cannot sort the rows it holds and call
# that the order. Both were true before; these hold them true.


def _seed_node_list(engine) -> None:  # type: ignore[no-untyped-def]
    """Nodes that tie on role, and one of each position confidence."""
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM node WHERE node_num BETWEEN 9700 AND 9799"))
        rows = [
            # num, name, role, lat, lon, bits
            (9701, "alpha", "ROUTER", 33.5, -112.1, None),
            (9702, "bravo", "ROUTER", 33.6, -112.2, 13),
            (9703, "charlie", "ROUTER", None, None, None),
            (9704, "delta", "CLIENT", 33.7, -112.3, None),
            (9705, "echo", None, 33.8, -112.4, 13),
            (9706, "foxtrot", None, 0.0, 0.0, None),
        ]
        for num, name, role, lat, lon, bits in rows:
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, long_name, role, "
                    "last_lat, last_lon, last_position_precision_bits, "
                    "first_seen, last_heard, updated_at) VALUES "
                    "(:num, :nid, :name, :role, :lat, :lon, :bits, :now, :now, :now)"
                ),
                {
                    "num": num,
                    "nid": f"!{num:08x}",
                    "name": name,
                    "role": role,
                    "lat": lat,
                    "lon": lon,
                    "bits": bits,
                    "now": now,
                },
            )


def test_the_total_counts_matches_not_returned_rows(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The page said "300 nodes match" when it meant "here are 300"."""
    _seed_node_list(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        response = client.get("/api/nodes?limit=2")
        every = client.get("/api/nodes?limit=500")
    assert len(response.json()) == 2
    total = int(response.headers["X-Total-Count"])
    assert total == len(every.json())
    assert total > 2, "the fixture is too small to tell a cap from a count"


def test_an_unknown_sort_is_refused_by_name(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Nothing a caller sends may reach the query."""
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        answer = client.get("/api/nodes?sort=last_heard%3B+drop+table+node")
    assert answer.status_code == 422
    assert "sort must be one of" in answer.json()["detail"]


def test_paging_returns_each_node_once(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The tie-break is what makes this true when a column has ties.

    Sorting by role puts several nodes on the same value. Without a
    total order Postgres may place equal rows differently between two
    queries, and a node then lands on two pages or on none.
    """
    _seed_node_list(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    seen: list[str] = []
    with TestClient(app) as client:
        first = client.get("/api/nodes?sort=role&order=asc&limit=3&offset=0")
        total = int(first.headers["X-Total-Count"])
        seen += [row["node_id"] for row in first.json()]
        offset = len(seen)
        while offset < total and offset < 500:
            page = client.get(f"/api/nodes?sort=role&order=asc&limit=3&offset={offset}")
            rows = page.json()
            if not rows:
                break
            seen += [row["node_id"] for row in rows]
            offset += len(rows)
    assert len(seen) == len(set(seen)), "a node arrived on two pages"
    assert len(set(seen)) == total, "a node arrived on no page"


def test_nulls_sort_last_whichever_way_it_was_clicked(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A node with no role is not the smallest role."""
    _seed_node_list(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        for order in ("asc", "desc"):
            rows = client.get(f"/api/nodes?sort=role&order={order}&limit=500").json()
            roles = [row["role"] for row in rows]
            named = [index for index, role in enumerate(roles) if role is not None]
            blank = [index for index, role in enumerate(roles) if role is None]
            if named and blank:
                assert max(named) < min(blank), f"{order}: a null sorted before a value"


def test_position_filter_matches_the_gaps_rule(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The three states must partition the list, and agree with Python.

    A node that sent no precision field at all is exact, not missing.
    Null island is no position. If this drifts from
    `gaps.signals.position_confidence`, two pages disagree about one
    node.
    """
    _seed_node_list(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        totals = {}
        for state in ("exact", "coarse", "none"):
            answer = client.get(f"/api/nodes?limit=1&position={state}")
            totals[state] = int(answer.headers["X-Total-Count"])
        everything = int(client.get("/api/nodes?limit=1").headers["X-Total-Count"])
        none_rows = client.get("/api/nodes?limit=500&position=none").json()
    assert sum(totals.values()) == everything, totals
    ids = {row["node_id"] for row in none_rows}
    assert f"!{9703:08x}" in ids, "a node with no coordinates is not 'no position'"
    assert f"!{9706:08x}" in ids, "null island is not 'no position'"


# --- the filter panel: facets and the gaps filter ----------------------


def test_facets_count_with_their_own_filter_lifted(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Counting a facet with itself applied answers the wrong question.

    It would show the chosen value holding everything and the others
    holding nothing, which tells a reader only that the filter is on.
    What they are asking is "if I picked this instead, how many".
    """
    _seed_node_list(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        loose = client.get("/api/nodes/facets").json()
        tight = client.get("/api/nodes/facets?role=ROUTER").json()
    roles = {entry["value"]: entry["count"] for entry in loose["role"]}
    still = {entry["value"]: entry["count"] for entry in tight["role"]}
    assert still == roles, "the role facet narrowed itself"
    assert any(entry["value"] == "CLIENT" for entry in tight["role"]), (
        "a role you could switch to disappeared from its own facet"
    )


def test_facets_narrow_the_other_groups(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Every other facet must answer within the filters in force."""
    _seed_node_list(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        loose = client.get("/api/nodes/facets").json()
        tight = client.get("/api/nodes/facets?role=ROUTER").json()
    total = sum(entry["count"] for entry in loose["position"])
    narrowed = sum(entry["count"] for entry in tight["position"])
    assert narrowed < total, f"position did not narrow under a role filter ({narrowed} vs {total})"


def test_gaps_without_a_preset_is_refused(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A node can need help on one preset and be fine on another.

    Answering "needs help" without saying on which mesh would be the
    merge AGENTS.md 9.7 forbids everywhere else.
    """
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        answer = client.get("/api/nodes?gaps=bad")
    assert answer.status_code == 422
    assert "gaps_preset" in answer.json()["detail"]


def test_an_unassessed_preset_is_not_an_empty_answer(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """No assessment is a different fact from no nodes.

    Returning an empty list would say "no node needs help", which is an
    answer we do not have.
    """
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        answer = client.get("/api/nodes?gaps=bad&gaps_preset=NoSuchPreset")
    assert answer.status_code == 409
    assert "no gap assessment" in answer.json()["detail"]


def test_the_summary_returns_what_the_filters_need(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The channel picker offered nothing because the list never said.

    `channel` was filterable before it was returned, so the control that
    built its options from the rows could never list one.
    """
    _seed_node_list(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        rows = client.get("/api/nodes?limit=500").json()
    assert rows, "the fixture seeded nothing"
    for field in ("channel", "is_licensed", "position_confidence"):
        assert field in rows[0], f"the list filters on {field} but does not return it"
    assert rows[0]["position_confidence"] in {"exact", "coarse", "none"}


def _seed_quiet_nodes(engine) -> None:  # type: ignore[no-untyped-def]
    """Nodes heard at three different times, plus one never heard at all.

    Every one carries a hardware model and a role, which the facet case
    below needs: those two facets drop the nodes that report nothing, so
    with NULLs in them their counts could not be compared to a total.
    """
    now = datetime.now(UTC)
    rows = [
        (9710, "fresh", now),
        (9711, "hours", now - timedelta(hours=2)),
        (9712, "weeks", now - timedelta(days=14)),
        (9713, "silent", None),
    ]
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM node WHERE node_num BETWEEN 9710 AND 9719"))
        for num, name, heard in rows:
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, long_name, hw_model, role, "
                    "first_seen, last_heard, updated_at) VALUES "
                    "(:num, :nid, :name, 'HELTEC_V3', 'CLIENT', :now, :heard, :now)"
                ),
                {"num": num, "nid": f"!{num:08x}", "name": name, "now": now, "heard": heard},
            )


def test_quiet_hours_is_the_other_side_of_active_hours(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """ "Which routers have gone quiet" had no way to be asked (§6.2).

    `active_hours` asks "heard since"; nothing asked "not heard since",
    which is the question. The only way to ask it was to widen the window
    to any time, sort ascending, and read from the top -- which answers a
    different question and puts the answer first by luck.

    The two must partition the nodes that have ever been heard, or a
    reader combining them gets rows that are in neither set or in both.
    """
    _seed_quiet_nodes(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        quiet = client.get("/api/nodes?limit=500&quiet_hours=1").json()
        active = client.get("/api/nodes?limit=500&active_hours=1").json()
        band = client.get("/api/nodes?limit=500&active_hours=24&quiet_hours=1").json()
        refused = client.get("/api/nodes?quiet_hours=0")
    names = {row["node_id"]: row["long_name"] for row in quiet}
    assert "hours" in names.values(), "a node heard two hours ago is not quiet for an hour"
    assert "weeks" in names.values(), "a node heard a fortnight ago is not quiet"
    assert "fresh" not in names.values(), "a node heard just now counts as quiet"
    # A node that has never been heard has no answer to "how long since",
    # and `active_hours` leaves it out too. It must not be quiet forever.
    assert "silent" not in names.values(), "a node never heard is reported as quiet"
    assert "silent" not in {row["long_name"] for row in active}

    ours = {f"!{num:08x}" for num in (9710, 9711, 9712)}
    quiet_ours = {row["node_id"] for row in quiet} & ours
    active_ours = {row["node_id"] for row in active} & ours
    assert not (quiet_ours & active_ours), "a node is both quiet and active for the same hour"
    assert quiet_ours | active_ours == ours, "a heard node is in neither set"

    # The band: heard this day, but not this hour.
    assert {row["long_name"] for row in band} & {"fresh", "hours", "weeks"} == {"hours"}, (
        "the two windows do not compose into a band"
    )
    assert refused.status_code == 422, "an hour of zero is not a window"


def test_the_facet_counts_honour_quiet_hours(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """A filter the facets endpoint ignores is the worst kind.

    FastAPI drops a query parameter a handler does not declare, without a
    word -- so a filter added to the list and forgotten here would leave
    every count in the panel describing a larger set than the rows beside
    them, which is the one thing that endpoint's docstring promises.

    **Every group, not one of them.** The endpoint counts the value facets
    through one helper and the position states through a statement of
    their own, so a filter can reach one path and not the other. Checking
    `position` alone passed against exactly that mutation.
    """
    _seed_quiet_nodes(migrated_engine)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        loose = client.get("/api/nodes/facets").json()
        tight = client.get("/api/nodes/facets?quiet_hours=1").json()
        rows = client.get("/api/nodes?limit=1&quiet_hours=1")
    total = int(rows.headers["X-Total-Count"])
    for group in ("position", "hw", "role"):
        counted = sum(entry["count"] for entry in tight[group])
        everything = sum(entry["count"] for entry in loose[group])
        assert counted == total, (
            f"the {group} facet counts {counted} nodes and the list counts {total}"
        )
        assert counted < everything, (
            f"quiet_hours changed nothing in the {group} facet "
            f"({counted} of {everything}), so it is being ignored there"
        )


def _seed_drawn_trace(migrated_engine, packet_id: int | None) -> int:  # type: ignore[no-untyped-def]
    """Insert one traceroute and return its row ID."""
    with migrated_engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    "INSERT INTO traceroute (from_node_num, to_node_num, packet_id, seen_at) "
                    "VALUES (7801, 7802, :p, :now) RETURNING id"
                ),
                {"p": packet_id, "now": datetime.now(UTC)},
            ).scalar_one()
        )


_GRAPHVIZ = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<g class="graph"><polygon fill="white" points="0,0 10,0 10,10"/>'
    b'<g class="edge"><path stroke="black" d="M0,0L5,5"/></g></g></svg>'
)


def test_the_trace_drawing_is_served_recoloured(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str, monkeypatch
) -> None:
    """mesh-graph's white drawing comes back transparent, with light edges (#51)."""
    from sonoran.api.routes import traceroutes

    asked: list[int] = []

    async def fake_fetch(settings, key):  # type: ignore[no-untyped-def]
        asked.append(key)
        return _GRAPHVIZ

    monkeypatch.setattr(traceroutes, "fetch_trace_svg", fake_fetch)
    trace_id = _seed_drawn_trace(migrated_engine, 780001)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        detail = client.get(f"/api/traceroutes/{trace_id}").json()
        response = client.get(f"/api/traceroutes/{trace_id}/drawing.svg")

    assert detail["drawing_url"] == f"api/traceroutes/{trace_id}/drawing.svg"
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert asked == [780001], "the trace key comes from the row, never from the request"
    assert b'fill="white"' not in response.content
    assert b'stroke="black"' not in response.content


def test_a_trace_mesh_graph_never_drew_is_a_404(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str, monkeypatch
) -> None:
    from sonoran.api.routes import traceroutes

    async def nothing(settings, key):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(traceroutes, "fetch_trace_svg", nothing)
    trace_id = _seed_drawn_trace(migrated_engine, 780002)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        assert client.get(f"/api/traceroutes/{trace_id}/drawing.svg").status_code == 404
        assert client.get("/api/traceroutes/999999999/drawing.svg").status_code == 404


def test_an_unreachable_mesh_graph_is_a_502(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str, monkeypatch
) -> None:
    import httpx

    from sonoran.api.routes import traceroutes

    async def down(settings, key):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(traceroutes, "fetch_trace_svg", down)
    trace_id = _seed_drawn_trace(migrated_engine, 780003)
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        assert client.get(f"/api/traceroutes/{trace_id}/drawing.svg").status_code == 502


def test_the_firehose_summary_says_what_each_packet_held(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """`summary=true` gives one line per packet, from its decoded row.

    A kind with nothing stored gets no line, never a guess. Battery above
    100 is how Meshtastic says the node is on external power.
    """
    now = datetime.now(UTC)
    sender = 7901
    with migrated_engine.begin() as connection:
        for packet_id, portnum in ((790001, 3), (790002, 67), (790003, 4), (790004, 67)):
            connection.execute(
                text(
                    "INSERT INTO packet (from_node_num, packet_id, portnum, hop_start, "
                    "first_seen_at) VALUES (:s, :p, :n, 3, :now) ON CONFLICT DO NOTHING"
                ),
                {"s": sender, "p": packet_id, "n": portnum, "now": now},
            )
        connection.execute(
            text(
                "INSERT INTO position_metrics (node_num, packet_id, latitude, longitude, "
                "precision_bits, time) VALUES (:s, 790001, 33.4484, -112.074, 13, :now)"
            ),
            {"s": sender, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO device_metrics (node_num, packet_id, battery_level, voltage, time) "
                "VALUES (:s, 790002, 101, 4.2, :now)"
            ),
            {"s": sender, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO environment_metrics (node_num, packet_id, temperature, "
                "relative_humidity, barometric_pressure, time) "
                "VALUES (:s, 790004, 21.5, 40, 1012.8, :now)"
            ),
            {"s": sender, "now": now},
        )

    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    with TestClient(app) as client:
        plain = client.get("/api/packets?from=!00001edd&limit=10").json()
        rich = client.get("/api/packets?from=!00001edd&limit=10&summary=true").json()

    assert "summary" not in plain[0], "summaries are opt in"
    by_id = {row["packet_key"].split(":")[1]: row["summary"] for row in rich}
    assert by_id["790001"].startswith("33.4484, -112.0740, within about")
    assert by_id["790002"] == "on power, 4.20 V"
    assert by_id["790003"] is None, "node info stores nothing to show"

    # A measurement is a number and its SI unit, for the browser to write
    # in the reader's units (#291). The line used to say "21.5 C" to
    # everybody, with no degree sign.
    parts = {row["packet_key"].split(":")[1]: row["summary_parts"] for row in rich}
    assert parts["790004"] == [
        {"value": 21.5, "unit": "°C"},
        ", ",
        "humidity 40 %",
        ", ",
        {"value": 1012.8, "unit": "hPa"},
    ]
    assert by_id["790004"] == "21.5 °C, humidity 40 %, 1012.8 hPa"
    position = parts["790001"]
    assert position[0] == "33.4484, -112.0740"
    assert position[1] == ", within about "
    assert position[2]["unit"] == "m" and position[2]["value"] > 0
    assert parts["790003"] is None


def _seed_four_kinds_of_port_zero(migrated_engine) -> int:  # type: ignore[no-untyped-def]
    """Insert one node with all four shapes of a stored `portnum = 0`.

    Plus a real port, so the test can also say that the other bands did
    not move. Returns the node number.
    """
    node_num = 7311
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                "last_heard) VALUES (:n, :nid, :sn, :now, :now, :now) "
                "ON CONFLICT (node_num) DO NOTHING"
            ),
            {"n": node_num, "nid": f"!{node_num:08x}", "sn": "PZ", "now": now},
        )
        rows = (
            (1, 0, "pki"),
            (2, 0, "no_key"),
            (3, 0, "readable"),
            (4, 0, None),
            (5, 1, "readable"),
        )
        for packet_id, portnum, state in rows:
            connection.execute(
                text(
                    "INSERT INTO packet (from_node_num, packet_id, portnum, payload_state, "
                    "channel, want_ack, first_seen_at) "
                    "VALUES (:n, :pid, :p, :s, 'MediumFast', false, :now)"
                ),
                {"n": node_num, "pid": packet_id, "p": portnum, "s": state, "now": now},
            )
    return node_num


def _forget_node(migrated_engine, node_num: int) -> None:  # type: ignore[no-untyped-def]
    """Remove one seeded node and everything keyed to it."""
    with migrated_engine.begin() as connection:
        for table in ("packet_seen", "packet_key", "packet"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE from_node_num = :n"), {"n": node_num}
            )
        connection.execute(text("DELETE FROM node WHERE node_num = :n"), {"n": node_num})


def test_port_zero_is_no_longer_one_bucket_called_unknown_app(  # type: ignore[no-untyped-def]
    migrated_engine,
    timescale_url: str,
) -> None:
    """The user-visible half of #157, asserted on the endpoint.

    A census against production found that a stored `portnum = 0` was
    91.7% PKI direct messages, 8.2% packets on a channel with no key,
    and 0.1% genuine `UNKNOWN_APP` -- and this activity listing drew all
    of them as `UNKNOWN_APP`.

    The helper that decides the name has its own unit tests. This is the
    claim those cannot make: that the **query** carries the state far
    enough for the name to be chosen, which is the part that needed a
    `group_by` and is the part a refactor would quietly drop.
    """
    node_num = _seed_four_kinds_of_port_zero(migrated_engine)
    try:
        app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
        with TestClient(app) as client:
            activity = client.get(f"/api/nodes/!{node_num:08x}/detail").json()["activity"]
    finally:
        # Put the database back. The container is session-scoped, so a
        # node left behind is a node every later test can see -- and
        # this one did exactly that: the siting tests count struggling
        # nodes, and two of them went red on a node they never seeded.
        # A fixture that only ever adds rows is a slow-acting failure
        # in whatever runs after it.
        _forget_node(migrated_engine, node_num)

    names = {row["portnum"] for row in activity["by_portnum"]}
    assert "UNREADABLE_PKI" in names, "a direct message nobody here can read is named as one"
    assert "UNREADABLE_NO_KEY" in names, "a packet on a channel with no key is named as one"
    assert "UNREADABLE_UNRECORDED" in names, (
        "a row stored before revision 0015 says nobody asked, rather than "
        "being folded into the commonest value"
    )
    assert "UNKNOWN_APP" in names, "the genuine UNKNOWN_APP keeps its name"
    assert "TEXT_MESSAGE_APP" in names, "a real port is unaffected"

    # Five packets in, five counted out: the split must not lose or
    # double-count anything. The old query grouped by portnum alone, so
    # a test that only checked the names would pass on a listing that
    # had silently merged four rows into one.
    assert activity["packet_count"] == 5
    assert sum(row["count"] for row in activity["by_portnum"]) == 5
    assert len(activity["by_portnum"]) == 5, activity["by_portnum"]


def test_the_route_widgets_read_every_traceroute_in_the_window(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """No row limit decides what the node page's links are (#290).

    The panel read the newest 2000 traceroutes that named the node and
    said so under the tiles. At the 30 day default that was about a
    tenth of the busiest node's evidence. Here 2100 recent requests reach
    9901 from 9902, and one older one reaches it from 9903, twenty days
    back. All of it must be counted, and the older link must be there.
    """
    now = datetime.now(UTC)
    try:
        with migrated_engine.begin() as connection:
            connection.execute(text("DELETE FROM traceroute WHERE to_node_num = 9901"))
            # One hop each, from the asker straight to 9901, with a
            # reading for it: a request the broker saw arrive.
            connection.execute(
                text(
                    "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                    "route, snr_towards, seen_at) "
                    "SELECT 9902, 9901, 'LongFast', 990000 + g, CAST('[]' AS jsonb), "
                    "CAST('[20]' AS jsonb), :now - make_interval(secs => g) "
                    "FROM generate_series(1, 2100) AS g"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                    "route, snr_towards, seen_at) "
                    "VALUES (9903, 9901, 'LongFast', 993000, CAST('[]' AS jsonb), "
                    "CAST('[12]' AS jsonb), :old)"
                ),
                {"old": now - timedelta(days=20)},
            )

        app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
        with TestClient(app) as client:
            body = client.get("/api/nodes/!000026ad/routes?hours=720").json()
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(text("DELETE FROM traceroute WHERE to_node_num = 9901"))

    hears = {row["node_id"]: row for row in body["hears"]}
    assert body["traces_read"] == 2101, "every traceroute in the window is read"
    assert "trace_limit_reached" not in body, "there is no limit left to report"
    assert hears["!000026ae"]["count"] == 2100, "each report is counted, not the newest 2000"
    assert "!000026af" in hears, "a link seen only twenty days ago is still a link"
    assert hears["!000026af"]["count"] == 1


def test_a_sighting_is_direct_by_its_own_hop_start_or_else_its_packets(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """The node page reads `packet_seen.hop_start`, and joins only old rows (#304).

    Revision 0017 writes each sighting's own `hop_start`. Rows written
    before it hold NULL and are never backfilled, so they must still be
    judged by their packet's. 9921 sends two packets:

    - packet 1, `packet.hop_start` 3: 9922 hears it direct by its own
      value, 9923 direct by the packet's (an old row), 9924 two hops
      away, and 9921 uploads it itself.
    - packet 2, `packet.hop_start` NULL: 9924 hears it direct, which only
      its own value can say.
    """
    sender = 9921
    now = datetime.now(UTC)
    sightings = (
        # packet, gateway, own hop_start, hop_limit
        (1, 9922, 3, 3),
        (1, 9923, None, 3),
        (1, 9924, 3, 1),
        (1, 9921, 3, 3),
        (2, 9924, 3, 3),
    )
    try:
        with migrated_engine.begin() as connection:
            for packet_id, hop_start in ((1, 3), (2, None)):
                connection.execute(
                    text(
                        "INSERT INTO packet (from_node_num, packet_id, portnum, channel, "
                        "hop_start, want_ack, first_seen_at) "
                        "VALUES (:n, :pid, 1, 'LongFast', :hs, false, :now)"
                    ),
                    {"n": sender, "pid": packet_id, "hs": hop_start, "now": now},
                )
            for packet_id, gateway, hop_start, hop_limit in sightings:
                connection.execute(
                    text(
                        "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                        "mqtt_topic, channel, rx_snr, hop_limit, hop_start, seen_at) "
                        "VALUES (:n, :pid, :gw, 'msh/test', 'LongFast', 5.0, :hl, :hs, :now)"
                    ),
                    {
                        "n": sender,
                        "pid": packet_id,
                        "gw": gateway,
                        "hl": hop_limit,
                        "hs": hop_start,
                        "now": now,
                    },
                )
        app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
        with TestClient(app) as client:
            routes = client.get(f"/api/nodes/!{sender:08x}/routes?hours=24").json()
            heard = client.get(f"/api/nodes/!{sender:08x}/heard-by?hours=24").json()
    finally:
        _forget_node(migrated_engine, sender)

    linked = {row["node_id"]: row["count"] for row in routes["heard_by"]}
    assert linked == {"!000026c2": 1, "!000026c3": 1, "!000026c4": 1}, (
        "9922 by its own hop_start, 9923 by its packet's, 9924 by its own on packet 2 "
        "only; the sender's own upload is never a link"
    )
    assert routes["hop_depth"]["counts"] == [{"hops": 0, "packets": 2}]

    direct = {row["node_id"]: (row["count"], row["direct_count"]) for row in heard}
    assert direct["!000026c2"] == (1, 1)
    assert direct["!000026c3"] == (1, 1), "an old row is judged by its packet"
    assert direct["!000026c4"] == (2, 1), "two hops on packet 1, direct on packet 2"
    assert direct["!000026c1"] == (1, 0), "a node's own upload is not a direct link"
