#!/usr/bin/env python3
"""Compare two `meshtastic --export-config` dumps, every field.

The point of this script is that it is not selective. The #201 bug --
a write that zeroed every setting it did not change -- survived a
meshtasticd test because that test re-read the field that was changed
and the fields that were explicitly protected. Every field it looked
at was a field somebody was already thinking about.

So this compares the flattened union of both dumps and reports
everything that moved, including fields that appeared or vanished. A
field that disappears is the signature of the bug: the firmware
replaces a config section with what it is sent, so a section sent
without one of its fields comes back with that field at zero.
"""

import sys

import yaml


def load(path: str) -> dict:
    """Read an export, ignoring the CLI's warnings on stderr-in-stdout."""
    with open(path, encoding="utf-8") as handle:
        keep = [
            line
            for line in handle
            if "NotOpenSSLWarning" not in line and "warnings.warn" not in line
        ]
    return yaml.safe_load("".join(keep)) or {}


def flatten(value: dict, prefix: str = "") -> dict:
    out: dict = {}
    for key, item in (value or {}).items():
        if isinstance(item, dict):
            out.update(flatten(item, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = item
    return out


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: diff_config.py BEFORE.yaml AFTER.yaml expected.field[,field...]")
        return 2
    before, after = flatten(load(sys.argv[1])), flatten(load(sys.argv[2]))
    expected = {f for f in sys.argv[3].split(",") if f}

    keys = set(before) | set(after)
    changed = {k for k in keys if before.get(k) != after.get(k)}
    for key in sorted(changed):
        print(f"  {key}: {before.get(key, '<absent>')!r} -> {after.get(key, '<absent>')!r}")
    print(f"\nfields compared: {len(keys)}   changed: {len(changed)}")

    # A field present before and gone after is the zeroing bug, and is
    # reported separately because it is the one that stops a radio.
    vanished = sorted(k for k in before if k not in after)
    if vanished:
        print(f"\nFAIL: fields LOST, which is the #201 zeroing shape: {vanished}")
        return 1

    unexpected = sorted(changed - expected)
    if unexpected:
        print(f"\nfields that changed and were not asked for: {unexpected}")
        print("Each needs an explanation before this is called a pass.")
        return 1
    print(f"\nPASS: only {sorted(expected)} changed, and nothing was lost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
