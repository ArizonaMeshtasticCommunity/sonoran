"""The live map's pending-mark queue has a ceiling.

`setPaused(true)` cancels the animation frame, so nothing drains the
queue -- while the 15-second poll keeps calling `enqueue`. Holding the
buffer across a pause is deliberate and is written up in the file.
Holding it *without limit* was not: pause the map and walk away, and
it grew for as long as you were gone, with an O(n log n) sort of the
whole backlog every 15 seconds and an O(n) walk on resume.

This is a source check, which is what this repo uses for JavaScript
invariants (see `test_live_map.py`). It is weaker than driving the
queue would be, and the PR says so: `enqueue` is module-private, so
there is no way to push marks from the page without adding a hook that
exists only for the test.
"""

import re
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "map-live.js"
).read_text(encoding="utf-8")


def test_the_queue_has_a_declared_ceiling() -> None:
    assert "QUEUE_LIMIT" in SOURCE, (
        "the pending-mark queue has no cap, so pausing the map grows it "
        "for as long as the page is left open"
    )


def test_the_ceiling_is_tied_to_what_can_be_on_screen() -> None:
    """A number picked from nowhere ages badly.

    The pool is what can be drawn at once, so the cap is expressed in
    pool-loads rather than as a bare integer.
    """
    found = re.search(r"const QUEUE_LIMIT = ([^;]+);", SOURCE)
    assert found, "QUEUE_LIMIT is not declared as a constant"
    assert "POOL_SIZE" in found.group(1), (
        f"the cap is a bare number ({found.group(1).strip()}); tie it to "
        f"POOL_SIZE so it follows what the map can actually show"
    )


def test_every_producer_is_capped_not_just_one() -> None:
    """Two things push onto this queue: packets and traceroute hops.

    Capping one leaves the other unbounded, which is the same bug with
    a narrower trigger.
    """
    pushes = [m.start() for m in re.finditer(r"queue\.push\(", SOURCE)]
    assert len(pushes) >= 2, "expected at least two producers"
    for start in pushes:
        window = SOURCE[start : start + 500]
        assert "trimQueue()" in window, (
            "a queue.push site is not followed by a trim, so that producer "
            "can still grow the queue without limit"
        )


def test_the_newest_marks_are_the_ones_kept() -> None:
    """On resume somebody wants what the mesh is doing now.

    Dropping from the front keeps the newest. Dropping from the back
    would keep an hour-old backlog and discard the live traffic, which
    is the wrong way round and easy to write by accident.
    """
    start = SOURCE.index("function trimQueue()")
    body = SOURCE[start : start + 300]
    assert "splice(0," in body.replace(" ", ""), (
        "trimQueue does not drop from the front, so the marks kept are "
        "the oldest rather than the newest"
    )
