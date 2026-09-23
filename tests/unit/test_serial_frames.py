"""Meshtastic's serial framing, decoded from a stream (#116).

`#116` asks for a "Connect a node by USB" button, and says in as many
words: *unit-test the frame decoder — split frames, log text mixed in,
a bad length.* That is the half of the issue that needs no hardware,
and it is the half where the bugs are. The Web Serial plumbing around
it is a dozen lines that can only be written against a real board.

The firmware wraps every protobuf as

    0x94 0xC3 <len-hi> <len-lo> <payload>

and prints its debug log down the **same** port, between frames and in
arbitrarily sized pieces. So a reader cannot assume one `read()` is one
frame, that a frame arrives whole, or that what sits between two frames
is nothing.

**This is not a port of upstream's `readSerialConfig()`.** That writes
`"\\r\\n"` and hopes for YAML text back, which is not how the firmware
talks — see #115. The issue says not to port it and this does not.

The cases run under node rather than being read out of the source,
because every bug a stream decoder can have is a bug about what happens
*across two reads*. A test that greps for `0x94` would pass against a
decoder that drops every frame split down the middle.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "unit" / "js" / "serial_frames_cases.mjs"
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "serial-frames.js"


def test_the_cases_and_the_module_are_both_there() -> None:
    """The control.

    If either file moved, the run below would fail for a reason that
    has nothing to do with the decoder, and the message would be
    node's rather than ours.
    """
    assert MODULE.exists(), f"{MODULE} is missing"
    assert CASES.exists(), f"{CASES} is missing"


def test_the_decoder_handles_a_real_stream() -> None:
    """Twenty-odd cases, including a frame split at every byte.

    `node` is required rather than optional. This repo already needs it
    — `tools/dev/e2e.js`, `tools/dev/serve_local.js` — and GitHub's own
    runner cannot execute `actions/checkout` without it. Skipping here
    would look exactly like passing, which is the failure mode this
    suite has been bitten by before.
    """
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so the serial frame decoder went unchecked. "
        "It is not optional: this repo already requires node for the e2e "
        "suite and the dev server, and a skip here is indistinguishable "
        "from a pass."
    )
    done = subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_broken_decoder_would_be_caught() -> None:
    """The negative control, run in the same tick as the positive one.

    Without this, a cases file that silently stopped asserting — an
    import that resolved to nothing, a helper that always reported
    PASS — would keep this green for ever. So the module is mutated in
    a temporary copy and the same cases are run against it.

    The mutation is the most tempting wrong implementation: return the
    payload without waiting for all of it.
    """
    node = shutil.which("node")
    assert node, "node is not on PATH"
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "      if (end > this.buffer.length) {",
        "      if (false) {",
    )
    assert broken != source, (
        "the incomplete-frame guard is no longer where this test mutates "
        "it, so this control is checking nothing"
    )
    with _temporarily(MODULE, broken):
        done = subprocess.run(
            [node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
        )
    assert done.returncode != 0, (
        "the cases pass against a decoder that hands back frames before "
        "they have all arrived, so they are not testing the thing they "
        "are named for"
    )


class _temporarily:
    """Swap a file's contents for the length of a block, then restore."""

    def __init__(self, path: Path, content: str) -> None:
        self.path = path
        self.content = content
        self.original = path.read_text(encoding="utf-8")

    def __enter__(self) -> None:
        self.path.write_text(self.content, encoding="utf-8")

    def __exit__(self, *exc: object) -> None:
        self.path.write_text(self.original, encoding="utf-8")


def test_the_module_does_not_reach_for_the_network_or_the_dom() -> None:
    """It is a pure function over bytes, and should stay one.

    That is what lets it be tested under node at all, and what keeps
    the "nothing leaves your device" promise in #116 easy to verify:
    a decoder that cannot fetch cannot leak a channel key.
    """
    source = MODULE.read_text(encoding="utf-8")
    for banned in ("fetch(", "XMLHttpRequest", "document.", "window.", "navigator."):
        assert banned not in source, (
            f"the frame decoder reaches for {banned!r}; it is meant to be a "
            f"pure function over bytes so it can be tested off-device and "
            f"cannot leak what it decodes"
        )


@pytest.mark.parametrize("promise", ["0x94", "0xc3", "512"])
def test_the_constants_are_the_protocol_ones(promise: str) -> None:
    source = MODULE.read_text(encoding="utf-8").lower()
    assert promise in source, f"{promise} is no longer in the module"
