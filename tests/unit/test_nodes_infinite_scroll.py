"""The nodes list scrolls on instead of stopping at a cap (§6.2).

Will: replace "569 nodes · showing 300" with infinite scroll. The API
already takes `limit`/`offset`.

Three things here are load-bearing and none of them is visible in the
diff:

* **The sort stays on the server.** The list is paged, so a browser that
  reordered the rows it held would sort one page and leave the rest in
  the old order -- and present the result as the order of the whole mesh.
  An e2e journey watches for `sort=` on the request; these cases hold the
  code that makes it possible, which is that one column list is used for
  the first page and for every appended one.
* **`.more-wrap` is `display: flex`,** and a class rule beats the user
  agent's `[hidden] { display: none }`. Without an explicit rule the foot
  of a finished list stays on the page and the observer watching it keeps
  reporting it as in view -- an invisible control and a spinning wheel.
* **An absent total is not zero.** `X-Total-Count` can be missing, and
  `Number(null)` is 0. The behaviour cases in `js/nodes_paging_cases.mjs`
  run that arm; the mutation case below proves those cases can fail.

The behaviour cases are run under node, and each is mutated here, because
a check only ever seen passing is not evidence that it can fail.
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
INDEX = STATIC / "index.html"
CSS = STATIC / "app.css"
CASES = ROOT / "tests" / "unit" / "js" / "nodes_paging_cases.mjs"


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
        "node is not on PATH, so the paging logic went unchecked. A skip here "
        "looks exactly like a pass."
    )
    return node


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node_bin(), str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
    )


def _app() -> str:
    """`app.js` with comments stripped, so prose cannot answer for code."""
    text = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def _html() -> str:
    return re.sub(r"<!--.*?-->", "", INDEX.read_text(encoding="utf-8"), flags=re.S)


def test_the_comment_stripper_works() -> None:
    """Positive control: without it every case below reads the comments."""
    app = _app()
    assert "function mergeNodePage" in app, "the stripper removed real code"
    assert "keyset pagination" not in app, "comment text is leaking through"
    assert "data-node-more" in _html()
    assert "infinite scroll has no affordance" not in _html(), "HTML comments leak"


# --- the behaviour cases, and proof that they can fail ---------------


def test_the_paging_cases_pass() -> None:
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_an_offset_that_counted_kept_rows_would_be_caught() -> None:
    """The bug this function exists to prevent.

    Advancing the offset by the rows we KEPT rather than by the rows the
    server SERVED means every dropped duplicate is requested again, and
    the list pages forever without reaching its end. It is invisible on a
    mesh that never reorders, which is most of them most of the time.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "    offset: offset + served.length,",
        "    offset: offset + added.length,",
    )
    assert broken != source, "the offset line has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when the offset counts only the kept rows"
    assert "offset" in done.stderr, f"the failure does not name the offset: {done.stderr}"


def test_a_list_that_drew_duplicates_would_be_caught() -> None:
    """The plan's own risk: "rows will repeat"."""
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "    if (!row || row.node_id == null || seen.has(row.node_id)) continue;",
        "    if (!row) continue;",
    )
    assert broken != source, "the duplicate test has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when a repeated row is drawn twice"
    assert "twice" in done.stderr, f"the failure does not name the repeat: {done.stderr}"


