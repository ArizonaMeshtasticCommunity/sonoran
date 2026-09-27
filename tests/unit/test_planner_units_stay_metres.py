"""The planner's typed boxes are metres, and this holds them there.

`docs/PLANNER.md` 4: the engine takes feet, `planner-params.js` converts,
and feeding metres straight through **overstates every antenna by 3.28
times**. The rest of the dashboard reads in feet by default (§3.2), so the
obvious tidy-up is to relabel these boxes — and that is the one change
here that produces a wrong prediction which looks entirely right.

The decision taken in §6.5, and why it is not "we ran out of time":

* A share link carries `tx_height` in **metres** (`docs/PLANNER.md` 5.1),
  and it must, or the same link predicts two different things for two
  readers with different settings.
* So a box in feet needs a conversion on the way into the link and back
  out of it, and that round trip is not exact. 6 m written by a metric
  reader is 19.685 ft; shown to one decimal it is 19.7 ft, which converts
  back to 6.0045 m. The link would mean slightly different things
  depending on who opened it, which is worse than a label somebody has to
  read.
* `SonoranUnits.heightToM` exists for the day that is worked through
  properly, with the link kept in metres and a measured prediction on both
  sides. It is deliberately NOT called from the planner.

What was done instead, because the label alone is a trap for a reader who
has never seen it: an echo under each box, read-only, in the reader's own
units. Measured in Chromium on this instance, imperial (the default):

    tx_height 3     "This box is in metres — that is about 10 ft."
    metric          the echo is hidden entirely
    empty box       the echo is hidden, and does not read "0 ft"

`Length (ft)` on the cable box is not part of any of this: cable is sold
in feet and the catalogue's figures are per 100 ft.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
RAW = (STATIC / "planner.js").read_text(encoding="utf-8")
PLANNER = "\n".join(
    line
    for line in re.sub(r"/\*.*?\*/", "", RAW, flags=re.S).splitlines()
    if (s := line.strip()) and not s.startswith("//")
)

# The boxes a reader types a height or a distance into, and what their
# label must say. The unit in the label is the unit the value is in.
TYPED = {
    "tx_height": "m",
    "rx_height": "m",
    "clutter_height": "m",
    "radius": "km",
}


def test_every_typed_box_names_the_unit_it_is_actually_in() -> None:
    """The label and the arithmetic, checked against each other.

    A label change without the conversion is a silently wrong prediction.
    This is the half that catches the label moving on its own.
    """
    for name, unit in TYPED.items():
        match = re.search(rf"<label[^>]*>([^<]*)<input data-planner=\"{name}\"", HTML)
        assert match, f"{name} is not a labelled input any more"
        caption = match.group(1)
        assert f"({unit})" in caption, (
            f"{name} is in {unit} and its label reads {caption.strip()!r}"
        )


def test_nothing_converts_a_typed_height_on_its_way_in() -> None:
    """And this is the half that catches the conversion moving on its own.

    If `heightToM` ever appears here, the labels above have to change in
    the same commit, and a prediction has to be measured on both sides.
    """
    assert "heightToM" not in PLANNER, (
        "the planner now converts a typed height; the labels still say metres, and "
        "docs/PLANNER.md 5.1 still says the share link is metres"
    )


def test_the_share_link_still_carries_metres() -> None:
    """The reason the boxes cannot simply be relabelled.

    `radius` is the one field whose form unit differs from the engine's,
    and the conversion is a factor of 1000 either way — nothing to do with
    the reader's settings.
    """
    params = (STATIC / "planner-params.js").read_text(encoding="utf-8")
    assert "const FORM_DEFAULTS = { ...DEFAULTS, radius: DEFAULTS.radius / 1000 };" in params, (
        "the form's units are no longer derived from the engine's by one known factor"
    )
    assert "request.radius = request.radius * 1000;" in PLANNER, (
        "the range is no longer read as kilometres"
    )
    assert "SonoranUnits" not in params, (
        "planner-params.js now reads a display setting, so the share link is "
        "unit-dependent and a link means different things to different readers"
    )


def test_the_echo_is_only_shown_to_a_reader_who_needs_it() -> None:
    """A metric reader would only see the box repeated."""
    body = PLANNER[PLANNER.index("function showHeightHints(") :]
    body = body[: body.index("\n/*") if "\n/*" in body else len(body)]
    assert "SonoranUnits.imperial()" in body, "the echo does not ask what the reader wants"
    assert "if (!imperial" in body, "the echo is shown to a metric reader too"


def test_an_empty_box_does_not_echo_as_zero() -> None:
    """`Number('')` is 0, and "0 ft" under an empty height box states a
    mast lying flat on the ground.

    Five bugs in this repository have been a value meaning ABSENT sharing
    storage with a value that means something (#149, #157, #190, #197).
    """
    body = PLANNER[PLANNER.index("function showHeightHints(") :][:1600]
    assert "raw === '' ? null : Number(raw)" in body, (
        "an empty height box is read with Number(), which makes it 0"
    )
    assert "metres === null" in body, "the absent case is not handled separately"


def test_the_echo_follows_the_units_setting() -> None:
    """The settings page can change it in another tab.

    A stale unit under a box about units is worse than no box at all.
    """
    assert "SonoranSettings.onChange(() => showHeightHints())" in PLANNER, (
        "the echo does not follow the setting, so it can say feet to a metric reader"
    )


def test_the_echo_cannot_be_typed_into() -> None:
    """It is a `<p>`, not a second box. Two boxes for one number is how a
    reader ends up typing into the wrong one."""
    for name in ("tx_height", "rx_height"):
        match = re.search(
            rf"<p class=\"muted planner-unit-hint\" data-planner-hint=\"{name}\"", HTML
        )
        assert match, f"the echo for {name} is not a paragraph"
    assert ".planner-unit-hint[hidden] { display: none; }" in CSS


def test_the_cable_length_is_not_treated_as_a_units_setting_field() -> None:
    """Cable is sold in feet and `radio/cables.py` is per 100 ft."""
    assert "<label>Length (ft) <input data-cable-length" in HTML, (
        "the cable length changed units; the catalogue is still per 100 ft"
    )
    assert "const FEET_PER_100 = 100;" in PLANNER
