"""`/api/chat/overview` costs the same whether the mesh has 2 channels or 20.

The endpoint used to issue one SELECT per distinct channel in the
window, and each pass cost four round trips, because `_as_messages`
issues three of its own for names, reactions and reply parents. Channel
names arrive from MQTT, so **the mesh decided how many times that loop
ran** -- the chat page already surfaces unrecognised names in a "Custom"
group, so new ones are a thing that happens rather than a hypothetical.

Measured against the dev instance before the change, at the maximum
knobs the endpoint accepts (`hours=8760&per_channel=200`), 10 channels
and 1,212 messages: 2.19 s / 1.79 s / 2.03 s.

The replacement is a single ROW_NUMBER window partitioned by channel,
plus one `_as_messages` call over every row together.

Two things these tests pin, because both are easy to lose:

* the output must not change, including the awkward cases -- a channel
  with no channel name at all, and a channel whose every message in the
  window is a tapback, which has a count but no messages;
* the query count must stop growing with the channel count, which is the
  entire point and is invisible to an output comparison.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from sonoran.api.app import create_app
from sonoran.config import Settings
from tests.integration.conftest import role_url


def _seed_channels(migrated_engine, count: int) -> None:  # type: ignore[no-untyped-def]
    """Messages across `count` named channels, plus the two odd ones."""
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO node (node_num, node_id, short_name, first_seen, "
                "updated_at, last_heard) VALUES (9001, '!00002329', 'CHAT', "
                ":now, :now, :now) ON CONFLICT (node_num) DO NOTHING"
            ),
            {"now": now},
        )
        rows = []
        for index in range(count):
            for message in range(3):
                rows.append(
                    {
                        "channel": f"Channel{index}",
                        "body": f"message {message} on {index}",
                        "seen": now - timedelta(minutes=message),
                        "emoji": False,
                    }
                )
        # No channel name at all -- PARTITION BY has to group these the
        # way the old `IS NULL` branch did.
        rows.append({"channel": None, "body": "no channel", "seen": now, "emoji": False})
        # Every message a tapback: a count with no messages.
        rows.append({"channel": "OnlyEmoji", "body": "\U0001f44d", "seen": now, "emoji": True})
        for row in rows:
            connection.execute(
                text(
                    "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                    "emoji, seen_at) VALUES (9001, 4294967295, :channel, :body, "
                    ":emoji, :seen)"
                ),
                row,
            )


def _api_url(timescale_url: str) -> str:
    """Make an async URL for the migration-created API role."""
    return role_url(timescale_url, "azmsh_api")


def _client(timescale_url: str) -> TestClient:
    app = create_app(Settings(_env_file=None, database_url_api=_api_url(timescale_url)))
    return TestClient(app)


def _overview(client: TestClient) -> dict:
    response = client.get("/api/chat/overview?hours=168&per_channel=25")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_awkward_channels_survive(migrated_engine, timescale_url) -> None:  # type: ignore[no-untyped-def]
    """A nameless channel and an all-tapback channel both keep sections."""
    _seed_channels(migrated_engine, 4)
    with _client(timescale_url) as client:
        body = _overview(client)

    sections = {str(section.get("channel")): section for section in body["sections"]}

    assert "None" in sections, (
        "the channel with no name lost its section; PARTITION BY must group "
        "NULLs the way the old `IS NULL` branch did"
    )
    assert sections["None"]["messages"], "the nameless channel's messages went missing"

    assert "OnlyEmoji" in sections, "a channel of pure tapbacks lost its section"
    assert sections["OnlyEmoji"]["count"] >= 1
    assert sections["OnlyEmoji"]["messages"] == [], (
        "tapbacks are not messages of their own and must not appear as any"
    )


def test_messages_stay_newest_first_within_a_channel(migrated_engine, timescale_url) -> None:  # type: ignore[no-untyped-def]
    """The window's ORDER BY is inside a subquery; it is easy to lose."""
    _seen_order_channels = 4
    _seed_channels(migrated_engine, _seen_order_channels)
    with _client(timescale_url) as client:
        body = _overview(client)

    for section in body["sections"]:
        stamps = [message["seen_at"] for message in section["messages"]]
        assert stamps == sorted(stamps, reverse=True), (
            f"channel {section.get('channel')!r} came back out of order: {stamps}"
        )


def test_the_query_count_does_not_follow_the_channel_count(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url
) -> None:
    """The actual fix, and the only test here that would catch a revert.

    An output comparison passes for the loop and for the window alike.
    """
    counted: list[int] = []

    def count_one(*_args: object, **_kwargs: object) -> None:
        counted.append(1)

    _seed_channels(migrated_engine, 3)
    with _client(timescale_url) as client:
        engine = client.app.state.session_factory.kw["bind"].sync_engine
        event.listen(engine, "before_cursor_execute", count_one)
        try:
            counted.clear()
            _overview(client)
            few = len(counted)

            _seed_channels(migrated_engine, 15)
            counted.clear()
            _overview(client)
            many = len(counted)
        finally:
            event.remove(engine, "before_cursor_execute", count_one)

    assert few > 0, "no queries were observed at all, so this test proves nothing"
    assert many <= few + 2, (
        f"the overview issued {few} queries for a few channels and {many} for "
        f"many; the per-channel loop is back"
    )
