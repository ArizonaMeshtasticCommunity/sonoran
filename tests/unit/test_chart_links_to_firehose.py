"""The dashboard's packet-types chart as a link into the firehose.

`docs/design/2026-09-26-ux-overhaul.md` §7.1, with the part of §5.1 it
depends on: "Firehose: must accept a type filter and a window in the URL,
for §7.1 to link into it. Show the window ("24 h") in the header."

§7.1's stated risk is the one worth reading twice:

> The chart is ECharts; its click events give a series index, not a
> portnum. The mapping has to be explicit or the wrong filter opens --
> silently, because a valid-looking filter with no rows looks like a
> quiet mesh.

Three separate ways that could have happened here, and each has a test:

* the index could be mapped by CATEGORY NAME, which two bands can share;
* three of the bands are not port numbers at all (#157), and filtering
  on the `0` underneath them returns all four groups;
* the chart counted every packet ever on every channel under a heading
  that said "24 h", so "the same 24 hours" was not a window it held.
"""

import inspect
import re

from fastapi.testclient import TestClient

from sonoran.api.app import STATIC_DIR, create_app
from sonoran.api.cache import KeyedCache
from sonoran.api.routes.stats import _portnums_cache, portnums
from sonoran.config import Settings


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.S)
    return "\n".join(
        line
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("//")
    )


def test_the_comment_stripper_works() -> None:
    """Positive control."""
    code = _code("app.js")
    assert "PAGES.firehose = async" in code, "the stripper removed real code"
    assert "looks like a quiet mesh" not in code, "comments are leaking through"


# --- §5.1: the filter is in the address ------------------------------


def test_the_firehose_filter_lives_in_the_fragment() -> None:
    """A filtered firehose has to be something you can be SENT.

    A filter held only in a variable, or only in the input box, cannot be
    linked to -- and §7.1 is a link. The fragment also survives a reload
    and never rides on a `Referer` (AGENTS.md 9.9.1), which is why
    `#chat/<channel>` and the planner's share link are built this way.
    """
    code = _code("app.js")
    assert "function firehoseHref(type, hours)" in code
    assert "if (known === 'firehose')" in code
    assert "query.get('type')" in code
    assert "query.get('hours')" in code


def test_an_address_with_no_filter_means_no_filter() -> None:
    """`#firehose` on its own must clear it, not keep the last one.

    Otherwise Back out of a filtered view lands on the same filtered
    view, and the reader cannot tell why the page will not let go.
    """
    code = _code("app.js")
    router = code[code.index("if (known === 'firehose') {") :]
    router = router[: router.index("\n  }")]
    assert "|| ''" in router, "an absent type must become empty, not stay put"


def test_a_window_has_to_be_a_positive_number_of_hours() -> None:
    """`new Date(NaN)` puts `since=Invalid Date` in the query and 422s.

    `Number('')` is 0 and `Number('abc')` is NaN, and neither of those is
    a smaller window -- both are no window at all.
    """
    code = _code("app.js")
    assert "Number.isFinite(hours) && hours > 0 ? String(hours) : ''" in code


def test_the_page_uses_the_wire_value_from_the_url_not_the_box() -> None:
    """The request must not depend on a label round-tripping to an enum.

    `portnumWire(portnumLabel(x))` is x for every type in the table
    today. The day a label is added without its reverse entry it becomes
    `<LABEL>_APP` and the endpoint answers 422 -- so the URL carries the
    wire value and the box is set from it, never read back for the
    request.
    """
    code = _code("app.js")
    page = code[code.index("PAGES.firehose = async") :]
    page = page[: page.index("\n};")]
    assert "const portnum = firehoseFilter.type;" in page
    assert "box.value = firehoseFilter.type ? portnumLabel(firehoseFilter.type) : ''" in page
    assert "portnumWire(" not in page, "the request is being built from the input box"


def test_the_controls_write_the_address_rather_than_redrawing() -> None:
    """Two sources of truth for one filter is one too many.

    A control that re-rendered directly would move the page without
    moving the URL, and the address bar would then describe the view the
    reader had before they touched anything.
    """
    code = _code("app.js")
    handler = code[code.index("const goFirehose = () => {") :]
    handler = handler[: handler.index("\n  };")]
    assert "firehoseHref(portnumWire(typed), hours)" in handler
    assert "location.hash = href.slice(1)" in handler
    # Assigning a hash that is already set fires no `hashchange`, so
    # pressing Filter twice would do nothing the second time.
    assert "if (location.hash === href) render('firehose');" in handler


def test_the_window_is_shown_and_the_unbounded_case_is_named() -> None:
    """§5.1 asks for the window in the header.

    "All time" matters as much as "Last 24 h": a page showing 150 rows
    out of a database and a page showing 150 rows out of one day look
    identical and answer different questions.
    """
    html = TestClient(create_app(Settings(_env_file=None))).get("/").text
    section = html[html.index('data-page="firehose"') :]
    section = section[: section.index("</section>")]
    assert "data-firehose-window" in section
    assert "data-firehose-hours" in section
    assert '<option value="">All time</option>' in section, "the default must stay all time"
    code = _code("app.js")
    assert "function firehoseWindowWord(hours)" in code
    assert "return 'All time';" in code
    # 24 hours is "24 h" in both places, or the two pages name the same
    # window differently.
    assert "n % 24 === 0 && n >= 48" in code


