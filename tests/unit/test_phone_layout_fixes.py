"""Four phone layouts seen on a real iPhone in the installed app (#322).

Each was measured at 390 px with live data before and after:

- RF, the waterfall's channel names: three fixed rows overlapped, and
  ran 53 px past the panel. The marks of a 250 kHz channel were 2 to
  6 px wide, so the two edges of "MediumFast slot 18" merged into one
  thick bar.
- RF, what is being swept: the bar was a 44 px button in an 18 px
  track, and eight frequency labels overlapped on 324 px.
- Firehose and traceroutes: "to" fell under "from" whenever the names
  did not fit, and the traceroutes table scrolled sideways on every row.
- Map: the controls were pushed right, leaving a ragged left edge.

After: no name overlaps or leaves the panel at 320, 390 or 1440 px, and
no "to" falls to its own line in 150 firehose and 100 traceroute rows.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
RF = (STATIC / "rf.js").read_text(encoding="utf-8")


def _phone_cards() -> str:
    """The 40rem block that lays the two tables out as cards."""
    start = CSS.index("@media (max-width: 40rem) {\n  [data-firehose-table] table,")
    return CSS[start : CSS.index("\n}\n", start)]


def test_channel_names_are_placed_from_the_drawn_width() -> None:
    assert "row-${index % 3}" not in RF, "the three fixed rows are back"
    assert "function fitChannels(page)" in RF
    assert "fitChannels(page);" in RF
    # Short names only when the full ones need more than three rows.
    assert "if (rows > 3) rows = place(true);" in RF


def test_a_channel_too_narrow_for_two_edges_is_one_line() -> None:
    assert "mark.classList.add('narrow')" in RF
    rule = re.search(r"\.rf-mark\.narrow \{([^}]*)\}", CSS)
    assert rule, "no rule for a narrow mark"
    assert "border-right: 0" in rule.group(1)


def test_short_channel_names_follow_the_mesh_spelling() -> None:
    """`MediumFast slot 18` is `MF 18`: the capitals of the preset word,
    then the slot number."""
    match = re.search(r"function shortChannel\(name\) \{(.*?)\n  \}", RF, flags=re.S)
    assert match
    body = match.group(1)
    assert "(?:[A-Z][a-z]+){2,}" in body
    assert r"\bslot\s+" in body


def test_the_sweeps_bar_keeps_the_tracks_height_on_a_touch_screen() -> None:
    block = CSS[CSS.index("The touch rule makes every button 44 px tall") :]
    block = block[: block.index("\n}\n")]
    assert ".rf-sweeps-bar { min-height: 0; padding-block: 0; }" in block
    # The finger still gets a large target, drawn as nothing.
    assert ".rf-sweeps-bar::after" in block


def test_the_sweeps_axis_drops_a_label_that_would_touch_another() -> None:
    assert "function fitAxis(axis)" in RF
    keep = re.search(r"const AXIS_KEEP = \[([^\]]*)\]", RF)
    ticks = re.search(r"const AXIS_TICKS = \[([^\]]*)\]", RF)
    assert keep and ticks
    kept = [item.strip() for item in keep.group(1).split(",")]
    # Both ends first, and nothing kept that is not a tick.
    assert kept[:2] == ["25e6", "6e9"]
    assert set(kept) <= {item.strip() for item in ticks.group(1).split(",")}


def test_both_tables_are_cards_on_a_phone() -> None:
    block = _phone_cards()
    for table in ("[data-firehose-table]", "[data-traceroute-table]"):
        assert f"{table} tr::after" in block, table


def test_to_cannot_fall_under_from() -> None:
    """A wrapping flex line wraps an item before it shrinks one. "To"
    starts from nothing and takes what is left, so the line always fits.
    """
    block = _phone_cards()
    assert ":is(td, th):nth-child(3) { flex: 1 1 0; }" in block
    # And a name's button is capped to its cell, so it can shrink.
    assert "td:nth-child(3) .linky { max-width: calc(100% - 1.4em); }" in block


def test_a_trace_card_hides_what_the_trace_page_shows() -> None:
    """The card rule for cells must not bring Hops and Signal back."""
    block = _phone_cards()
    assert "[data-traceroute-table] .low { display: none; }" in block
    assert "[data-traceroute-table] .stick { position: static;" in block


def test_the_dense_head_centres_its_controls_on_a_phone() -> None:
    match = re.search(
        r"@media \(max-width: 40rem\) \{\s*\.page-head\.dense \.controls \{([^}]*)\}", CSS
    )
    assert match
    assert "justify-content: center" in match.group(1)


def test_the_busy_legend_wraps_on_a_phone() -> None:
    """One scrolling line showed "LongSl" and a "1/11" pager at 390 px.
    Below 600 px the names wrap under the chart, which grows to hold them.
    """
    assert "const LEGEND_NARROW = 600;" in RF
    assert "type: 'plain', bottom: 0" in RF
    assert "target.style.height = `calc(15rem + ${height}px)`;" in RF
    # The grid's foot moves up by the legend, so the axis stays clear.
    assert "bottom: 28 + Number(target.dataset.legendHeight || 0)" in RF


def test_the_firehose_search_shows_its_whole_hint() -> None:
    """It read "Packet ty" on a phone and "Packet type, such as Posi" on
    a desktop."""
    search = '[data-page="firehose"] .page-head .controls > input[type="search"]'
    assert f"{search} {{ flex-basis: 100%; }}" in CSS
    assert f"{search} {{ min-width: 16.5rem; }}" in CSS


APP = (STATIC / "app.js").read_text(encoding="utf-8")


def test_a_chart_follows_its_own_box() -> None:
    """On an iPhone, in the installed app, the Statistics charts were drawn
    a third of their panel's width and stayed so: ECharts resizes only when
    told, and only the window's resize event told it. Each chart's box is
    now watched, and a real change of size redraws it.
    """
    assert "const chartBoxes = window.ResizeObserver" in APP
    assert "if (chartBoxes) chartBoxes.observe(target);" in APP
    # A hidden box (0 x 0) is left alone and drawn when it comes back.
    assert "if (!width || !height) continue;" in APP


def test_the_logo_goes_to_the_dashboard() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    link = re.search(r'<a class="brand-home" href="#dashboard"[^>]*>', html)
    assert link, "the logo is not a link to the dashboard"
    # A phone hides the wordmark, so the link carries its own name.
    assert 'aria-label="Sonoran, go to the dashboard"' in link.group(0)
    assert html.index(link.group(0)) < html.index("data-brand-mark")
    # Outside the menu, so it closes the menu itself.
    assert "const home = $('[data-brand-home]');" in APP


def test_the_meshs_own_channel_is_dashed_like_the_rest() -> None:
    """Orange tells it apart; dashed, with no fill, keeps the levels
    under it readable, as the white preset marks do."""
    rule = re.search(r"\.rf-mark\.custom \{([^}]*)\}", CSS)
    assert rule
    assert "2px dashed var(--accent)" in rule.group(1)
    assert "solid" not in rule.group(1)
    assert "background" not in rule.group(1)
