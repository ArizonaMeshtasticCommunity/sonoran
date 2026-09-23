"""The browser's half of the #157 label fix, run rather than read.

`labels.js` turns `TELEMETRY_APP` into "Telemetry" for every page. The
three new names for what a `portnum` of 0 turns out to be go through
the same door, and they must go through *one* of its two tables and not
the other:

* `PORTNUM_LABELS` is also read **backwards** by `portnumWire`, so the
  firehose filter can turn "Position" into `POSITION_APP` for an API
  that takes a number or an exact protobuf name.
* `UNREADABLE_PKI` is not a port number. The API answers 422 for it.

Putting the new names in the port table would therefore offer the
filter three phrases that cannot work -- a bug nobody would find until
somebody typed one. Source text cannot tell you which map a lookup
found, so these cases run the shipped file under node.
"""

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "labels.js"
CASES = ROOT / "tests" / "unit" / "js" / "labels_cases.mjs"


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
        "node is not on PATH, so the browser labels went unchecked. It is "
        "not optional: this repo already requires node for the e2e suite "
        "and the dev server, and a skip here looks exactly like a pass."
    )
    return node


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
    )


def test_the_cases_and_the_module_are_both_there() -> None:
    """The control, so a missing file fails as itself."""
    assert MODULE.exists(), f"{MODULE} is missing"
    assert CASES.exists(), f"{CASES} is missing"


def test_the_browser_names_the_three_unreadable_buckets() -> None:
    """The positive arm: the labels resolve and nothing else moved."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_label_that_did_not_resolve_would_be_caught() -> None:
    """Negative control: stop `portnumLabel` reading the new table.

    Without this, a cases file that had quietly stopped asserting would
    keep the test above green for ever.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace("return TRAFFIC_LABELS.get(key)\n      ||", "return")
    assert broken != source, (
        "the lookup this control mutates has moved, so it is checking "
        "nothing. A mutation that does not apply is indistinguishable "
        "from one the cases survive."
    )
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with the traffic-label table unreachable, so they "
        "are not testing the names they are named for"
    )


def test_putting_the_new_names_in_the_port_table_would_be_caught() -> None:
    """The control that guards the real risk.

    This is the mistake a future change is most likely to make: the new
    names look like port names, `PORTNUM_LABELS` is where port names
    live, and moving them there works perfectly until somebody types
    "Direct message, encrypted" into the firehose filter and the API
    answers 422.

    So the mutation is not a broken lookup -- it is the plausible,
    tidy-looking refactor.
    """
    source = MODULE.read_text(encoding="utf-8")
    anchor = "  const WIRE_BY_LABEL = new Map();"
    assert anchor in source, "the reverse index has moved; this control is checking nothing"
    broken = source.replace(
        anchor,
        "  for (const [k, v] of TRAFFIC_LABELS) PORTNUM_LABELS.set(k, v);\n" + anchor,
        1,
    )
    assert broken != source
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with the unreadable names in the port table, so "
        "the firehose filter could offer a value the API refuses and "
        "nothing here would notice"
    )
