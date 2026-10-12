"""Reachability is the share of traceroutes to a node that it answered (#293).

Will decided on 2026-10-08 to replace "Most consistently reachable", which
was the share of awake hours in which a gateway heard a node. That is one
way only, and a node beside any gateway scored 100 percent by sending one
packet an hour, so the board was uptime.

The new measure asks the other direction: did traffic sent TO the node
arrive, and did the node answer it? A traceroute request and its reply
are the only round trip this database can prove.

These tests pin the parts that need no database: how a request is matched
to its answer, and the floor below which a node is not ranked.
"""

import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from sonoran.api import traces
from sonoran.api.app import create_app
from sonoran.api.routes import leaderboards
from sonoran.api.traces import TraceKey, answer_counts
from sonoran.config import Settings
from sonoran.gaps import boards, signals, store
from sonoran.jobs import gaps as gaps_job

A, B, C, T = 0x0A, 0x0B, 0x0C, 0x7E  # three askers and one target


def _ask(asker: int, target: int, packet_id: int) -> TraceKey:
    """A request as stored: from the asker, to the target, no request ID."""
    return TraceKey(asker, target, None, packet_id)


def _answer(asker: int, target: int, request: int, packet_id: int = 0) -> TraceKey:
    """A reply as stored: it travels back, so `from` is the target."""
    return TraceKey(target, asker, request, packet_id or request + 1_000_000)


# --- matching a request to its answer ---------------------------------


def test_a_matched_pair_counts_as_answered() -> None:
    counts = answer_counts([_ask(A, T, 1), _answer(A, T, 1)])
    assert counts[T] == traces.Answers(requests=1, answered=1, senders=1)


def test_a_request_with_no_reply_is_unanswered() -> None:
    counts = answer_counts([_ask(A, T, 1), _ask(B, T, 2), _answer(B, T, 2)])
    assert counts[T] == traces.Answers(requests=2, answered=1, senders=2)


def test_a_reply_seen_twice_counts_once() -> None:
    """Two gateways upload the same reply. It is one answer."""
    reply = _answer(A, T, 1)
    counts = answer_counts([_ask(A, T, 1), reply, reply, _answer(A, T, 1, packet_id=99)])
    assert counts[T].answered == 1


def test_a_request_seen_twice_counts_once() -> None:
    counts = answer_counts([_ask(A, T, 1), _ask(A, T, 1)])
    assert counts[T].requests == 1


def test_a_reply_whose_request_was_never_seen_counts_in_neither() -> None:
    counts = answer_counts([_ask(A, T, 1), _answer(A, T, 7)])
    assert counts[T] == traces.Answers(requests=1, answered=0, senders=1)


def test_a_reply_from_the_wrong_node_does_not_count() -> None:
    """C replies with T's request ID. C was not asked; T did not answer."""
    counts = answer_counts([_ask(A, T, 1), _answer(A, C, 1)])
    assert counts[T].answered == 0
    assert C not in counts


def test_a_reply_to_another_asker_does_not_count() -> None:
    """Packet IDs are per sender. B's request 1 is not A's request 1."""
    counts = answer_counts([_ask(A, T, 1), _answer(B, T, 1)])
    assert counts[T].answered == 0


def test_a_self_trace_is_ignored() -> None:
    """A node that traceroutes itself proves nothing about reaching it."""
    counts = answer_counts([_ask(T, T, 1), _answer(T, T, 1), _ask(A, T, 2)])
    assert counts[T] == traces.Answers(requests=1, answered=0, senders=1)


def test_a_broadcast_traceroute_names_no_target() -> None:
    counts = answer_counts([_ask(A, traces.BROADCAST, 1)])
    assert counts == {}


def test_the_pairing_reads_the_endpoints_through_the_one_rule() -> None:
    """A reply's endpoints are the wrong way round. `trace_endpoints` says so.

    AGENTS.md 9.18: the rules for reading a row live in `api/traces.py`,
    and a second reading of them is how three pages came to disagree.
    """
    body = inspect.getsource(traces.answer_counts)
    assert "trace_endpoints(" in body
    assert "is_reply(" in body


# --- the floor and the order -------------------------------------------


def _row(node: int, requests: int, answered: int, senders: int) -> dict[str, object]:
    return {
        "node_id": f"!{node:08x}",
        "display_name": f"N{node}",
        "requests": requests,
        "answered": answered,
        "senders": senders,
    }


def _order(board: dict[str, object]) -> list[object]:
    rows = board["rows"]
    assert isinstance(rows, list)
    return [row["node_id"] for row in rows]


def test_nine_traceroutes_are_below_the_floor() -> None:
    board = leaderboards._reachable_board([_row(1, 9, 9, 3)], 168)
    assert _order(board) == []
    assert board["not_ranked"] == 1


