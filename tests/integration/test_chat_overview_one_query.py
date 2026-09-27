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
        # Start from nothing. Without this the rows accumulate across
        # calls and across runs against a reusable database, and an
        # assertion about WHICH messages a section holds turns into an
        # assertion about how many times the suite has been run. CI
        # hides it behind a fresh container; a developer reusing a
        # database does not have that luxury.
        connection.execute(text("DELETE FROM text_message WHERE from_node_num = 9001"))
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
        # And the empty string, which is a DIFFERENT row out of GROUP BY
        # and classifies to the same label. If a rewrite ever merges the
        # two, this is what catches it.
        rows.append({"channel": "", "body": "empty channel", "seen": now, "emoji": False})
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
    """A nameless channel and an all-tapback channel both keep sections.

    **This test was wrong before it was right, and the way it was wrong
    matters.** It keyed sections on `str(section["channel"])` and looked
    for `"None"`. There is no such key: `classify()` maps a NULL channel
    to `{"channel": "", "label": "(no channel)"}` and always has. CI
    failed with "the channel with no name lost its section" and the
    section was there the whole time, under a name the test invented.

    It also collapsed the two cases it most needed to tell apart. A NULL
    channel and an EMPTY-STRING channel are separate rows out of
    `GROUP BY`, and both classify to `channel: ""` — so keying sections
    by that value merges two distinct sections and hides exactly the bug
    a windowed rewrite could introduce.

    So this asserts on the messages, which are what would actually go
    missing, and seeds both cases to prove they stay apart.
    """
    _seed_channels(migrated_engine, 4)
    with _client(timescale_url) as client:
        body = _overview(client)

    named = {section["channel"]: section for section in body["sections"] if section["channel"]}
    nameless = [section for section in body["sections"] if not section["channel"]]

    # NULL and "" both land here. They must be two sections, not one.
    assert len(nameless) == 2, (
        f"expected the NULL-channel and empty-string-channel sections to stay "
        f"separate, got {len(nameless)}: {[s['count'] for s in nameless]}"
    )
    # Each of the two must hold its OWN message. Asserting only that both
    # bodies appear SOMEWHERE among them passes when the two are merged:
    # one section ends up with both messages and the other with none, and
    # the union looks identical. Verified -- collapsing NULL and "" in
    # the grouping did not fail an earlier version of this assertion.
    held = [{message["body"] for message in section["messages"]} for section in nameless]
    mine = [bodies & {"no channel", "empty channel"} for bodies in held]

    # The property is that the two never MERGE, stated without assuming
    # this test owns the table -- `test_api.py` seeds its own
    # NULL-channel rows, so an exact-list assertion passes alone and
    # fails in the full suite, which is a worse kind of wrong than
    # either bug it was meant to catch.
    assert sorted(mine, key=sorted) == [{"empty channel"}, {"no channel"}], (
        f"the NULL and empty-string channels did not each keep exactly their own message: {mine}"
    )

    assert "OnlyEmoji" in named, "a channel of pure tapbacks lost its section"
    # No messages to count, since #297: the count is what the channel
    # page can load. The tapback is still there, as a reaction.
    assert named["OnlyEmoji"]["count"] == 0
    assert named["OnlyEmoji"]["reactions"] >= 1
    assert named["OnlyEmoji"]["messages"] == [], (
        "tapbacks are not messages of their own and must not appear as any"
    )


def test_the_count_is_what_the_channel_page_can_load(migrated_engine, timescale_url) -> None:  # type: ignore[no-untyped-def]
    """The overview count leaves tapbacks out, as `/api/chat` does (#297).

    MediumFast said "Open all 1,252 messages" over a channel page that
    ends at 663: the count read every row and the page lists none of the
    reactions. So the count is compared with what paging `/api/chat`
    actually reaches over the same window, not with a number worked out
    here.
    """
    _seed_channels(migrated_engine, 2)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for minute in range(3):
            connection.execute(
                text(
                    "INSERT INTO text_message (from_node_num, to_node_num, channel, body, "
                    "emoji, seen_at) VALUES (9001, 4294967295, 'Channel0', :body, "
                    "true, :seen)"
                ),
                {"body": "\U0001f44d", "seen": now - timedelta(minutes=minute, seconds=30)},
            )
    since = (now - timedelta(hours=168)).isoformat()
    with _client(timescale_url) as client:
        body = _overview(client)
        listed = client.get("/api/chat", params={"channel": "Channel0", "since": since})
        everything = client.get(
            "/api/chat", params={"channel": "Channel0", "since": since, "reactions": "true"}
        )
    assert listed.status_code == 200 and everything.status_code == 200
    section = next(s for s in body["sections"] if s["channel"] == "Channel0")
    assert section["count"] == len(listed.json()) == 3, (
        f"the overview says {section['count']} messages and the channel page lists "
        f"{len(listed.json())}; the tapbacks are being counted as messages"
    )
    assert section["reactions"] == len(everything.json()) - len(listed.json()) == 3


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
