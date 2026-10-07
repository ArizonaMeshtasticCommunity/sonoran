"""Compare what the live API answers before and after a deploy.

The tests run on a fresh database. A deploy runs on months of data, and
a migration that is correct on an empty table can still hide what is
already stored. On 2026-10-07 revision 0020 put every stored spectrum
minute under the source `-`, while new minutes arrived under `pi5`: the
waterfall opened on a range one minute long, every test passed, and
`/health` said ok. This catches that kind of change by reading the API
the way the page does, before and after::

    python tools/deploy_check.py snapshot http://127.0.0.1:8000 > before.json
    # ... deploy ...
    python tools/deploy_check.py compare before.json http://127.0.0.1:8000

`compare` prints one line per check and exits 1 when anything the page
shows got smaller or went away. It needs only the standard library, and
it only reads: every request is a GET.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

# A drop larger than this, in a count that should only grow or hold, fails.
DROP = 0.2
# Spectrum windows the page offers, and what they are checked by.
WINDOWS = (6, 24, 168)
TIMEOUT_S = 60.0


def get(base: str, path: str) -> tuple[int, Any, dict[str, str]]:
    """GET one path. Returns the status, the JSON (or None) and the headers."""
    request = urllib.request.Request(
        base.rstrip("/") + path, headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read()
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.status, json.loads(body or b"null"), headers
    except urllib.error.HTTPError as exc:
        return exc.code, None, {}
    except (urllib.error.URLError, TimeoutError, ValueError):
        return 0, None, {}


def snapshot(base: str) -> dict[str, Any]:
    """Read what the page reads, and keep the numbers that must not shrink."""
    out: dict[str, Any] = {"base": base, "status": {}, "counts": {}, "spectrum": {}}

    def keep(path: str) -> Any:
        status, body, headers = get(base, path)
        out["status"][path] = status
        return body, headers

    health, _ = keep("/health")
    stats, _ = keep("/api/stats")
    if isinstance(stats, dict):
        for name, value in stats.items():
            if isinstance(value, int):
                out["counts"][f"stats.{name}"] = value
    keep("/api/rf/kinds")
    _, latest = keep("/api/rf/latest?minutes=15&limit=1")
    if "x-total-count" in latest:
        out["counts"]["rf.latest_15min"] = int(latest["x-total-count"])
    stations, _ = keep("/api/rf/stations")
    if isinstance(stations, list):
        out["counts"]["rf.stations"] = len(stations)
        for station in stations:
            name = station.get("station")
            if not name or not station.get("spectrum_last"):
                continue
            entry: dict[str, Any] = {}
            ranges, _ = keep(f"/api/rf/spectrum/{quote(name)}/ranges")
            if isinstance(ranges, dict):
                entry["ranges"] = {r["id"]: r["minutes"] for r in ranges.get("ranges", [])}
            for hours in WINDOWS:
                answer, _ = keep(f"/api/rf/spectrum/{quote(name)}?hours={hours}")
                if isinstance(answer, dict):
                    rows = answer.get("rows", [])
                    # Rows that hold a sweep. Older APIs had no `minutes`:
                    # every row they sent held one.
                    swept = sum(1 for row in rows if row.get("minutes", 1))
                    entry[f"swept_{hours}h"] = swept
            out["spectrum"][name] = entry
    out["health"] = health
    return out


def compare(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (level, message) for each check: `ok`, `warn` or `FAIL`."""
    results: list[tuple[str, str]] = []
    for path, status in before["status"].items():
        now = after["status"].get(path)
        if status == 200 and now != 200:
            results.append(("FAIL", f"{path}: was 200, now {now}"))
    for name, value in before["counts"].items():
        now = after["counts"].get(name)
        if now is None:
            results.append(("FAIL", f"{name}: was {value}, now missing"))
        elif value and now < value * (1 - DROP):
            results.append(("FAIL", f"{name}: was {value}, now {now}"))
        else:
            results.append(("ok", f"{name}: {value} -> {now}"))
    for station, entry in before["spectrum"].items():
        now = after["spectrum"].get(station)
        if now is None:
            results.append(("FAIL", f"spectrum {station}: no longer listed"))
            continue
        for key, value in entry.items():
            if key == "ranges":
                continue
            new = now.get(key)
            if new is None or (value and new < value * (1 - DROP)):
                # The page opens on this. A drop here is history the reader
                # can no longer see, whatever is still in the database.
                results.append(("FAIL", f"spectrum {station} {key}: was {value}, now {new}"))
            else:
                results.append(("ok", f"spectrum {station} {key}: {value} -> {new}"))
        old_total = sum(entry.get("ranges", {}).values())
        new_total = sum(now.get("ranges", {}).values())
        if old_total and new_total < old_total * (1 - DROP):
            results.append(
                ("FAIL", f"spectrum {station} minutes in all ranges: {old_total} -> {new_total}")
            )
        if len(now.get("ranges", {})) > len(entry.get("ranges", {})):
            results.append(
                (
                    "warn",
                    f"spectrum {station}: {len(entry.get('ranges', {}))} -> "
                    f"{len(now.get('ranges', {}))} ranges; a history split in two looks like this",
                )
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    take = commands.add_parser("snapshot", help="print what the API answers now, as JSON")
    take.add_argument("base", help="the API's base URL, such as http://127.0.0.1:8000")
    check = commands.add_parser("compare", help="compare a snapshot with the API now")
    check.add_argument("before", help="a snapshot file")
    check.add_argument("base", help="the API's base URL")
    args = parser.parse_args(argv)
    if args.command == "snapshot":
        json.dump(snapshot(args.base), sys.stdout, indent=1, sort_keys=True)
        print()
        return 0
    with open(args.before) as handle:
        before = json.load(handle)
    results = compare(before, snapshot(args.base))
    for level, message in results:
        print(f"{level:<5} {message}")
    failed = sum(1 for level, _ in results if level == "FAIL")
    print(f"{failed} failed, {len(results) - failed} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
