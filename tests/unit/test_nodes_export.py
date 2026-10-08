"""The node list exports what it shows, as CSV or JSON (#350).

The claims, and why each is here:

* **The file holds the rows the list would show.** The export route
  builds its query with the same function as `/api/nodes`, so a filter
  cannot reach one and miss the other. Here that is proved on the SQL
  itself, for several filter combinations: the statement the export runs
  is the statement the list runs, less the paging. The integration test
  `tests/integration/test_nodes_export.py` proves it on rows.
* **A cell cannot become a formula.** A node name is typed by whoever
  owns the node. A spreadsheet runs a cell that starts with `=`, `+`,
  `-` or `@` as a formula, so such a cell is prefixed with `'`.
* **The file has a ceiling, and says so rather than cutting.** A file
  that silently stops at a cap is a file that lies about the mesh. Over
  the ceiling the route refuses with a sentence a reader can act on.
* **It is a download.** `Content-Disposition: attachment` with a file
  name, a content type, and no cache.
"""

import csv
import io
import json
import re
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from sonoran.api import export
from sonoran.api.app import create_app
from sonoran.api.dependencies import get_session
from sonoran.api.schemas import NodeSummary
from sonoran.config import Settings

HEARD = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


def _summary(**values: Any) -> NodeSummary:
    base: dict[str, Any] = {
        "node_id": "!0000abcd",
        "node_num": 0xABCD,
        "long_name": "Example",
        "short_name": "EXM",
        "display_name": "Example",
        "hw_model": "TBEAM",
        "role": "CLIENT",
        "last_heard": HEARD,
        "is_mqtt_gateway": True,
        "has_position": False,
    }
    base.update(values)
    return NodeSummary(**base)


def _read_csv(text: str) -> list[list[str]]:
    assert text.startswith("﻿"), "the CSV has no byte order mark, so Excel misreads names"
    return list(csv.reader(io.StringIO(text[1:])))


# ------------------------------------------------------------ columns


def test_the_default_columns_are_the_screen_columns_in_screen_order() -> None:
    assert export.parse_columns(None) == ("name", "node_id", "hw", "role", "flags", "last_heard")
    assert export.parse_columns("") == export.DEFAULT_COLUMNS


def test_a_chosen_order_is_kept() -> None:
    """The page sends its columns in the order it draws them."""
    assert export.parse_columns("last_heard,node_id,name") == ("last_heard", "node_id", "name")


@pytest.mark.parametrize("raw", ["name,secret", "lat", "name,name", "name,,role"])
def test_an_unknown_or_repeated_column_is_refused(raw: str) -> None:
    """Only the listed columns exist. A name is never looked up as a field."""
    with pytest.raises(ValueError):
        export.parse_columns(raw)


def test_no_column_exports_a_field_the_list_does_not_show() -> None:
    """Privacy: the export adds no field. Above all, no coordinates."""
    fields = {field for _, field in export.fields(export.DEFAULT_COLUMNS)}
    assert fields == {
        "display_name",
        "short_name",
        "node_id",
        "hw_model",
        "role",
        "is_mqtt_gateway",
        "has_position",
        "last_heard",
    }
    assert fields <= set(NodeSummary.model_fields)


# ------------------------------------------------------- the formula guard


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_a_cell_that_would_run_as_a_formula_is_prefixed(lead: str) -> None:
    assert export.safe_cell(f"{lead}HYPERLINK(1)") == f"'{lead}HYPERLINK(1)"


@pytest.mark.parametrize("value", ["!0000abcd", "Base 1", "", "a=b", "x-1"])
def test_an_ordinary_cell_is_untouched(value: str) -> None:
    assert export.safe_cell(value) == value


# ------------------------------------------------------------- the CSV


def test_the_csv_header_follows_the_column_order() -> None:
    text = export.to_csv([_summary()], ("node_id", "flags", "name"))
    rows = _read_csv(text)
    assert rows[0] == ["Node ID", "Gateway", "Position", "Name", "Short name"]
    assert rows[1] == ["!0000abcd", "true", "false", "Example", "EXM"]


def test_the_csv_writes_every_default_column() -> None:
    rows = _read_csv(export.to_csv([_summary()], export.DEFAULT_COLUMNS))
    assert rows[0] == [
        "Name",
        "Short name",
        "Node ID",
        "Hardware",
        "Role",
        "Gateway",
        "Position",
        "Last heard",
    ]
    # The time as the list's JSON carries it, which is a fact that stays
    # true in a saved file. "5 minutes ago" would not.
    assert rows[1][-1] == "2026-10-01T12:30:00Z"


