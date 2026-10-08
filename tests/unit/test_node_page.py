"""Tests for the node page endpoints and the leaderboards (#52 to #56, #60).

The database queries behind these have integration tests. These cover
the parts that need no database: the gaps rows the node page reads from
the artefact, the request rules, and the ranking of the boards.
"""

import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.api.routes import leaderboards, node_page
from sonoran.config import Settings
from sonoran.gaps import store

NODE = "!0000abcd"


def _settings(cache: Path) -> Settings:
    return Settings(_env_file=None, coverage_cache_dir=str(cache))


def _row(node_id: str, packets: int, **extra: object) -> dict[str, object]:
    return {
        "node_id": node_id,
        "display_name": node_id,
        "packets": packets,
        "active_hours": 0,
        "rf_hours": 0,
        "direct_gateways": 0,
        "worst_state": "unknown",
        "signals": {},
    } | extra


def _write(cache: Path, presets: dict[str, list[dict[str, object]]]) -> None:
    settings = _settings(cache)
    store.write_index(
        settings,
        {
            "presets": [
                {"preset": name, "label": name, "node_count": len(rows)}
                for name, rows in presets.items()
            ]
        },
    )
    for name, rows in presets.items():
        store.write_preset(
            settings,
            name,
            {
                "preset": name,
                "window_hours": 168,
                "generated_at": "2026-09-22T00:00:00+00:00",
                "gateways_active": 5,
                "signal_order": ["radio_isolated"],
                "signal_labels": {"radio_isolated": "Reaches us only through MQTT"},
                "nodes": rows,
            },
        )


# ---------------------------------------------------------------- gaps


