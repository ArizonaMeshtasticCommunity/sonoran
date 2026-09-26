"""The gaps page, after Will read it (2026-09-26).

Six changes, each from a specific complaint, and each held here because
the page is the kind of thing that drifts back:

1. the headline sentence went ("I don't like the ... text. I don't think
   this is needed");
2. the signal tiles lost their "cannot tell" number ("If we cannot tell,
   then let's just leave it off the report");
3. the tiles sit in one row on a desktop;
4. there is space between the tiles and what follows ("you can see no
   padding on desktop");
5. the order is widgets, then map, then table;
6. the long explanatory prose is gone from the page and kept as comments
   ("keep it as internal documentation for future agents but not seen to
   the user").

The reasoning removed from the page was not deleted. It is in comments in
`gaps.js`, `siting.js`, `gaps/signals.py` and `gaps/siting.py`, and the
caveats are still served by the API. These cases check that the prose is
off the PAGE, not that it stopped existing.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"


def _gaps_section() -> str:
    """The gaps page's markup, with HTML comments stripped.

    Comments are removed because this change deliberately MOVED prose
    into comments. Searching the raw section would find the explanation
    of a removal and read it as the thing still being there -- the
    exact false pass this repository keeps re-learning.
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    start = html.index('data-page="gaps"')
    section = html[start : html.index("</section>", start)]
    return re.sub(r"<!--.*?-->", "", section, flags=re.S)


def test_the_comment_stripper_works() -> None:
    """Positive control: every case below depends on it."""
    section = _gaps_section()
    assert "data-gaps-counts" in section, "the stripper removed real markup"
    assert "Will asked for it to go" not in section, "comment text is leaking through"


# --- 1. the headline sentence ---------------------------------------


def test_the_headline_sentence_is_gone() -> None:
    """Both the element and the code that wrote it."""
    assert "data-gaps-lead" not in _gaps_section()
    code = (STATIC / "gaps.js").read_text(encoding="utf-8")
    body = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    assert "leadSentence" not in body, "the sentence is still being built"


# --- 2. no "cannot tell" on the tiles -------------------------------


def test_the_tiles_do_not_show_what_we_cannot_tell() -> None:
    code = re.sub(r"/\*.*?\*/", "", (STATIC / "gaps.js").read_text(encoding="utf-8"), flags=re.S)
    tile = code[code.index("function signalTile") :]
    tile = tile[: tile.index("\n  function ")]
    assert "cannot tell" not in tile, "the tile still prints a cannot-tell count"
    assert "'unknown'" not in tile, "the tile still builds an unknown half"
    # The half that remains has to still be there: a tile with no number
    # would satisfy the line above.
    assert "'bad'" in tile, "the tile no longer shows the count it found"


def test_the_unknown_nodes_are_still_reachable() -> None:
    """Not shouted is not hidden.

    Dropping the tile number is only acceptable because the table keeps
    its own view of those nodes. If that went too, the page would have
    stopped reporting them at all, which is not what was asked.
    """
    section = _gaps_section()
    assert "data-gaps-view" in section, "the table's view switch is gone"


# --- 3, 4. one row, and space below ---------------------------------


def test_the_tiles_are_one_row_on_a_desktop() -> None:
    """Six tiles at the shared 17rem minimum wrapped inside the 100rem cap."""
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "gaps.css").read_text(encoding="utf-8"), flags=re.S)
    rule = css[css.index("[data-gaps-counts].grid") :]
    rule = rule[: rule.index("}")]
    assert "grid-template-columns" in rule
    found = re.search(r"minmax\(min\((\d+(?:\.\d+)?)rem", rule)
    assert found, f"no minimum width in {rule!r}"
    minimum = float(found.group(1))
    # Six tiles plus five 1rem gaps must fit the 100rem cap.
    assert 6 * minimum + 5 <= 100, f"six tiles at {minimum}rem will not fit one row"


def test_the_page_is_a_column_with_a_gap() -> None:
    """`.page.active` is `display: block` and `.panel` has no margin."""
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "gaps.css").read_text(encoding="utf-8"), flags=re.S)
    rule = css[css.index('.page.active[data-page="gaps"] {') :]
    rule = rule[: rule.index("}")]
    assert "flex" in rule and "gap:" in rule, rule


