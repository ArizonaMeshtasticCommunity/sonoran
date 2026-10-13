"""The tables the background jobs write, against a real database (#351).

The unit tests read these through an in-memory stand-in
(`tests/unit/job_outputs.py`). This file holds the SQL to the same
behaviour: the filters, the order, the live names, the grants, the
whole-run swap and the one-time import of the old files.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from sonoran.config import Settings
from sonoran.coverage import store as coverage_store
from sonoran.gaps import store
from sonoran.jobs import legacy_import
from tests.integration.conftest import role_url, run_store, wipe_job_outputs

# Node numbers no other test uses.
A, B, C = 0x0DB0_0001, 0x0DB0_0002, 0x0DB0_0003
NOW = "2026-10-12T12:00:00+00:00"


def _id(node_num: int) -> str:
    return f"!{node_num:08x}"


def _settings(timescale_url: str, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=role_url(timescale_url, "azmsh_api"),
        database_url_jobs=role_url(timescale_url, "azmsh_jobs"),
        database_url_api=role_url(timescale_url, "azmsh_api"),
        coverage_cache_dir=str(tmp_path / "coverage"),
    )


@pytest.fixture
def clean(migrated_engine) -> Iterator[None]:  # type: ignore[no-untyped-def]
    def wipe() -> None:
        wipe_job_outputs(migrated_engine)
        with migrated_engine.begin() as connection:
            connection.execute(text("DELETE FROM node WHERE node_num = ANY(:n)"), {"n": [A, B, C]})

    wipe()
    # A node row of a gaps run names a real node (`gaps_node` references
    # `node`), so the three nodes these runs name exist.
    for node_num, name in ((A, "Node A"), (B, "Node B"), (C, "Node C")):
        _add_node(migrated_engine, node_num, name)
    yield
    wipe()


def _add_node(engine: Any, node_num: int, long_name: str, role: str | None = "ROUTER") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO node (node_num, node_id, long_name, short_name, role,"
                " first_seen, updated_at, is_mqtt_gateway)"
                " VALUES (:n, :i, :l, :s, :r, now(), now(), false)"
                " ON CONFLICT (node_num) DO NOTHING"
            ),
            {"n": node_num, "i": _id(node_num), "l": long_name, "s": long_name[:4], "r": role},
        )


def _row(node_num: int, worst: str, signals: dict[str, str], direct: int = 0) -> dict[str, Any]:
    return {
        "node_id": _id(node_num),
        "display_name": "written at run time",
        "role": "CLIENT",
        "preset": "LongFast",
        "latitude": 33.4,
        "longitude": -112.1,
        "position_confidence": "exact",
        "position_deviation_m": None,
        "is_mqtt_gateway": False,
        "mobile": False,
        "position_spread_km": None,
        "packets": 10,
        "rf_packets": 8,
        "ambiguous_packets": 0,
        "active_hours": 6,
        "rf_hours": 5,
        "direct_gateways": direct,
        "worst_state": worst,
        "bad_count": sum(1 for state in signals.values() if state == "bad"),
        "unknown_count": sum(1 for state in signals.values() if state == "unknown"),
        "signals": {name: {"state": state, "value": None} for name, state in signals.items()},
    }


def _assessment(rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "available": True,
        "preset": "LongFast",
        "label": "Long fast",
        "window_hours": 168,
        "generated_at": NOW,
        "assessed_count": len(rows),
        "needs_help_count": 1,
        "not_enough_evidence_count": 1,
        "signal_order": ["radio_isolated", "weak_best_link"],
        "trace_answers": [{"node_id": _id(A), "requests": 12, "answered": 9, "senders": 3}],
        "nodes": rows,
    } | extra


ROWS = [
    _row(A, "bad", {"radio_isolated": "bad", "weak_best_link": "ok"}, direct=2),
    _row(B, "unknown", {"radio_isolated": "ok", "weak_best_link": "unknown"}, direct=5),
    _row(C, "ok", {"radio_isolated": "ok"}, direct=0),
]


def _write(settings: Settings, rows: list[dict[str, Any]] = ROWS) -> None:
    assert run_store(settings, store.write_preset, "LongFast", _assessment(rows))
    run_store(
        settings,
        store.write_index,
        {"generated_at": NOW, "window_hours": 168, "presets": [{"preset": "LongFast"}]},
    )


# --- a whole run --------------------------------------------------------


def test_a_run_reads_back_as_it_was_written(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    _write(settings)
    held = run_store(settings, store.read_preset, "LongFast")
    assert held is not None
    assert [row["node_id"] for row in held["nodes"]] == [_id(A), _id(B), _id(C)]
    for written, read in zip(ROWS, held["nodes"], strict=True):
        for key in store.ROW_COLUMNS:
            assert read[key] == written[key], key
        # The signals come back from `gaps_signal`, in the job's order.
        assert list(read["signals"]) == list(written["signals"])
        for name, signal in written["signals"].items():
            assert read["signals"][name]["state"] == signal["state"]
            assert isinstance(read["signals"][name]["sentence"], str)
    assert held["trace_answers"][0]["answered"] == 9
    assert held["window_hours"] == 168
    assert held["generated_at"] == NOW

    index = run_store(settings, store.read_index)
    assert index is not None
    assert index["presets"][0]["preset"] == "LongFast"
    assert index["presets"][0]["node_count"] == 3


def test_a_name_is_read_live_not_frozen_at_run_time(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    """The issue's second point: a renamed node reads with its new name."""
    settings = _settings(timescale_url, tmp_path)
    _write(settings)
    with migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE node SET long_name = 'New Name' WHERE node_num = :n"), {"n": A}
        )
    row = run_store(settings, store.node_row, "LongFast", A)
    assert row is not None
    assert row["display_name"] == "New Name"
    assert row["role"] == "ROUTER"