def test_the_csv_quotes_what_needs_quoting() -> None:
    awkward = 'Comma, "quote"\nand a new line'
    rows = _read_csv(export.to_csv([_summary(display_name=awkward)], ("name",)))
    assert rows[1][0] == awkward


def test_a_hostile_name_is_defused_in_the_file() -> None:
    hostile = '=HYPERLINK("http://example.invalid","x")'
    text = export.to_csv([_summary(display_name=hostile, short_name="@SUM")], ("name",))
    rows = _read_csv(text)
    assert rows[1] == ["'" + hostile, "'@SUM"]


def test_an_empty_value_is_an_empty_cell() -> None:
    rows = _read_csv(
        export.to_csv([_summary(hw_model=None, last_heard=None)], ("hw", "last_heard"))
    )
    assert rows[1] == ["", ""]


def test_lines_end_with_crlf() -> None:
    """RFC 4180."""
    assert "\r\n" in export.to_csv([_summary()], ("node_id",))


# ------------------------------------------------------------- the JSON


def test_the_json_is_the_list_values_in_column_order() -> None:
    node = _summary(display_name="=1+1")
    rows = json.loads(export.to_json([node], ("node_id", "name", "last_heard")))
    assert list(rows[0]) == ["node_id", "display_name", "short_name", "last_heard"]
    listed = node.model_dump(mode="json")
    # No formula guard in JSON: nothing evaluates it, and the value must
    # equal the list's value byte for byte.
    assert rows[0] == {key: listed[key] for key in rows[0]}


# ----------------------------------------------------------- the route


class _FakeSession:
    """Records every statement, answers with the counts and rows given."""

    def __init__(self, total: int, rows: list[Any]) -> None:
        self.total = total
        self.rows = rows
        self.statements: list[Any] = []

    async def scalar(self, statement: Any) -> int:
        self.statements.append(statement)
        return self.total

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: self.rows)


def _node(num: int, **values: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "node_num": num,
        "long_name": f"Node {num}",
        "short_name": f"N{num}",
        "hw_model": "TBEAM",
        "role": "ROUTER",
        "last_heard": HEARD - timedelta(minutes=num),
        "is_mqtt_gateway": False,
        "last_lat": None,
        "last_lon": None,
        "last_channel": "LongFast",
        "is_licensed": False,
        "last_position_precision_bits": None,
    }
    base.update(values)
    return SimpleNamespace(**base)


@pytest.fixture
def fake() -> Iterator[tuple[TestClient, list[_FakeSession]]]:
    sessions: list[_FakeSession] = []
    app = create_app(Settings(_env_file=None))

    def make(total: int = 2, rows: list[Any] | None = None) -> None:
        sessions.append(_FakeSession(total, rows if rows is not None else []))

    async def override() -> AsyncIterator[_FakeSession]:
        yield sessions[-1]

    app.dependency_overrides[get_session] = override
    client = TestClient(app)
    client.make = make  # type: ignore[attr-defined]
    yield client, sessions


def test_the_route_is_a_download(fake: tuple[TestClient, list[_FakeSession]]) -> None:
    client, _ = fake
    rows = [(_node(1), None), (_node(2), None)]
    client.make(total=2, rows=rows)  # type: ignore[attr-defined]
    answer = client.get("/api/nodes/export?format=csv")
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "text/csv; charset=utf-8"
    disposition = answer.headers["content-disposition"]
    assert re.fullmatch(r'attachment; filename="sonoran-nodes-\d{8}-\d{6}Z\.csv"', disposition)
    assert answer.headers["cache-control"] == "no-store"
    assert answer.headers["x-total-count"] == "2"
    assert len(_read_csv(answer.text)) == 3


def test_the_json_route_is_a_download(fake: tuple[TestClient, list[_FakeSession]]) -> None:
    client, _ = fake
    client.make(total=1, rows=[(_node(1), None)])  # type: ignore[attr-defined]
    answer = client.get("/api/nodes/export?format=json&columns=node_id,role")
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "application/json"
    assert answer.headers["content-disposition"].endswith('.json"')
    assert answer.json() == [{"node_id": "!00000001", "role": "ROUTER"}]


