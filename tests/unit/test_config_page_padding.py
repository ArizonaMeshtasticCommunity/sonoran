"""The config checker's widgets need space between them (Will, 2026-09-26).

Reported alongside the gaps page's version of the same complaint: "you
can see no padding on desktop". This one took longer because it was first
recorded as not reproducible from the markup, which was wrong -- it
reproduces the moment the page is actually loaded. Measured in a browser
before the fix, the gap between "1. Where is the node" and the row under
it was 0 px; after, 16 px.

The cause is two ordinary facts meeting: `[data-config-input]` is a plain
`<div>`, so block layout, and `.panel` sets no margin. Nothing was
overriding anything.

The fix is an adjacent-sibling margin, NOT a grid or flex container, and
that choice is what these cases mostly protect. `.grid` carries
`margin-inline: auto`; an auto inline margin on a grid or flex ITEM
absorbs free space rather than stretching, so making this container a
grid shrinks the `.grid two` inside it to its content width. That is
#193.1 and it has already cost one round trip on the gaps page.
"""

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "app.css"
).read_text(encoding="utf-8")
HTML = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "index.html"
).read_text(encoding="utf-8")
WITHOUT_COMMENTS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


def _rule(selector: str) -> str | None:
    """The body of one rule, or None when it is not there."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", WITHOUT_COMMENTS)
    return match.group(1) if match else None


def test_the_widgets_are_spaced() -> None:
    body = _rule("[data-config-input] > * + *")
    assert body is not None, (
        "nothing spaces the config checker's widgets; they sit flush, which is what Will reported"
    )
    assert "margin-top" in body, f"the rule does not set margin-top: {body!r}"
    # A gap of nothing is the bug with a rule in front of it.
    size = re.search(r"margin-top:\s*([\d.]+)(rem|px|em)", body)
    assert size, f"the margin has no measurable size: {body!r}"
    assert float(size.group(1)) > 0, f"the margin is zero: {body!r}"


def test_the_container_is_still_block() -> None:
    """The #193.1 trap, asserted directly.

    If somebody later spaces these with `display: grid; gap`, the
    `.grid two` inside shrinks to its content and the page looks worse
    than it did before the padding was added.
    """
    body = _rule("[data-config-input]")
    if body is None:
        return  # No rule at all is the correct state: <div> is block already.
    assert "display: grid" not in body and "display: flex" not in body, (
        "[data-config-input] became a grid or flex container. Its child .grid "
        "carries `margin-inline: auto`, which on a grid/flex item absorbs free "
        f"space instead of stretching, so the row shrinks to its content: {body!r}"
    )


def test_the_widgets_are_actually_siblings() -> None:
    """The selector has to match the real markup.

    `> * + *` spaces SIBLINGS. If the widgets were ever wrapped
    individually, the rule would still parse, still pass a text check, and
    space nothing.
    """
    start = HTML.index("<div data-config-input>")
    end = HTML.index('<section class="page"', start)
    region = HTML[start:end]
    # Counted at the top level of the container, not everywhere inside it.
    depth = 0
    top_level = 0
    for match in re.finditer(r"<(/?)div\b([^>]*)>", region):
        closing = match.group(1)
        if closing:
            depth -= 1
        else:
            if depth == 1 and ("panel" in match.group(2) or "grid" in match.group(2)):
                top_level += 1
            depth += 1
    assert top_level >= 2, (
        f"only {top_level} widget(s) are direct children of [data-config-input], "
        "so a sibling margin has nothing to space"
    )
