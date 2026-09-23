"""Simple or Advanced, without either one changing the answer (#113).

Simple hides the boxes the pickers fill — transmit power, both antenna
gains, cable loss — and leaves the pickers, the site and the height.
Advanced is the form as it was.

**Nothing is removed from the DOM and no value is cleared.** Hiding is
`display: none` on the label, so every field keeps whatever a picker put
in it, `readForm` still reads it, and the share link still carries it.
Switching mode changes what a person is ASKED for and never what gets
predicted — which is the only way this is safe to add to a form somebody
may already have filled in.

Measured in a browser against this tree served locally:

    default         simple, 0 advanced fields visible, 4 pickers visible
    after pickers   power "22", tx_gain "8", loss "0.98"
    advanced        4 advanced fields visible, values IDENTICAL
    values survived true
    after reload    mode remembered as "simple"

(25 ft of LMR-400 at 3.937 dB/100ft is 0.98 dB, so the picker and the
datasheet still agree through all of this.)
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
PLANNER = (STATIC / "planner.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def test_the_switch_exists_and_names_both_modes() -> None:
    for mode in ("simple", "advanced"):
        assert f'data-planner-mode="{mode}"' in HTML, f"no {mode} control"


def test_hiding_is_css_and_not_removal() -> None:
    """The property everything else here depends on.

    If Simple ever removed or cleared these fields, a prediction run in
    Simple would differ from the same one in Advanced — silently.
    """
    assert ".planner-form.is-simple [data-advanced-only] { display: none; }" in CSS, (
        "the advanced fields are not hidden by CSS; if they are being "
        "removed or cleared instead, the mode changes the prediction"
    )
    body = PLANNER[PLANNER.index("function applyPlannerMode(") :][:600]
    for forbidden in (".value = ''", ".remove()", "replaceChildren"):
        assert forbidden not in body, f"applyPlannerMode does {forbidden}"


def test_only_the_fields_a_picker_fills_are_hidden() -> None:
    """Site, height and the map have no picker, so Simple must keep them."""
    assert HTML.count("data-advanced-only") == 4, (
        f"{HTML.count('data-advanced-only')} fields are marked advanced; "
        f"expected the four the pickers fill (tx_power, tx_gain, rx_gain, "
        f"system_loss)"
    )
    for kept in ('data-planner="lat"', 'data-planner="tx_height"', 'data-planner="site_name"'):
        index = HTML.index(kept)
        label = HTML.rfind("<label", 0, index)
        assert "data-advanced-only" not in HTML[label:index], f"{kept} is hidden in Simple"


def test_simple_is_the_default_for_a_first_visit() -> None:
    """The reader who benefits is the one who has not been here before."""
    body = PLANNER[PLANNER.index("function plannerMode(") :][:400]
    assert "=== 'advanced' ? 'advanced' : 'simple'" in body, (
        "the default is not Simple, or is decided some other way"
    )


def test_the_choice_is_remembered_and_survives_refused_storage() -> None:
    body = PLANNER[PLANNER.index("const MODE_STORE") :][:1200]
    assert "localStorage.setItem(MODE_STORE" in body, "the choice is not remembered"
    assert body.count("catch") >= 2, (
        "a browser that refuses storage throws instead of keeping the default"
    )


def test_the_switch_says_which_mode_is_on() -> None:
    """Two buttons that look the same are not a switch."""
    assert "aria-pressed" in HTML[HTML.index("mode-switch") : HTML.index("mode-switch") + 500]
    assert "setAttribute('aria-pressed'" in PLANNER, "the state is set once and never updated"
    assert '[aria-pressed="true"]' in CSS, "the active mode is not visually distinct"
