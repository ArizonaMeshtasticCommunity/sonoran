"""The Statistics page's date range (#294).

Will: "the stats page needs the ability to set the date range with some
common quick click buttons at the top right of the page and all the
stats, widgets, etc should adjust to them. Default is last 30 days
rolling." He also asked for a from/to range.

Three things are held here. The API turns a range into one window, in
one place (`sonoran/api/window.py`). The page's range survives the
address in both directions. And no quick range offers more than the
packets the database keeps.
"""

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sonoran.api import window as window_module
from sonoran.api.app import create_app
from sonoran.api.cache import KeyedCache
from sonoran.api.routes import leaderboards, stats
from sonoran.api.window import MAX_HOURS, resolve
from sonoran.config import Settings

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(_env_file=None)


# --- the window, in the API ------------------------------------------


def test_a_rolling_window_ends_now() -> None:
    window = resolve(_settings(), 168, None, None, 24, now=NOW)
    assert window is not None
    assert window.end == NOW
    assert window.start == NOW - timedelta(hours=168)
    assert window.key == "h168"


def test_no_window_is_all_time_where_that_was_the_answer() -> None:
    assert resolve(_settings(), None, None, None, None, now=NOW) is None


def test_a_date_is_a_local_midnight_not_a_utc_one() -> None:
    """Arizona is UTC-7 all year, so its midnight is 07:00 UTC.

    Read as UTC, every day boundary on the page would move to 5 pm.
    """
    window = resolve(_settings(), None, datetime(2026, 9, 1), datetime(2026, 9, 11), None, now=NOW)
    assert window is not None
    assert window.start == datetime(2026, 9, 1, 7, 0, tzinfo=UTC)
    assert window.end == datetime(2026, 9, 11, 7, 0, tzinfo=UTC)


def test_a_window_never_ends_in_the_future() -> None:
    """Only rows with a wrong clock live there (AGENTS.md 9.4)."""
    window = resolve(
        _settings(), None, datetime(2026, 9, 20), datetime(2026, 10, 30), None, now=NOW
    )
    assert window is not None
    assert window.end == NOW


@pytest.mark.parametrize(
    ("hours", "since", "until", "why"),
    [
        (24, datetime(2026, 9, 1), None, "both"),
        (None, None, datetime(2026, 9, 1), "start"),
        (None, datetime(2026, 9, 10), datetime(2026, 9, 5), "before it ends"),
        (None, datetime(2026, 10, 5), None, "before now"),
        (None, datetime(2026, 8, 1), datetime(2026, 9, 20), "at most"),
    ],
)
def test_a_window_that_cannot_be_answered_is_refused(
    hours: int | None, since: datetime | None, until: datetime | None, why: str
) -> None:
    with pytest.raises(HTTPException) as caught:
        resolve(_settings(), hours, since, until, None, now=NOW)
    assert caught.value.status_code == 422
    assert why in str(caught.value.detail)


def test_the_largest_window_is_the_packet_retention() -> None:
    """A longer window over `packet` reads ground already deleted."""
    assert MAX_HOURS == _settings().retention_days_packet * 24


def test_every_statistics_endpoint_refuses_a_window_out_of_range() -> None:
    paths = ["", "/top", "/activity", "/broadcast", "/hardware", "/daily", "/leaderboards"]
    with TestClient(create_app(_settings())) as client:
        for path in paths:
            for query in ("hours=0", "hours=721", "since=2026-08-01&until=2026-09-20"):
                response = client.get(f"/api/stats{path}?{query}")
                assert response.status_code == 422, (path, query, response.status_code)


def test_the_windowed_answers_are_held_in_bounded_caches() -> None:
    """At 30 days every load read the whole of `packet` three times over."""
    for cache in (
        stats._window_cache,
        stats._hardware_window_cache,
        stats._top_cache,
        stats._activity_cache,
        stats._broadcast_cache,
        stats._daily_cache,
        leaderboards._link_caches,
    ):
        assert isinstance(cache, KeyedCache)
        assert 0 < cache._capacity <= 32


def test_the_top_senders_ignore_future_rows() -> None:
    """`/top` had a lower bound only (#294's minor finding)."""
    source = Path(stats.__file__).read_text(encoding="utf-8")
    body = source[source.index("async def _read_top(") :]
    body = body[: body.index("\n\n\n")]
    assert "Packet.first_seen_at < now" in body


