"""A furthest-node distance from a rounded position, with its error bar (#257).

Will: "Why doesn't every node have a FURTHEST NODE THAT HEARD IT or
FURTHEST NODE IT HEARD? It should definitely have each of the metrics."

Counted on the seeded mesh before the change, 13 of 24 nodes had no
"furthest node that heard it": 4 because their own position is rounded,
1 with no position, and 8 with no single-hop link on record -- one of
which nine gateways had heard with no hop used, which the page did not
count. After it, 8 remain, and each says why.

Two rules hold throughout, and the cases below pin both:

* **A rounded position never becomes a precise-looking figure.** Its
  distance travels as `approx_distance_km` with `distance_error_km`,
  never as `distance_km`, and the page rounds it to its own error.
* **Absent is not zero.** A missing estimate prints nothing, never
  "about 0 ft", which would claim two nodes stand on one spot.

The page half runs under node (`js/node_distance_cases.mjs`), and each
of its claims is broken here once, because a check only ever seen
passing is not evidence that it can fail.
"""

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sonoran.api.routes.node_page import _approximate, _furthest, _no_distance_reason

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "app.js"
CASES = ROOT / "tests" / "unit" / "js" / "node_distance_cases.mjs"

# Two points about 145 km apart in central Arizona.
MESA = (33.42, -111.83)
FLAG = (35.20, -111.65)


# --- the API half --------------------------------------------------


def test_an_exact_pair_is_not_an_estimate() -> None:
    """Both exact: no error bar, so it belongs in `distance_km` instead."""
    placed = {1: (*MESA, 0.0), 2: (*FLAG, 0.0)}
    assert _approximate(placed, 1, 2) is None


def test_a_rounded_end_gives_an_estimate_and_its_bound() -> None:
    placed = {1: (*MESA, 2.9), 2: (*FLAG, 0.0)}
    estimate = _approximate(placed, 1, 2)
    assert estimate is not None
    distance, error = estimate
    assert 190 < distance < 210, distance
    assert error == 2.9


def test_the_error_bar_adds_both_ends() -> None:
    """Each end can have moved the worst way, so the bound is the sum."""
    placed = {1: (*MESA, 2.9), 2: (*FLAG, 1.459)}
    estimate = _approximate(placed, 1, 2)
    assert estimate is not None
    assert estimate[1] == round(2.9 + 1.459, 2)


def test_a_missing_position_is_no_estimate() -> None:
    assert _approximate({1: (*MESA, 2.9)}, 1, 2) is None


def test_the_furthest_ranks_an_estimate_beside_an_exact_distance() -> None:
    """A partner about 200 km away is further than an exact 5 km one."""
    rows: list[dict[str, object]] = [
        {"node_id": "!a", "distance_km": 5.0, "approx_distance_km": None},
        {"node_id": "!b", "distance_km": None, "approx_distance_km": 200.0},
        {"node_id": "!c", "distance_km": None, "approx_distance_km": None},
    ]
    best = _furthest(rows)
    assert best is not None and best["node_id"] == "!b"


def test_no_distance_of_either_kind_is_no_furthest() -> None:
    assert _furthest([{"distance_km": None, "approx_distance_km": None}]) is None


def test_the_reason_names_the_cause_the_reader_can_act_on() -> None:
    assert _no_distance_reason([], True, quiet=True) == "quiet"
    assert _no_distance_reason([], True, quiet=False) == "no_link"
    # Its own missing position comes first: its partners sharing theirs
    # would not help.
    assert _no_distance_reason([{"node_id": "!a"}], False, quiet=False) == "no_position"
    assert _no_distance_reason([{"node_id": "!a"}], True, quiet=False) == "partners_no_position"


# --- the page half, and proof that it can fail --------------------


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
    assert node, "node is not on PATH, so the page cases went unchecked"
    return subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT)


def _broken(old: str, new: str) -> subprocess.CompletedProcess[str]:
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(old, new)
    assert broken != source, f"{old!r} has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        return _run()


def test_the_page_cases_pass() -> None:
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_an_estimate_printed_to_a_tenth_would_be_caught() -> None:
    """The false precision #257 forbids: "about 288.5 km" from a 2.9 km bound."""
    done = _broken(
        "  const shown = Math.round(estimate / step) * step;",
        "  const shown = estimate;",
    )
    assert done.returncode != 0
    assert "rounded to its own error" in done.stderr, done.stderr


def test_an_error_that_swallows_the_distance_would_be_caught() -> None:
    done = _broken("  if (error >= estimate) {", "  if (false) {")
    assert done.returncode != 0
    assert "upper bound" in done.stderr, done.stderr


def test_a_missing_estimate_read_as_zero_would_be_caught() -> None:
    done = _broken(
        "  if (!(error > 0) || estimate == null) return null;",
        "  if (!(error > 0)) return null;",
    )
    assert done.returncode != 0
    assert "never" in done.stderr, done.stderr
