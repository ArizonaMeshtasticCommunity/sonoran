"""Draft a node catalogue from Meshtastic's own hardware resource (#110).

The web flasher builds its device list from a public resource:

    https://api.meshtastic.org/resource/deviceHardware

117 entries as of 2026-09-23, each giving `hwModel`, `hwModelSlug`,
`platformioTarget`, `architecture`, `supportLevel`, `displayName` and
`tags`. **It carries no RF data at all** -- no chip, no transmit power,
no stock antenna, no connector -- which is exactly what #110 predicted
and is the reason this is a draft rather than a catalogue.

What this script does is the half that can be done honestly: fetch the
real list and join it against `radio/hardware.py`'s profile table, so
the gap between "boards a newcomer can flash" and "boards we can
predict for" is a number somebody can look at rather than a guess.

It writes a draft for a person to review. It is NOT run at page load,
and nothing it writes is trusted until the RF figures in it have been
read off a datasheet and sourced, one board at a time.

    uv run python tools/dev/board_catalogue.py            # report the gap
    uv run python tools/dev/board_catalogue.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sonoran.radio.hardware import _PROFILES, hardware_profile

SOURCE = "https://api.meshtastic.org/resource/deviceHardware"

# supportLevel in the resource. 1 is the largest group and 3 appears on
# the boards the project promotes; the resource does not document the
# scale, so it is carried through rather than interpreted.
SUPPORT_LEVELS = {1: "1", 2: "2", 3: "3", None: "unset"}


def fetch(url: str = SOURCE) -> list[dict[str, Any]]:
    """Read the resource the flasher reads.

    The User-Agent is not optional: the endpoint answers urllib's
    default with 403 while serving curl the same request happily. A
    request that says who it is gets an answer.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sonoran-board-catalogue/1.0 (+https://github.com/ArizonaMeshtasticCommunity/sonoran)"
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def draft(boards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per board, saying what we know and what we do not."""
    rows = []
    for board in boards:
        slug = board.get("hwModelSlug") or ""
        profile = hardware_profile(slug)
        known = slug in _PROFILES
        rows.append(
            {
                "slug": slug,
                "name": board.get("displayName"),
                "architecture": board.get("architecture"),
                "support_level": SUPPORT_LEVELS.get(board.get("supportLevel"), "unset"),
                "tags": board.get("tags") or [],
                # From radio/hardware.py, not from the resource.
                "profile_is_exact": known,
                # `inferred` is the difference between a family rule's
                # guess and UNKNOWN_PROFILE, which is nothing at all.
                "profile_is_inferred": bool(profile.inferred) and not known,
                # The figures are carried for EVERY board, inferred ones
                # included. A picker that showed nothing for two thirds
                # of the catalogue would be less useful and no more
                # honest than one that shows the family rule's answer
                # and says it is a family rule's answer. The flag above
                # is what makes that distinction available to say.
                "chipset": profile.chipset,
                "assumed_tx_power_dbm": profile.assumed_tx_power_dbm,
                "assumed_antenna_gain_dbi": profile.assumed_antenna_gain_dbi,
                "fixed_antenna": profile.fixed_antenna,
                # Everything #110 asks for that the resource cannot give.
                "pa_present": None,
                "max_tx_power_dbm": None,
                "connector": None,
                "stock_antenna_key": None,
                "form_factor": None,
                "source": None,
                "checked": None,
            }
        )
    return sorted(rows, key=lambda row: (not row["profile_is_exact"], row["slug"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the draft to this path")
    parser.add_argument("--url", default=SOURCE)
    args = parser.parse_args()

    try:
        boards = fetch(args.url)
    except Exception as error:
        # Not reaching the resource is not evidence about the catalogue.
        print(f"could not read {args.url}: {error}", file=sys.stderr)
        return 2

    rows = draft(boards)
    covered = [row for row in rows if row["profile_is_exact"]]
    inferred = [row for row in rows if row["profile_is_inferred"]]
    nothing = [
        row for row in rows if not row["profile_is_exact"] and not row["profile_is_inferred"]
    ]

    print(f"{len(rows)} boards offered by the flasher.")
    print(f"  {len(covered):>3} have an exact RF profile in radio/hardware.py")
    print(f"  {len(inferred):>3} are guessed by a family rule (chipset right, details assumed)")
    print(f"  {len(nothing):>3} fall through to UNKNOWN_PROFILE, which knows nothing\n")
    missing = inferred + nothing

    by_level = Counter(row["support_level"] for row in missing)
    print("uncovered boards by support level:", dict(sorted(by_level.items())))
    print("\nuncovered, most-supported first:")
    for row in sorted(missing, key=lambda r: r["support_level"], reverse=True)[:25]:
        print(f"  [{row['support_level']}] {row['slug']:<28} {row['name']}")

    if args.json:
        args.json.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"\ndraft written to {args.json}")
        print("Nothing in it is sourced yet. Every RF figure is null on purpose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