def test_the_window_module_is_the_only_reader_of_since() -> None:
    """One place turns the query into a window, so widgets cannot disagree."""
    source = Path(stats.__file__).read_text(encoding="utf-8")
    assert "since: datetime | None = Query" not in source
    assert "window_query" in source and "optional_window" in source
    assert window_module.MAX_HOURS == MAX_HOURS


# --- the range, on the page ------------------------------------------


def _node() -> str:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the range went unchecked. A skip looks like a pass."
    return node


def _range_code() -> str:
    start = APP.index("const STATS_RANGES = ")
    end = APP.index("/** Show the range in force on the control. */")
    name = APP.index("function windowName(")
    name_end = APP.index("\n}\n", name) + 2
    return APP[name:name_end] + APP[start:end]


def _run(expression: str) -> object:
    script = f"{_range_code()}\nconsole.log(JSON.stringify({expression}));"
    done = subprocess.run(
        [_node(), "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_address_carries_the_range_both_ways() -> None:
    assert _run(
        "['#stats', '#stats?range=7d', '#stats?range=24h', '#stats?range=90d',"
        " '#stats?from=2026-09-01&to=2026-09-10', '#stats?from=2026-09-01',"
        " '#stats?from=2026-02-30', '#stats?from=2026-09-10&to=2026-09-01']"
        ".map((hash) => statsRangeFromAddress(hash))"
    ) == [
        {"key": "30d", "from": None, "to": None},
        {"key": "7d", "from": None, "to": None},
        {"key": "24h", "from": None, "to": None},
        # An unknown range is the default, never an error.
        {"key": "30d", "from": None, "to": None},
        {"key": "custom", "from": "2026-09-01", "to": "2026-09-10"},
        {"key": "custom", "from": "2026-09-01", "to": None},
        # Not a real date, so no range at all.
        {"key": "30d", "from": None, "to": None},
        # An end before the start is dropped, not believed.
        {"key": "custom", "from": "2026-09-10", "to": None},
    ]


def test_the_range_is_asked_for_in_the_apis_words() -> None:
    assert _run(
        "[{key: '30d'}, {key: '24h'}, {key: 'custom', from: '2026-09-01', to: '2026-09-10'},"
        " {key: 'custom', from: '2026-09-01', to: null}].map((r) => statsRangeQuery(r))"
    ) == [
        "hours=720",
        "hours=24",
        # The last day shown is the 10th, so the window ends at the 11th.
        "since=2026-09-01&until=2026-09-11",
        "since=2026-09-01",
    ]


def test_a_range_too_long_to_answer_is_refused_in_words() -> None:
    refusals = _run(
        "[['2026-08-01', '2026-09-20'], ['2026-09-10', '2026-09-01'], [null, null],"
        " ['2026-09-01', '2026-09-30'], ['2026-09-01', '2026-09-20']]"
        ".map(([from, to]) => statsRangeRefusal(from, to))"
    )
    assert isinstance(refusals, list)
    assert "at most 30 days" in refusals[0]
    assert "before the start" in refusals[1]
    assert "start date" in refusals[2]
    assert refusals[3] is None, "30 days inclusive is the largest range and is allowed"
    assert refusals[4] is None


def test_the_quick_ranges_are_the_ones_will_named_and_30_days_is_the_default() -> None:
    buttons = re.findall(r'data-stats-quick="(\w+)"', HTML)
    assert buttons == ["24h", "7d", "30d"]
    assert re.search(r'data-stats-quick="30d" aria-pressed="true"', HTML)
    assert "const STATS_DEFAULT_RANGE = '30d';" in APP


def test_no_quick_range_offers_more_than_the_packets_kept() -> None:
    hours = _run("Object.values(STATS_RANGES)")
    assert isinstance(hours, list)
    assert max(hours) == _settings().retention_days_packet * 24
    assert _run("STATS_MAX_DAYS") == _settings().retention_days_packet


def test_the_range_is_written_without_a_history_entry() -> None:
    body = APP[APP.index("function statsWriteRange(") :]
    body = body[: body.index("\n}\n")]
    assert "history.replaceState" in body
    assert "location.hash =" not in body


def test_every_widget_on_the_page_names_its_range() -> None:
    page = HTML[HTML.index('data-page="stats"') :]
    page = page[: page.index("</section>")]
    assert page.count("data-range-chip") == 5, "a widget does not say which range it counts"
    assert "Busiest senders (24 h)" not in page, "a fixed window is still written in the heading"
