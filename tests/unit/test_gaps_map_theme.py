"""The gaps map draws in the theme the rest of the page draws in.

The two marker colours were written into the script as `#ef6f5c` and
`#8fa6c4` -- the DARK values of `--gap-bad` and `--gap-unknown`. The
light theme overrides both. So in light mode the map painted salmon
and pale blue while the legend, chips, rows, findings and tiles beside
it all painted the darker light-theme colours, on a page whose entire
job is colour-coded severity.

Measured by sampling the canvas the markers are drawn on, against the
deployed instance:

    light, before   painted #ef6f5c   token said #b7352a
    light, after    painted #b7352a   token said #b7352a
    dark,  before   painted #ef6f5c   token said #ef6f5c
    dark,  after    painted #ef6f5c   unchanged

The markers are on a canvas because the map uses `preferCanvas`, which
is also why this was invisible to any DOM-based check.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
GAPS_JS = (STATIC / "gaps.js").read_text(encoding="utf-8")
GAPS_CSS = (STATIC / "gaps.css").read_text(encoding="utf-8")


def test_the_marker_colours_are_not_written_into_the_script() -> None:
    """A hex literal as the marker's COLOUR cannot follow a theme.

    A literal as the `themeColour` fallback is fine and deliberate --
    see the fallback test below. So this reads the two options that
    decide what is painted, not every hex in the neighbourhood. The
    first draft banned both and failed on its own fix.
    """
    start = GAPS_JS.index("L.circleMarker(")
    block = GAPS_JS[start : start + 400]
    for option in ("color:", "fillColor:"):
        line = next(part.strip() for part in block.split("\n") if part.strip().startswith(option))
        assert not re.search(r"#[0-9a-fA-F]{6}", line), (
            f"the marker's {option} is a literal ({line!r}); the light theme "
            f"overrides these tokens, so the map and its own legend disagree"
        )


def test_the_marker_reads_the_same_tokens_the_legend_uses() -> None:
    """Not merely 'a token' -- the ones the rest of the page uses."""
    start = GAPS_JS.index("L.circleMarker(")
    block = GAPS_JS[start - 400 : start + 400]
    for token in ("gap-bad", "gap-unknown"):
        assert token in block, f"the marker does not read --{token}"
        assert f"var(--{token})" in GAPS_CSS or f"--{token}:" in GAPS_CSS, (
            f"--{token} is not a real token in gaps.css"
        )


def test_the_fallbacks_are_the_dark_values() -> None:
    """A browser that cannot resolve the property draws what it drew before.

    Falling back to nothing would leave an invisible marker, which is
    worse than an out-of-theme one.
    """
    start = GAPS_JS.index("function themeColour(")
    assert "|| fallback" in GAPS_JS[start : start + 300], (
        "themeColour has no fallback, so an unresolvable token paints nothing"
    )
    start = GAPS_JS.index("L.circleMarker(")
    block = GAPS_JS[start - 400 : start + 400]
    assert "themeColour('gap-bad'" in block and "themeColour('gap-unknown'" in block


def test_the_classes_that_were_written_for_this_and_never_used_are_gone() -> None:
    """`.gap-marker-bad` / `.gap-marker-unknown` were the intended
    mechanism and were never wired to anything. Leaving them beside a
    working one invites somebody to wire up the wrong half."""
    assert "gap-marker" not in GAPS_CSS, (
        "the unused marker classes are still there, as a second and "
        "half-finished way to do what themeColour now does"
    )
