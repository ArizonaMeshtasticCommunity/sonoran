"""The serial exchange, driven against a simulated node (#116).

A real board is still needed for the hand-test this issue asks for.
Timing, buffering and driver quirks are exactly what a simulator cannot
reproduce, and that half stays open.

What a simulator **can** prove is that the conversation is right: the
right request goes out framed, the reply is reassembled from arbitrary
chunk boundaries, firmware log text on the same port is ignored,
another session's completion id does not end ours, a silent node times
out, and **the port is closed on every path out**.

That last one is why this exists rather than being left for the board.
A port left open blocks the Meshtastic app and the CLI, and the reader
has no way to know why.

**A real bug came out of it.** The first version checked the deadline
between reads. That looks equivalent to racing the read and is not: a
node that goes quiet never resolves `read()` at all, so the loop blocks
and the deadline is never reached. The page hung with no error — the
opposite of the timeout the issue asks for. It is now a race, and the
silent-node case is what found it.

Frames are built from bytes the **Python** protobuf modules encoded and
decoded by the generated descriptor through protobuf.js, so the two
sides are checked against each other rather than one side twice.
"""

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "unit" / "js" / "serial_read_cases.mjs"
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "serial-read.js"


def _vectors(tmp_path: Path) -> Path:
    from sonoran.meshtastic import mesh_pb2

    from_radio = mesh_pb2.FromRadio()  # type: ignore[attr-defined]
    from_radio.id = 42
    from_radio.my_info.my_node_num = 0xA038F6BC
    complete = mesh_pb2.FromRadio()  # type: ignore[attr-defined]
    complete.config_complete_id = 12345

    path = tmp_path / "serial-vectors.json"
    path.write_text(
        json.dumps(
            {
                "my_info": base64.b64encode(from_radio.SerializeToString()).decode(),
                "complete": base64.b64encode(complete.SerializeToString()).decode(),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_module_and_cases_are_both_there() -> None:
    """The control, so a missing file fails as itself."""
    assert MODULE.exists() and CASES.exists()


def test_the_exchange_works_against_a_simulated_node(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so the serial exchange went unchecked. A skip "
        "here is indistinguishable from a pass."
    )
    done = subprocess.run(
        [node, str(CASES)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        env={**os.environ, "SONORAN_SERIAL_VECTORS": str(_vectors(tmp_path))},
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    # Named rather than counted, so a case quietly disappearing is not
    # mistaken for a pass.
    for promise in (
        "closes the port after a timeout",
        "closes the port after a hang-up",
        "reassembles across single-byte reads",
        "ignores log text on the same port",
        "real FromRadio bytes carry my_info",
    ):
        assert f"PASS {promise}" in done.stdout, f"the case {promise!r} did not run"


def test_nothing_leaves_the_browser() -> None:
    """#116's promise, and the reason it matters here.

    What comes back over USB holds the channel PSKs, the MQTT password
    and the admin keys. A `fetch` in this file would be the one place
    they could go.
    """
    body = MODULE.read_text(encoding="utf-8")
    for banned in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "navigator.send"):
        assert banned not in body, (
            f"the serial reader reaches for {banned!r}; what it reads contains "
            f"channel keys and the MQTT password"
        )


def test_the_read_is_raced_against_the_deadline() -> None:
    """The bug the simulator found, held so it cannot come back.

    Checking the clock between reads leaves a quiet node hanging the
    page for ever, because `read()` never resolves.
    """
    body = MODULE.read_text(encoding="utf-8")
    assert "Promise.race([" in body, (
        "the read is no longer raced against the deadline, so a node that "
        "goes silent hangs the page with no error"
    )


def test_every_path_closes_the_port() -> None:
    body = MODULE.read_text(encoding="utf-8")
    start = body.index("export async function readConfig(")
    assert "finally {" in body[start:], (
        "readConfig no longer closes the port in a finally block; a failed "
        "read leaves it held and blocks the Meshtastic app"
    )
