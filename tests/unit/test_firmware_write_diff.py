"""The detector that would have caught #201, held to catching it.

`tools/firmware-write-check/` drives the shipped write path against
real firmware and then compares a whole `--export-config` dump before
and after. It exists because of a specific failure: the original
meshtasticd test re-read the field it changed and the fields it
protected, so every field it inspected was one somebody was already
thinking about. The write was zeroing all the others, and the test
passed.

These cases need no Docker and no radio. They check the *detector*,
not the firmware -- if the comparison ever stops noticing a lost
field, the expensive hardware test stops meaning anything, quietly.
"""

import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "firmware-write-check" / "diff_config.py"

BEFORE = {
    "channel_url": "https://example.invalid/e/#AAAA",
    "config": {
        "lora": {
            "hopLimit": 3,
            "txEnabled": True,
            "txPower": 30,
            "usePreset": True,
        },
        "security": {"adminKey": "KEY", "serialEnabled": True},
    },
}


def _write(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(
        "# start of Meshtastic configure yaml\n" + yaml.safe_dump(data), encoding="utf-8"
    )
    return path


def _run(before: Path, after: Path, expected: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(before), str(after), expected],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_is_there() -> None:
    assert SCRIPT.exists()


def test_one_intended_change_passes(tmp_path: Path) -> None:
    """The shape of a correct write: the ticked field moved, nothing else."""
    lora = {**BEFORE["config"]["lora"], "hopLimit": 5}
    after = {**BEFORE, "config": {**BEFORE["config"], "lora": lora}}
    done = _run(
        _write(tmp_path, "b.yaml", BEFORE),
        _write(tmp_path, "a.yaml", after),
        "config.lora.hopLimit",
    )
    assert done.returncode == 0, done.stdout
    assert "PASS" in done.stdout


def test_a_lost_field_fails(tmp_path: Path) -> None:
    """The #201 bug itself. `txEnabled` vanishing is a stopped radio.

    This is the case the original test could not see, so it is the
    reason this file exists.
    """
    after = {**BEFORE, "config": {**BEFORE["config"], "lora": {"hopLimit": 5}}}
    done = _run(
        _write(tmp_path, "b.yaml", BEFORE),
        _write(tmp_path, "a.yaml", after),
        "config.lora.hopLimit",
    )
    assert done.returncode == 1
    assert "fields LOST" in done.stdout
    assert "config.lora.txEnabled" in done.stdout, (
        "the lost field that stops the radio was not named"
    )


def test_an_unrequested_change_fails(tmp_path: Path) -> None:
    """A field that changed without being ticked is not a pass either.

    Separate from a lost field: nothing vanished here, a setting the
    reader never chose simply moved. Silently tolerating it is how a
    write that does more than it showed gets called correct.
    """
    lora = {**BEFORE["config"]["lora"], "hopLimit": 5, "txPower": 14}
    after = {**BEFORE, "config": {**BEFORE["config"], "lora": lora}}
    done = _run(
        _write(tmp_path, "b.yaml", BEFORE),
        _write(tmp_path, "a.yaml", after),
        "config.lora.hopLimit",
    )
    assert done.returncode == 1
    assert "config.lora.txPower" in done.stdout


def test_a_protected_key_being_emptied_is_caught(tmp_path: Path) -> None:
    """The lockout case, named explicitly.

    #117 forbids writing keys. If a security write ever empties
    `adminKey`, that is the reader losing administrative access to
    their own node, and it must not read as an ordinary diff.
    """
    after = {**BEFORE, "config": {**BEFORE["config"], "security": {"serialEnabled": True}}}
    done = _run(
        _write(tmp_path, "b.yaml", BEFORE),
        _write(tmp_path, "a.yaml", after),
        "config.lora.hopLimit",
    )
    assert done.returncode == 1
    assert "config.security.adminKey" in done.stdout
