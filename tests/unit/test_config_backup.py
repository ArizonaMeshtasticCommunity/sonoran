"""The backup offered before a USB write must be able to restore (#117).

The page shows "Download a backup of the current config first", ticked
by default, immediately above a control that writes to somebody's
radio. The file it produced could not restore anything.

Found on real hardware, not here. `ConfigFixer.exportFixed` writes a
DeviceProfile-shaped document with top-level `device:`, `lora:` and
`module:`. `meshtastic --configure` reads **`config:`,
`module_config:`, `owner` and `channel_url`** and ignores the rest, so
the file downloaded cleanly, parsed as YAML, and restored nothing. It
also dropped the channels, keys, bandwidth, spreadFactor and txPower,
wrote literal `undefined`, and its header named `--import-config`,
which is not a CLI flag.

**A backup that silently restores nothing is worse than no backup**:
the tick box is what makes the write feel safe enough to do.

The cases run under node because the thing under test is a file format
-- whether these bytes are bytes the CLI consumes. Every source-level
check the old code had, it passed.
"""

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "config-backup.js"
CHECK = ROOT / "src" / "sonoran" / "web" / "static" / "config-check.js"
CASES = ROOT / "tests" / "unit" / "js" / "config_backup_cases.mjs"


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
        "node is not on PATH, so the backup format went unchecked. A skip "
        "here looks exactly like a pass, and this file is what somebody "
        "restores from after a write goes wrong."
    )
    return node


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
    )


def test_the_files_are_there() -> None:
    """The control, so a moved file fails as itself."""
    assert MODULE.exists()
    assert CASES.exists()


def test_the_backup_is_restorable() -> None:
    """The positive arm: the bytes are what the CLI reads."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_deviceprofile_shaped_file_would_be_caught() -> None:
    """The control for the actual bug.

    The mutation is the old behaviour: emit `device:` at the top level
    instead of `config:`. That is a file which downloads, parses, and
    restores nothing.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "if (body.length) lines.push('config:', ...body);",
        "if (body.length) lines.push('device:', ...body);",
    )
    assert broken != source, (
        "the top-level key is no longer written where this control mutates "
        "it, so the control is checking nothing"
    )
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with a top-level key the CLI ignores, so nothing "
        "here protects against a backup that restores nothing"
    )


def test_a_refusal_that_became_a_shrug_would_be_caught() -> None:
    """Refusing must stay a refusal.

    If an unreadable node produced an empty file instead of an error,
    the person would get a download and believe they were covered.
    """
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "    throw new Error(\n"
        "      'The node\\'s settings were not read, so a backup would be empty. "
        "Read the node again.',\n"
        "    );",
        "    return { data: '', filename: 'empty.yaml', mimeType: 'text/yaml' };",
    )
    if broken == source:  # formatting drift; fall back to the message
        broken = source.replace("so a backup would be empty", "so here is an empty one")
    assert broken != source, "the refusal is not where this control mutates it"
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "an unreadable node no longer refuses"


def test_the_write_path_uses_the_new_backup() -> None:
    """The old exporter must not still be the one wired up.

    A correct module nothing calls is the same bug with extra files.
    """
    check = CHECK.read_text(encoding="utf-8")
    assert "ConfigBackup.buildBackup(state.config)" in check
    assert "ConfigFixer.exportFixed(state.config, 'node-backup'" not in check, (
        "the USB write still writes the DeviceProfile backup"
    )


def test_a_failed_backup_stops_the_write() -> None:
    """The tick box is what makes the write feel safe.

    If the backup cannot be written, proceeding as though it had been
    is the dishonest half of the original bug.
    """
    check = CHECK.read_text(encoding="utf-8")
    block = check[check.index("if ($('[data-serial-backup]', page).checked) {") :][:1400]
    assert "return;" in block, "a backup that could not be written no longer stops the write"


def test_the_confirm_names_the_node_not_its_number() -> None:
    """`myNodeNum` is a decimal integer nobody recognises.

    The confirm dialog is the last thing a person reads before their
    radio reboots.
    """
    check = CHECK.read_text(encoding="utf-8")
    assert "info.longName || info.shortName" in check


def test_the_write_reuses_the_granted_port() -> None:
    """The picker opened twice for a device already chosen.

    `getPorts()` returns what this origin was already granted, so the
    common path needs no prompt. The prompt stays as the fallback.
    """
    check = CHECK.read_text(encoding="utf-8")
    assert "navigator.serial.getPorts" in check
    assert "await navigator.serial.requestPort()" in check, (
        "the fallback prompt is gone, so a first-time write cannot pick a port"
    )


def test_the_firmware_version_reaches_the_checker() -> None:
    """A USB read holds it and the page said "not found".

    `parser.js` looks at the top level and at `myNodeInfo`; the read
    puts it in `metadata`, so the "is it current" check had nothing to
    compare and said so.
    """
    check = CHECK.read_text(encoding="utf-8")
    assert "config.metadata.firmwareVersion" in check
    assert "config.firmwareVersion = config.metadata.firmwareVersion" in check
