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