def test_a_new_run_replaces_the_old_one_whole(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    _write(settings)
    _write(settings, ROWS[:1])
    held = run_store(settings, store.read_preset, "LongFast")
    assert [row["node_id"] for row in held["nodes"]] == [_id(A)]


def test_a_preset_the_job_dropped_is_dropped(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    """The old files were left behind and kept answering. The rows are not."""
    settings = _settings(timescale_url, tmp_path)
    _write(settings)
    run_store(
        settings, store.write_index, {"generated_at": NOW, "window_hours": 168, "presets": []}
    )
    assert run_store(settings, store.read_preset, "LongFast") is None
    assert run_store(settings, store.read_index) == {
        "generated_at": NOW,
        "window_hours": 168,
        "presets": [],
    }


# --- the reads the routes make ------------------------------------------


@pytest.mark.parametrize(
    ("signal", "state", "expected"),
    [
        (None, None, [A, B, C]),
        ("radio_isolated", "bad", [A]),
        ("weak_best_link", None, [A, B]),
        (None, "unknown", [B]),
        (None, "ok", [A, B, C]),
    ],
)
def test_the_filters_select_in_sql(
    timescale_url: str,
    migrated_engine: Any,
    tmp_path: Path,
    clean: None,
    signal: str | None,
    state: str | None,
    expected: list[int],
) -> None:
    settings = _settings(timescale_url, tmp_path)
    _write(settings)
    matched, rows, following = run_store(settings, store.node_rows, "LongFast", signal, state, 100)
    assert matched == len(expected)
    assert [row["node_id"] for row in rows] == [_id(n) for n in expected]
    assert following is None
    _, first, _ = run_store(settings, store.node_rows, "LongFast", signal, state, 1)
    assert [row["node_id"] for row in first] == [_id(n) for n in expected[:1]]


def test_the_pages_join_up_with_no_row_twice_and_none_missed(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    _write(settings)
    seen: list[str] = []
    after = None
    for _ in range(5):
        _, rows, after = run_store(settings, store.node_rows, "LongFast", None, None, 1, after)
        seen += [row["node_id"] for row in rows]
        if after is None:
            break
    assert seen == [_id(A), _id(B), _id(C)]


def test_a_row_whose_node_has_no_record_is_left_out_not_fatal(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    """`gaps_node` references `node`. One unknown node must not fail the run."""
    settings = _settings(timescale_url, tmp_path)
    stranger = _row(0x0DB0_00FF, "bad", {"radio_isolated": "bad"})
    _write(settings, [*ROWS, stranger])
    held = run_store(settings, store.read_preset, "LongFast")
    assert [row["node_id"] for row in held["nodes"]] == [_id(A), _id(B), _id(C)]


def test_deleting_a_run_deletes_everything_under_it(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    _write(settings)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM gaps_run"))
        for table in ("gaps_node", "gaps_signal", "gaps_trace_answer"):
            left = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            assert left == 0, table


def test_the_direct_board_is_one_order_by(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    _write(settings)
    rows = run_store(settings, store.top_direct, "LongFast", None, 10)
    assert [row["node_id"] for row in rows] == [_id(B), _id(A)], "most gateways first, none unheard"


def test_the_gaps_state_filter_of_the_node_list(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    assert run_store(settings, store.node_nums, "LongFast", "bad") is None, "no run is not empty"
    _write(settings)
    assert run_store(settings, store.node_nums, "LongFast", "bad") == {A}


# --- the siting answer --------------------------------------------------


def _candidate(position: int, area: int, node_num: int | None = None) -> dict[str, Any]:
    return {
        "kind": "existing" if node_num else "ground",
        "area": area,
        "latitude": 33.4 + position / 100,
        "longitude": -112.1,
        "elevation_m": 400,
        "prominence_m": 30,
        "node_id": None if node_num is None else _id(node_num),
        "display_name": None,
        "method": "terrain_screen",
        "state": "ok",
        "screen_score": 5 - position,
        "screen_unknown": 0,
        "newly_usable": None,
        "newly_usable_nodes": [_id(A)],
        "already_usable": 1,
        "baseline_unknown": 0,
        "run_stamp": "20261012T000000Z",
        "reason": "screened",
    }


SITING = {
    "available": True,
    "preset": "LongFast",
    "generated_at": NOW,
    "areas": [
        {
            "area": 0,
            "point_count": 2,
            "node_count": 3,
            "node_ids": [_id(A), _id(B), _id(C)],
            "centroid": [33.41, -112.11],
            "bounds": [33.4, -112.12, 33.42, -112.1],
            "width_km": 2.5,
            "points": [
                {
                    "latitude": 33.4,
                    "longitude": -112.12,
                    "node_count": 2,
                    "node_ids": [_id(A), _id(B)],
                    "names": ["Node A", "Node B"],
                },
                {
                    "latitude": 33.42,
                    "longitude": -112.1,
                    "node_count": 1,
                    "node_ids": [_id(C)],
                    "names": ["Node C"],
                },
            ],
        }
    ],
    "candidates": [_candidate(0, 0, B), _candidate(1, 0), _candidate(2, 0)],
    "caveats": [{"key": "k", "text": "t"}],
}


def test_a_siting_answer_reads_back_as_it_was_written(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    assert run_store(settings, store.write_siting, "LongFast", SITING)
    held = run_store(settings, store.read_siting, "LongFast")
    assert held is not None
    assert held["areas"] == SITING["areas"]
    assert held["caveats"] == SITING["caveats"]
    assert "candidates" not in held

    matched, rows, following = run_store(settings, store.read_candidates, "LongFast", 0, 2)
    assert matched == 3
    assert following is not None
    # The name of an existing node is joined live; a sentence is made from the reason.
    assert rows[0]["display_name"] == "Node B"
    assert isinstance(rows[0]["sentence"], str)
    for key in ("latitude", "screen_score", "newly_usable_nodes", "run_stamp", "reason"):
        assert rows[1][key] == SITING["candidates"][1][key], key
    _, rest, last = run_store(settings, store.read_candidates, "LongFast", 0, 2, following)
    assert [row["latitude"] for row in rest] == [SITING["candidates"][2]["latitude"]]
    assert last is None


# --- who may do what ----------------------------------------------------


def _try(timescale_url: str, role: str, sql: str) -> bool:
    engine = create_engine(role_url(timescale_url, role).replace("+asyncpg", "+psycopg"))
    try:
        with engine.begin() as connection:
            connection.execute(text(sql))
        return True
    except DBAPIError:
        return False
    finally:
        engine.dispose()


def test_the_jobs_role_replaces_and_the_api_role_only_reads(
    timescale_url: str, migrated_engine: Any, clean: None
) -> None:
    insert = "INSERT INTO gaps_index (id, generated_at, window_hours) VALUES (1, now(), 168)"
    assert _try(timescale_url, "azmsh_jobs", insert)
    assert not _try(timescale_url, "azmsh_jobs", "UPDATE gaps_index SET window_hours = 24")
    assert _try(timescale_url, "azmsh_api", "SELECT * FROM gaps_node")
    assert not _try(timescale_url, "azmsh_api", "DELETE FROM gaps_index")
    assert not _try(timescale_url, "azmsh_ingest", "SELECT * FROM gaps_node")
    assert _try(timescale_url, "azmsh_jobs", "DELETE FROM gaps_index")


# --- the files from before #351 -----------------------------------------


def _write_old_files(root: Path) -> None:
    gaps_dir = root / "gaps"
    gaps_dir.mkdir(parents=True)
    (gaps_dir / "index.json").write_text(
        json.dumps({"generated_at": NOW, "window_hours": 168, "presets": [{"preset": "LongFast"}]})
    )
    (gaps_dir / "LongFast.json").write_text(json.dumps(_assessment(ROWS)))
    (gaps_dir / "boards-LongFast-24.json").write_text(
        json.dumps({"preset": "LongFast", "window_hours": 24, "generated_at": NOW, "nodes": []})
    )
    (gaps_dir / "siting-LongFast.json").write_text(json.dumps(SITING))
    (root / "calibration.json").write_text(
        json.dumps(
            {
                "generated_at": NOW,
                "summary": {"count": 3},
                "model_bias_db": 0.5,
                "residual_spread_db": 2.0,
                "rounds": 4,
                "nodes": [
                    {
                        "node_id": _id(A),
                        "offset_db": -2.0,
                        "observations": 9,
                        "counterparties": 4,
                        "censored": 0,
                        "reported": 5,
                        "residual_spread_db": 1.0,
                        "locked": False,
                    }
                ],
            }
        )
    )


def test_the_old_files_are_imported_once(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    _write_old_files(Path(settings.coverage_cache_dir))

    imported = run_store(settings, legacy_import.run_once, settings)
    assert set(imported) == {
        "gaps/LongFast.json",
        "gaps/boards-LongFast-24.json",
        "gaps/siting-LongFast.json",
        "calibration.json",
    }
    assert [row["node_id"] for row in run_store(settings, store.read_preset, "LongFast")["nodes"]]
    # The board file came from before #293 and held no traceroute counts.
    assert run_store(settings, store.trace_answers, "LongFast", 24) is None
    assert run_store(settings, store.read_candidates, "LongFast", None, 10)[0] == 3
    assert run_store(settings, coverage_store.calibration_offsets) == {_id(A): -2.0}

    # The second start imports nothing, and never overwrites a newer run.
    _write(settings, ROWS[:1])
    assert run_store(settings, legacy_import.run_once, settings) == []
    held = run_store(settings, store.read_preset, "LongFast")
    assert [row["node_id"] for row in held["nodes"]] == [_id(A)]
    # The files are left where they were, for a rollback.
    assert (Path(settings.coverage_cache_dir) / "calibration.json").exists()


def test_a_box_with_no_old_files_imports_nothing(
    timescale_url: str, migrated_engine: Any, tmp_path: Path, clean: None
) -> None:
    settings = _settings(timescale_url, tmp_path)
    assert run_store(settings, legacy_import.run_once, settings) == []
    assert run_store(settings, store.read_index) is None
    assert run_store(settings, coverage_store.read_calibration) is None
