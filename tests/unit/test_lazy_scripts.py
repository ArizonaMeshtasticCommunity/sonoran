"""ECharts and the config checker load only where they are used (#277).

Every page downloaded the same bundle, and ECharts was 327 kB of it
gzipped, which Nodes, Chat, the map and the firehose never use. Measured
on the seeded dev database, cold, Chromium: the nodes page went from
912 kB to 451 kB, and its load event under a 400 kbit/s, 562 ms link
from 21.3 s to 10.3 s.

The libraries sit inside `<template data-lazy-scripts>` in index.html,
where a script never runs, and `loadScripts` in app.js copies them into
the page when a page needs them. The e2e journey "chart and checker
libraries load only where used" opens each chart page cold. These tests
hold the parts one browser run cannot see.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def _template(name: str) -> str:
    start = HTML.index(f'<template data-lazy-scripts="{name}">')
    return HTML[start : HTML.index("</template>", start)]


def _outside_templates() -> str:
    return re.sub(r"<template data-lazy-scripts=.*?</template>", "", HTML, flags=re.S)


def test_echarts_is_not_loaded_by_every_page() -> None:
    assert "echarts.min.js" in _template("charts")
    assert not re.search(r"<script[^>]*echarts\.min\.js", _outside_templates())


def test_the_config_checker_is_not_loaded_by_every_page() -> None:
    held = _template("config")
    for name in (
        "protobuf.min.js",
        "js-yaml.min.js",
        "meshtastic-proto.js",
        "meshtastic-serial-proto.js",
        "config-check.js",
    ):
        loaded = re.compile(rf"<script[^>]*src=\"[^\"]*/{re.escape(name)}")
        assert loaded.search(held), name
        assert not loaded.search(_outside_templates()), name


def test_the_integrity_hashes_travel_with_the_scripts() -> None:
    """`loadScript` copies them; the template must still carry them."""
    assert _template("config").count('integrity="sha384-') == 2
    assert "'integrity'" in APP


def test_every_page_that_calls_echarts_is_a_chart_page() -> None:
    """planner.js and rf.js call ECharts directly, not through `chart()`."""
    found = re.search(r"CHART_PAGES = new Set\(\[(.*?)\]\)", APP)
    assert found, "CHART_PAGES is gone"
    pages = set(re.findall(r"'(\w+)'", found.group(1)))
    assert {"dashboard", "graph", "node", "stats"} <= pages
    for script, page in (("planner.js", "planner"), ("rf.js", "rf")):
        assert "echarts.init" in (STATIC / script).read_text(encoding="utf-8")
        assert page in pages, f"{script} draws a chart but #{page} does not load ECharts"


def test_the_router_and_the_config_page_wait_for_their_scripts() -> None:
    assert "if (CHART_PAGES.has(name)) await chartsReady();" in APP
    assert "await loadScripts('config');" in APP
