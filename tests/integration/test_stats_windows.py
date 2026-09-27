"""The statistics endpoints count over the window the reader asked for.

#292: the dashboard's four headline tiles. Will confirmed that Packets
and Uploads become a rolling last 24 hours, and that Nodes and Gateways
stay totals of every node ever seen.

#294: every widget on the Statistics page reads the range chosen at the
top of the page, and says where packet retention cuts it short.

The database is shared by the whole integration session, so each test
measures the change its own rows make rather than an absolute count.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.api.cache import clear_all
from sonoran.config import Settings
from tests.integration.conftest import role_url

# Every node these tests add is numbered in this range, so they can be
# taken out again. Left behind, they change the counts of tests that run
# later in the same session: run first, they broke two in test_api.py.
OWN_NODES = (292000, 294999)


@pytest.fixture(autouse=True)
def _remove_own_rows(migrated_engine) -> Iterator[None]:  # type: ignore[no-untyped-def]
    yield
    with migrated_engine.begin() as connection:
        for table, column in (
            ("packet_seen", "from_node_num"),
            ("packet", "from_node_num"),
            ("node", "node_num"),
        ):
            connection.execute(
                text(f"DELETE FROM {table} WHERE {column} BETWEEN :low AND :high"),
                {"low": OWN_NODES[0], "high": OWN_NODES[1]},
            )


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


# --- #294: every widget on the Statistics page reads one range -------


PHOENIX = ZoneInfo("America/Phoenix")


def test_the_daily_chart_counts_each_local_day(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """Packets on three Arizona days, one a minute either side of midnight.

    A UTC day would put the minute before local midnight and the minute
    after it into the same day. Arizona is UTC-7 all year.
    """
    node = 294001
    midnight = datetime.now(PHOENIX).replace(hour=0, minute=0, second=0, microsecond=0)
    midnight -= timedelta(days=3)
    days = [(midnight + timedelta(days=offset)).date().isoformat() for offset in (-1, 0, 1)]
    until = (midnight + timedelta(days=2)).date().isoformat()
    query = f"/api/stats/daily?since={days[0]}&until={until}"
    with _client(timescale_url) as client:
        before = _read(client, query)
        with migrated_engine.begin() as connection:
            _node(connection, node, gateway=False)
            _packet(connection, node, 1, midnight - timedelta(minutes=1))
            _packet(connection, node, 2, midnight + timedelta(minutes=1))
            _packet(connection, node, 3, midnight + timedelta(minutes=2))
            _packet(connection, node, 4, midnight + timedelta(days=1, hours=1))
        after = _read(client, query)

    def by_day(body: dict[str, object]) -> dict[str, dict[str, int]]:
        listed = body["days"]
        assert isinstance(listed, list)
        return {row["day"]: row for row in listed}

    old, new = by_day(before), by_day(after)
    assert list(new) == days
    change = {day: new[day]["packet_count"] - old[day]["packet_count"] for day in days}
    assert change == {days[0]: 1, days[1]: 2, days[2]: 1}
    uploads = {day: new[day]["observation_count"] - old[day]["observation_count"] for day in days}
    assert uploads == change
    assert after["timezone"] == "America/Phoenix"


def test_a_long_window_is_drawn_by_day_and_a_short_one_by_hour(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    with _client(timescale_url) as client:
        assert _read(client, "/api/stats/activity?hours=24")["bucket"] == "hour"
        assert _read(client, "/api/stats/activity?hours=72")["bucket"] == "hour"
        week = _read(client, "/api/stats/activity?hours=168")
    assert week["bucket"] == "day"
    # Each day starts at a local midnight: 07:00 UTC in Arizona.
    starts = week["hours"]
    assert isinstance(starts, list)
    for moment in starts:
        assert datetime.fromisoformat(str(moment)).astimezone(PHOENIX).hour == 0


def test_the_busiest_senders_ignore_a_future_clock(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """`/top` had a lower bound only, so a row dated ahead counted in every window."""
    node = 294101
    with migrated_engine.begin() as connection:
        _node(connection, node, gateway=False)
        for packet_id in range(1, 400):
            _packet(connection, node, packet_id, datetime.now(UTC) + timedelta(hours=2))
    with _client(timescale_url) as client:
        clear_all()
        rows = client.get("/api/stats/top?hours=24&limit=100").json()
    assert f"!{node:08x}" not in {row["node_id"] for row in rows}


def test_the_hardware_mix_follows_the_window(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    """Boards heard in the window, from the packets, not every node ever seen."""
    recent, older = 294201, 294202
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for node, board in ((recent, "WINDOW_RECENT_BOARD"), (older, "WINDOW_OLDER_BOARD")):
            _node(connection, node, gateway=False)
            connection.execute(
                text("UPDATE node SET hw_model = :b WHERE node_num = :n"),
                {"b": board, "n": node},
            )
        _packet(connection, recent, 1, now - timedelta(hours=2))
        _packet(connection, older, 1, now - timedelta(days=10))

    def boards(client: TestClient, query: str) -> set[str]:
        clear_all()
        return {row["hw_model"] for row in client.get(f"/api/stats/hardware{query}").json()}

    with _client(timescale_url) as client:
        day = boards(client, "?hours=24")
        month = boards(client, "?hours=720")
        ever = boards(client, "")
    assert "WINDOW_RECENT_BOARD" in day and "WINDOW_OLDER_BOARD" not in day
    assert {"WINDOW_RECENT_BOARD", "WINDOW_OLDER_BOARD"} <= month
    assert {"WINDOW_RECENT_BOARD", "WINDOW_OLDER_BOARD"} <= ever


def test_a_range_that_starts_before_retention_says_where_it_counts_from(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    start = (datetime.now(PHOENIX) - timedelta(days=40)).date()
    end = (datetime.now(PHOENIX) - timedelta(days=15)).date()
    with _client(timescale_url) as client:
        body = _read(client, f"/api/stats?since={start}&until={end}")
        daily = _read(client, f"/api/stats/daily?since={start}&until={end}")
    kept = datetime.fromisoformat(str(body["retained_from"]))
    assert kept > datetime.fromisoformat(str(body["window_start"]))
    assert body["previous"] is None
    listed = daily["days"]
    assert isinstance(listed, list)
    # Days older than retention are left out, never drawn as a zero.
    assert listed and listed[0]["day"] > start.isoformat()
