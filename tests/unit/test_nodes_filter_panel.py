"""More filters, and a hardware picker that fits (§6.2).

Two of Will's items:

* "More filters: everything sortable becomes filterable."
* "Hardware filter: **57 models**, 17 of them with <=2 nodes. Top 10 plus
  a search box plus 'show more'."

The first is a claim about two files at once -- the sorts live in
`api/routes/nodes.py` and the filters in `app.js` -- so it is checked as
a contract between them rather than as a list somebody keeps up to date.
That found the one column filterable in a single direction: `last_heard`
had "heard since" and nothing for "not heard since", which is what "which
routers have gone quiet" actually is.

The second is mostly `facetSlice`, whose behaviour cases run under node in
`js/nodes_facet_slice_cases.mjs` and are mutated here.
"""

import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
MODULE = STATIC / "app.js"
CSS = STATIC / "app.css"
API = ROOT / "src" / "sonoran" / "api" / "routes" / "nodes.py"
CASES = ROOT / "tests" / "unit" / "js" / "nodes_facet_slice_cases.mjs"

# Every sortable column, and what narrows it.
#
# The keys are the names in `SORTS`; the values are how the panel or the
# controls above it filter that same column. Two columns are narrowed by
# the search box rather than by the panel, and that is deliberate: `q`
# searches the long name, the short name and the node ID, so a second copy
# of it inside the panel would be two controls doing one job -- which this
# page has already been corrected for once.
SORT_FILTERS = {
    "last_heard": ("active_hours", "quiet_hours"),
    "first_seen": ("first_seen_hours",),
    "name": ("q",),
    "node_id": ("q",),
    "hw": ("hw",),
    "role": ("role",),
    "channel": ("channel",),
    "position": ("position",),
}


@contextmanager
def _temporarily(path: Path, text: str) -> Iterator[None]:
    original = path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _node_bin() -> str:
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so the facet slice went unchecked. A skip here "
        "looks exactly like a pass."
    )
    return node


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node_bin(), str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
    )


def _app() -> str:
    text = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def _css() -> str:
    """`app.css` without its comments.

    A rule here is explained in a comment that quotes the colour it
    replaced, so reading the raw file finds `#fff` inside the note saying
    `#fff` is gone -- the trap this repository keeps meeting from both
    directions.
    """
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)


def _sorts() -> set[str]:
    """The sortable columns, read out of the API's own whitelist."""
    api = API.read_text(encoding="utf-8")
    block = api[api.index("SORTS: dict[str, Any] = {") :]
    block = block[: block.index("\n}")]
    found = set(re.findall(r'^\s*"(\w+)":', block, re.M))
    assert len(found) >= 8, f"the sort whitelist did not parse: {found}"
    return found


def test_the_comment_stripper_works() -> None:
    app = _app()
    assert "function facetSlice" in app, "the stripper removed real code"
    assert "57 hardware models" not in app, "comment text is leaking through"


# --- everything sortable is filterable -------------------------------


def test_the_table_of_sorts_is_the_api_s_own() -> None:
    """The control: this case is what makes the next one mean anything.

    A hand-written list of sorts would drift from `SORTS` and then agree
    with itself forever.
    """
    assert _sorts() == set(SORT_FILTERS), (
        f"the API sorts on {_sorts()} and this file knows about {set(SORT_FILTERS)}"
    )


def test_every_sortable_column_can_be_narrowed() -> None:
    """Will: everything sortable becomes filterable.

    A reader who sorts a column to find something is one step from
    wanting only that something. Sorting `hw` to group the Heltecs and
    then having to scroll past 300 rows of them is the case.
    """
    app = _app()
    api = API.read_text(encoding="utf-8")
    for column, keys in SORT_FILTERS.items():
        for key in keys:
            assert f"'{key}'" in app, f"{column} is sortable but nothing in the browser sends {key}"
            assert re.search(rf"\b{key}\b", api), (
                f"the browser sends {key} for {column} and the API does not read it"
            )


def test_the_panel_offers_every_filter_the_browser_sends() -> None:
    """A parameter with no control is a filter only a URL can reach."""
    app = _app()
    panel = app[app.index("const NODE_FILTERS = [") : app.index("const nodeFilters = new Map()")]
    for key in ("hw", "role", "channel", "position", "active_hours", "first_seen_hours"):
        assert f"key: '{key}'" in panel, f"{key} is not a control in the panel"
    assert "key: 'quiet_hours'" in panel, (
        "nothing in the panel asks for nodes that have gone quiet, which was the "
        "one sortable column filterable in a single direction"
    )


