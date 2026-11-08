"""Nodes that share one rounded position are spread apart on the map.

beta-sonoran#401 (Tyler): when more than one node lands on the same
place because of location precision, the dots sit on top of each other
and only one can be clicked. Move each one a little, by 2 % of its
precision cell, in a direction taken from its node number, so the same
node always lands in the same place.

A node that sends a reduced precision position keeps the top `bits` of
each coordinate (firmware `PositionModule.cpp`, `position_precision`),
so its true place is anywhere in that cell. A move of 2 % of the cell
stays inside it and claims nothing new.
"""

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "src" / "sonoran" / "web" / "static" / "app.js").read_text(encoding="utf-8")
MAP_ROUTE = (ROOT / "src" / "sonoran" / "api" / "routes" / "map.py").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start : APP.index("\n}\n", start) + 2]


def _spread(rows: list[dict[str, object]]) -> dict[str, list[float]]:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the spread went unchecked. A skip looks like a pass."
    script = (
        _function("precisionMetres")
        + _function("spreadSharedPositions")
        + f"const out = spreadSharedPositions({json.dumps(rows)});"
        + "console.log(JSON.stringify(Object.fromEntries(out)));"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert isinstance(result, dict)
    return result


def _metres(a: list[float], b: list[float]) -> float:
    north = (a[0] - b[0]) * 111_320
    east = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
    return math.hypot(north, east)


ROUNDED = {"lat": 33.45, "lon": -112.07, "precision_bits": 13}


def test_two_nodes_on_one_rounded_position_are_drawn_apart() -> None:
    rows = [
        {"node_id": "!00000001", "node_num": 1, **ROUNDED},
        {"node_id": "!00000002", "node_num": 2, **ROUNDED},
    ]
    at = _spread(rows)
    assert at["!00000001"] != at["!00000002"], "the two dots are still drawn on one spot"
    cell = 23905787.925 / 2**13
    for node_id in at:
        moved = _metres(at[node_id], [ROUNDED["lat"], ROUNDED["lon"]])
        assert math.isclose(moved, 0.02 * cell, rel_tol=0.02), (
            f"{node_id} moved {moved:.1f} m, not 2 % of its {cell:.0f} m cell"
        )


def test_the_move_is_the_same_on_every_refresh() -> None:
    """Seeded by the node number, so a dot never jumps between polls."""
    rows = [
        {"node_id": "!00000001", "node_num": 1, **ROUNDED},
        {"node_id": "!00000002", "node_num": 2, **ROUNDED},
    ]
    assert _spread(rows) == _spread(list(reversed(rows)))


def test_a_node_alone_on_its_position_is_not_moved() -> None:
    rows = [
        {"node_id": "!00000001", "node_num": 1, **ROUNDED},
        {"node_id": "!00000003", "node_num": 3, "lat": 33.5, "lon": -112.0, "precision_bits": 13},
    ]
    at = _spread(rows)
    assert at["!00000001"] == [ROUNDED["lat"], ROUNDED["lon"]]


def test_a_full_precision_position_is_not_moved() -> None:
    """Two nodes that both send an exact place are at that place."""
    exact = {"lat": 33.45, "lon": -112.07, "precision_bits": 32}
    rows = [
        {"node_id": "!00000001", "node_num": 1, **exact},
        {"node_id": "!00000002", "node_num": 2, **exact},
    ]
    at = _spread(rows)
    assert at["!00000001"] == at["!00000002"] == [33.45, -112.07]


def test_the_map_draws_the_spread_position_and_the_api_sends_the_precision() -> None:
    body = APP[APP.index("function drawMapNodes(rows) {") :]
    body = body[: body.index("\n}\n")]
    assert "spreadSharedPositions(" in body, "drawMapNodes still draws each dot on its raw position"
    assert re.search(r'"precision_bits":\s*node\.last_position_precision_bits', MAP_ROUTE), (
        "/api/map/nodes does not send the precision the spread needs"
    )
