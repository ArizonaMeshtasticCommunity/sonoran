"""Ground speed and ground track are shown in the units the firmware sends.

Report (Discord, 2026-10-25): packet !a6960bfc/2507943990 has a raw
ground speed of 127. That is km/h (79 mph); the site printed 284 mph,
which is 127 m/s. Its ground track, 30975000, was printed as
"30975000 deg"; the firmware sends degrees * 10^-5, so it is 309.75.

Sources: meshtastic/protobufs mesh.proto (Position.ground_speed "Ground
speed in km/h"); meshtastic/firmware src/gps/GPS.cpp (`ground_speed =
reader.speed.kmph()`, `ground_track = course * 1e3`, "degrees * 10^-5").

`js/position_units_cases.mjs` runs the shipped `app.js` and `units.js`
under node. Each mutation below is a plausible wrong version, applied to
a COPY of `app.js`, and each must turn the cases red.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "app.js"
CASES = ROOT / "tests" / "unit" / "js" / "position_units_cases.mjs"


def _node() -> str:
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so the position units went unchecked; a skip looks like a pass."
    )
    return node


def _run(module: Path = MODULE) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(CASES)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        env={**os.environ, "SONORAN_APP_JS": str(module)},
    )


def _mutated(tmp_path: Path, edits: list[tuple[str, str]]) -> Path:
    source = MODULE.read_text(encoding="utf-8")
    for old, new in edits:
        # An edit that matches nothing would leave the copy intact and prove nothing.
        assert source.count(old) == 1, f"the mutation no longer matches app.js: {old!r}"
        source = source.replace(old, new)
    copy = tmp_path / "app.js"
    copy.write_text(source, encoding="utf-8")
    return copy


def test_the_behaviour_holds() -> None:
    """The positive arm. Every mutation below must turn this red."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "checks passed" in done.stdout


MUTATIONS: dict[str, tuple[list[tuple[str, str]], str]] = {
    # The bug as reported: the packet page reads km/h as m/s.
    "packet_page_reads_ms": (
        [
            (
                "ground_speed: ['Ground speed', (v) => SonoranUnits.speedFromKmh(v)],",
                "ground_speed: ['Ground speed', (v) => SonoranUnits.speedFromMs(v)],",
            )
        ],
        "FAIL KMH: the packet page",
    ),
    # Fixing one page and missing the other.
    "node_page_reads_ms": (
        [
            (
                "['Ground speed', SonoranUnits.speedFromKmh(row.ground_speed)]",
                "['Ground speed', SonoranUnits.speedFromMs(row.ground_speed)]",
            )
        ],
        "FAIL KMH: the node page",
    ),
    # Reading the proto comment's old "1/100 degrees" instead of the firmware.
    "track_in_hundredths": (
        [("GROUND_TRACK_PER_DEGREE = 1e5;", "GROUND_TRACK_PER_DEGREE = 100;")],
        "FAIL TRACK: 30975000 is 309.75 degrees",
    ),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_broken_version_fails(tmp_path: Path, name: str) -> None:
    edits, expected = MUTATIONS[name]
    done = _run(_mutated(tmp_path, edits))
    assert done.returncode != 0, f"{name}: the cases passed against a broken app.js"
    assert expected in done.stderr, f"{name}: failed, but not for the named reason:\n{done.stderr}"
