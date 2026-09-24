"""The #199 and #196 design pass, run rather than read.

Two behaviours carry real weight here and neither can be checked by
grepping source:

* `shortUrl` has to do the right thing to a **real** Google Maps link,
  which is what 21 of the latest 50 messages contained.
* A URL must come out as a `span`, never an anchor. A message body is
  text anyone on the mesh can send and nothing checks who sent it, so a
  clickable link would lend this site's credibility to a stranger's
  destination -- the #81 shape in a new place.

So the shipped `app.js` is loaded under node and the functions are
called. The Python side owns the controls: that the cases really run,
and that a broken implementation would be caught.
"""

import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "app.js"
CASES = ROOT / "tests" / "unit" / "js" / "design_pass_cases.mjs"
INDEX = ROOT / "src" / "sonoran" / "web" / "static" / "index.html"
CSS = ROOT / "src" / "sonoran" / "web" / "static" / "app.css"


@contextmanager
def _temporarily(path: Path, text: str) -> Iterator[None]:
    original = path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _node() -> str:
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so the message and marker behaviour went "
        "unchecked. It is not optional: this repo already needs node for "
        "the e2e suite, and a skip here looks exactly like a pass."
    )
    return node


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
    )


def test_the_files_are_where_the_cases_expect() -> None:
    """The control, so a moved file fails as itself."""
    assert MODULE.exists()
    assert CASES.exists()


def test_the_behaviour_holds() -> None:
    """The positive arm."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_url_turned_into_a_link_would_be_caught() -> None:
    """The control that guards the security decision.

    This is the change a future contributor is most likely to make --
    "why isn't this clickable?" -- so the mutation is that exact edit,
    not an obviously broken one.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "node.append(el('span', { class: 'link-text', title: chunk, text: shortUrl(chunk) }));",
        "node.append(el('a', { class: 'link-text', href: chunk, text: shortUrl(chunk) }));",
    )
    assert broken != source, (
        "the URL node is no longer built where this control mutates it, so "
        "it is checking nothing. A mutation that does not apply is "
        "indistinguishable from one the cases survive."
    )
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with a message body rendering a clickable link, so "
        "nothing here protects against putting an unchecked destination on "
        "the project's own page"
    )


def test_a_dot_that_ignores_the_zoom_would_be_caught() -> None:
    """The control for #196's radius scale."""
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "  if (zoom <= 7) return 2.5;",
        "  if (zoom <= 7) return 5;  // the old fixed size",
    )
    assert broken != source, "the radius scale has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass with the opening view back at the old fixed radius"


# --- the parts that are markup or style, not behaviour -------------


def _css_without_comments() -> str:
    """Return `app.css` with `/* ... */` removed.

    The first version of the case below read the raw file and failed --
    on its own comment, which quotes the `border: 0` it exists to
    forbid. That is the fifth time in this session that a source-text
    assertion has answered from a comment rather than from code, so the
    stripping is factored out and controlled.
    """
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)


def test_the_css_comment_stripper_works() -> None:
    """Positive control for the helper above."""
    assert _css_without_comments().count("/*") == 0
    assert ".watch-control button {" in _css_without_comments()


def test_the_every_node_label_says_what_it_does() -> None:
    """It dropped the preset filter AND the window: 401 nodes to 1,268.

    A reader could not tell that, and the reporter guessed it "just
    shows offline nodes". AGENTS.md 9.7 requires that mixing presets is
    stated, so it belongs in the label rather than a tooltip.
    """
    html = INDEX.read_text(encoding="utf-8")
    assert "Every preset, any time" in html
    assert ">Every node<" not in html, "the old label is still on a control"


def test_the_watch_mode_button_has_a_boundary() -> None:
    """WCAG 2.1 SC 1.4.11 wants 3:1 for a control's boundary.

    It was `border: 0` on a panel background over dark map tiles, so
    there was no boundary at all to measure.
    """
    css = _css_without_comments()
    block = css[css.index(".watch-control button {") :]
    rule = block[: block.index("}")]
    assert "border: 1px" in rule, "the watch control still has no visible edge"
    assert "border: 0" not in rule, "the rule still zeroes the border"


def test_automated_senders_are_quieter_but_still_there() -> None:
    """The reporter decided every message stays. This changes weight only.

    A filter or a fold would be the thing that was explicitly ruled
    out, so the test asserts the mechanism is a colour on the body and
    nothing that removes an item.
    """
    css = CSS.read_text(encoding="utf-8")
    assert ".messages li.quiet .body { color: var(--muted); }" in css
    app = MODULE.read_text(encoding="utf-8")
    assert "QUIET_CHANNELS" in app
    # Nothing may drop a message for being automated.
    assert ".filter((m) => !QUIET" not in app
    assert "QUIET_CHANNELS.has(message.channel) ? null" not in app


def test_a_focus_mark_that_did_not_hold_would_be_caught() -> None:
    """Control for #193.6's marker.

    The mutation is the implementation I first wrote and rejected: mark
    the node by opening its popup. That does not survive -- the live map
    polls, `drawMapNodes` clears the layer, and the popup goes with it
    within seconds (measured: already closed six seconds after following
    the link). So the mutation removes the per-call mark and the cases
    must notice.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "const focused = mapState.focusNodeId && node.node_id === mapState.focusNodeId;",
        "const focused = false;  // the popup-only version",
    )
    assert broken != source, "the focus mark is no longer computed where this control mutates it"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with no focus mark at all, so a #map/node link "
        "would centre on a node the reader cannot pick out"
    )


def test_the_focus_preset_is_applied_before_the_fetch() -> None:
    """Carrying the preset is worthless unless it is used (#193.6).

    I wrote the comment explaining this trap and then did not implement
    it: `mapFocus.preset` was stored and never read, so a link to a node
    on any other preset would have landed on empty ground -- exactly
    what the issue warned about. Verified live afterwards: following
    `?preset=Weather` selects Weather, not the MediumFast default.
    """
    source = MODULE.read_text(encoding="utf-8")
    choose = source.index("async function linkChannelOptions(")
    body = source[choose : source.index("\n}", choose)]
    assert "mapFocus.preset" in body, (
        "the preset in a #map/node link is not applied where the channel "
        "is chosen, so it cannot affect the fetch"
    )
