"""The serial client API has a schema to decode with (#116).

The vendored config checker ships `meshtastic-proto.js`, and its own
header calls it "minimal, for DeviceProfile". Measured with a parse
that first proved it could find the 41 messages that ARE there:

    Config, ModuleConfig, DeviceProfile     present
    ToRadio, FromRadio, MeshPacket, Data    ABSENT

So #116's "the protobuf schema is already loaded" holds for the
file-upload path and **not** for the serial one. Step 2 of its plan —
send a `ToRadio { want_config_id }`, read `FromRadio` until
`config_complete_id` matches — could not be written against what was
vendored, board or no board.

That file is upstream's, pinned and watched by `vendor-pin.yml`, so
extending it locally would be invisible to that check and lost on the
next bump. `tools/generate_serial_descriptor.py` writes a separate file
of ours instead, generated from the same Python protobuf modules the
ingest decodes with — one schema, two consumers, no hand-maintained
second copy to drift.

**The generator resolves dependencies by walking fields**, which is not
gold-plating: the first version used a hand-written module list,
included `AdminMessage` and omitted `DeviceConnectionStatus`, and
protobuf.js rejected the whole descriptor with "no such Type or Enum".
Loudly, which was the one good thing about it.
"""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "unit" / "js" / "serial_descriptor_cases.mjs"
DESCRIPTOR = ROOT / "src" / "sonoran" / "web" / "static" / "meshtastic-serial-proto.js"


def _vectors(tmp_path: Path) -> Path:
    """Real bytes, encoded by the Python side, for the JS side to read."""
    import base64

    from sonoran.meshtastic import mesh_pb2

    from_radio = mesh_pb2.FromRadio()  # type: ignore[attr-defined]
    from_radio.id = 42
    from_radio.my_info.my_node_num = 0xA038F6BC

    complete = mesh_pb2.FromRadio()  # type: ignore[attr-defined]
    complete.config_complete_id = 12345

    to_radio = mesh_pb2.ToRadio()  # type: ignore[attr-defined]
    to_radio.want_config_id = 12345

    path = tmp_path / "vectors.txt"
    path.write_text(
        "\n".join(
            f"{name}: {base64.b64encode(message.SerializeToString()).decode()}"
            for name, message in (
                ("my_info", from_radio),
                ("complete", complete),
                ("toradio", to_radio),
            )
        ),
        encoding="utf-8",
    )
    return path


def test_the_generated_descriptor_is_committed() -> None:
    """The control. Without it the run below fails for the wrong reason."""
    assert DESCRIPTOR.exists(), (
        "the generated descriptor is missing; run "
        "`uv run python tools/generate_serial_descriptor.py`"
    )
    assert "window.MeshtasticSerialProto" in DESCRIPTOR.read_text(encoding="utf-8")


def test_it_does_not_reach_for_new_function() -> None:
    """The constraint that shaped the existing generator.

    This dashboard's `script-src` carries no `unsafe-eval`, which is
    what stops a config somebody hands us from becoming running code.
    `Root.fromJSON` builds decoders reflectively; a descriptor that
    compiled strings would be refused by the page.
    """
    body = DESCRIPTOR.read_text(encoding="utf-8")
    for banned in ("new Function", "eval("):
        assert banned not in body, f"the descriptor contains {banned!r}"


def test_protobufjs_decodes_what_python_encoded(tmp_path: Path) -> None:
    """The real question, and the negative control travels with it.

    The cases file also asserts the VENDORED descriptor cannot find
    `ToRadio`. Without that, a run where protobuf.js silently fell back
    to the old descriptor would look exactly like a pass.
    """
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so the descriptor went unchecked. It is not "
        "optional: this repo already needs node for e2e and the dev server, "
        "and a skip here is indistinguishable from a pass."
    )
    done = subprocess.run(
        [node, str(CASES)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        env={**os.environ, "SONORAN_VECTORS": str(_vectors(tmp_path))},
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert "byte-identical re-encode: true" in done.stdout
    assert "vendored descriptor has ToRadio: false" in done.stdout


def test_the_roots_the_serial_exchange_needs_are_present() -> None:
    body = DESCRIPTOR.read_text(encoding="utf-8")
    for name in ("ToRadio", "FromRadio", "MeshPacket", "Data", "AdminMessage"):
        assert f'"{name}"' in body, (
            f"{name} is missing from the generated descriptor, so the serial "
            f"exchange cannot be built against it"
        )
