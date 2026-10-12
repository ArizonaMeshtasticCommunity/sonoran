"""The gaps leaderboards follow the Statistics range (#294).

Will chose option A on 2026-10-08: the two boards read from the gaps
assessment follow the page's range, 24 h, 7 d and 30 d, instead of the
job's fixed 7 days.

The job writes a small file for each extra window beside the assessment.
These tests pin the parts that need no database: which window a request
gets, what is said when no file can answer it, how often each file is
rebuilt, and that the ranking itself lives in one function.
"""

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.api.routes import leaderboards
from sonoran.config import Settings
from sonoran.gaps import boards, signals, store

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _settings(cache: Path, **extra: Any) -> Settings:
    return Settings(_env_file=None, coverage_cache_dir=str(cache), **extra)


def _row(node_id: str, active_hours: int, rf_hours: int, direct: int = 0) -> dict[str, object]:
    return {
        "node_id": node_id,
        "display_name": node_id,
        "packets": active_hours,
        "active_hours": active_hours,
        "rf_hours": rf_hours,
        "direct_gateways": direct,
    }


# The seven day assessment ranks A first; the 24 hour file ranks B first.
WEEK = [_row("!0000000a", 100, 100, direct=1), _row("!0000000b", 100, 10, direct=5)]
DAY = [_row("!0000000a", 20, 2, direct=4), _row("!0000000b", 20, 20, direct=0)]
LONG = [_row("!0000000a", 300, 30), _row("!0000000b", 300, 300)]


def _write_assessment(settings: Settings, rows: list[dict[str, object]] = WEEK) -> None:
    store.write_index(
        settings, {"presets": [{"preset": "LongFast", "label": "Long fast", "node_count": 2}]}
    )
    store.write_preset(
        settings,
        "LongFast",
        {"preset": "LongFast", "window_hours": settings.gaps_window_hours, "nodes": rows},
    )


def _write_board(settings: Settings, asked: int, hours: int, rows: list[dict[str, object]]) -> None:
    path = store.write_boards(
        settings,
        "LongFast",
        asked,
        {
            "preset": "LongFast",
            "window_hours": hours,
            "generated_at": NOW.isoformat(),
            "nodes": rows,
        },
    )
    assert path is not None