def test_a_full_page_treated_as_the_end_would_be_caught() -> None:
    """`<` not `<=`: an exactly full page is not the last one.

    With `<=` a mesh whose count is a multiple of the page size loses its
    last page, and nothing on the screen says a row is missing.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "    exhausted: served.length < pageSize,",
        "    exhausted: served.length <= pageSize,",
    )
    assert broken != source, "the exhausted test has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when a full page ends the list"


def test_an_absent_total_read_as_zero_would_be_caught() -> None:
    """The `Number(null) === 0` bug, for the sixth time in this repo."""
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "  if (total == null) return `${count(shown)} loaded · the total is unknown`;",
        "  if (false) return '';",
    )
    assert broken != source, "the absent-total branch has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when an absent total falls through to arithmetic"


# --- the wiring, which the behaviour cases cannot see ----------------


def test_the_foot_of_the_list_is_in_the_markup() -> None:
    """A live region has to exist before its contents change.

    Built at the same moment as its text, a `role="status"` is not
    reliably announced -- so a screen reader would be told nothing about
    a page that arrived from scrolling, which is now every page.
    """
    html = _html()
    assert "data-node-more" in html, "the foot of the list is not in the markup"
    assert "data-node-more-button" in html, "there is no button beside the scrolling"
    foot = html[html.index("data-node-more") : html.index("</p>", html.index("data-node-more"))]
    assert 'role="status"' in foot, "the progress line is not a live region"
    assert "data-node-progress" in foot


def test_the_foot_is_outside_the_sideways_scrolling_box() -> None:
    """`.table-wrap` scrolls sideways.

    The button this replaces was appended inside it, so on a phone with
    the table scrolled right to read the last column, the button had
    scrolled off to the left.
    """
    html = _html()
    table = html.index("data-node-table")
    wrap_ends = html.index("</div>", table)
    assert html.index("data-node-more") > wrap_ends, "the foot is inside the scrolling box"
    assert "target.append(el('p', { class: 'more-wrap' }" not in _app(), (
        "the old in-table button is back"
    )


def test_a_hidden_foot_is_really_hidden() -> None:
    """`.more-wrap` is `display: flex`, which beats `[hidden]`.

    Without this rule the foot of a finished list stays visible saying
    nothing, and the observer watching it goes on reporting it as in
    view -- so the page asks for pages that do not exist.
    """
    css = CSS.read_text(encoding="utf-8")
    assert ".more-wrap { display: flex" in css, "the rule this guards against has moved"
    assert ".more-wrap[hidden] { display: none; }" in css, (
        "a hidden foot would still be drawn, because a class rule beats [hidden]"
    )


def test_the_scroll_and_the_button_ask_the_same_way() -> None:
    """Two callers, one set of reasons not to fetch.

    A guard written at each caller is a guard that drifts: the button
    checked `nodeTotal` and the observer checked the flag, and then one of
    them asked for a page past the end.
    """
    app = _app()
    assert app.count("function nodeMore(") == 1
    body = app[app.index("function nodeMore(") :]
    body = body[: body.index("\n}")]
    assert "nodeLoadingMore" in body, "nothing stops two scroll events fetching the same offset"
    assert "nodeExhausted" in body, "nothing stops a request past the end of the list"
    assert "currentPage !== 'nodes'" in body, "a background page would keep fetching"
    # Both callers go through it.
    assert "button.addEventListener('click', nodeMore)" in app
    assert "nodeMore();" in app[app.index("function wireNodeScroll(") :]


def test_the_observer_is_rearmed_after_every_page() -> None:
    """Otherwise the list stalls on a tall screen.

    One page of rows does not always push the foot back out of view. The
    intersection state then never changes, no second callback is
    delivered, and the list stops -- while looking as though it simply
    ran out.
    """
    app = _app()
    assert "function rearmNodeScroll(" in app
    body = app[app.index("function rearmNodeScroll(") :]
    body = body[: body.index("\n}")]
    assert "unobserve" in body and "observe" in body, "re-arming does not re-observe"
    loader = app[app.index("async function loadNodes(") :]
    loader = loader[: loader.index("\nfunction nodeColumns(")]
    assert "rearmNodeScroll()" in loader, "a loaded page does not re-arm the observer"


def test_scrolling_is_not_the_only_way_to_read_on() -> None:
    """The plan: "a 'load more' button as well as auto-load".

    Infinite scroll on its own has no affordance, gives a keyboard
    nothing to operate, and breaks "jump to the end".
    """
    assert "data-node-more-button" in _html()
    app = _app()
    assert "typeof IntersectionObserver !== 'function'" in app, (
        "a browser without the observer would get no paging at all"
    )
    watch = app[app.index("function wireNodeScroll(") :]
    watch = watch[: watch.index("\n}")]
    assert watch.index("addEventListener('click', nodeMore)") < watch.index(
        "typeof IntersectionObserver"
    ), "the button is wired after the early return, so it is lost on those browsers"


def test_the_button_keeps_focus_while_a_page_is_in_flight() -> None:
    """`disabled` on a focused button throws focus to the document.

    A keyboard reader pressing the button would lose their place in the
    list on every page.
    """
    app = _app()
    body = app[app.index("function drawNodeMore(") :]
    body = body[: body.index("\n}")]
    assert "aria-disabled" in body
    assert "button.disabled" not in body, (
        "disabling the button blurs it, which loses a keyboard reader's place"
    )
    assert "wrap.focus()" in body, "focus is dropped when the button goes at the end of the list"


def test_the_appended_rows_come_from_the_same_column_list() -> None:
    """A second row renderer would drift from the first page's.

    It also has to be the reason the sort can stay on the server: one
    column list, one `sortState`, and the appended rows carry the order
    they were served in.
    """
    app = _app()
    assert app.count("function nodeColumns(") == 1
    loader = app[app.index("async function loadNodes(") :]
    loader = loader[: loader.index("\nfunction nodeColumns(")]
    assert "nodeColumns(" in loader, "the loader builds its own columns"
    assert "table(columns, appended" in loader, "appended rows are not built by table()"
    assert "table(columns, nodeRows" in loader, "the first page is not built by table()"


def test_a_new_order_starts_the_list_again() -> None:
    """Paging on after a re-sort would mix two orderings in one table."""
    app = _app()
    loader = app[app.index("async function loadNodes(") :]
    loader = loader[: loader.index("\nfunction nodeColumns(")]
    sort = loader[loader.index("const columns = nodeColumns(") :]
    sort = sort[: sort.index("});")]
    assert "reset: true" in sort, "a column click pages on from the middle of the old order"


def test_a_failed_later_page_keeps_the_rows_already_read() -> None:
    """The first page's error replaces the table; a later one must not.

    Throwing away two hundred correct rows over a failed request for the
    next hundred loses the reader's place as well as their rows.
    """
    app = _app()
    loader = app[app.index("async function loadNodes(") :]
    loader = loader[: loader.index("\nfunction nodeColumns(")]
    guard = loader[loader.index("if (answer instanceof Error)") :]
    guard = guard[: guard.index("const merged")]
    assert "if (reset) return replace(target, failure(answer));" in guard, (
        "a failed later page still replaces the whole table"
    )
    assert "drawNodeMore(page, answer)" in guard, "a failed later page says nothing"
    body = app[app.index("function drawNodeMore(") :]
    body = body[: body.index("\n}")]
    assert "Try again" in body, "a failed page is a dead end"


def test_the_stale_answer_path_does_not_wedge_the_list() -> None:
    """The flag has to be cleared on every way out of the loader.

    An abandoned page that left `nodeLoadingMore` set is in flight
    forever, and both the button and the observer refuse to ask again.
    """
    app = _app()
    loader = app[app.index("async function loadNodes(") :]
    loader = loader[: loader.index("\nfunction nodeColumns(")]
    token = loader.index("if (token !== nodeSearchToken) return;")
    after = loader[token:]
    assert "nodeLoadingMore = false;" in after[: after.index("if (answer instanceof Error)")], (
        "the in-flight flag survives a stale answer, which wedges the list"
    )


def test_the_page_is_no_longer_capped_at_300() -> None:
    """The cap was large because a cap was the whole paging story.

    It is now the first paint instead: 300 rows of six columns is 1,800
    cells built before anything is on the screen.
    """
    app = _app()
    assert "const NODE_PAGE = 100;" in app, "the request size is not the page size"
    assert "limit: String(NODE_PAGE)," in app, "the request does not ask for one page"


def test_the_line_above_the_table_no_longer_says_showing() -> None:
    """The plan names that string as the one infinite scroll replaces.

    How much has loaded is now a fact about the foot of the list, and it
    is written there -- beside the control that changes it, which is the
    same rule the filter count follows.
    """
    app = _app()
    body = app[app.index("function describeNodeList(") :]
    body = body[: body.index("\n}")]
    assert "showing" not in body, "the head line still describes the page rather than the mesh"
    assert "nodeTotal == null" in body, "an absent total would print as a number"
