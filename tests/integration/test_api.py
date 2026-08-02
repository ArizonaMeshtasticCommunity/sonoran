"""Database-backed tests for the public GET API."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.config import Settings


def _api_url(timescale_url: str) -> str:
    """Make an async URL for the migration-created API role."""
    _, address = timescale_url.split("@", maxsplit=1)
    return f"postgresql+asyncpg://azmsh_api:change_me@{address}"


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
