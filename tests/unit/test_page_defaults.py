"""What the pages open on, and why those are the right defaults.

Each of these is a default somebody has to live with on every visit,
so each is pinned rather than left to drift back.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
PARAMS = (STATIC / "planner-params.js").read_text(encoding="utf-8")


def test_the_node_page_opens_on_thirty_days() -> None:
    """#98. A day shows no pattern for a node that reports every few hours."""
    start = INDEX.index("data-node-hours")
    block = INDEX[start : INDEX.index("</select>", start)]
    chosen = re.findall(r'<option value="(\d+)" selected>', block)
    assert chosen == ["720"], f"the node page opens on {chosen}, not 30 days"


def test_the_script_fallback_agrees_with_the_markup() -> None:
    """Two places name this default, and they must not disagree.

    The select carries it, and `loadNodeDetail` falls back to it when
    the select has no value. A mismatch means the page behaves one way
    on load and another after a re-render.
    """
    start = INDEX.index("data-node-hours")
    block = INDEX[start : INDEX.index("</select>", start)]
    markup = re.findall(r'<option value="(\d+)" selected>', block)[0]
    fallback = re.search(r"\[data-node-hours\]', page\)\.value \|\| '(\d+)'", APP)
    assert fallback, "the script fallback for the node window could not be found"
    assert fallback.group(1) == markup, (
        f"the markup opens on {markup} h and the script falls back to {fallback.group(1)} h"
    )


def test_the_planner_opens_on_medium_fast_with_its_own_sensitivity() -> None:
    """#105. The preset and its sensitivity are one choice, not two.

    A form opening on Medium fast with Long fast's -139 dBm would
    predict a reach nobody has. The change handler keeps them together
    after the first load; the defaults have to keep them together
    before it.
    """
    # Inside DEFAULTS only. The PRESETS list above it also has
    # `sensitivity:` on every entry, and a file-wide search finds the
    # first of those instead.
    block = PARAMS[PARAMS.index("const DEFAULTS = {") :]
    block = block[: block.index("\n};")]
    preset = re.search(r"preset: '(\w+)'", block)
    sensitivity = re.search(r"sensitivity: (-?\d+)", block)
    assert preset and sensitivity, "DEFAULTS has no preset or no sensitivity"
    assert preset.group(1) == "MEDIUM_FAST", f"the planner opens on {preset.group(1)}"

    listed = re.search(r"\{ key: 'MEDIUM_FAST'[^}]*sensitivity: (-?\d+)", PARAMS)
    assert listed, "MEDIUM_FAST is not in the preset list"
    assert sensitivity.group(1) == listed.group(1), (
        f"the default sensitivity is {sensitivity.group(1)} but MEDIUM_FAST needs {listed.group(1)}"
    )


def test_the_four_summary_panels_can_share_a_row() -> None:
    """#102. They are short, and took two rows plus a screen of scroll.

    Measured on a 1500 px viewport: four panels at tops
    [1338, 1338, 1338, 1800] became [598, 598, 598, 598].
    """
    assert "grid summary-row" in APP, "the summary panels have no row of their own"
    # Into the code, not into a comment that mentions the selector. A
    # rule added elsewhere in app.css explains why it overrides
    # `.grid.summary-row`'s own margin, and naming it in prose was
    # enough to make a raw `index` find the wrong place -- the sixth
    # time a source-text assertion in this repository has answered from
    # a comment.
    code = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    start = code.index(".grid.summary-row {")
    rule = code[start : code.index("}", start)]
    assert "minmax(min(" in rule, (
        "the summary row omits the `min(..., 100%)` guard every other grid "
        "here uses; that is what stops the track floor exceeding the "
        "container on a phone, and its absence is what made Statistics "
        "scroll sideways"
    )
