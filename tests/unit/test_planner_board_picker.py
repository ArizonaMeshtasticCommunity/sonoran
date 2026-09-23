"""The planner asks which radio, and says how well it knows the answer (#110, #113).

"Power (dBm)" is a number most people have never looked up. The board is
on the desk in front of them.

**The distinction this carries is the point.** 54 of the 117 boards the
flasher offers have a hand-written RF profile in `radio/hardware.py`;
the other 63 get a family rule that reads the chipset out of the board's
name and assumes the rest. Both are offered — hiding two thirds of the
catalogue would be less useful and no more honest — but a figure guessed
from a name must never look like one somebody measured, and a coverage
map is very good at making a guess look authoritative.

Measured in a browser against this tree served locally:

    on load        picker visible, 118 options, known boards first
    known board    tx_power "22", tx_gain "2.15"
                   "SX1262 at 22 dBm, with the antenna it ships with
                    (2.15 dBi). The operator can set the power lower."
    guessed board  tx_power "22"
                   "No measured profile for this board. Assuming 22 dBm
                    and 2.15 dBi from its family — check your radio's
                    settings and correct the fields if you know better."

The board list is a snapshot in `radio/boards.json`, written by
`tools/dev/board_catalogue.py`. #110 is explicit that it must not be
fetched at page load: a planner that stops working because somebody
else's endpoint is down is worse than one whose list is a week old.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
PLANNER = (STATIC / "planner.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
BOARDS = json.loads(
    (ROOT / "src" / "sonoran" / "radio" / "boards.json").read_text(encoding="utf-8")
)


def _wiring() -> str:
    start = PLANNER.index("async function wireBoardRun(")
    return PLANNER[start : PLANNER.index("\n/*\n * Pick the antenna", start)]


def test_the_snapshot_holds_the_whole_catalogue() -> None:
    assert len(BOARDS) > 100, f"only {len(BOARDS)} boards snapshotted"
    exact = [b for b in BOARDS if b["profile_is_exact"]]
    assert 40 < len(exact) < len(BOARDS), (
        f"{len(exact)} of {len(BOARDS)} exact — if every board is exact the "
        f"flag has stopped meaning anything"
    )


def test_every_board_carries_a_figure_even_when_it_is_assumed() -> None:
    """A picker showing nothing for two thirds of the list is not more
    honest, only less useful."""
    for board in BOARDS:
        assert board["assumed_tx_power_dbm"] is not None, f"{board['slug']} has no power"
        assert board["assumed_antenna_gain_dbi"] is not None, f"{board['slug']} has no gain"


def test_the_note_distinguishes_measured_from_assumed() -> None:
    """The single thing that makes offering the guessed boards defensible."""
    body = _wiring()
    assert "profile_is_exact" in body, "the picker does not read the flag at all"
    assert "No measured profile" in body, (
        "a guessed transmit power is presented the same way as a known "
        "one, which a coverage map then makes look authoritative"
    )


def test_the_guessed_boards_are_marked_in_the_list_itself() -> None:
    """Before the choice, not only after it."""
    assert "(assumed)" in _wiring(), (
        "guessed boards are indistinguishable from known ones until after they are picked"
    )


def test_known_boards_come_first() -> None:
    """The boards we can answer for should be findable without scrolling
    past sixty we cannot."""
    assert "a.profile_is_exact ? -1 : 1" in _wiring()


def test_it_fills_the_fields_the_engine_reads() -> None:
    body = _wiring()
    assert "field('tx_power')" in body and "field('tx_gain')" in body
    assert body.count("dispatchEvent(new Event('change'") == 2, (
        "a field is written without firing change, so the share link and "
        "the run state do not notice"
    )


def test_a_sealed_antenna_is_called_out() -> None:
    """There is nothing to unscrew, so advice about antennas is wrong
    for these boards."""
    assert "fixed_antenna" in _wiring()
    assert any(b["fixed_antenna"] for b in BOARDS), "no board reports a fixed antenna"


def test_typing_a_figure_is_still_possible() -> None:
    assert "I'll type the power myself" in _wiring()
    assert "data-board-run hidden" in HTML, "the picker shows before it can work"
