"""The node page's Identity and Device fields (#254), run rather than read.

`js/node_fields_cases.mjs` loads the shipped `app.js` under node and
calls the functions that decide what is red: at every threshold, with
every shape of a missing value, and for altitude in all three states.

The Python side owns the controls. Each mutation below is an edit a
future contributor could plausibly make, applied to a COPY of `app.js`
(`SONORAN_APP_JS` points the cases at it), and each must fail with a
message that names the cause. A guard that nothing can break is not a
guard, and a test that fails with "exit 1" teaches nobody anything.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "app.js"
CASES = ROOT / "tests" / "unit" / "js" / "node_fields_cases.mjs"


def _node() -> str:
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so what turns red on the node page went "
        "unchecked. It is not optional: this repo already needs node for "
        "the e2e suite, and a skip here looks exactly like a pass."
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


def _mutated(tmp_path: Path, old: str, new: str) -> Path:
    source = MODULE.read_text(encoding="utf-8")
    # The control on the control: an edit that matches nothing would
    # leave the copy intact and "prove" nothing at all.
    assert source.count(old) == 1, f"the mutation no longer matches app.js: {old!r}"
    copy = tmp_path / "app.js"
    copy.write_text(source.replace(old, new), encoding="utf-8")
    return copy


def test_the_files_are_where_the_cases_expect() -> None:
    assert MODULE.exists()
    assert CASES.exists()


def test_the_behaviour_holds() -> None:
    """The positive arm. Every mutation below must turn this red."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "checks passed" in done.stdout


MUTATIONS = {
    # `Number(null)` is 0 and `null < 5` is true: without the refusal a
    # node that sent no battery level reads as a flat battery.
    "absent_is_not_bad": (
        "return typeof value === 'number' && Number.isFinite(value) ? value : null;",
        "return Number(value);",
        "ABSENT: a battery_level of null",
    ),
    # The firmware holds back AT 25 %, so `>` would call 25 % fine.
    "polite_line_is_inclusive": (
        "if (value >= CHANNEL_USE_POLITE) return { state: 'warn', word: 'Busy' };",
        "if (value > CHANNEL_USE_POLITE) return { state: 'warn', word: 'Busy' };",
        "BOUNDARY: channel_utilization 25 is warn",
    ),
    # A second copy of a firmware figure, drifting from the one it copied.
    "firmware_figure": (
        "const CHANNEL_USE_MAX = 40;",
        "const CHANNEL_USE_MAX = 45;",
        "FIRMWARE: the hard channel line is 40 %",
    ),
    # The simplification that makes "no position" red for altitude.
    "no_position_is_not_red": (
        "  const position = node.position;\n"
        "  if (!position || reading(position.lat) == null"
        " || reading(position.lon) == null) return null;",
        "  const position = node.position || {};",
        "ALTITUDE: no position at all is not red for altitude",
    ),
    # TAK roles send `altitude_hae`, which ingest does not keep.
    "tak_is_exempt": (
        "  if (ALTITUDE_NOT_OURS.has(node.role)) return null;\n",
        "",
        "ALTITUDE: TAK sends altitude_hae",
    ),
    # A word beside the colour is the WCAG 1.4.1 requirement.
    "colour_is_not_the_only_signal": (
        "      ` ${flag.word}`));",
        "      ''));",
        "WORDS: a flagged channel_utilization carries a word",
    ),
    # The Power card going back to its own comparison.
    "one_battery_band": (
        "      powerState = band;",
        "      powerState = battery > BATTERY_WEAK ? 'ok'"
        " : battery >= BATTERY_LOW ? 'warn' : 'bad';",
        "ONE BAND: the Power card holds no comparison of its own",
    ),
    "placeholders_are_capitalised": (
        "text: node.hw_model || 'Unknown' },",
        "text: node.hw_model || 'unknown' },",
        'CAPITAL: Hardware placeholder "unknown"',
    ),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_broken_guard_is_caught_and_named(tmp_path: Path, name: str) -> None:
    old, new, message = MUTATIONS[name]
    done = _run(_mutated(tmp_path, old, new))
    assert done.returncode != 0, f"{name}: the cases passed against a broken copy"
    assert message in done.stderr, (
        f"{name}: the cases failed, but not with a message naming the cause "
        f"({message!r}):\n{done.stderr}"
    )
