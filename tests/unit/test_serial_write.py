"""Writing settings to a node over USB (#117).

This changes somebody's radio, so the cases that matter most are the
ones about what it **refuses** to write.

#117: *"Never change keys or security settings unless the reader asks:
channel PSKs, admin keys, private key, `is_managed`, and serial /
Bluetooth enable. A mistake there can lock someone out of their own
node."*

That is held as a **deny list the plan is filtered through**, in two
places — when the preview is built and again when the write happens.
Twice on purpose: "the preview already filtered it" is one refactor
away from being untrue, and the cost of being wrong is somebody losing
administrative access to their own hardware.

The admin sequence is `begin_edit_settings`, one `set_config` or
`set_module_config` **per section**, then a single
`commit_edit_settings`. Per section rather than per field because the
API sets a whole section at a time — two messages for two fields of one
section would make the second overwrite the first with stale values.

**Still needs a board.** #117's "Done when" is a read → preview → apply
→ reboot → read-again cycle on real hardware, and a simulator cannot
produce that. What it can prove is the sequence and, more importantly,
the refusals.
"""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "unit" / "js" / "serial_write_cases.mjs"
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "serial-write.js"


def test_the_module_and_cases_are_both_there() -> None:
    assert MODULE.exists() and CASES.exists()


def test_the_write_path_behaves(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node, "node is not on PATH; a skip here is indistinguishable from a pass"
    done = subprocess.run(
        [node, str(CASES)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        env={**os.environ},
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    # Named, so a case quietly disappearing is not read as a pass.
    for promise in (
        "never writes a key or is_managed",
        "never writes bluetooth.enabled",
        "commits exactly once",
        "one setConfig for the section",
        "no changes means no admin traffic",
        "writes bluetooth when asked for by name",
    ):
        assert f"PASS {promise}" in done.stdout, f"the case {promise!r} did not run"


def test_the_deny_list_names_everything_the_issue_names() -> None:
    """Read off #117 rather than remembered.

    Each of these can cost somebody access to their own node, and a
    list that drifts from the issue is worse than no list because it
    reads as deliberate.
    """
    body = MODULE.read_text(encoding="utf-8")
    for field in ("adminKey", "privateKey", "isManaged", "psk"):
        assert field in body, f"{field} is no longer protected from being written"
    assert "bluetooth" in body and "serial" in body, (
        "turning off Bluetooth or serial can remove the last way into a node"
    )


def test_the_refusal_happens_at_the_write_and_not_only_in_the_preview() -> None:
    """Defence in depth, and the reason is specific.

    A preview that filters is a UI decision; the write is where the
    damage happens. If only the preview filtered, any future caller
    that builds rows another way writes a PSK.
    """
    body = MODULE.read_text(encoding="utf-8")
    start = body.index("export async function applyChanges(")
    apply_body = body[start:]
    assert "row.protected" in apply_body, (
        "applyChanges no longer filters protected rows itself, so it trusts "
        "its caller not to hand it a channel PSK"
    )


def test_it_does_not_port_the_cli_string_approach() -> None:
    """#115 and #117 both say not to. The firmware does not speak it.

    Comments are stripped first. The module's own comment quotes
    `meshtastic --set` to say what must NOT be ported, so a plain
    substring search finds the banned text inside the explanation of
    why it is banned. That is the fourth time this trap has caught a
    test in this repo, which is why the helper exists at all.
    """
    import re

    body = MODULE.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "--set" not in code, (
        "the CLI string approach is back in the CODE; the firmware does not understand it (#115)"
    )
    assert "--set" in body, (
        "the comment warning the next person off the CLI approach is gone, "
        "so this test is now the only record of it"
    )


# ------------------------------------------------------------ the UI


def _config_check() -> str:
    return (ROOT / "src" / "sonoran" / "web" / "static" / "config-check.js").read_text(
        encoding="utf-8"
    )


def test_a_protected_row_is_never_offered_as_a_tick_box() -> None:
    """A tick box implies a choice the reader should not make casually.

    Protected rows are reported in a sentence underneath instead, so
    the reader knows they exist and that they were left alone. Verified
    in a browser against a node reporting an admin key: the note reads
    "1 security setting (security.adminKey) will not be written.
    Changing these can lock you out of your own node." and the row is
    absent from the list.
    """
    body = _config_check()
    start = body.index("function drawSerialPlan(")
    plan = body[start : body.index("\n}", start)]
    assert "rows.filter((row) => !row.protected)" in plan, (
        "the preview no longer separates protected rows, so a channel PSK "
        "or an admin key can be ticked like any other setting"
    )
    assert "lock you out of your own node" in body, (
        "the sentence explaining why those settings were skipped is gone"
    )


def test_the_backup_is_written_before_the_change_not_after() -> None:
    """A backup taken after a failed write is a backup of the wreckage."""
    body = _config_check()
    start = body.index("async function applySerial(")
    apply_body = body[start : body.index("\n}\n", start)]
    backup = apply_body.index("data-serial-backup")
    confirm = apply_body.index("window.confirm")
    assert backup < confirm, (
        "the backup is offered after the confirmation, so a reader who "
        "confirms quickly can write before anything is saved"
    )


def test_the_reader_is_told_when_the_mesh_changes() -> None:
    """Region and preset move the node to a different mesh (#117).

    Verified in a browser: "This changes which mesh the node is on:
    modemPreset unset -> 4, channelNum unset -> 18 ...".
    """
    assert "changes which mesh the node is on" in _config_check()


def test_the_port_is_released_when_the_page_goes_away() -> None:
    """A port left open blocks the Meshtastic app and the CLI.

    `readConfig` closes its own port; this covers the reader
    navigating away mid-read, which that cannot.
    """
    body = _config_check()
    assert "'pagehide'" in body, "nothing releases the serial port when the reader leaves the page"
