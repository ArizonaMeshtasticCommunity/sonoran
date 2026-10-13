"""Read models: freshness, ranking, the build plan and the scheduler (#371).

`tests/integration/test_read_models.py` checks every stored view against
the live one through the API.
"""

import asyncio
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from sonoran import read_models
from sonoran.api.routes import graph, leaderboards, stats
from sonoran.api.routes import map as map_routes
from sonoran.api.routes.graph import Edge
from sonoran.config import Settings
from sonoran.jobs import read_models as job
from sonoran.jobs import scheduler

NOW = datetime.now(UTC)


def _settings(**extra: object) -> Settings:
    return Settings(_env_file=None, **extra)  # type: ignore[arg-type]


def test_a_30_day_window_is_built_less_often() -> None:
    settings = _settings(read_models_interval_minutes=10, read_models_long_every=3)
    assert read_models.build_interval(24, settings) == timedelta(minutes=10)
    assert read_models.build_interval(720, settings) == timedelta(minutes=30)


def test_a_build_older_than_three_intervals_is_not_served() -> None:
    settings = _settings(read_models_interval_minutes=10)
    now = datetime.now(UTC)
    assert read_models.is_fresh(now - timedelta(minutes=29), 24, settings)
    assert not read_models.is_fresh(now - timedelta(minutes=31), 24, settings)
    assert read_models.is_fresh(now - timedelta(minutes=89), 720, settings)


def test_turned_off_means_nothing_stored_is_served() -> None:
    settings = _settings(read_models_enabled=False)
    assert not read_models.is_fresh(datetime.now(UTC), 24, settings)


def test_links_rank_by_reports_then_by_node_numbers() -> None:
    """The tie-break makes a stored build and a live graph keep the same links."""
    edges = [
        Edge(source=5, target=6, kind="neighbor", snr=None, time=NOW, forward=2, backward=1),
        Edge(source=1, target=9, kind="neighbor", snr=None, time=NOW, forward=2, backward=1),
        Edge(source=3, target=4, kind="neighbor", snr=None, time=NOW, forward=9, backward=0),
    ]
    ranked = read_models.rank_edges(reversed(edges))
    assert [(edge.source, edge.target) for edge in ranked] == [(3, 4), (1, 9), (5, 6)]


def test_the_plan_covers_the_graph_and_the_board_once_each() -> None:
    planned = job.plan_links(["MediumFast", "Weather"], ["MediumFast", "LongFast"])
    assert len(planned) == len(set(planned)), "a window would be built twice"
    for hours in read_models.GRAPH_HOURS:
        assert (read_models.EVERY_CHANNEL, hours) in planned
        assert ("Weather", hours) in planned
    for hours in read_models.BOARD_HOURS:
        assert ("LongFast", hours) in planned
    assert ("Weather", 720) not in planned, "a topic channel has no board"


def test_the_scheduler_runs_the_read_models_on_their_own_clock() -> None:
    tasks = {task.name: task for task in scheduler.build_tasks(_settings())}
    assert "read-models" in tasks
    assert tasks["read-models"].next_delay() == 600.0
    off = {task.name for task in scheduler.build_tasks(_settings(read_models_enabled=False))}
    assert "read-models" not in off


def test_the_read_models_step_aside_for_a_coverage_run(monkeypatch: pytest.MonkeyPatch) -> None:
    task = next(t for t in scheduler.build_tasks(_settings()) if t.name == "read-models")

    def no_engine(*_: object) -> None:
        raise AssertionError("it opened the database during a coverage run")

    monkeypatch.setattr(scheduler, "make_engine", no_engine)
    scheduler.RUNNING.add("coverage")
    try:
        asyncio.run(task.run())
    finally:
        scheduler.RUNNING.discard("coverage")


def test_each_long_view_reads_the_stored_build_first() -> None:
    """The four views the jobs build; the live code stays as the fallback."""
    for function, call in (
        (graph._mesh_graph, "read_models.read_links("),
        (leaderboards._link_board, "read_links("),
        (stats._read_broadcast, "read_models.read_broadcast("),
        (map_routes.map_nodes, "read_models.has_channel_nodes("),
    ):
        assert call in inspect.getsource(function), function.__name__


def test_the_statistics_counts_read_the_hourly_totals() -> None:
    for function, call in (
        (stats._read_top, "hourly.top_senders("),
        (stats._read_hardware, "hourly.senders_heard("),
        (stats.broadcast_ranking, "hourly.sender_port_counts("),
    ):
        assert call in inspect.getsource(function), function.__name__
