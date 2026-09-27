"""Simple or Advanced, without either one changing the answer (#113, §6.5).

Simple hides what a newcomer has no way to answer and leaves the pickers,
the site and the two heights. §6.5 widened the list that moves: the boxes
the pickers fill — transmit power, both antenna gains, cable loss — and
then the frequency, the frequency slot, the receiver sensitivity, and all
of Ground and air.

Advanced is the whole form.

**Nothing is removed from the DOM and no value is cleared.** Hiding is
`display: none` on the label, so every field keeps whatever a picker put
in it, `readForm` still reads it, and the share link still carries it.
Switching mode changes what a person is ASKED for and never what gets
predicted — which is the only way this is safe to add to a form somebody
may already have filled in.

Measured in Chromium against this tree, 1500x1050, on the seeded
database, after §6.5 widened the list:

    simple          9 advanced markers, 0 of them visible
    advanced        9 advanced markers, 9 visible
    mode switch     0 of 21 field values changed
    run in simple   "5 of 22 nodes reached, 1783 km2, 16.5 mi furthest"
    run in advanced the same 21 words, the same five nodes, the same dBm

The last two lines are the point of the whole item. The earlier
measurement, from #113 when four fields moved, read:

    after pickers   power "22", tx_gain "8", loss "0.98"
    values survived true

(25 ft of LMR-400 at 3.937 dB/100ft is 0.98 dB, so the picker and the
datasheet agreed through that too.)
"""

import re
from html.parser import HTMLParser
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


def _planner_form() -> str:
    """Just the form, so a marker on another page cannot be counted."""
    start = HTML.index('<div class="panel planner-form"')
    return HTML[start : HTML.index('<div class="planner-map-side">', start)]


# Every control §6.5 moves out of Simple, and the reason it cannot be
# answered by somebody who has just got their first node.
MOVED = {
    "tx_power": "the picker fills it from the board",
    "tx_gain": "the picker fills it from the antenna",
    "rx_gain": "the picker fills it from the antenna",
    "system_loss": "the picker works it out from the cable and its length",
    "frequency_mhz": "it follows the preset and the slot",
    "sensitivity": "it follows the preset",
    "radio_climate": "desert, until #239 answers it from the coordinate",
    "polarization": "Meshtastic is vertical",
    "clutter_height": "it is a model input, not a thing you know",
    "radius": "30 km is a sensible first run",
    "ground_dielectric": "a model constant",
    "ground_conductivity": "a model constant",
    "atmosphere_bending": "a model constant",
    "situation_fraction": "a model constant",
    "time_fraction": "a model constant",
}

# What Simple must keep. Nothing fills these in for the reader: the site
# is a place only they know, and the heights are the two numbers the
# prediction turns on most.
KEPT = ("site_name", "lat", "lon", "tx_height", "rx_height", "preset")


class _Advanced(HTMLParser):
    """Which controls in the planner form are under `data-advanced-only`.

    A real parser and not a `rfind`, because the marker can sit on the
    control's own `<label>`, on the `.pair` around it, on the `<details>`
    around that, or on the `<h3>` before it — and "the nearest opening tag
    behind this string" gets that wrong in the one direction that matters.
    The first draft of this test looked backwards for the nearest `<label`,
    found the field's own label inside a `.pair` that carried the marker,
    and reported fourteen correctly-hidden controls as still visible.

    Maps `data-planner` value (or `data-planner-slot`) to True or False.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.found: dict[str, bool] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        held = dict(attrs)
        marked = "data-advanced-only" in held
        under = marked or any(flag for _, flag in self.stack)
        name = held.get("data-planner")
        if name:
            self.found[name] = under
        if "data-planner-slot" in held:
            self.found["data-planner-slot"] = under
        # `<input>` and the rest never close, so they never go on the
        # stack. If one did, everything after it would inherit its state.
        if tag not in ("input", "br", "img", "hr", "meta", "link", "use", "path"):
            self.stack.append((tag, marked))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def _controls() -> dict[str, bool]:
    parser = _Advanced()
    parser.feed(_planner_form())
    return parser.found


def _is_advanced(name: str) -> bool:
    found = _controls()
    assert name in found, f"{name} is not a control on the planner form any more"
    return found[name]


def test_every_control_the_plan_moves_is_advanced_only() -> None:
    """§6.5's list, one case, so a half-done move fails by name."""
    missing = [f"{name} ({why})" for name, why in MOVED.items() if not _is_advanced(name)]
    assert not missing, f"still asked for in Simple: {missing}"
    # The slot picker is not a `data-planner` field: it is derived from the
    # frequency and never travels in a share link.
    assert _is_advanced("data-planner-slot"), "the frequency slot is asked for in Simple"


def test_simple_keeps_what_nothing_can_fill_in_for_the_reader() -> None:
    """The other half. Without it, "move it to advanced" passes by moving
    everything, and Simple becomes a page with a Run button on it."""
    hidden = [name for name in KEPT if _is_advanced(name)]
    assert not hidden, f"hidden in Simple, and nothing else supplies them: {hidden}"


def test_the_ground_and_air_heading_goes_with_its_fields() -> None:
    """A heading over nothing reads as a section that failed to load."""
    assert "<h3 data-advanced-only>Ground and air</h3>" in HTML, (
        "the Ground and air heading is still shown in Simple, over no fields"
    )


def test_no_pair_mixes_the_two_modes() -> None:
    """A hidden grid item leaves its column behind.

    `grid-template-columns: 1fr 1fr` makes two tracks whatever is in them,
    so a Simple field paired with an Advanced one sat at half width with
    no partner beside it — which is how "I'll type the power myself" came
    to be cut off mid-word inside a 145 px select. Every `.pair` holds two
    fields of the same mode instead.
    """
    form = _planner_form()
    mixed = []
    for match in re.finditer(r'<div class="pair"([^>]*)>(.*?)</div>', form, re.S):
        row = match.group(2)
        advanced_row = "data-advanced-only" in match.group(1)
        marked = row.count("data-advanced-only")
        labels = row.count("<label")
        if advanced_row and marked:
            mixed.append(f"a row marked advanced also marks {marked} of its fields")
        if not advanced_row and marked and marked != labels:
            mixed.append(f"{marked} of {labels} fields in one row are advanced: {row[:70]!r}")
    assert not mixed, "; ".join(mixed)


def test_a_row_with_one_control_is_not_a_pair() -> None:
    """The truncation §6.5 names, held closed.

    Measured at a 1500 px window: the board picker's `<select>` was 145 px
    inside a 336 px form and read "I'll type the power my…". Outside a
    `.pair` it is 300 px and the whole option fits.
    """
    for single in ("data-board-run", 'data-antenna-run="tx"', 'data-antenna-run="rx"'):
        index = HTML.index(single)
        opening = HTML.rfind("<div", 0, index)
        assert "pair" not in HTML[opening:index], (
            f"{single} holds one control and is still a .pair, so its select is half width"
        )
    # The positive control: the cable run really is two controls and
    # really should be a pair, so this test cannot pass by banning `.pair`.
    index = HTML.index("data-cable-run")
    opening = HTML.rfind("<div", 0, index)
    assert "pair" in HTML[opening:index], "the cable run is two controls and should stay a pair"


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