def test_the_quiet_window_is_measured_by_the_server() -> None:
    """`before` would put the clock in the browser's hands.

    A device whose clock is wrong would then filter on the wrong hour,
    with nothing on the page saying so -- and a band built from
    `active_hours` and a browser-named moment is measured against two
    clocks.
    """
    api = API.read_text(encoding="utf-8")
    assert "quiet_hours" in api
    quiet = api[api.index("if quiet_hours is not None:") :]
    quiet = quiet[: quiet.index("return statement")]
    assert "datetime.now(UTC) - timedelta(hours=quiet_hours)" in quiet, (
        "the quiet window is not measured from the server's clock"
    )
    app = _app()
    ranges = app[app.index("const NODE_RANGES = [") : app.index("const nodeFilters = new Map()")]
    assert "before" not in ranges, "the browser is naming the moment itself"


def test_the_facets_endpoint_reads_the_same_filters_as_the_list() -> None:
    """Otherwise every count in the panel describes a larger set.

    FastAPI drops an undeclared query parameter without a word, and
    `nodeFacetQuery` is built from `nodeQuery`, so a filter added to one
    handler and not the other fails silently and in the direction that
    looks fine.
    """
    api = API.read_text(encoding="utf-8")
    listing = api[api.index("async def list_nodes(") : api.index("async def node_facets(")]
    facets = api[api.index("async def node_facets(") :]
    facets = facets[: facets.index('@router.get("/{node_id}"')]
    for key in ("q", "hw", "role", "gateway", "active_hours", "first_seen_hours", "quiet_hours"):
        assert f"{key}:" in listing, f"the list does not take {key}"
        assert f"{key}:" in facets, f"the facets do not take {key}, so their counts would be wrong"


# --- the hardware picker ---------------------------------------------


def test_the_hardware_filter_is_a_top_ten_with_a_search_box() -> None:
    """Will's numbers: 57 models, 17 of them with two nodes or fewer."""
    app = _app()
    block = app[app.index("key: 'hw',") :]
    block = block[: block.index("key: 'channel',")]
    assert "top: 10," in block, "the hardware facet is not sliced"
    assert "search:" in block, "the hardware facet has no search box"


def test_only_a_long_facet_gets_a_box_and_a_button() -> None:
    """A box to search four models says there is more to find.

    The seeded database has four hardware models, so this is the shape
    most development sees -- and a control that opens nothing is worse
    than no control.
    """
    app = _app()
    body = app[app.index("function facetGroup(") :]
    body = body[: body.index("\n}")]
    assert "labelled.length > filter.top" in body, "the box is offered whatever the length"
    assert "long && filter.search" in body, "a facet with no search text still gets a box"


def test_the_search_box_has_a_name_of_its_own() -> None:
    """A placeholder is not a label: it is gone as soon as anything is
    typed, and some screen readers never read it."""
    app = _app()
    body = app[app.index("function facetGroup(") :]
    body = body[: body.index("\n}")]
    assert "'aria-label': filter.search" in body, "the facet search box is unnamed"
    assert "placeholder: filter.search" in body


def test_typing_does_not_rebuild_the_panel_underneath_the_box() -> None:
    """Rebuilding the grid takes the box the reader is typing into.

    The caret and the focus go with it, so the box accepts one character
    and then stops being the focused element.
    """
    app = _app()
    body = app[app.index("function facetGroup(") :]
    body = body[: body.index("\n}")]
    typing = body[body.index("box.addEventListener('input'") :]
    typing = typing[: typing.index("});")]
    assert "paint()" in typing, "typing does not repaint the values"
    assert "drawNodeFilters" not in typing, (
        "typing rebuilds the whole panel, which destroys the box being typed into"
    )


def test_what_was_typed_survives_choosing_a_value() -> None:
    """Choosing a value DOES rebuild the panel, by design.

    So the text cannot live in the input alone, or it vanishes the moment
    the reader clicks the model they had just searched for.
    """
    app = _app()
    assert "const nodeFacetSearch = new Map()" in app
    body = app[app.index("function facetGroup(") :]
    body = body[: body.index("\n}")]
    assert "value: nodeFacetSearch.get(filter.key)" in body, (
        "the box is rebuilt empty, so the search is lost on every click"
    )


def test_the_counts_beside_each_value_are_not_invented() -> None:
    """A facet count of zero never comes back from the server.

    An ABSENT count is not a zero either, and this is the file where
    `Number(null) === 0` has cost five bugs: `optionButton` draws no badge
    for null rather than a badge reading 0.
    """
    app = _app()
    body = app[app.index("function optionButton(") :]
    body = body[: body.index("\n}")]
    assert "total == null ? null" in body, "an absent count would be drawn as a number"


