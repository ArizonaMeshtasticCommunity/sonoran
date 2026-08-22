"""Check a published coverage map against a mesh that really works.

A prediction can be self consistent and still be wrong. The one test
that means anything is whether the map contains the nodes the mesh
demonstrably reaches: a node that answers over the radio, at a place
the map says nothing reaches, is a map that is too pessimistic. A map
that contains everything, including nodes nothing has ever heard, is
too generous.

This reads a node list from a MeshMonitor instance, samples the tiles
of the current run at each node, and reports how many agree.

    uv run python tools/validate_coverage.py https://mesh.example.org

`MESHMONITOR_TOKEN` is used when it is set. The `/api/nodes` endpoint
is usually open and does not need one.

The answer is a percentage, not a pass or a fail. A mesh is not a
controlled experiment: a node reached over four hops can sit well
outside any one site and still work, so a hundred percent is neither
expected nor desirable. Read the figure for each hop count. The nodes
heard directly are the ones the map should contain.
"""

import argparse
import json
import math
import os
import struct
import sys
import urllib.request
import zlib
from pathlib import Path
from typing import Any

import numpy as np

# The zoom to sample at.
#
# High enough that one pixel is small against a footprint, and low
# enough that a run has written the tiles. See `COVERAGE_MAX_ZOOM`.
SAMPLE_ZOOM = 11

# The roles a coverage run predicts from. See `sonoran/roles.py`.
INFRASTRUCTURE = {2: "ROUTER", 4: "REPEATER", 11: "ROUTER_LATE"}


def fetch_nodes(base: str) -> list[dict[str, Any]]:
    """Return the node list of a MeshMonitor instance."""
    # Name the caller. A default urllib agent string is refused by some
    # proxies and by a web application firewall in front of a server.
    request = urllib.request.Request(
        f"{base.rstrip('/')}/api/nodes", headers={"User-Agent": "sonoran-validate-coverage"}
    )
    token = os.environ.get("MESHMONITOR_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=180) as response:
        body: list[dict[str, Any]] = json.load(response)
    return body


def tile_of(latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
    """Return the fractional tile position of a place."""
    count = 2**zoom
    x = (longitude + 180.0) / 360.0 * count
    y = (1.0 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2.0 * count
    return x, y


def read_png(path: Path) -> np.ndarray | None:
    """Return one tile as an RGBA array, or None when it is not there.

    A tile the run never wrote is ground no node reaches, which is the
    same answer as a transparent pixel.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    position = 8
    width = height = 0
    pixels = b""
    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            pixels += body
        position += 12 + length
    raw = np.frombuffer(zlib.decompress(pixels), dtype=np.uint8)
    return raw.reshape(height, width * 4 + 1)[:, 1:].reshape(height, width, 4)


class Sampler:
    """Reads the tiles of one run, holding each one it opens."""

    def __init__(self, run: Path, preset: str, layer: str) -> None:
        self.root = run / preset / layer
        self.held: dict[tuple[int, int], np.ndarray | None] = {}

    def covered(self, latitude: float, longitude: float) -> bool:
        """Return true when the map draws coverage at a place."""
        x, y = tile_of(latitude, longitude, SAMPLE_ZOOM)
        key = (int(x), int(y))
        if key not in self.held:
            self.held[key] = read_png(self.root / str(SAMPLE_ZOOM) / str(key[0]) / f"{key[1]}.png")
        tile = self.held[key]
        if tile is None:
            return False
        column = min(int((x - key[0]) * 256), 255)
        row = min(int((y - key[1]) * 256), 255)
        return bool(tile[row, column, 3] > 0)


def main() -> int:
    """Compare a run against a mesh."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meshmonitor", help="base URL of a MeshMonitor instance")
    parser.add_argument("--cache", default="/var/lib/sonoran/coverage")
    parser.add_argument("--preset", default="LongFast")
    parser.add_argument("--layer", default="usable")
    arguments = parser.parse_args()

    index = Path(arguments.cache) / "index.json"
    try:
        stamp = json.loads(index.read_text(encoding="utf-8"))["current"]
    except (OSError, ValueError, KeyError):
        print(f"no published run in {arguments.cache}", file=sys.stderr)
        return 1
    run = Path(arguments.cache) / "runs" / stamp
    sampler = Sampler(run, arguments.preset, arguments.layer)
    print(f"run {stamp}, layer {arguments.layer} of {arguments.preset}")

    nodes = fetch_nodes(arguments.meshmonitor)
    placed = [
        node
        for node in nodes
        if (node.get("position") or {}).get("latitude") is not None
        and (node.get("position") or {}).get("longitude") is not None
    ]
    # A node with a hop count answered over the radio. One that arrived
    # only over MQTT says nothing about where the radio reaches.
    heard = [n for n in placed if n.get("hopsAway") is not None and not n.get("viaMqtt")]
    print(f"{len(nodes)} nodes, {len(placed)} placed, {len(heard)} reached over the radio\n")

    def report(label: str, group: list[dict[str, Any]]) -> None:
        if not group:
            return
        inside = sum(
            1
            for node in group
            if sampler.covered(node["position"]["latitude"], node["position"]["longitude"])
        )
        print(f"  {label:28} {inside:5}/{len(group):<5} {100 * inside / len(group):5.1f}% inside")

    report("all reached over the radio", heard)
    report("heard directly, no hops", [n for n in heard if n.get("hopsAway") == 0])
    report("one hop away", [n for n in heard if n.get("hopsAway") == 1])
    report("two hops or more", [n for n in heard if (n.get("hopsAway") or 0) >= 2])

    def role(node: dict[str, Any]) -> str | None:
        value = (node.get("user") or {}).get("role")
        try:
            return INFRASTRUCTURE.get(int(value)) if value is not None else None
        except (TypeError, ValueError):
            return None

    report("infrastructure", [n for n in placed if role(n)])
    print(
        "\nA hundred percent is not the target. A node reached over "
        "several hops\ncan sit well outside any one site and still work. "
        "The nodes heard\ndirectly are the ones the map should contain."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
