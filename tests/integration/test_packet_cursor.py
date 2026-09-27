"""The node page's packet listing pages by cursor (#259).

The page scrolls on instead of pressing "Older", and it asks for each
next page with `before=<cursor>` rather than an offset. Two claims are
worth a database:

* **Paging by cursor returns exactly the one-page answer, in every sort.**
  The seed is built to make that hard: rows that tie on the sort value
  and on `first_seen_at`, and rows whose observation summary is NULL,
  which sort last whichever way the column is clicked.
* **A packet that arrives between two pages moves nothing.** With an
  offset it pushes the last row of page one onto page two, and the
  reader sees it twice. A cursor names that row, so it cannot.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.config import Settings
from tests.integration.conftest import role_url

NODE = 0x0C0FFEE0
GATEWAY = 0x0C0FFEE1
SORTS = ("time", "type", "to", "channel", "size", "hops", "gateways", "snr", "rssi")


def _seed(migrated_engine) -> datetime:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(microsecond=0)
    with migrated_engine.begin() as connection:
        # The database lives for the whole session, so each test starts
        # from this node's rows alone.
        for table in ("packet_seen", "packet"):
            connection.execute(text(f"DELETE FROM {table} WHERE from_node_num = :n"), {"n": NODE})
        for node in (NODE, GATEWAY):
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, first_seen, updated_at, last_heard) "
                    "VALUES (:n, :id, :now, :now, :now) ON CONFLICT (node_num) DO NOTHING"
                ),
                {"n": node, "id": f"!{node:08x}", "now": now},
            )
        # Inserted in REVERSE, so the surrogate `id` runs opposite to
        # `packet_id`. The cursor names a row by its identity, and a
        # listing that broke ties on `id` would disagree with it on every
        # tie -- but only when the two orders differ, which insertion in
        # packet order would hide.
        for index in reversed(range(13)):
            # Pairs share a timestamp, and three port numbers repeat, so
            # nearly every sort has ties to break.
            moment = now - timedelta(minutes=index // 2)
            connection.execute(
                text(
                    "INSERT INTO packet (from_node_num, packet_id, to_node_num, portnum, "
                    "channel, hop_start, first_seen_at, raw_bytes) "
                    "VALUES (:n, :p, :to, :port, :ch, 3, :at, :raw)"
                ),
                {
                    "n": NODE,
                    "p": 1000 + index,
                    "to": 0xFFFFFFFF if index % 3 else 7,
                    "port": (1, 3, 67)[index % 3],
                    "ch": "LongFast" if index % 2 else None,
                    "at": moment,
                    "raw": b"x" * (10 + index % 4),
                },
            )
            # Every other packet has an observation; the rest have none,
            # so their summary is NULL and must sort last both ways.
            if index % 2 == 0:
                connection.execute(
                    text(
                        "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                        "mqtt_topic, rx_snr, rx_rssi, hop_limit, seen_at) "
                        "VALUES (:n, :p, :g, 'msh/test', :snr, :rssi, :hl, :at)"
                    ),
                    {
                        "n": NODE,
                        "p": 1000 + index,
                        "g": GATEWAY,
                        "snr": float(index % 3),
                        "rssi": -100 + index % 3,
                        "hl": 3 - index % 2,
                        "at": moment,
                    },
                )
    return now


def _client(timescale_url: str) -> TestClient:
    return TestClient(
        create_app(Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api")))
    )


def _page_through(client: TestClient, query: str, size: int) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    before = None
    for _ in range(100):
        answer = client.get(
            f"/api/nodes/!{NODE:08x}/packets?{query}&limit={size}"
            + (f"&before={before}" if before else "")
        )
        assert answer.status_code == 200, answer.text
        page = answer.json()
        rows += [(row["from_node"], row["packet_id"]) for row in page]
        if len(page) < size:
            return rows
        before = answer.headers["X-Next-Before"]
    raise AssertionError("the cursor never reached the end")


def test_every_sort_pages_to_the_one_page_answer(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    _seed(migrated_engine)
    with _client(timescale_url) as client:
        for sort in SORTS:
            for order in ("asc", "desc"):
                query = f"hours=24&sort={sort}&order={order}"
                whole = [
                    (row["from_node"], row["packet_id"])
                    for row in client.get(
                        f"/api/nodes/!{NODE:08x}/packets?{query}&limit=500"
                    ).json()
                ]
                assert len(whole) == 13, (sort, order, len(whole))
                paged = _page_through(client, query, 2)
                assert paged == whole, f"sort={sort} order={order}: {paged} != {whole}"


def test_a_packet_arriving_between_pages_moves_nothing(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    now = _seed(migrated_engine)
    with _client(timescale_url) as client:
        first = client.get(f"/api/nodes/!{NODE:08x}/packets?hours=24&limit=4")
        held = [row["packet_id"] for row in first.json()]
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO packet (from_node_num, packet_id, portnum, first_seen_at) "
                    "VALUES (:n, 9999, 1, :at)"
                ),
                {"n": NODE, "at": now + timedelta(seconds=30)},
            )
        cursor = first.headers["X-Next-Before"]
        by_cursor = client.get(
            f"/api/nodes/!{NODE:08x}/packets?hours=24&limit=4&before={cursor}"
        ).json()
        by_offset = client.get(f"/api/nodes/!{NODE:08x}/packets?hours=24&limit=4&offset=4").json()
    assert not {row["packet_id"] for row in by_cursor} & set(held), "the cursor repeated a row"
    # The control: the same arrival DOES move an offset page, so the test
    # above is measuring something.
    assert {row["packet_id"] for row in by_offset} & set(held), "offset paging was not disturbed"


def test_a_cursor_from_another_sort_is_refused(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    _seed(migrated_engine)
    with _client(timescale_url) as client:
        first = client.get(f"/api/nodes/!{NODE:08x}/packets?hours=24&limit=2&sort=time")
        cursor = first.headers["X-Next-Before"]
        answer = client.get(
            f"/api/nodes/!{NODE:08x}/packets?hours=24&limit=2&sort=type&before={cursor}"
        )
    assert answer.status_code == 422
    assert "sort=time" in answer.json()["detail"]
