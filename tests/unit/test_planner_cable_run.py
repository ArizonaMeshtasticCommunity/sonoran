"""The planner offers a cable and a length instead of a dB figure (#112).

"Cable loss (dB)" asks a newcomer for a number they have no way to
arrive at. They do know which cable they bought and roughly how long the
run is, and the answer matters: at 915 MHz, 30 ft of LMR-195 is 3.33 dB
and the same run of LMR-400 is 1.18 dB.

Measured in a browser, against this tree served locally with `/api`
proxied to the dev instance:

    on load          picker visible, options
                     ["I'll type the loss myself", LMR-195, LMR-240, LMR-400],
                     loss box "2"
    LMR-400, 30 ft   loss box "1.18"
                     "30 ft of LMR-400 loses about 1.18 dB at each end —
                      roughly 24% of the power, before the antenna."
    LMR-195, 30 ft   loss box "3.33"
    back to manual   note hidden, the last figure left in the box

Both figures match `test_cable_loss.py` exactly, so the browser is
computing from the same datasheet numbers and not from a second copy.

Getting that pass took a detour worth recording: three attempts to
splice the new markup into the DEPLOYED page failed, because the
deployed instance still serves the old `index.html`. The fix was to stop
patching somebody else's HTML and serve this tree — `tools/dev/
serve_local.js` does that now, and it is the right harness for any
change that touches markup.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
PLANNER = (STATIC / "planner.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def _wiring() -> str:
    start = PLANNER.index("async function wireCableRun(")
    return PLANNER[start : PLANNER.index("\nfunction wirePlanner(", start)]


def test_the_controls_exist_in_the_page() -> None:
    for marker in ("data-cable-run", "data-cable-type", "data-cable-length", "data-cable-note"):
        assert marker in HTML, f"{marker} is not in the planner form"


def test_it_fills_the_existing_box_rather_than_replacing_it() -> None:
    """The dB field stays the one the engine and the share link read.

    Replacing it would have meant touching the share format and the
    request builder for a convenience.
    """
    body = _wiring()
    assert "field('system_loss')" in body, (
        "the cable run does not write into the loss field, so choosing a "
        "cable changes nothing the engine sees"
    )
    assert "dispatchEvent(new Event('change'" in body, (
        "the box is written without firing change, so the share link and "
        "the run state do not notice"
    )


def test_an_advanced_user_can_still_type_a_figure() -> None:
    # In Advanced the empty choice still offers typing (#314: Simple asks
    # for a choice instead).
    source = (STATIC / "planner.js").read_text(encoding="utf-8")
    assert 'advanced: "I\'ll type the loss myself"' in source, "no way back to typing the dB"
    assert "emptyChoice(PICKERS[3])" in _wiring()


def test_the_helper_stays_hidden_until_its_data_arrives() -> None:
    """A failed fetch must not leave dead controls on the form."""
    assert "data-cable-run hidden" in HTML, "the controls are visible before they work"
    body = _wiring()
    assert body.index("if (!cables || !cables.length) return;") < body.index(
        "run.hidden = false"
    ), "the controls are revealed before the catalogue is known to exist"


def test_the_note_says_it_in_words_as_well_as_decibels() -> None:
    """ "2.3 dB" means nothing to somebody buying their first coax."""
    body = _wiring()
    assert "% of the power" in body, "the loss is only ever stated in dB"
    assert "each end" in body, (
        "the note does not say the figure applies per end, while the model applies it twice"
    )


def test_the_catalogue_is_fetched_and_not_copied() -> None:
    body = _wiring()
    assert "api/radio/cables" in PLANNER, "the planner does not read the served catalogue"
    assert "11.1" not in body and "3.9" not in body, (
        "datasheet figures are hard-coded in the planner, so they can "
        "drift from radio/cables.py without either copy looking wrong"
    )
