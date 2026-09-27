"""The statistics endpoints count over the window the reader asked for.

#292: the dashboard's four headline tiles. Will confirmed that Packets
and Uploads become a rolling last 24 hours, and that Nodes and Gateways
stay totals of every node ever seen.

The database is shared by the whole integration session, so each test
measures the change its own rows make rather than an absolute count.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.api.cache import clear_all
from sonoran.config import Settings
from tests.integration.conftest import role_url


def _client(timescale_url: str) -> TestClient:
    settings = Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api"))
    return TestClient(create_app(settings))


def _packet(connection, node: int, packet_id: int, when: datetime) -> None:  # type: ignore[no-untyped-def]
    """One packet and one upload of it, both received at `when`."""
    connection.execute(
        text(
            "INSERT INTO packet (from_node_num, packet_id, portnum, first_seen_at) "
            "VALUES (:n, :p, 1, :t) ON CONFLICT DO NOTHING"
        ),
        {"n": node, "p": packet_id, "t": when},
    )
    connection.execute(
        text(
            "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
            "mqtt_topic, seen_at) VALUES (:n, :p, :n, 'msh/US/AZ/test', :t) "
            "ON CONFLICT DO NOTHING"
        ),
        {"n": node, "p": packet_id, "t": when},
    )


def _node(connection, node: int, *, gateway: bool) -> None:  # type: ignore[no-untyped-def]
    long_ago = datetime.now(UTC) - timedelta(days=200)
    connection.execute(
        text(
            "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
            "last_heard, is_mqtt_gateway) VALUES (:n, :nid, 'WIN', :t, :t, :t, :g) "
            "ON CONFLICT (node_num) DO NOTHING"
        ),
        {"n": node, "nid": f"!{node:08x}", "t": long_ago, "g": gateway},
    )


def _read(client: TestClient, path: str) -> dict[str, object]:
    clear_all()
    response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def test_the_rolling_day_counts_receive_time_inside_the_window(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """1 h and 23 h ago count. 25 h ago is the day before. The future is not counted.

    A row two hours in the future is what a gateway clock wrote before
    the AGENTS.md 9.4 fix. It must not count in any window.
    """
    node = 292001
    with _client(timescale_url) as client:
        before = _read(client, "/api/stats?hours=24")
        lifetime_before = _read(client, "/api/stats")
        now = datetime.now(UTC)
        with migrated_engine.begin() as connection:
            _node(connection, node, gateway=False)
            # A gateway flagged long ago that has uploaded nothing today.
            # "Gateways" is every one ever seen (Will), so it still counts.
            _node(connection, node + 1, gateway=True)
            _packet(connection, node, 1, now - timedelta(hours=1))
            _packet(connection, node, 2, now - timedelta(hours=23))
            _packet(connection, node, 3, now - timedelta(hours=25))
            _packet(connection, node, 4, now + timedelta(hours=2))
        after = _read(client, "/api/stats?hours=24")
        lifetime_after = _read(client, "/api/stats")

    assert after["window_hours"] == 24
    assert after["packet_count"] - before["packet_count"] == 2  # type: ignore[operator]
    assert after["observation_count"] - before["observation_count"] == 2  # type: ignore[operator]
    previous_after = after["previous"]
    previous_before = before["previous"]
    assert isinstance(previous_after, dict) and isinstance(previous_before, dict)
    assert previous_after["packet_count"] - previous_before["packet_count"] == 1
    assert previous_after["observation_count"] - previous_before["observation_count"] == 1
    # Nodes and gateways are totals of every node ever seen, window or not.
    assert after["node_count"] - before["node_count"] == 2  # type: ignore[operator]
    assert after["gateway_count"] - before["gateway_count"] == 1  # type: ignore[operator]
    assert after["node_count"] == lifetime_after["node_count"]
    assert after["gateway_count"] == lifetime_after["gateway_count"]
    # Without `hours` the answer is what it always was: every row held,
    # the future one included, and no window fields.
    assert lifetime_after["packet_count"] - lifetime_before["packet_count"] == 4  # type: ignore[operator]
    assert "window_hours" not in lifetime_after
    assert "previous" not in lifetime_after


def test_no_comparison_is_made_with_rows_retention_has_deleted(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """The 30 days before a 30 day window are gone, so there is no `previous`."""
    with _client(timescale_url) as client:
        month = _read(client, "/api/stats?hours=720")
        week = _read(client, "/api/stats?hours=168")
    assert month["previous"] is None
    assert isinstance(week["previous"], dict)


def test_a_window_outside_the_allowed_range_is_refused(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    with _client(timescale_url) as client:
        for hours in (0, -1, 721):
            assert client.get(f"/api/stats?hours={hours}").status_code == 422, hours
