"""The packet page map and the node page neighbor lines (beta-sonoran#412).

The request, in the requester's words: "maps on the individual packet web
pages just like Meshview", and "the neighbors with the lines that shows
them connected to each other on the individual node pages".

The behaviour is in `tests/unit/js/where_heard_cases.mjs`, which runs the
shipped functions under node. This file runs it, puts back the two
plausible wrong versions to prove the cases catch them, and checks how
the maps are wired into the pages.
"""

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
APP_JS = STATIC / "app.js"
CASES = ROOT / "tests" / "unit" / "js" / "where_heard_cases.mjs"


@contextmanager
def _temporarily(path: Path, text: str) -> Iterator[None]:
    original = path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _run() -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the maps went unchecked; a skip looks like a pass"
    return subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT)


def _mutated(anchor: str, replacement: str) -> subprocess.CompletedProcess[str]:
    source = APP_JS.read_text(encoding="utf-8")
    assert source.count(anchor) == 1, (
        f"the anchor {anchor.strip()!r} has moved, so this control checks nothing. "
        "A mutation that does not apply looks the same as one the cases survive."
    )
    with _temporarily(APP_JS, source.replace(anchor, replacement, 1)):
        return _run()


def _between(start: str, end: str) -> str:
    source = APP_JS.read_text(encoding="utf-8")
    first = source.index(start)
    return source[first : source.index(end, first)]


def test_the_cases_pass() -> None:
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_line_to_every_gateway_would_be_caught() -> None:
    """Meshview's shape with a line added: a path nobody measured (AGENTS.md 9.20)."""
    done = _mutated("line: Boolean(sender && heard.direct),", "line: Boolean(sender),")
    assert done.returncode != 0, (
        "the cases pass with a line drawn to relayed gateways, which claims a "
        "straight path for a packet that took hops nobody saw"
    )


def test_the_sender_as_its_own_gateway_would_be_caught() -> None:
    """The sender's own upload is not a radio link (AGENTS.md 9.5.1)."""
    done = _mutated("    if (row.self_reported) continue;\n", "")
    assert done.returncode != 0, (
        "the cases pass with the sender drawn as a gateway that heard itself"
    )


def test_every_packet_gets_the_map_not_only_a_position_packet() -> None:
    """Meshview draws it on every packet page."""
    page = _between("PAGES.packet = async", "\n};")
    assert "wherePanel(" in page, "the packet page does not build the map panel"
    assert "drawWhereHeard(" in page, "the packet page builds the panel and draws nothing on it"
    assert "panels.push(wherePanel(" in page, (
        "the map panel is not pushed with the others, so some packets may not get it"
    )


def test_the_packet_map_explains_its_marks_with_the_glossary() -> None:
    """AGENTS.md 3B: each technical word carries its tooltip."""
    panel = _between("function wherePanel(", "\n}")
    for term in ("gateway", "hop", "direct"):
        assert f"'data-term': '{term}'" in panel, f"the packet map key has no {term} tooltip"


def test_the_node_map_draws_the_neighbor_lines() -> None:
    draw = _between("function drawNodeMap(", "\n/*\n * The node's health")
    assert "neighborMapMarks(" in draw, "the node map does not read the neighbors"
    assert "L.polyline(" in draw, "the node map draws no line to a neighbor"


def test_the_node_map_says_what_a_line_means() -> None:
    """A neighbor line is one direction only. The issue says so."""
    panel = _between("function nodeMapPanel(", "function drawNodeMap(")
    assert "'data-term': 'neighbor-info'" in panel, "the neighbor line has no glossary tooltip"
    assert "This node heard" in panel, "the key does not say which way a line was measured"


def test_both_maps_leave_the_page_scroll_alone() -> None:
    """A map that grabs the wheel traps a reader scrolling past it (#103)."""
    draw = _between("function drawWhereHeard(", "\n}")
    assert "scrollWheelZoom: false" in draw
    assert "L.Browser.mobile" in draw
    assert "packetMaps.delete(" in draw or "old.remove()" in draw, "old packet maps are kept"
