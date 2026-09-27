"""The four summary tiles are one compact block on a phone (#278).

The mobile review measured the four numbers at 292 px, 35% of the first
screen, and asked for a strip about 120 px tall below 40rem. The layout
itself is measured in the browser by the e2e journey "the summary tiles
are one compact block on a phone (#278)". These tests hold the two parts
that a later edit could quietly undo.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def _phone_rules() -> str:
    """The body of the 40rem block that holds the tile rules."""
    for match in re.finditer(r"@media \(max-width: 40rem\) \{", CSS):
        body = CSS[match.end() : CSS.index("\n}\n", match.end())]
        if ".grid[data-summary]" in body:
            return body
    raise AssertionError("no 40rem rule for the summary tiles")


def test_the_tiles_are_compact_below_40rem() -> None:
    rules = _phone_rules()
    assert ".grid[data-summary] .stat {" in rules
    # The change sits on the figure's line, not a line of its own.
    assert "grid-area: 1 / 2" in rules
    # The "i" keeps its tap area without growing the row.
    assert re.search(r"\.hint-open \{ margin-block: -", rules)


def test_the_folded_words_stay_for_a_screen_reader() -> None:
    """Off the screen, never `display: none`, which would hide them from everybody."""
    rules = _phone_rules()
    rest = rules[rules.index(".delta-rest {") :]
    rest = rest[: rest.index("}")]
    assert "clip-path: inset(50%)" in rest
    assert "display: none" not in rest


def test_the_change_is_split_from_its_words() -> None:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the split went unchecked. A skip looks like a pass."
    start = APP.index("function compactDelta(")
    code = APP[start : APP.index("\n}\n", start) + 2]
    script = (
        "const el = (tag, props) => ({ rest: props.text });\n"
        + code
        + "console.log(JSON.stringify(['▲ 4% on the day before', 'same as the day before',"
        " '12 yesterday', null].map(compactDelta)));"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [
        ["▲ 4%", {"rest": " on the day before"}],
        ["same", {"rest": " as the day before"}],
        # Nothing to fold: the whole line stays.
        "12 yesterday",
        None,
    ]
