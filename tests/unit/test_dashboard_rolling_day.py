"""The dashboard's four headline tiles over a rolling last 24 hours (#292).

Will: "I think the 4 main stats on the dashboard should show the rolling
last 24 hours stats." He then confirmed that Nodes and Gateways stay
totals of every node ever seen, and only Packets and Uploads roll.

The counting itself is tested against a database in
`tests/integration/test_stats_windows.py`. These tests hold the page to
asking for the window, and the delta line to comparing like with like.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.api.cache import KeyedCache
from sonoran.api.routes import stats
from sonoran.config import Settings

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "src" / "sonoran" / "web" / "static" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start : APP.index("\n}\n", start) + 2]


def _node() -> str:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the delta line went unchecked. A skip looks like a pass."
    return node


def _change(cases: list[tuple[int | None, int | None]]) -> list[str | None]:
    script = (
        _function("changeOn")
        + f"console.log(JSON.stringify({json.dumps(cases)}"
        + ".map(([now, before]) => changeOn(now, before, 'the day before'))));"
    )
    done = subprocess.run(
        [_node(), "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert isinstance(result, list)
    return result


def test_the_dashboard_asks_for_the_rolling_day() -> None:
    dashboard = APP[APP.index("PAGES.dashboard = async") :]
    dashboard = dashboard[: dashboard.index("\n};\n")]
    assert "loadSummary(page, { hours: DASHBOARD_SUMMARY_HOURS })" in dashboard
    assert re.search(r"const DASHBOARD_SUMMARY_HOURS = 24;", APP)
    summary = _function("loadSummary")
    # The Statistics page passes its own range as `query` (#294); the
    # dashboard's `hours` becomes the same query.
    assert "hours ? `hours=${hours}` : null" in summary
    assert "`api/stats?${asked}`" in summary


def test_the_delta_compares_with_the_window_before() -> None:
    """Not with the UTC snapshot, which is a total held and not a day's traffic."""
    assert _change([(104, 100), (96, 100), (100, 100), (5, 0), (0, 0), (5, None), (None, 5)]) == [
        "▲ 4% on the day before",
        "▼ 4% on the day before",
        "same as the day before",
        "none on the day before",
        "same as the day before",
        # No comparison when retention has already deleted the day before.
        None,
        None,
    ]


def test_the_rolling_tiles_say_so_and_the_totals_say_so_too() -> None:
    """One row of tiles must not mix two meanings unlabelled (AGENTS.md 9.7 in spirit)."""
    summary = _function("loadSummary")
    assert "label('Packets', true)" in summary
    assert "label('Uploads', true)" in summary
    assert "label('Nodes', false)" in summary
    assert "label('Gateways', false)" in summary
    assert "'all time'" in summary


def test_a_window_out_of_range_is_refused() -> None:
    # Entered, so the lifespan sets up the session factory. The session
    # opens no connection until a query runs, and a refused value runs none.
    with TestClient(create_app(Settings(_env_file=None))) as client:
        for hours in (0, 721, -5):
            assert client.get(f"/api/stats?hours={hours}").status_code == 422, hours


def test_the_windowed_answers_are_held_in_a_bounded_cache() -> None:
    """A caller varying `hours` cannot grow the cache without limit."""
    assert isinstance(stats._window_cache, KeyedCache)
    assert 0 < stats._window_cache._capacity <= 32
