"""One way to open a row (Phase A, §3.4; Phase C, §5.1).

Will: "I don't think we need a repeating 'open' link to the left of every
row. I do think we should make the whole row clickable and maybe make the
time clickable and always on the left so people know it's clickable."

Two of the three already existed. `table()` has taken `options.rowHref`
since before this work, and it ignores clicks that land on a link or a
button so inner node chips still go to their own pages. What was missing
was using it, and what was wrong was the Firehose: a leading column whose
only content was the word "Open" on every row, beside a Time column that
was plain text.

**The first cell stays a real `<a href>`.** That is the part of the pattern
worth defending: a click handler has no URL, so right-click, copy-link,
middle-click and open-in-new-tab all stop working and none of them fail
visibly.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"


def _app() -> str:
    text = re.sub(r"/\*.*?\*/", "", (STATIC / "app.js").read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("//")
    )


def _columns(marker: str, until: str) -> list[str]:
    return re.findall(r"label: '([^']+)'", _block(marker, until))


def _block(marker: str, until: str) -> str:
    app = _app()
    start = app.index(marker)
    return app[start : start + app[start:].index(until)]


def _firehose() -> str:
    """The firehose table, anchored on its own container.

    NOT on `const packetHref`: three tables define one, and anchoring on
    the name landed on an earlier table whose Time column is plain text
    and whose Kind column IS a packet link. Every firehose assertion here
    was reading that other table and passing for the wrong reason -- found
    by a mutation that should have failed and did not.
    """
    app = _app()
    start = app.index("data-firehose-table")
    # To the end of the FUNCTION. `rowHref` is an option passed after the
    # empty-message string, so a window cut there reports a clickable row
    # as broken -- the same mistake the traceroutes case made.
    return app[start : start + app[start:].index("\n};")]


def test_the_comment_stripper_works() -> None:
    app = _app()
    assert "function table(" in app, "the stripper removed real code"
    assert "worth defending" not in app, "comments are leaking through"


def test_no_table_carries_a_repeating_open_link() -> None:
    """The word "Open" on every row, in a column of its own."""
    app = _app()
    assert "open-link" not in app, "the per-row Open link is back"
    assert "'Open \\u203a'" not in app, "a row still prints the word Open"
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\.open-link[^{]*\{", css), "the dead .open-link CSS is back"


def test_the_firehose_leads_with_a_clickable_time() -> None:
    block = _firehose()
    columns = re.findall(r"label: '([^']+)'", block)
    assert columns and columns[0] == "Time", f"the first column is {columns[0]!r}"
    assert "Packet" not in columns, "the Open/Packet column is back"
    # The time cell itself must be the anchor, and it must carry the href.
    time_cell = block[block.index("label: 'Time'") :]
    time_cell = time_cell[: time_cell.index("label: '", 20)]
    assert "el('a'" in time_cell, f"the time cell is not a link: {time_cell!r}"
    assert "href: packetHref(row)" in time_cell, f"the link has no href: {time_cell!r}"
    assert "rowHref: packetHref" in block, "the row is no longer clickable"


def test_the_traceroutes_table_leads_with_a_clickable_time() -> None:
    columns = _columns("PAGES.traceroutes", "No traceroutes recorded")
    assert columns[0] == "Time", f"the first column is {columns[0]!r}"
    app = _app()
    # The window runs to the end of the FUNCTION, not to the empty-message
    # string: `rowHref` is an option passed after it, so a window cut there
    # reported a correct page as broken.
    block = app[app.index("PAGES.traceroutes") :]
    block = block[: block.index("\n};")]
    assert "href: `#traceroute/${row.id}`" in block, "the time cell is not a link"
    assert "rowHref:" in block, "the whole row does not open the trace"


def test_the_traceroutes_table_dropped_the_two_columns_will_named() -> None:
    """Drawing and Packet.

    Checked before removing, rather than assumed: the drawing is on the
    individual trace page (`graph_url` in the trace view), and the reverse
    lookup `api/traceroutes/by-packet/...` is called from the PACKET page,
    so a reader can still get between a packet and its trace. The column
    went; the road did not.
    """
    columns = _columns("PAGES.traceroutes", "No traceroutes recorded")
    assert "Drawing" not in columns
    assert "Packet" not in columns
    app = _app()
    # The capabilities that must survive the columns.
    assert "graph_url" in app, "the drawing is no longer reachable anywhere"
    assert "by-packet" in app, "the packet-to-trace lookup is gone"


def test_a_row_click_does_not_swallow_the_links_inside_it() -> None:
    """From and To hold node chips that must still go to their own pages."""
    app = _app()
    body = app[app.index("const open = (event) =>") :]
    body = body[: body.index("\n    };")]
    assert "closest('a, button, input, summary')" in body, (
        "a click on an inner link now opens the row instead"
    )


def test_a_clickable_row_is_reachable_without_a_mouse() -> None:
    """The row has no tab stop; the link in its first cell does.

    That is why the first cell must stay a link rather than becoming part
    of the handler -- otherwise the row is operable only by pointer.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "tr.row-link:focus-within td" in css, "nothing shows which row the keyboard is on"
    assert "tr.row-link { cursor: pointer; }" in css, "the row does not look clickable"