def test_the_count_on_an_option_is_not_the_filters_badge() -> None:
    """Two rules were called `.filter-count` and the later one won.

    The badge on the Filters button and the count beside every value in
    the panel share a class name. Unscoped, the badge's rule turned every
    count in the panel into an orange pill -- and because
    `.filter-option.chosen .filter-count` is more specific still, the
    chosen option's count came out `--accent` on `--accent`: 1:1, and
    invisible. Measured in Chromium on 2026-09-26, with ten of these
    counts on the screen at once.
    """
    css = _css()
    assert ".toggle .filter-count {" in css, "the badge rule is unscoped again"
    badge = css[css.index(".toggle .filter-count {") :]
    badge = badge[: badge.index("}")]
    assert "background: var(--accent)" in badge, "this case is not reading the badge rule"
    quiet = css[css.index(".filter-count { font-size") :]
    quiet = quiet[: quiet.index("}")]
    assert "background" not in quiet, "the count inside the panel has a background of its own"


def test_the_counts_are_readable_in_both_themes() -> None:
    """Named as token pairs, so `test_palette.py` measures them.

    Both pairs here are already held to 4.5:1 in both themes by that
    file -- `--text` on `--panel-2`, and `--on-accent` on `--accent`. The
    pair this replaces, `--accent` on `--panel-2`, is the 4.38:1 light
    reading that #120 removed from the pressed toggle.
    """
    css = _css()
    chosen = css[css.index(".filter-option.chosen .filter-count") :]
    chosen = chosen[: chosen.index("}")]
    assert "var(--text)" in chosen, "the chosen count is not on a measured pair"
    assert "var(--accent)" not in chosen, (
        "--accent on --panel-2 is 4.38:1 in the light theme, the pair #120 removed"
    )
    badge = css[css.index(".toggle .filter-count {") :]
    badge = badge[: badge.index("}")]
    assert "color: var(--on-accent)" in badge, (
        "white on the dark theme's accent is 2.90:1; --on-accent is the tested pair"
    )
    assert "#fff" not in badge


def test_the_box_cannot_widen_the_panel() -> None:
    """The fieldset is a grid column.

    A `size` in characters sets an intrinsic width the grid has to
    honour, and at 320 px that is how a filter panel pushes the document
    sideways -- which an e2e journey fails on.
    """
    css = CSS.read_text(encoding="utf-8")
    box = css[css.index(".filter-search {") :]
    box = box[: box.index("}")]
    assert "width: 100%" in box
    assert "box-sizing: border-box" in box, "padding would take it past its column"
    assert "min-width: 0" in box, "a text input has an intrinsic minimum width"
    app = _app()
    group = app[app.index("function facetGroup(") :]
    group = group[: group.index("\n}")]
    assert "size:" not in group, "a size in characters sets an intrinsic width"


# --- the behaviour cases, and proof that they can fail ---------------


def test_the_facet_slice_cases_pass() -> None:
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_dropping_the_chosen_value_would_be_caught() -> None:
    """The mutation that misleads.

    Without it the fieldset shows "Any" as the chosen option while the
    filter is in force, and there is no way to take it off from there.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "  return { shown: shown.concat(keep), more: held.length - keep.length,"
        " matched: matches.length };",
        "  return { shown, more: held.length, matched: matches.length };",
    )
    assert broken != source, "the slice's return has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when a chosen value is sliced away"
    assert "chosen value outside the top slice" in done.stderr, (
        f"the failure does not name the cause: {done.stderr}"
    )


def test_a_search_that_matched_nothing_would_be_caught() -> None:
    """`matched` is the only way to tell "no match" from "nothing left"."""
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace("  const matches = wanted", "  const matches = false")
    assert broken != source, "the query filter has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when the search filters nothing"


def test_searching_only_the_wire_value_would_be_caught() -> None:
    """A role reads "Client, base station" and travels as CLIENT_BASE.

    This is the graph search bug (#223) in another costume: two ways of
    asking the same question, one of which the reader cannot see.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "      String(entry.words == null ? entry.value : entry.words).toLowerCase()"
        ".includes(wanted)\n      || String(entry.value).toLowerCase().includes(wanted))",
        "      String(entry.value).toLowerCase().includes(wanted))",
    )
    assert broken != source, "the match has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when only the wire value is searched"
    assert "what the reader can see" in done.stderr, (
        f"the failure does not name the cause: {done.stderr}"
    )
