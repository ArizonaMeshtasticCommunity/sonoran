"""The mesh graph's "Find a node" box (#223).

Reported by a user as doing nothing. It was not doing nothing -- it was
doing something invisible, for two independent reasons:

* The highlight tested `display_name` alone, while `focusNode` tested
  `display_name` and `node_id`. A **short name** matched neither, and a
  short name is what the reporter typed. Two code paths asking the same
  question different ways.
* Past 120 nodes a dot is 3 px and a match was a 2 px border on it.
  In a mesh of four hundred that is not findable, so even a correct
  match read as nothing happening.

The reporter also found it in the "one node" view, which is the one view
where the query WAS used for something structural -- it chooses the
centre. That is why it appeared to work there and nowhere else.
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
CASES = ROOT / "tests" / "unit" / "js" / "graph_search_cases.mjs"


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
        "node is not on PATH, so the graph search went unchecked. A skip "
        "here looks exactly like a pass."
    )
    return node


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node_bin(), str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
    )


def _code() -> str:
    """`app.js` with comments stripped, so prose cannot answer for code."""
    text = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def test_the_files_are_there() -> None:
    assert MODULE.exists()
    assert CASES.exists()


def test_the_search_matches_and_the_mark_is_findable() -> None:
    """The positive arm, run under node."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_short_name_that_stopped_matching_would_be_caught() -> None:
    """The control for the reported bug itself.

    The mutation is the old behaviour: test `display_name` only.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "const fields = [node.display_name, node.short_name, node.long_name, node.node_id];",
        "const fields = [node.display_name];",
    )
    assert broken != source, "the field list has moved, so this control is checking nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass when only display_name is searched, which is the bug that was reported"
    )


def test_one_matcher_serves_both_the_highlight_and_the_focus() -> None:
    """The two paths must not drift apart again.

    They already did: that is why the search worked in the one view that
    used `focusNode` and nowhere else.
    """
    code = _code()
    assert code.count("function matchesGraphQuery(") == 1
    # The focus view and the node styling both call it.
    assert "data.nodes.find((node) => matchesGraphQuery(node, query))" in code
    assert "const match = matchesGraphQuery(node, query);" in code
    # And nothing tests display_name by hand any more.
    assert "node.display_name.toLowerCase().includes(query)" not in code, (
        "a hand-rolled name test is back, which is how these drifted"
    )


def test_the_page_says_what_the_search_found() -> None:
    """ "It does nothing" must not be a possible reading again.

    A reader needs to tell "found, look for the ringed node" from "that
    name is not here" -- and from "it is here but this view does not
    draw it", which the backbone view really can do.
    """
    assert "data-graph-search-note" in INDEX.read_text(encoding="utf-8")
    code = _code()
    assert "No node in this view matches" in code
    assert "ringed in the graph" in code
    assert "try Whole preset" in code, (
        "the backbone view can hide a matching node and the note does not say so"
    )


def test_the_note_hides_when_nothing_is_typed() -> None:
    """An empty box must not leave a message on the page."""
    code = _code()
    assert "searchNote.hidden = !query;" in code