def test_an_empty_filtered_table_names_the_filter_it_applied() -> None:
    """§7.1's risk, in the one place a reader meets it.

    The filter has three parts and two are invisible: the preset comes
    from the menu and the window from the URL. "No packets match the
    filter." left no way to tell a quiet mesh from a packet type that
    never runs on the preset being looked at.
    """
    code = _code("app.js")
    page = code[code.index("PAGES.firehose = async") :]
    page = page[: page.index("\n};")]
    assert "The mesh may be quiet, or this may not be traffic that runs here." in page
    assert "], rows, nothing, { rowHref: packetHref }));" in page


# --- §7.1: the chart ------------------------------------------------


def test_the_band_mapping_is_an_array_indexed_by_data_index() -> None:
    """Not a lookup by category name.

    Two bands can carry the same label -- a port the protocol has
    renamed, or two states folded to one word -- and a name lookup would
    send both to one filter with nothing to say which was clicked.
    `params.dataIndex` indexes the very array the bars were built from.
    """
    code = _code("app.js")
    chart = code[code.index("const bands = top.map((row) => {") :]
    chart = chart[: chart.index("\n};")]
    assert "bands[params.dataIndex]" in chart
    assert "bands[item.dataIndex]" in chart, "the tooltip must read the same mapping"
    assert "wire.get(item.name)" not in chart, "back to a lookup by category name"


def test_the_three_bands_that_are_not_port_numbers_are_not_links() -> None:
    """`UNREADABLE_*` is what `traffic_label` calls a portnum of 0 (#157).

    `labels.js` already records that the API answers 422 for them and
    keeps them out of the filter's vocabulary. Filtering on the `0`
    underneath instead would return all four groups: the wrong filter,
    arriving quietly.

    They stay on the chart, because they are most of the traffic on this
    mesh. They are simply not doors.
    """
    code = _code("app.js")
    chart = code[code.index("const bands = top.map((row) => {") :]
    chart = chart[: chart.index("\n};")]
    assert "filterable: !/^UNREADABLE_/.test(wire)" in chart
    assert "if (!band || !band.filterable) return;" in chart
    assert "cursor: band.filterable ? 'pointer' : 'default'" in chart
    # And `labels.js` still keeps them out of the reverse table, which is
    # the other half of the same rule.
    labels = _code("labels.js")
    wire_table = labels[labels.index("const WIRE_BY_LABEL") :]
    wire_table = wire_table[: wire_table.index("function portnumWire")]
    assert "TRAFFIC_LABELS" not in wire_table


def test_one_click_stays_one_click_across_re_renders() -> None:
    """`chart()` reuses the instance and `setOption` keeps its handlers.

    Measured with the `off` taken out: four returns to the dashboard left
    four click listeners on one instance, and the count has no ceiling.
    """
    code = _code("app.js")
    assert "instance.off('click');" in code
    chart = code[code.index("if (instance) {") :]
    chart = chart[: chart.index("\n  }")]
    assert chart.index("instance.off('click')") < chart.index("instance.on('click'")


def test_the_chart_covers_the_window_its_heading_claims() -> None:
    """ "over the same 24 hours" is only possible if the chart holds 24 hours.

    It did not. The panel says "Packet types (24 h)" and the request had
    no window on it at all, so the figures were every packet ever stored
    on every channel. Once a band became a link into a 24-hour firehose
    on one preset, a band counting 500 all-time packets would have opened
    a table with none in it.
    """
    code = _code("app.js")
    assert "const PORTNUM_CHART_HOURS = 24;" in code
    assert "api/stats/portnums?hours=${PORTNUM_CHART_HOURS}" in code
    assert "firehoseHref(band.wire, PORTNUM_CHART_HOURS)" in code
    # The heading and the constant have to agree, so the heading is read.
    html = TestClient(create_app(Settings(_env_file=None))).get("/").text
    assert "<h3>Packet types (24 h)</h3>" in html


def test_the_chart_is_scoped_to_the_preset_the_reader_chose() -> None:
    """AGENTS.md 9.7, and the other half of "the same" packets.

    The firehose filters to the preset in the menu. A chart counting
    every preset would name a number the firehose does not hold, and on a
    preset that never sends a type the link would open empty.
    """
    code = _code("app.js")
    assert "presetChannel() ? `&channel=${encodeURIComponent(presetChannel())}` : ''" in code


def test_an_empty_chart_says_which_filter_emptied_it() -> None:
    """Two filters now, so "the window" is not enough to act on."""
    code = _code("app.js")
    assert "No packet was stored in the last ${PORTNUM_CHART_HOURS} h" in code


# --- the endpoint ----------------------------------------------------


def test_the_portnums_hold_is_keyed_by_its_parameters() -> None:
    """A one-value hold would answer every caller with the first one's window.

    The dashboard asks for 24 hours on one preset and the firehose's
    suggestion list asks for everything. With a `TimedCache` whichever
    arrived first would have answered both -- and a stale answer from a
    cache does not look like a cache, it looks like the endpoint
    returning somebody else's data.
    """
    assert isinstance(_portnums_cache, KeyedCache)


def test_the_portnums_filters_default_to_off() -> None:
    """The firehose's suggestion list still wants every type ever seen.

    "The types this mesh has actually sent, not every type the protocol
    defines" is the point of that list, and narrowing it to 24 hours
    would make the suggestions miss types that are real.
    """
    params = inspect.signature(portnums).parameters
    assert params["channel"].default is None
    # `hours` is a `Query(...)`, so the default is on the marker.
    assert params["hours"].default.default is None
    code = _code("app.js")
    fill = code[code.index("async function fillFirehoseTypes(page)") :]
    fill = fill[: fill.index("\n}")]
    assert "get('api/stats/portnums')" in fill, "the suggestion list gained a window"
