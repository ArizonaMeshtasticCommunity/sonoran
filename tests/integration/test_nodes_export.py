"""The node export holds exactly the rows the list shows (#350).

For each filter combination, the list is paged to its end by cursor,
the way the page reads it, and compared with the CSV file and the JSON
file of the same query: the same nodes, in the same order, with the
same values, and a count equal to the list's `X-Total-Count`.

The seed makes the comparison hard: names that tie, NULL roles and
hardware, two nodes never heard, gateways and licensed nodes mixed, and
one node with no usable position. One name is a spreadsheet formula, so
the guard is checked on a real row.
"""

import csv
import io
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.config import Settings
from tests.integration.conftest import role_url

FIRST = 0x0EE00000
COUNT = 18
# Every seeded node matches this search, and nothing else does.
QUERY = "q=exporttie"
HOSTILE = "=HYPERLINK(1) exporttie"

COMBINATIONS = (
    f"{QUERY}",
    f"{QUERY}&role=ROUTER&sort=name&order=asc",
    f"{QUERY}&gateway=true&position=exact&sort=hw&order=desc",
    f"{QUERY}&position=none&sort=role",
    f"{QUERY}&active_hours=1&licensed=true&sort=last_heard&order=asc",
    f"{QUERY}&channel=LongFast&sort=position&order=desc",
    f"{QUERY}&quiet_hours=1&sort=node_id",
)


def _seed(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(microsecond=0)
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM node WHERE node_num BETWEEN :a AND :b"),
            {"a": FIRST, "b": FIRST + COUNT},
        )
        for index in reversed(range(COUNT)):
            usable = index % 6 != 0
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, long_name, short_name, hw_model, role, "
                    "last_channel, last_position_precision_bits, last_lat, last_lon, "
                    "is_mqtt_gateway, is_licensed, last_heard, first_seen, updated_at) "
                    "VALUES (:n, :id, :long, :short, :hw, :role, :ch, :bits, :lat, :lon, "
                    ":gw, :lic, :heard, :first, :first)"
                ),
                {
                    "n": FIRST + index,
                    "id": f"!{FIRST + index:08x}",
                    "long": HOSTILE
                    if index == 7
                    else (None if index % 4 == 3 else f"exporttie {index % 3}"),
                    "short": "exporttie",
                    "hw": None if index % 5 == 0 else ("TBEAM", "HELTEC_V3")[index % 2],
                    "role": None if index % 3 == 0 else ("ROUTER", "CLIENT")[index % 2],
                    "ch": None if index % 2 else "LongFast",
                    "bits": None if index % 4 == 0 else (10, 32)[index % 2],
                    "lat": 33.4 + index / 1000 if usable else None,
                    "lon": -112.0 - index / 1000 if usable else None,
                    "gw": index % 3 == 1,
                    "lic": index % 2 == 0,
                    "heard": None if index in (5, 9) else now - timedelta(minutes=index * 10),
                    "first": now - timedelta(days=index // 3),
                },
            )


def _client(timescale_url: str) -> TestClient:
    return TestClient(
        create_app(Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api")))
    )


def _listed(client: TestClient, query: str) -> tuple[list[dict[str, object]], int]:
    """Every row the page would show, read by cursor in pages of three."""
    rows: list[dict[str, object]] = []
    cursor = None
    total = -1
    for _ in range(100):
        answer = client.get(f"/api/nodes?{query}&limit=3" + (f"&cursor={cursor}" if cursor else ""))
        assert answer.status_code == 200, answer.text
        total = int(answer.headers["X-Total-Count"])
        page = answer.json()
        rows += page
        if len(page) < 3:
            return rows, total
        cursor = answer.headers["X-Next-Cursor"]
    raise AssertionError("the list never reached its end")


def _csv(body: str) -> list[dict[str, str]]:
    assert body.startswith("﻿")
    return list(csv.DictReader(io.StringIO(body[1:])))


def _guarded(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    value = str(value)
    return "'" + value if value[:1] in "=+-@\t\r" else value


def test_the_file_equals_the_list_for_every_combination(
    migrated_engine, timescale_url: str
) -> None:  # type: ignore[no-untyped-def]
    _seed(migrated_engine)
    nonempty = 0
    with _client(timescale_url) as client:
        for query in COMBINATIONS:
            listed, total = _listed(client, query)
            assert len(listed) == total, (query, len(listed), total)
            nonempty += bool(listed)

            as_json = client.get(f"/api/nodes/export?{query}&format=json")
            assert as_json.status_code == 200, (query, as_json.text)
            assert as_json.headers["X-Total-Count"] == str(total)
            fields = list(as_json.json()[0]) if listed else []
            assert as_json.json() == [{key: row[key] for key in fields} for row in listed], query

            as_csv = client.get(f"/api/nodes/export?{query}&format=csv")
            assert as_csv.status_code == 200, (query, as_csv.text)
            rows = _csv(as_csv.text)
            assert len(rows) == total, query
            assert [row["Node ID"] for row in rows] == [row["node_id"] for row in listed], query
            for line, row in zip(rows, listed, strict=True):
                assert line == {
                    "Name": _guarded(row["display_name"]),
                    "Short name": _guarded(row["short_name"]),
                    "Node ID": row["node_id"],
                    "Hardware": _guarded(row["hw_model"]),
                    "Role": _guarded(row["role"]),
                    "Gateway": _guarded(row["is_mqtt_gateway"]),
                    "Position": _guarded(row["has_position"]),
                    "Last heard": _guarded(row["last_heard"]),
                }, query
    # Positive control: every combination matches rows, so each
    # equality above compared rows and not two empty lists.
    assert nonempty == len(COMBINATIONS)


def test_the_hostile_name_is_defused_on_a_real_row(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    _seed(migrated_engine)
    with _client(timescale_url) as client:
        rows = _csv(client.get(f"/api/nodes/export?{QUERY}&columns=name,node_id").text)
        listed = client.get(f"/api/nodes?{QUERY}&limit=500").json()
    names = {row["Node ID"]: row["Name"] for row in rows}
    assert names[f"!{FIRST + 7:08x}"] == "'" + HOSTILE
    # And the list itself still shows the name as it was typed.
    assert any(row["display_name"] == HOSTILE for row in listed)


def test_the_file_holds_no_position(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """The list shows no coordinates, so the file holds none."""
    _seed(migrated_engine)
    with _client(timescale_url) as client:
        body = client.get(f"/api/nodes/export?{QUERY}&format=json").text
        refused = client.get(f"/api/nodes/export?{QUERY}&columns=name,last_lat")
    assert "33.4" not in body and "-112.0" not in body
    assert "last_lat" not in body and "last_lon" not in body
    assert refused.status_code == 422


def test_the_columns_follow_the_order_asked(migrated_engine, timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    _seed(migrated_engine)
    with _client(timescale_url) as client:
        body = client.get(f"/api/nodes/export?{QUERY}&columns=last_heard,role,node_id").text
    header = next(csv.reader(io.StringIO(body[1:])))
    assert header == ["Last heard", "Role", "Node ID"]
