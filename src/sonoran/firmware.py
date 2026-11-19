"""Firmware versions: what a node reports, and the stable release (#406).

A node tells the mesh its firmware version in one place only: the
`firmware_version` field of a `MapReport` (protobufs `mqtt.proto`). A
node sends one when its owner turns on map reporting. NodeInfo carries
no version.

The stable release comes from `https://api.meshtastic.org/github/firmware/list`,
the list that flasher.meshtastic.org reads (meshtastic/web-flasher
`stores/firmwareStore.ts`). It has a `stable` and an `alpha` list.
Meshtastic gives its stable releases the title "Beta"; the list puts
them under `stable`, and the GitHub API marks them `prerelease: false`.

A version string is `MAJOR.MINOR.PATCH.HASH`, for example
`2.7.26.54e0d8d` (the release tag without its `v`). Only the three
numbers are compared. Two builds of one release are the same release.

This module does no I/O.
"""

import re
from dataclasses import dataclass
from typing import Literal

FirmwareStatus = Literal["current", "behind", "newer", "unknown"]

# The longest version string we keep. Real ones are about 14
# characters (`2.7.26.54e0d8d`); a local build adds a short suffix.
# A longer string is not a version, so it is not stored.
MAX_VERSION_LENGTH = 32

_VERSION = re.compile(r"^v?(\d{1,3})\.(\d{1,3})\.(\d{1,4})(?:\.[0-9A-Za-z._-]*)?$")
_PRINTABLE = re.compile(r"^[\x21-\x7e]+$")

RELEASE_PAGE = "https://github.com/meshtastic/firmware/releases/tag/"


@dataclass(frozen=True)
class Release:
    """One firmware release from the official list."""

    version: str
    page_url: str


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """Return (major, minor, patch), or None when the text is not a version."""
    if not text:
        return None
    match = _VERSION.match(text.strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def clean_reported_version(text: str | None) -> str | None:
    """Return the version a node reported, fit to store, or None.

    The text comes from a radio packet, so anybody can send anything.
    Only short printable text is kept. It is shown as text and compared
    by `parse_version`, so a string that is not a version shows as
    unknown and never as behind.
    """
    if not text:
        return None
    value = text.strip()
    if not value or len(value) > MAX_VERSION_LENGTH or not _PRINTABLE.match(value):
        return None
    return value


def firmware_status(reported: str | None, stable: str | None) -> FirmwareStatus:
    """Compare a node's reported version with the stable release.

    `newer` is an alpha or a build of its own. `unknown` is a node that
    sent no report, a version we cannot read, or no stable release known.
    """
    node = parse_version(reported)
    release = parse_version(stable)
    if node is None or release is None:
        return "unknown"
    if node < release:
        return "behind"
    if node > release:
        return "newer"
    return "current"


def stable_from_release_list(body: object) -> Release | None:
    """Return the newest stable release in the official list, or None.

    The list is newest first today. That is not promised, so the
    newest is chosen by version. An entry that is not a version is
    skipped. The link is always rebuilt on the meshtastic/firmware
    release page, because it is put on our page.
    """
    if not isinstance(body, dict):
        return None
    releases = body.get("releases")
    stable = releases.get("stable") if isinstance(releases, dict) else None
    if not isinstance(stable, list):
        return None
    best: tuple[tuple[int, int, int], str] | None = None
    for entry in stable:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        tag = entry["id"].strip()
        version = tag.removeprefix("v")
        parsed = parse_version(version)
        if parsed is None or clean_reported_version(version) is None:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, version)
    if best is None:
        return None
    return Release(version=best[1], page_url=RELEASE_PAGE + "v" + best[1])
