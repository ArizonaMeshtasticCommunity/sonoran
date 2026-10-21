"""The live traffic feed follows the map's lines, not the poll (#386).

Will: "the box for Live traffic only updates in chunks and leads to like
5 or 6 things happening. Is there a way to make this more real time and
match the lines as they are happening on the map?"

The cause: the poll fetches fifteen seconds of traffic at once. The map
spreads the batch over the next fifteen seconds (`enqueue` in
`map-live.js`), so its lines start one at a time. The feed took the
whole batch at fetch time, so a poll added five or six rows together,
each up to fifteen seconds before its line.

The cases in `tests/unit/js/live_feed_pacing_cases.mjs` run the real
engine under node. Each control below breaks the engine the way a
plausible edit would, and requires the cases to fail.
"""

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
MODULE = STATIC / "map-live.js"
CASES = ROOT / "tests" / "unit" / "js" / "live_feed_pacing_cases.mjs"


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
    assert node, "node is not on PATH, so the feed timing went unchecked"
    return subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT)


def _broken(old: str, new: str) -> subprocess.CompletedProcess[str]:
    source = MODULE.read_text(encoding="utf-8")
    assert old in source, f"the mutation did not land: {old!r}"
    with _temporarily(MODULE, source.replace(old, new, 1)):
        return _run()


def test_the_feed_timing_holds() -> None:
    """The positive arm."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_feed_that_is_never_told_would_be_caught() -> None:
    """No release callback: the feed could only follow the poll."""
    done = _broken(
        "if (onRelease && releasedPackets.length) onRelease(releasedPackets);",
        "void releasedPackets;",
    )
    assert done.returncode != 0
    assert "released on its own frame" in done.stderr


def test_a_feed_that_lists_the_whole_batch_would_be_caught() -> None:
    """An empty waiting list is the old behaviour: every row at fetch time."""
    done = _broken(
        "for (const item of queue) if (item.packet) keys.add(item.packet.key);",
        "void queue;",
    )
    assert done.returncode != 0
    assert "every packet waits before the first frame" in done.stderr


def test_a_release_at_fetch_time_would_be_caught() -> None:
    """A batch released at once, which is the chunk in the report."""
    done = _broken(
        "queue.push({ at: now + (packet.timeMs - lo) * factor, packet });",
        "queue.push({ at: now, packet });",
    )
    assert done.returncode != 0
    assert "released one by one" in done.stderr


def test_the_page_lists_only_what_the_map_has_drawn() -> None:
    """The feed reads the engine's waiting list, and the engine calls it."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    body = app[app.index("function paintTrafficFeed()") :]
    body = body[: body.index("\n}\n")]
    assert "mapState.live.pendingKeys()" in body
    assert "!pending.has(packet.key)" in body
    assert "onRelease: () => paintTrafficFeed()," in app


def test_a_feed_row_wears_its_family_and_says_it_in_words() -> None:
    """Colour ties the row to its line; the packet type text keeps it
    readable without colour (WCAG 1.4.1)."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    row = app[app.index("function trafficRow(packet)") :]
    row = row[: row.index("\n}\n")]
    assert "dataset: { family }" in row
    assert "familyMark(family), portnumLabel(packet.portnum)" in row
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for key, token in (
        ("POSITION_APP", "position"),
        ("NODEINFO_APP", "nodeinfo"),
        ("TELEMETRY_APP", "telemetry"),
        ("TEXT_MESSAGE_APP", "text"),
        ("TRACEROUTE_APP", "trace"),
        ("ROUTING_APP", "routing"),
        ("OTHER", "other"),
    ):
        # The same token the map reads for that family.
        assert f'[data-family="{key}"] {{ --pkt: var(--pkt-{token}); }}' in css
        assert f"token: 'pkt-{token}'" in MODULE.read_text(encoding="utf-8")