def test_no_assessment_is_a_working_state(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        body = client.get(f"/api/nodes/{NODE}/gaps").json()
    assert body == {
        "available": False,
        "reason": "no_assessment",
        "assessments": [],
        "not_listed": [],
    }


def test_a_node_gets_its_own_row_from_each_preset(tmp_path: Path) -> None:
    """The row is served as the job wrote it, busiest preset first."""
    _write(
        tmp_path,
        {
            "LongFast": [_row(NODE, 10)],
            "MediumFast": [_row(NODE, 90), _row("!00000001", 5)],
            "ShortFast": [_row("!00000001", 5)],
        },
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        body = client.get(f"/api/nodes/{NODE}/gaps").json()
    assert body["available"] is True
    assert [item["preset"] for item in body["assessments"]] == ["MediumFast", "LongFast"]
    assert body["assessments"][0]["node"] == _row(NODE, 90)
    assert body["assessments"][0]["signal_labels"]["radio_isolated"]
    # Not assessed is a different answer from assessed and fine.
    assert body["not_listed"] == ["ShortFast"]


def test_the_node_gaps_route_opens_no_database_session() -> None:
    """It reads the artefact, as `/api/gaps` does, and computes nothing."""
    parameters = inspect.signature(node_page.node_gaps).parameters
    assert "session" not in parameters
    assert "select(" not in inspect.getsource(node_page.node_gaps)


# ------------------------------------------------------------- history


def test_every_window_stays_near_three_hundred_points() -> None:
    for hours in (1, 6, 24, 168, 720):
        points = hours * 3600 / node_page.bucket_seconds(hours)
        assert points <= 300, hours


# ------------------------------------------------------------- packets


def test_a_packet_sort_must_be_one_of_the_documented_columns(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get(f"/api/nodes/{NODE}/packets?sort=raw_bytes")
    assert response.status_code == 422


def test_an_observation_sort_needs_a_bounded_window(tmp_path: Path) -> None:
    """A sort by gateways summarises the whole window first.

    Without a bound it would summarise a node's whole history on a
    shared database, so it is refused before any query runs.
    """
    with TestClient(create_app(_settings(tmp_path))) as client:
        for query in ("sort=gateways", "sort=snr&hours=720"):
            response = client.get(f"/api/nodes/{NODE}/packets?{query}")
            assert response.status_code == 422, query


def test_a_cursor_that_is_not_one_is_refused(tmp_path: Path) -> None:
    """#259: a malformed `before` is a 422, never an unfiltered listing."""
    with TestClient(create_app(_settings(tmp_path))) as client:
        for cursor in ("garbage!!", "e30", "WyJ0aW1lIl0"):
            response = client.get(f"/api/nodes/{NODE}/packets?before={cursor}")
            assert response.status_code == 422, cursor


def test_a_cursor_carries_its_sort_and_is_refused_under_another() -> None:
    """The sort travels with every page, so page two cannot reorder."""
    from datetime import UTC, datetime

    import pytest
    from fastapi import HTTPException

    from sonoran.api.routes import nodes
    from sonoran.db.models import Packet

    row = Packet(from_node_num=5, packet_id=9, first_seen_at=datetime(2026, 9, 1, tzinfo=UTC))
    cursor = nodes._packet_cursor("snr", "asc", -3.25, row)
    value, when, sender, packet_id = nodes._read_packet_cursor(cursor, "snr", "asc")
    assert (value, when, sender, packet_id) == (-3.25, row.first_seen_at, 5, 9)
    with pytest.raises(HTTPException) as refused:
        nodes._read_packet_cursor(cursor, "snr", "desc")
    assert "sort=snr&order=asc" in str(refused.value.detail)


def test_the_packet_direction_is_sent_or_heard(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get(f"/api/nodes/{NODE}/packets?direction=to")
    assert response.status_code == 422


# -------------------------------------------------------- leaderboards


def test_the_reachable_board_ranks_by_share_of_awake_hours() -> None:
    rows = [
        _row("!00000001", 100, active_hours=100, rf_hours=50),
        _row("!00000002", 100, active_hours=48, rf_hours=48),
        # One lucky hour is not a record.
        _row("!00000003", 5, active_hours=2, rf_hours=2),
        _row("!00000004", 100, active_hours=200, rf_hours=200),
    ]
    board = leaderboards._reachable_board(rows, 168)
    assert [row["node_id"] for row in board["rows"]] == ["!00000004", "!00000002", "!00000001"]
    assert board["rows"][2]["value"] == 50.0
    assert board["cannot_know"]


def test_the_direct_board_counts_gateways_and_skips_the_unheard() -> None:
    rows = [
        _row("!00000001", 10, direct_gateways=3),
        _row("!00000002", 10, direct_gateways=0),
        _row("!00000003", 10, direct_gateways=9),
    ]
    board = leaderboards._direct_board(rows, 168)
    assert [row["node_id"] for row in board["rows"]] == ["!00000003", "!00000001"]


def test_no_board_counts_packets() -> None:
    """A packet count rewards the behaviour that hurts a shared channel."""
    source = inspect.getsource(leaderboards)
    assert "func.count" not in source
    for board in (leaderboards._reachable_board([], 1), leaderboards._direct_board([], 1)):
        assert "packet" not in board["title"].lower()


def test_leaderboards_default_to_the_busiest_preset(tmp_path: Path) -> None:
    _write(tmp_path, {"LongFast": [_row(NODE, 1)], "MediumFast": [_row(NODE, 1), _row("!1", 1)]})
    assert leaderboards._assessed_presets(_settings(tmp_path)) == ["MediumFast", "LongFast"]


def _health_cards_source() -> str:
    """The body of `healthChecks`, which decides what state a check is.

    It was `healthCards` until #95 split the checks from their
    rendering; the state logic these tests guard moved with the data,
    unchanged. The name is the only thing that changed here.
    """
    source = (
        Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    start = source.index("function healthChecks(")
    return source[start : start + 9000]


def test_heard_over_the_air_reads_radio_isolated_alone() -> None:
    """#327. The card no longer counts gateways in direct range.

    It used to read `sole_observer` and mark one direct gateway as a
    fault. That signal is gone. The card's colour is `radio_isolated`,
    which is `ok` only when something heard the node over the air, so a
    node nothing heard still never reads as health (#87).
    """
    body = _health_cards_source()
    start = body.index("const heardState")
    window = body[start - 200 : start + 200]
    assert "signal('radio_isolated')" in window
    assert "signal('sole_observer')" not in body


def test_a_rounded_position_is_not_a_fault() -> None:
    """#96. Sharing a position is optional, and rounding one is a choice.

    A coarse position used to read `warn` over the promise "Green when
    it shares its position at full precision". The mesh asks for
    neither, and rounding is how somebody keeps their house off a
    public map.
    """
    body = _health_cards_source()
    start = body.index("const position = {")
    window = body[start : start + 500]
    coarse = window[window.index("coarse:") :]
    assert coarse.lstrip().startswith("coarse: ['ok'"), (
        f"a rounded position is still scored as a fault: {coarse[:60]!r}"
    )


def test_no_card_promises_full_precision() -> None:
    """The promise has to match the rule that decides the colour.

    Only the `green:` lines are read. Prose about the old behaviour is
    allowed to quote it -- a comment explaining why something changed
    has to be able to say what it used to say.
    """
    import re

    body = _health_cards_source()
    promises = re.findall(r"green:\s*[`'\"]([^`'\"]*)", body)
    assert promises, "no green promises found; the test is looking in the wrong place"
    offenders = [text for text in promises if "full precision" in text]
    assert not offenders, (
        f"a card still tells the reader that green needs a full precision "
        f"position, which is not what the check does and not a rule this "
        f"mesh has: {offenders!r}"
    )