def test_an_unknown_column_or_format_is_a_422(fake: tuple[TestClient, list[_FakeSession]]) -> None:
    client, _ = fake
    client.make()  # type: ignore[attr-defined]
    assert client.get("/api/nodes/export?columns=name,last_lat").status_code == 422
    assert client.get("/api/nodes/export?format=xlsx").status_code == 422
    # The list's own refusals reach the export too, because it is the
    # same parameter set.
    assert client.get("/api/nodes/export?sort=secret").status_code == 422
    assert client.get("/api/nodes/export?gaps=bad").status_code == 422


def test_over_the_ceiling_is_refused_not_cut(
    fake: tuple[TestClient, list[_FakeSession]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, sessions = fake
    monkeypatch.setattr(export, "EXPORT_LIMIT", 3)
    client.make(total=4, rows=[(_node(n), None) for n in range(4)])  # type: ignore[attr-defined]
    answer = client.get("/api/nodes/export")
    assert answer.status_code == 422
    assert "4 nodes match" in answer.text and "3" in answer.text
    # Refused on the count, before a single row was read.
    assert len(sessions[-1].statements) == 1


def test_rows_that_grew_past_the_count_are_refused_too(
    fake: tuple[TestClient, list[_FakeSession]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The count is a second query. Nodes heard between the two can
    carry the rows past the ceiling, and the file must not be cut then
    either."""
    client, sessions = fake
    monkeypatch.setattr(export, "EXPORT_LIMIT", 3)
    client.make(total=3, rows=[(_node(n), None) for n in range(4)])  # type: ignore[attr-defined]
    answer = client.get("/api/nodes/export")
    assert answer.status_code == 422
    limit = sessions[-1].statements[1]._limit_clause.value
    assert limit == 4, "the rows are read one past the ceiling, so an overflow is seen"


def test_exactly_the_ceiling_is_served(
    fake: tuple[TestClient, list[_FakeSession]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = fake
    monkeypatch.setattr(export, "EXPORT_LIMIT", 3)
    client.make(total=3, rows=[(_node(n), None) for n in range(3)])  # type: ignore[attr-defined]
    answer = client.get("/api/nodes/export")
    assert answer.status_code == 200, answer.text
    assert len(_read_csv(answer.text)) == 4


def _sql(statement: Any) -> tuple[str, dict[str, Any]]:
    """The statement without its paging, and its parameters.

    A time parameter (`active_hours` and the like) is measured from "now"
    on each call, so it is compared to the second rather than exactly.
    """
    compiled = statement.compile(dialect=postgresql.dialect())
    text = re.sub(r"\s+(LIMIT|OFFSET) %\(\w+\)s", "", str(compiled))
    paging = {name for name in re.findall(r"(?:LIMIT|OFFSET) %\((\w+)\)s", str(compiled))}
    params = {
        key: (value.replace(microsecond=0) if isinstance(value, datetime) else value)
        for key, value in compiled.params.items()
        if key not in paging
    }
    return text, params


@pytest.mark.parametrize(
    "query",
    [
        "q=base",
        "role=ROUTER&active_hours=24&sort=name&order=asc",
        "gateway=true&position=none&channel=LongFast&sort=hw&order=desc",
        "licensed=true&quiet_hours=24&first_seen_hours=720&hw=TBEAM&sort=position",
        "",
    ],
)
def test_the_export_runs_the_list_query(
    fake: tuple[TestClient, list[_FakeSession]], query: str
) -> None:
    """Filters cannot drift between the screen and the file.

    The list's count and rows and the export's count and rows are
    compiled and compared. Only the paging may differ.
    """
    client, sessions = fake
    client.make(total=0, rows=[])  # type: ignore[attr-defined]
    assert client.get(f"/api/nodes?{query}").status_code == 200
    listed = sessions[-1].statements
    client.make(total=0, rows=[])  # type: ignore[attr-defined]
    assert client.get(f"/api/nodes/export?{query}").status_code == 200
    exported = sessions[-1].statements
    assert len(listed) == len(exported) == 2
    for mine, theirs in zip(listed, exported, strict=True):
        assert _sql(mine) == _sql(theirs)


def test_the_export_is_counted_in_the_request_budget() -> None:
    """One export is one request of the general budget, like a page."""
    from sonoran.api.limits import TILE_PREFIXES

    assert not "/api/nodes/export".startswith(TILE_PREFIXES)
    app = create_app(
        Settings(
            _env_file=None, api_rate_limit_enabled=True, api_rate_burst=1, api_rate_per_second=0.001
        )
    )

    async def override() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(0, [])

    app.dependency_overrides[get_session] = override
    client = TestClient(app)
    assert client.get("/api/nodes/export").status_code == 200
    assert client.get("/api/nodes/export").status_code == 429