def test_ten_traceroutes_from_one_sender_are_below_the_floor() -> None:
    """One bad vantage point would otherwise decide a node's whole score."""
    board = leaderboards._reachable_board([_row(1, 10, 10, 1)], 168)
    assert _order(board) == []
    assert board["not_ranked"] == 1


def test_ten_traceroutes_from_two_senders_are_ranked() -> None:
    board = leaderboards._reachable_board([_row(1, 10, 7, 2)], 168)
    assert _order(board) == ["!00000001"]
    assert board["not_ranked"] == 0
    (row,) = board["rows"]  # type: ignore[misc]
    assert row["value"] == 70.0
    assert row["unit"] == "%"
    assert row["detail"] == "7 of 10 answered, 2 senders"


def test_more_evidence_outranks_a_perfect_small_sample() -> None:
    """95 of 100 is better evidence of reachability than 10 of 10."""
    board = leaderboards._reachable_board([_row(1, 10, 10, 2), _row(2, 100, 95, 6)], 168)
    assert _order(board) == ["!00000002", "!00000001"]


def test_a_node_that_never_answered_is_ranked_and_says_zero() -> None:
    """Zero is a measurement here, not a missing value."""
    board = leaderboards._reachable_board([_row(1, 12, 0, 3), _row(2, 12, 6, 3)], 168)
    assert _order(board) == ["!00000002", "!00000001"]
    assert board["rows"][1]["value"] == 0.0  # type: ignore[index]


def test_the_board_says_how_many_were_left_out() -> None:
    rows = [_row(1, 3, 3, 1), _row(2, 9, 9, 4), _row(3, 20, 18, 3)]
    board = leaderboards._reachable_board(rows, 168)
    assert board["not_ranked"] == 2
    assert "2 traced nodes are not ranked" in str(board["measure"])


def test_the_board_names_what_it_measures_and_cannot_know() -> None:
    board = leaderboards._reachable_board([], 168)
    assert "traceroute" in str(board["title"]).lower()
    assert "answer" in str(board["title"]).lower()
    caveat = str(board["cannot_know"])
    assert "unanswered as far as we can tell" in caveat
    assert "nobody traceroutes" in caveat


def test_a_file_written_before_the_measure_says_so() -> None:
    """An older file holds no traceroute counts. That is not zero answers."""
    board = leaderboards._reachable_board(None, 168)
    assert board["rows"] == []
    assert "not counted" in str(board["measure"])


# --- one measure, in one place -----------------------------------------


def test_the_uptime_ratio_is_gone_from_the_leaderboards() -> None:
    """Will asked to replace it, not to keep it beside the new one."""
    source = inspect.getsource(leaderboards)
    assert "rf_hours" not in source
    assert "active_hours" not in source


def test_the_reachable_measure_is_one_function() -> None:
    source = inspect.getsource(leaderboards)
    body = inspect.getsource(leaderboards._reachable_board)
    for key in ('"answered"', '"senders"', "MIN_TRACES", "MIN_SENDERS"):
        assert source.count(key) == body.count(key) + (1 if key.startswith("MIN") else 0), key


def test_the_job_writes_the_counts_into_both_files() -> None:
    """The 7 d assessment and the extra windows carry the same counts."""
    assess = inspect.getsource(gaps_job.assess_preset)
    windows = inspect.getsource(gaps_job.write_board_windows)
    for body in (assess, windows):
        assert "read_trace_answers(" in body
        assert "TRACE_ANSWERS" in body


def test_a_board_file_without_the_counts_is_rebuilt() -> None:
    """A file from before #293 must not answer for six more hours."""
    from datetime import UTC, datetime

    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    held: dict[str, object] = {"window_hours": 720, "generated_at": now.isoformat()}
    assert boards.is_due(held, 720, now)
    assert not boards.is_due(held | {"trace_answers": []}, 720, now)


def test_the_read_selects_by_window_and_preset_never_by_recency() -> None:
    """AGENTS.md 9.19: a row limit must never decide what evidence exists."""
    body = inspect.getsource(signals.read_trace_answers)
    assert ".limit(" not in body
    assert "_on_preset(" in body
    assert "answer_counts(" in body


def test_the_gaps_summary_does_not_carry_the_trace_counts(tmp_path: Path) -> None:
    """The gaps page has no use for them; they stay in the file."""
    settings = Settings(_env_file=None, coverage_cache_dir=str(tmp_path))
    store.write_index(settings, {"presets": [{"preset": "LongFast", "node_count": 0}]})
    store.write_preset(
        settings,
        "LongFast",
        {
            "preset": "LongFast",
            "window_hours": 168,
            "nodes": [],
            "trace_answers": [_row(1, 10, 7, 2)],
        },
    )
    with TestClient(create_app(settings)) as client:
        summary = client.get("/api/gaps?channel=LongFast").json()
    assert summary["window_hours"] == 168
    assert "trace_answers" not in summary
