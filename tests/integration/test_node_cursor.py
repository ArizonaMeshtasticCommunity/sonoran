"""The node list pages by cursor (#250).

The list scrolls on, and it used to ask for each next page with an
offset. Two claims are worth a database:

* **Paging by cursor returns exactly the one-page answer, in every sort.**
  The seed is built to make that hard: nodes that tie on every sortable
  column, and nodes whose value is NULL, which sort last whichever way
  the column is clicked.
* **A node that moves between two pages moves nothing else.** In
  "quiet first" order (`last_heard` ascending) a node heard again jumps
  to the end of the list. With an offset every row behind it moves up
  by one, and the row at the page boundary is never served. Nothing in
  the browser can see that. A cursor names the last row served, so it
  cannot happen.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.config import Settings
from tests.integration.conftest import role_url

FIRST = 0x0CC00000
COUNT = 14
# Every seeded node matches this search, and nothing else in the
# session's database does, so the list under test is exactly the seed.
QUERY = "q=cursortie"
SORTS = ("last_heard", "first_seen", "name", "node_id", "hw", "role", "channel", "position")


def _seed(migrated_engine) -> datetime:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(microsecond=0)
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM node WHERE node_num BETWEEN :a AND :b"),
            {"a": FIRST, "b": FIRST + COUNT},
        )
        # Inserted in reverse, so that the physical order of the table
        # runs opposite to `node_num`. A list that broke ties by anything
        # else would then disagree with the cursor on every tie.
        for index in reversed(range(COUNT)):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, long_name, short_name, hw_model, role, "
                    "last_channel, last_position_precision_bits, last_heard, first_seen, "
                    "updated_at) VALUES (:n, :id, :long, :short, :hw, :role, :ch, :bits, "
                    ":heard, :first, :first)"
                ),
                {
                    "n": FIRST + index,
                    "id": f"!{FIRST + index:08x}",
                    # Three share one name, and a fourth has no long name
                    # at all, so `name` ties and falls back to the short.
                    "long": None if index % 4 == 3 else f"cursortie {index % 3}",
                    "short": "cursortie",
                    "hw": None if index % 5 == 0 else ("TBEAM", "HELTEC_V3")[index % 2],
                    "role": None if index % 3 == 0 else ("ROUTER", "CLIENT")[index % 2],
                    "ch": None if index % 2 else "LongFast",
                    "bits": None if index % 4 == 0 else (10, 32)[index % 2],
                    # Pairs share a time, and two nodes were never heard.
                    "heard": None if index in (5, 9) else now - timedelta(minutes=index // 2),
                    "first": now - timedelta(days=index // 3),
                },
            )
    return now


def _client(timescale_url: str) -> TestClient:
    return TestClient(
        create_app(Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api")))
    )


def _ids(answer) -> list[str]:  # type: ignore[no-untyped-def]
    assert answer.status_code == 200, answer.text
    return [row["node_id"] for row in answer.json()]


def _page_through(client: TestClient, query: str, size: int) -> list[str]:
    rows: list[str] = []
    cursor = None
    for _ in range(100):
        answer = client.get(
            f"/api/nodes?{query}&limit={size}" + (f"&cursor={cursor}" if cursor else "")
        )
        page = _ids(answer)
        rows += page
        if len(page) < size:
            return rows
        cursor = answer.headers["X-Next-Cursor"]
    raise AssertionError("the cursor never reached the end")


def test_every_sort_pages_to_the_one_page_answer(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    _seed(migrated_engine)
    with _client(timescale_url) as client:
        for sort in SORTS:
            for order in ("asc", "desc"):
                query = f"{QUERY}&sort={sort}&order={order}"
                whole = _ids(client.get(f"/api/nodes?{query}&limit=500"))
                assert len(whole) == COUNT, (sort, order, len(whole))
                for size in (2, 3):
                    paged = _page_through(client, query, size)
                    assert paged == whole, f"sort={sort} order={order} size={size}"


def test_a_node_heard_between_pages_skips_nothing(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    now = _seed(migrated_engine)
    query = f"{QUERY}&sort=last_heard&order=asc&limit=4"
    with _client(timescale_url) as client:
        before = _ids(client.get(f"/api/nodes?{QUERY}&sort=last_heard&order=asc&limit=500"))
        first = client.get(f"/api/nodes?{query}")
        held = _ids(first)
        # The quietest node on the first page is heard again, so it
        # jumps to the end of a "quiet first" list.
        with migrated_engine.begin() as connection:
            connection.execute(
                text("UPDATE node SET last_heard = :at WHERE node_id = :id"),
                {"at": now + timedelta(minutes=5), "id": held[0]},
            )
        by_cursor = _ids(client.get(f"/api/nodes?{query}&cursor={first.headers['X-Next-Cursor']}"))
        by_offset = _ids(client.get(f"/api/nodes?{query}&offset=4"))
    assert by_cursor == before[4:8], "the cursor skipped or repeated a row"
    # The control: the same change DOES make an offset page skip a node
    # that never moved, so the assertion above is measuring something.
    assert before[4] not in by_offset, "offset paging was not disturbed"


def test_a_cursor_from_another_sort_is_refused(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    _seed(migrated_engine)
    with _client(timescale_url) as client:
        first = client.get(f"/api/nodes?{QUERY}&limit=2&sort=name")
        cursor = first.headers["X-Next-Cursor"]
        answer = client.get(f"/api/nodes?{QUERY}&limit=2&sort=role&cursor={cursor}")
        other_order = client.get(f"/api/nodes?{QUERY}&limit=2&sort=name&order=asc&cursor={cursor}")
    assert answer.status_code == 422
    assert "sort=name" in answer.json()["detail"]
    assert other_order.status_code == 422


def test_a_hand_typed_cursor_is_refused_not_obeyed(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The cursor is opaque, and a reader can still type one. Rubbish,
    a wrong type in the value, or a node number that is not a number
    must answer 422, never 500 and never a quietly wrong page."""
    import base64
    import json

    def made(payload: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

    _seed(migrated_engine)
    bad = [
        "not-a-cursor",
        "e30",  # {}
        made(["node_id", "desc", "abc", 1]),
        made(["last_heard", "desc", "yesterday", 1]),
        made(["name", "desc", 7, 1]),
        made(["name", "desc", "x", "1"]),
        made(["position", "desc", True, 1]),
    ]
    with _client(timescale_url) as client:
        for cursor in bad:
            sort = "node_id"
            try:
                sort = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))[0]
            except (ValueError, KeyError, IndexError, TypeError):
                pass
            answer = client.get(f"/api/nodes?{QUERY}&sort={sort}&cursor={cursor}")
            assert answer.status_code == 422, (cursor, answer.status_code, answer.text)
