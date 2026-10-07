"""The planner asks which antenna, not how many dBi (#111, #113).

"Antenna gain (dBi)" asks for a number printed on a box the buyer no
longer has. #113 wants a newcomer to reach a prediction "without typing
a single dB value"; this is that for the antenna, as the cable picker is
for the cable.

Measured in a browser against this tree served locally:

    on load        both pickers visible, 6 options,
                   tx_gain "2.15" (the stock-antenna default)
    tx = 10 dBi    tx_gain "10", rx_gain untouched at "2.15"
                   "10 dBi claimed by Rokland, not measured. Flat open
                    country… A poor choice on a peak…"
    rx = 2.5 dBi   rx_gain "2.5", tx_gain still "10"

The two ends are independent on purpose: a rooftop omni talking to a
handheld is the normal case, not the exception.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
PLANNER = (STATIC / "planner.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def _wiring() -> str:
    start = PLANNER.index("async function wireAntennaRun(")
    return PLANNER[start : PLANNER.index("\nasync function wireCableRun(", start)]


def test_each_end_gets_its_own_picker() -> None:
    """One picker filling both ends would model a link nobody has."""
    for end in ("tx", "rx"):
        assert f'data-antenna-run="{end}"' in HTML, f"no {end} antenna picker"
        assert f'data-antenna-type="{end}"' in HTML
    assert "wireAntennaRun('tx', 'tx_gain')" in PLANNER
    assert "wireAntennaRun('rx', 'rx_gain')" in PLANNER


def test_it_fills_the_field_the_engine_reads() -> None:
    body = _wiring()
    assert "field(gainField)" in body, "the picker writes nowhere"
    assert "dispatchEvent(new Event('change'" in body, (
        "the gain is written without firing change, so the share link and "
        "the run state do not notice"
    )


def test_the_note_says_the_gain_is_a_claim() -> None:
    """The catalogue's whole point, carried through to the reader.

    A planner that presented a retail listing's number as fact would
    undo the reason `gain_dbi_claimed` is named that way.
    """
    assert "not measured" in _wiring(), (
        "the planner presents the seller's claimed gain as though it were measured"
    )


def test_the_beamwidth_is_shown_where_there_is_one() -> None:
    """The figure that decides whether high gain helps at all.

    Showing only the gain teaches exactly the mistake the catalogue was
    written to prevent: that 10 dBi is simply better than 5.8.
    """
    body = _wiring()
    assert "vertical_beamwidth_deg" in body, "the pattern height is never mentioned"


def test_typing_a_figure_is_still_possible() -> None:
    """In Advanced the empty choice still offers typing (#314: Simple
    asks for a choice instead)."""
    source = (STATIC / "planner.js").read_text(encoding="utf-8")
    assert 'advanced: "I\'ll type the gain myself"' in source
    assert "emptyChoice(PICKERS[end === 'tx' ? 1 : 2])" in _wiring()


def test_the_pickers_stay_hidden_until_the_catalogue_arrives() -> None:
    for end in ("tx", "rx"):
        assert f'data-antenna-run="{end}" hidden' in HTML, (
            f"the {end} picker is visible before it can work"
        )
    body = _wiring()
    assert body.index("if (!antennas || !antennas.length) return;") < body.index(
        "run.hidden = false"
    )


def test_no_gain_figure_is_hard_coded_in_the_planner() -> None:
    """One catalogue, fetched. Two copies would drift silently."""
    body = _wiring()
    assert "api/radio/antennas" in PLANNER
    for claimed in ("10.0", "5.8", "2.5,"):
        assert claimed not in body, f"{claimed} is hard-coded in the planner"