def test_the_column_children_are_told_to_stretch() -> None:
    """The trap this repository has already paid for once.

    `.grid` carries `margin-inline: auto`, and an auto inline margin on a
    flex item makes it shrink-to-fit rather than stretch. Without an
    explicit width the tiles would sit in a narrower column than the
    panels under them, which is the two-left-edges bug of #193.1.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "gaps.css").read_text(encoding="utf-8"), flags=re.S)
    rule = css[css.index('.page.active[data-page="gaps"] > * {') :]
    rule = rule[: rule.index("}")]
    assert "width: 100%" in rule, rule


# --- 5. widgets, then map, then table -------------------------------


def test_the_order_is_widgets_then_map_then_table() -> None:
    section = _gaps_section()
    tiles = section.index("data-gaps-counts")
    map_ = section.index('id="gaps-map"')
    table = section.index("data-gaps-table>")
    assert tiles < map_ < table, (
        f"order is tiles={tiles}, map={map_}, table={table}; "
        "it should read how many, then where, then the detail"
    )


# --- 6. the prose is off the page -----------------------------------


def test_the_explanatory_prose_is_no_longer_on_the_page() -> None:
    """Each phrase Will quoted, checked as absent from the rendered page."""
    section = _gaps_section()
    for phrase in (
        "No line is drawn between nodes",
        "left off the map",
        "How this is measured",
        "What a siting suggestion cannot know",
        "This half is predicted, not measured",
        "within eight kilometres",
        "of a ceiling of",
    ):
        assert phrase not in section, f"still on the page: {phrase!r}"


def test_the_prose_written_by_javascript_is_gone_too() -> None:
    """Removing the elements is not enough if the writers remain.

    A writer whose target is missing fails silently, so this would look
    fine while leaving dead code that the next person has to work out.
    """
    for name in ("gaps.js", "siting.js"):
        code = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
        for attribute in (
            "data-gaps-lead",
            "data-gaps-window",
            "data-gaps-limits",
            "data-gaps-map-note",
            "data-siting-lead",
            "data-siting-note",
            "data-siting-limits",
        ):
            assert attribute not in code, f"{name} still writes to {attribute}"


def test_the_siting_panel_still_says_it_is_a_prediction() -> None:
    """One word had to stay.

    The measured half and the predicted half sit on one page. "Predicted"
    is not explanation, it is the difference between them, and a reader
    who loses it reads a guess as a measurement.
    """
    section = _gaps_section()
    assert "Predicted, not measured" in section


def test_the_reasoning_survives_where_the_next_person_will_look() -> None:
    """Will asked for it as internal documentation, so it has to be there.

    Checked in the source, not the page: this is the half of the request
    that is easy to skip, because nothing visible breaks if the prose is
    simply deleted.
    """

    # Whitespace is collapsed first. These are wrapped comments, so a
    # phrase that reads as one line in the file is split by a newline and
    # a `*` in the middle -- searching the raw text failed a comment that
    # was there, which is a false RED and the mirror of the usual trap.
    def flat(name: str) -> str:
        return re.sub(r"\s*\*?\s+", " ", (STATIC / name).read_text(encoding="utf-8"))

    gaps = flat("gaps.js")
    assert "no signal on this page names both ends" in gaps, (
        "why there is no line layer was not kept as a comment"
    )
    assert "coarse or missing" in gaps, "the rule about coarse positions was not kept"
    siting = flat("siting.js")
    for kept in ("2.15 dBi", "eight kilometres", "METHOD_SPLAT"):
        assert kept in siting, f"{kept} was not kept as a comment"


def test_the_caveats_are_still_served_by_the_api() -> None:
    """The page stopped showing them; the data did not stop existing.

    Anything that wants to render them properly still can, which is what
    makes removing the list a presentation change rather than a loss.
    """
    route = (
        Path(__file__).resolve().parents[2] / "src" / "sonoran" / "api" / "routes" / "gaps.py"
    ).read_text(encoding="utf-8")
    assert "caveats" in route, "the API no longer serves the caveats"
