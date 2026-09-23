"""The live packet feed does not throw the reader's place away every poll.

The firehose rebuilt its whole table every 15 seconds and dropped the
result in with `replace()`. Every row node was destroyed and remade, so
a reader mid-sentence lost their text selection, and the row they were
reading jumped.

Measured with a headless browser against a seeded feed: scroll to a
row, select text inside it, wait one poll, then ask where that row went
and whether the selection survived.

    live      moved 82px / 180px / 300px      selection kept: never
    patched   moved  0px /   1px /   1px      selection kept: always

Three things had to be true to get there, and each one is a test below.
"""

import re
from pathlib import Path

APP_JS = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "app.js"
).read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    """Only the code counts.

    The first draft of these tests searched the raw text, so the
    comments explaining why NOT to use `replaceChildren` and `scrollBy`
    tripped the very assertions that ban them, and three of four tests
    failed against their own fix.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def _redraw_body() -> str:
    start = APP_JS.index("function redrawLiveTable(")
    end = APP_JS.index("\n}\n", start)
    return _strip_comments(APP_JS[start:end])


def test_the_firehose_redraws_through_the_reconciler() -> None:
    """The call site is the whole point -- the helper existing is not."""
    start = APP_JS.index("/* --- Firehose ---")
    block = APP_JS[start : start + 3000]
    assert "redrawLiveTable(" in block, (
        "the firehose no longer redraws through redrawLiveTable, so it is "
        "back to replacing the table and destroying the reader's selection"
    )


def test_the_rows_are_not_moved_wholesale() -> None:
    """`replaceChildren(...rows)` reuses the right nodes and still loses.

    A move is a remove plus an insert, and removing a node collapses any
    selection inside it. This was measured: with replaceChildren all 5
    marked nodes survived the poll and the selection still died. Only
    touching the rows that actually have to move keeps it.
    """
    body = _redraw_body()
    assert "replaceChildren" not in body, (
        "redrawLiveTable moves every row again; node reuse is not enough, "
        "a move collapses the selection just like a rebuild did"
    )
    assert "insertBefore" in body, "nothing inserts rows in place any more"


def test_rows_are_keyed_on_the_first_render_too() -> None:
    """Otherwise the next poll finds nothing to match and rebuilds.

    The first draft keyed rows only on the reconcile path. The very
    first render therefore wrote no keys, the following poll matched
    zero rows, treated all of them as new, and destroyed the selection
    exactly as before -- with more code in the way.
    """
    body = _redraw_body()
    first_render = body.index("if (!body || !freshBody)")
    assert "rowKey" in body[:first_render], (
        "rows are keyed only after the first render, so the first poll "
        "matches nothing and falls back to a full rebuild"
    )


def test_there_is_no_manual_scroll_anchor() -> None:
    """The browser already does this, and the two corrections stacked.

    An earlier draft measured the anchored row's offset and called
    scrollBy() to put it back. Because the mutation above is minimal,
    the browser's own scroll anchoring had ALREADY corrected it, so the
    page moved twice: 280px of drift against 82px for doing nothing.
    Removing it measured 0-1px.
    """
    body = _redraw_body()
    assert "scrollBy" not in body, (
        "a manual scroll anchor is back; it stacks on the browser's own "
        "anchoring and drifts further than no correction at all"
    )
