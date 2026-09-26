"""Live map line lifetimes, and what a mode switch does to them (#222).

Reported: "Lines vanish too quickly to read, whichever mode is on", and
switching modes "feels broken".

From the constants before the change:

    motion on   2 x 850 ms flight + 5 s hold + 3 s fade = 9.7 s
    motion off  painted whole     + 5 s hold + 3 s fade = 8.0 s
    poll                                                 15.0 s

So **both** states died before the next fetch and the map spent about
half of every cycle empty. The two modes are meant to answer different
questions -- motion says "just now, and that way" (rule B), motion off
is the lasting picture -- and neither did.

The cases run under node: the claims are arithmetic over the constants
and the behaviour of a rescale.
"""

import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "map-live.js"
CASES = ROOT / "tests" / "unit" / "js" / "live_lifetime_cases.mjs"


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
    assert node, "node is not on PATH, so the lifetimes went unchecked"
    return node


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
    )


def _code() -> str:
    text = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def test_the_files_are_there() -> None:
    assert MODULE.exists()
    assert CASES.exists()


def test_the_lifetimes_and_the_rescale_hold() -> None:
    """The positive arm."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_short_lasting_mode_would_be_caught() -> None:
    """The control for the reported symptom.

    The mutation is the old value: a hold that does not outlast the poll,
    which is what made the map empty between fetches.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace("const LIVE_HOLD_MS = 30000;", "const LIVE_HOLD_MS = 5000;")
    assert broken != source, "the hold constant has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with a hold shorter than the poll, so nothing here "
        "protects against the map emptying between fetches"
    )


def test_motion_stays_brief() -> None:
    """Rule B: motion means "just now, and that way", and nothing else.

    Making motion long-lived would satisfy "lines last longer" and
    destroy the distinction the issue is asking for.
    """
    code = _code()
    assert "const ARC_LIFE_MS = FLIGHT_PASSES_MS + HOLD_MS + FADE_MS;" in code, (
        "the motion lifetime has changed; #222 asks for it to stay as it is"
    )


def test_a_mode_switch_keeps_the_lines() -> None:
    """It used to blank the map, which is most of "feels broken".

    A mark is evidence a packet crossed the mesh. That does not stop
    being true because the reader changed how it is drawn.
    """
    code = _code()
    switch = code[code.index("setReduced(value)") :][:1200]
    assert "for (const slot of pool) slot.live = false;" not in switch, (
        "the toggle still drops every live mark"
    )
    assert "slot.born = nowAt;" in switch, "remaining life is not rescaled"


def test_the_rescale_leaves_traceroute_hops_alone() -> None:
    """They keep their own timing, which this issue does not change.

    And the constant naming them must be a real one: an undefined name
    reads as `undefined`, compares unequal, and would silently rescale
    the hops too.
    """
    code = _code()
    switch = code[code.index("setReduced(value)") :][:1200]
    assert "slot.kind === KIND_HOP" in switch
    assert "const KIND_HOP = 3;" in code, "KIND_HOP is not a declared constant"
    assert "KIND_TRACE" not in code, "a name that does not exist is being compared"


def test_arcs_thin_before_the_cap_refuses_packets() -> None:
    """The load risk the issue flagged, which the old ladder could not see.

    A mark held 33 s instead of 8 s is alive about four times as long, so
    the pool fills at roughly a quarter of the rate it used to. Neither
    the rate ladder nor the frame governor notices: refused packets are
    cheap to draw, so frames stay fast while the map quietly shows less.
    """
    code = _code()
    assert "function rungForMarks(" in code
    assert "rungForMarks(liveCount)" in code, "mark pressure is computed but never used"
    # It must be one of the inputs to the rung, not a replacement for the
    # others -- the rate ladder and the governor still matter.
    line = next(ln for ln in code.splitlines() if "rung = Math.max(" in ln)
    assert "rungForRate(stats.perSecond)" in line
    assert "governorRung" in line
    assert "rungForMarks(liveCount)" in line


def test_the_thinning_is_reported_not_quiet() -> None:
    """The caps comment sets the condition: thinning must not be silent.

    The rung is named in the status line, which is why adding pressure to
    it is allowed where a hidden filter would not be.
    """
    code = _code()
    assert "rung: () => rung," in code, (
        "the rung is no longer exposed, so pressure-driven thinning would be silent"
    )