@pytest.fixture
def no_link_board(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the link board off the database; it is not under test here."""

    async def fake(*_: object, **__: object) -> dict[str, object]:
        return {"key": "longest_link", "rows": [], "window_hours": 72, "follows_window": False}

    monkeypatch.setattr(leaderboards, "_link_board", fake)
    leaderboards._link_caches._held.clear()


def _gaps_boards(client: TestClient, query: str) -> dict[str, dict[str, Any]]:
    body = client.get(f"/api/stats/leaderboards?channel=LongFast&{query}").json()
    assert body["available"] is True, body
    return {board["key"]: board for board in body["boards"] if board["key"] != "longest_link"}


def _order(board: dict[str, Any]) -> list[str]:
    return [row["node_id"] for row in board["rows"]]


# --- which window a request gets ------------------------------------


def test_each_quick_range_reads_its_own_window(tmp_path: Path, no_link_board: None) -> None:
    settings = _settings(tmp_path)
    _write_assessment(settings)
    _write_board(settings, 24, 24, DAY)
    with TestClient(create_app(settings)) as client:
        day = _gaps_boards(client, "hours=24")
        week = _gaps_boards(client, "hours=168")
    assert _order(day["reachable"]) == ["!0000000b", "!0000000a"]
    assert _order(week["reachable"]) == ["!0000000a", "!0000000b"]
    assert _order(day["direct_gateways"]) == ["!0000000a"]
    assert _order(week["direct_gateways"]) == ["!0000000b", "!0000000a"]
    for board in (*day.values(), *week.values()):
        assert board["follows_window"] is True, board["key"]
    assert day["reachable"]["window_hours"] == 24
    assert week["reachable"]["window_hours"] == 168


def test_a_missing_window_file_serves_the_assessment_and_says_so(
    tmp_path: Path, no_link_board: None
) -> None:
    """An old deployment has only the seven day file. It still serves."""
    settings = _settings(tmp_path)
    _write_assessment(settings)
    with TestClient(create_app(settings)) as client:
        month = _gaps_boards(client, "hours=720")
    for board in month.values():
        assert board["follows_window"] is False
        assert board["window_hours"] == 168
    assert _order(month["reachable"]) == ["!0000000a", "!0000000b"]


def test_a_custom_range_is_never_passed_off_as_a_board_window(
    tmp_path: Path, no_link_board: None
) -> None:
    """A fixed from/to range cannot be precomputed. The boards say so."""
    settings = _settings(tmp_path)
    _write_assessment(settings)
    _write_board(settings, 24, 24, DAY)
    with TestClient(create_app(settings)) as client:
        custom = _gaps_boards(client, "since=2026-10-07")
    for board in custom.values():
        assert board["follows_window"] is False
        assert board["window_hours"] == 168


def test_no_window_is_the_assessment_as_before(tmp_path: Path, no_link_board: None) -> None:
    settings = _settings(tmp_path)
    _write_assessment(settings)
    _write_board(settings, 24, 24, DAY)
    with TestClient(create_app(settings)) as client:
        plain = _gaps_boards(client, "")
    assert _order(plain["reachable"]) == ["!0000000a", "!0000000b"]
    assert plain["reachable"]["window_hours"] == 168


def test_a_window_cut_short_by_retention_does_not_follow(
    tmp_path: Path, no_link_board: None
) -> None:
    """With 14 days of packets kept, the 30 d board holds 14 days."""
    settings = _settings(tmp_path, retention_days_packet=14)
    _write_assessment(settings)
    _write_board(settings, 720, 336, LONG)
    with TestClient(create_app(settings)) as client:
        month = _gaps_boards(client, "hours=720")
    assert month["reachable"]["window_hours"] == 336
    assert month["reachable"]["follows_window"] is False
    assert _order(month["reachable"]) == ["!0000000b", "!0000000a"]


def test_a_preset_with_no_assessment_borrows_no_board_file(
    tmp_path: Path, no_link_board: None
) -> None:
    settings = _settings(tmp_path)
    _write_board(settings, 24, 24, DAY)
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/stats/leaderboards?channel=LongFast&hours=24").json()
    assert body["assessed"] is False
    assert all(not board["rows"] for board in body["boards"])


# --- the windows the job writes -------------------------------------


def test_the_board_windows_are_the_page_buttons() -> None:
    """`STATS_RANGES` in app.js: 24 h, 7 d and 30 d."""
    assert boards.BOARD_WINDOW_HOURS == (24, 168, 720)
    app = (Path(boards.__file__).parents[1] / "web" / "static" / "app.js").read_text("utf-8")
    assert "const STATS_RANGES = { '24h': 24, '7d': 168, '30d': 720 };" in app


def test_a_window_is_capped_at_packet_retention(tmp_path: Path) -> None:
    assert boards.window_hours(_settings(tmp_path), 720) == 720
    assert boards.window_hours(_settings(tmp_path, retention_days_packet=14), 720) == 336
    assert boards.window_hours(_settings(tmp_path, retention_days_packet=14), 24) == 24


def test_the_assessment_window_gets_no_second_file(tmp_path: Path) -> None:
    """The seven day board is the assessment. Writing it twice costs a run."""
    assert boards.extra_windows(_settings(tmp_path)) == [24, 720]
    assert boards.extra_windows(_settings(tmp_path, gaps_window_hours=720)) == [24, 168]
    # 30 d capped to 7 d of retention is the assessment's own window.
    capped = _settings(tmp_path, retention_days_packet=7)
    assert boards.extra_windows(capped) == [24]


def _held(hours: int, age: timedelta) -> dict[str, object]:
    return {"window_hours": hours, "generated_at": (NOW - age).isoformat()}


def test_a_short_window_is_rebuilt_every_run_and_a_long_one_is_not() -> None:
    """The month board changes slowly, and it is the expensive read."""
    assert boards.is_due(None, 24, NOW)
    assert boards.is_due(_held(24, timedelta(minutes=30)), 24, NOW)
    assert not boards.is_due(_held(720, timedelta(hours=1)), 720, NOW)
    assert boards.is_due(_held(720, timedelta(hours=6)), 720, NOW)


def test_a_file_from_another_window_or_unreadable_is_rebuilt() -> None:
    assert boards.is_due(_held(336, timedelta(minutes=1)), 720, NOW)
    assert boards.is_due({"window_hours": 720, "generated_at": "yesterday"}, 720, NOW)
    assert boards.is_due({"window_hours": 720}, 720, NOW)


def test_a_board_file_name_is_checked_before_it_is_a_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert store.boards_path(settings, "../etc", 24) is None
    assert store.boards_path(settings, "LongFast", 25) is None
    expected = tmp_path / "gaps" / "boards-LongFast-24.json"
    assert store.boards_path(settings, "LongFast", 24) == expected
    assert store.read_boards(settings, "LongFast", 24) is None


def test_the_board_file_is_not_an_assessment_the_gaps_page_lists(tmp_path: Path) -> None:
    """`assessed_presets` reads the index, so a board file adds no preset."""
    settings = _settings(tmp_path)
    _write_assessment(settings)
    _write_board(settings, 24, 24, DAY)
    assert [item["preset"] for item in store.assessed_presets(settings)] == ["LongFast"]
    held = store.read_preset(settings, "LongFast")
    assert held is not None and held["nodes"] == WEEK


# --- one rule, in one place -----------------------------------------


def test_the_reachable_ranking_is_one_function() -> None:
    """#293 will change what this board measures. It swaps one function.

    Nothing else in the route reads the two hour counts, so the ratio is
    computed in exactly one place for every window.
    """
    source = inspect.getsource(leaderboards)
    body = inspect.getsource(leaderboards._reachable_board)
    assert source.count("rf_hours") == body.count("rf_hours")


def test_the_awake_floor_scales_with_a_short_window() -> None:
    """24 hours awake out of a 24 hour window would rank almost nobody."""
    half_day = [_row("!0000000c", 12, 12)]
    assert _order(leaderboards._reachable_board(half_day, 24)) == ["!0000000c"]
    assert _order(leaderboards._reachable_board(half_day, 168)) == []
    assert leaderboards.MIN_AWAKE_HOURS == 24


def test_the_board_evidence_shares_the_assessment_query() -> None:
    """The board windows read the same packet summary as the assessment.

    A second copy of the rule that says when a packet was heard on the
    air would drift from the first.
    """
    full = inspect.getsource(signals.read_evidence)
    lean = inspect.getsource(signals.read_reach_evidence)
    for body in (full, lean):
        assert "_packet_summary(" in body
        assert "_read_direct_gateways(" in body
    # The lean read is the cheap one: no neighbour, trace or position work.
    for costly in ("_read_neighbour_evidence", "read_trace_evidence", "_read_position_spread"):
        assert costly not in lean


def test_the_page_believes_the_api_and_not_its_own_button() -> None:
    """The chip reads `follows_window` from each board, never the board key.

    A page that decided by key which boards follow would go on saying
    "not the page range" for boards that now follow it, or worse, stop
    saying it for a custom range that they cannot follow.
    """
    app = (Path(boards.__file__).parents[1] / "web" / "static" / "app.js").read_text("utf-8")
    body = app[app.index("const boardWindow = (board) =>") :]
    body = body[: body.index("};")]
    assert "board.follows_window" in body
    assert "board.key" not in body
    assert "not the page range" in body
