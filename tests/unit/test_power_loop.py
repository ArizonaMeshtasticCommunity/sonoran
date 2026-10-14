"""A power loop is several restarts close together, counted (#365).

The issue's rule, as tests written before the code (AGENTS.md §3A.5):

- restarts are counted from `uptime_seconds` falling between readings;
- a power loop is at least `LOOP_RESTARTS` restarts inside `LOOP_SPAN`,
  and NodeInfo sent faster than its default;
- battery is context, never the trigger;
- the table puts real power loops first, then the rows that meet its own
  heading (3x the default or more).

`tests/integration/test_power_loop.py` checks the counting on real rows.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sonoran.api.routes import stats

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _at(hours: float) -> datetime:
    return NOW + timedelta(hours=hours)


def test_restarts_are_counted_inside_the_busiest_day() -> None:
    times = [_at(0), _at(1), _at(2), _at(30)]
    assert stats.most_restarts_within(times, timedelta(hours=24)) == 3
    assert stats.most_restarts_within([], timedelta(hours=24)) == 0
    assert stats.most_restarts_within([_at(0), _at(25)], timedelta(hours=24)) == 1


def test_the_busiest_span_says_where_it_starts() -> None:
    """NodeInfo is judged inside the same 24 h as the restarts.

    Measured on live data (docs/DECISIONS.md): a node with 15 restarts in
    one day averaged 0.87x NodeInfo over 30 days, and 1.75x on that day.
    A window-long average hides the day.
    """
    times = [_at(0), _at(40), _at(41), _at(42), _at(80)]
    count, start = stats.busiest_span(times, timedelta(hours=24))
    assert (count, start) == (3, _at(40))
    assert stats.busiest_span([], timedelta(hours=24)) == (0, None)


def test_the_loop_threshold_is_the_measured_one() -> None:
    """At 4 or more restarts in 24 h, every node also sent NodeInfo above its
    default that day (8 of 8); at 3, 5 of 14 did (docs/DECISIONS.md, #365)."""
    assert stats.LOOP_RESTARTS == 4


def test_a_power_loop_needs_restarts_and_a_fast_nodeinfo() -> None:
    many = stats.LOOP_RESTARTS + 2
    assert stats.is_power_loop(many, 4.0)
    assert not stats.is_power_loop(many, 1.0), "NodeInfo at the default is not a loop"
    assert not stats.is_power_loop(many, None), "no NodeInfo at all is not a loop"
    assert not stats.is_power_loop(1, 4.0), "one restart is not a loop"


def test_one_restart_on_a_low_battery_is_not_a_power_loop() -> None:
    """The issue's 'x man': 10 % battery, up 21 days, NodeInfo 1.1x."""
    assert not stats.is_power_loop(1, 1.1)


def test_loops_lead_then_the_rows_the_heading_names() -> None:
    def row(
        node: int, notable: list[str], loop: bool, packets: int
    ) -> tuple[bool, list[str], int, int]:
        return (loop, notable, packets, node)

    rows = [
        row(1, [], False, 900),  # busy, nothing notable
        row(2, ["POSITION_APP"], False, 100),  # meets the heading
        row(3, [], True, 50),  # a counted power loop
        row(4, ["POSITION_APP", "TELEMETRY_APP"], False, 80),
    ]
    order = sorted(
        rows,
        key=lambda r: stats.broadcast_order(
            loop=r[0], notable=r[1], faster=r[1], packets=r[2], node=r[3]
        ),
    )
    assert [r[3] for r in order] == [3, 4, 2, 1]


def test_battery_is_not_judged_without_a_source() -> None:
    """The 5-35 % band had no firmware, datasheet or measurement behind it (#359)."""
    assert "brownout_risk" not in stats.NodeHealth.__annotations__
    source = (ROOT / "src" / "sonoran" / "api" / "routes" / "stats.py").read_text("utf-8")
    assert "BROWNOUT_LOW" not in source and "BROWNOUT_HIGH" not in source


def test_the_page_says_how_many_restarts_not_a_guess() -> None:
    app = (ROOT / "src" / "sonoran" / "web" / "static" / "app.js").read_text("utf-8")
    body = app[app.index("function drawBroadcastTable") :]
    body = body[: body.index("\nfunction ")]
    assert "maybe power cycling" not in body
    assert "restarts_24h" in body and "times in 24 h" in body
