"""Aiming a directional antenna, and refusing to guess (#111).

`radio/antennas.py` used to exclude Yagis outright, with the reason
written in its docstring: the engine takes one gain and no azimuth, so a
directional antenna in the catalogue would have drawn a map claiming it
was aimed at every point at once. That docstring said the decision
belonged in `docs/PLANNER.md` before the first Yagi was added. This is
that change, so these cases hold the parts that make it safe.

The pattern maths lives in `static/antenna-pattern.js` and is exercised
by `js/antenna_pattern_cases.mjs` under plain node. What is checked here
is the wiring: that the engine is still asked for an omnidirectional run,
that the shaping happens afterwards on a scale where it is exact, and
that an antenna with no stated beamwidth is left unshaped rather than
given a plausible one.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
CASES = ROOT / "tests" / "unit" / "js" / "antenna_pattern_cases.mjs"


def _code(name: str) -> str:
    """A static file with its comments removed.

    Every source-text assertion in this repository answers the same
    question: is it reading the code, or a comment that mentions the
    code? A comment explaining a rule reads exactly like the rule, and
    that has produced a false pass here more than once.
    """
    text = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def test_the_comment_stripper_works() -> None:
    """Positive control for `_code`, which every case below leans on."""
    code = _code("antenna-pattern.js")
    assert "function patternLossDb" in code, "the stripper removed real code"
    assert "3GPP" not in code, "block comments are leaking through"


def test_the_pattern_cases_pass_under_node() -> None:
    """The maths itself, in the runtime that ships it."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([node, str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_engine_is_still_asked_for_an_omnidirectional_run() -> None:
    """The shaping is only exact because the run used boresight gain.

    If somebody ever passes an azimuth into `splat_create`, the pattern
    would be applied twice — once by the engine and once by the raster
    pass — and the map would be wrong by the square of the taper.
    """
    worker = _code("planner.worker.js")
    create = worker[worker.index("module._splat_create(") :]
    create = create[: create.index(")")]
    for absent in ("azimuth", "boresight", "beamwidth", "pattern"):
        assert absent not in create.lower(), (
            f"splat_create now takes {absent}; the raster pass would double-count it"
        )


def test_the_pattern_is_applied_after_the_engine_on_a_decibel_scale() -> None:
    """Order matters, and so does what it is subtracted from.

    The raster holds dBm + 200 — a linear decibel scale — which is the
    only reason a per-direction subtraction is exact rather than an
    approximation. The call has to come after that conversion.
    """
    planner = _code("planner.js")
    convert = planner.index("- 200")
    shape = planner.index("shapeByAntennaPattern(dbm")
    assert convert < shape, "the pattern is applied before the dB conversion"


def test_an_antenna_with_no_bearing_is_left_alone() -> None:
    """An omni must come out of this unchanged.

    The guard is the whole safety of the feature: every existing plan,
    and every omni, has no azimuth and must be untouched.
    """
    planner = _code("planner.js")
    body = planner[planner.index("function shapeByAntennaPattern") :]
    body = body[: body.index("\n}")]
    assert "Number.isFinite(boresight)" in body, "a missing bearing is not guarded"
    assert "return" in body, "there is no early exit for an unaimed antenna"


def test_a_missing_beamwidth_leaves_the_map_omnidirectional() -> None:
    """The L-Com Yagi states no beamwidth, and none is invented.

    This is the case the catalogue's caveat promises the reader, so it
    is held here rather than trusted.
    """
    body = _code("planner.js")
    body = body[body.index("function shapeByAntennaPattern") :]
    body = body[: body.index("\n}")]
    assert "beamwidth <= 0" in body or "!Number.isFinite(beamwidth)" in body, (
        "an unstated beamwidth would be modelled as though it were known"
    )


def test_zero_is_not_the_default_bearing() -> None:
    """Zero degrees is due north, which is a real answer.

    A `0` default would have aimed every directional antenna at the
    north pole and looked like somebody had chosen it.
    """
    params = _code("planner-params.js")
    block = params[params.index("const DEFAULTS = {") :]
    block = block[: block.index("};")]
    assert re.search(r"tx_azimuth:\s*null", block), "tx_azimuth does not default to null"
    assert re.search(r"tx_beamwidth:\s*null", block), "tx_beamwidth does not default to null"


def test_the_aiming_survives_a_share_link() -> None:
    """A plan that is aimed and shared must open aimed.

    Without this the link would round-trip to an omnidirectional map
    that still showed the directional antenna in the picker.
    """
    params = _code("planner-params.js")
    assert "'tx_azimuth'" in params and "'tx_beamwidth'" in params
    planner = _code("planner.js")
    fields = planner[planner.index("const FIELDS = [") :]
    fields = fields[: fields.index("]")]
    assert "'tx_azimuth'" in fields, "the form does not read the bearing back"


def test_the_bearing_box_is_hidden_for_an_omni() -> None:
    """A bearing box beside an omni is a question with no answer."""
    planner = _code("planner.js")
    body = planner[planner.index("function showAiming") :]
    body = body[: body.index("\nasync function")]
    assert "directional" in body, "the control does not switch on directionality"
    assert "hidden" in body, "nothing is ever hidden"


def test_the_far_end_is_told_what_is_assumed_rather_than_asked() -> None:
    """A coverage map has no single direction for the receiver.

    The far end is every point on the map at once, so the honest move is
    to state the assumption. If this ever became a silent boresight gain
    the map would over-promise by the whole gain of the antenna.
    """
    planner = _code("planner.js")
    body = planner[planner.index("function showAiming") :]
    body = body[: body.index("\nasync function")]
    assert "best case" in body, "the far-end assumption is not stated to the reader"


def test_the_markup_the_handler_targets_exists() -> None:
    """A handler pointing at a missing element fails silently.

    Three separate bugs in this repository have been a `querySelector`
    for something that was never in the HTML: the code runs, nothing
    happens, and no error is raised.
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for attribute in (
        'data-antenna-aim="tx"',
        'data-antenna-aim-note="tx"',
        'data-antenna-aim-note="rx"',
        'data-antenna-beamwidth="tx"',
        'data-planner="tx_azimuth"',
        'data-planner="tx_beamwidth"',
    ):
        assert attribute in html, f"{attribute} is not in the page"


def test_the_pattern_script_is_loaded_before_the_planner() -> None:
    """`planner.js` is a classic script and reads a global.

    Load them the wrong way round and `AntennaPattern` is undefined, so
    every Yagi is silently modelled as an omni — a map that looks right
    and is wrong by the entire taper.
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    # Matched on the src attribute, not the bare filename. The first
    # occurrence of "planner.js" in this page is inside a COMMENT about
    # what planner.js does, 41 kB above the script tag, so comparing the
    # bare names put the tag in the wrong order and failed a correct
    # page. The trap this file warns about, caught in this file.
    pattern_tag = html.index('src="static/antenna-pattern.js')
    planner_tag = html.index('src="static/planner.js')
    assert pattern_tag < planner_tag, "the pattern script loads after the planner that needs it"


def test_the_decision_is_written_down_where_the_catalogue_promised() -> None:
    """`antennas.py` sent the reader to `docs/PLANNER.md`."""
    doc = (ROOT / "docs" / "PLANNER.md").read_text(encoding="utf-8")
    assert "4.4 Directional antennas" in doc
    for claim in ("MAX_MODELLED_REJECTION_DB", "half-power", "front-to-back"):
        assert claim in doc, f"the model's {claim} is not documented"


def test_a_stated_beamwidth_reaches_the_field_the_raster_reads() -> None:
    """The catalogue figure must arrive where the shaping looks for it.

    The 12 dBi Yagi states 36 degrees. `shapeByAntennaPattern` reads the
    FORM, not the catalogue, so without a prefill choosing that antenna
    left the box empty and produced an unshaped omnidirectional map with
    a Yagi named in the picker — the most convincing kind of wrong,
    because every visible control agreed.
    """
    planner = _code("planner.js")
    body = planner[planner.index("function showAiming") :]
    body = body[: body.index("\nasync function")]
    assert "chosenBeamwidth" in body, "the catalogue beamwidth never reaches the form"
    assert "tx_beamwidth" in body, "the field the raster reads is not written"


def test_a_typed_beamwidth_is_not_overwritten_by_the_catalogue() -> None:
    """Somebody may hold the datasheet the shop did not print.

    `chosenBeamwidth` prefers a typed figure for exactly that reason, so
    the prefill has to pass the current value in rather than ignore it.
    """
    planner = _code("planner.js")
    body = planner[planner.index("function showAiming") :]
    body = body[: body.index("\nasync function")]
    assert "box.value" in body, "the current value is not consulted before overwriting"


def _body(code: str, start: str) -> str:
    """One function of `planner.js`, from its name to its closing brace."""
    body = code[code.index(start) :]
    return body[: body.index("\n}")]


def test_an_empty_bearing_does_not_stop_every_run() -> None:
    """The aiming boxes are empty for every omni.

    `readForm` asks for a number in every numeric box. The bearing and
    the width were added to `FIELDS` without an exception, so an empty
    bearing stopped every run with "tx azimuth needs a number", for an
    omni whose box is hidden as well.
    """
    planner = _code("planner.js")
    assert re.search(r"const OPTIONAL = new Set\(\[[^\]]*'tx_azimuth'", planner)
    assert re.search(r"const OPTIONAL = new Set\(\[[^\]]*'tx_beamwidth'", planner)
    read = _body(planner, "function readForm(")
    assert "OPTIONAL.has(name)" in read, "readForm does not let an aiming box stay empty"
    assert read.index("OPTIONAL.has(name)") < read.index("needs a number"), (
        "the empty aiming box is refused before it is let through"
    )


def test_an_empty_bearing_is_not_due_north() -> None:
    """`Number(null)` is 0, and 0 degrees is due north.

    An empty bearing reaches the raster pass as null. Read through
    `Number` first, it aimed the antenna at the pole and the guard below
    it passed, because 0 is a finite number.
    """
    body = _body(_code("planner.js"), "function shapeByAntennaPattern")
    guard = body.index("request.tx_azimuth == null")
    assert guard < body.index("Number(request.tx_azimuth)"), (
        "the bearing is read as a number before an empty one is refused"
    )


def test_an_aimed_antenna_asks_for_its_bearing() -> None:
    """A Yagi in the picker and no bearing would draw an omni's map."""
    read = _body(_code("planner.js"), "function readForm(")
    assert "siteAntennaIsAimed()" in read, "a run goes ahead with a Yagi that points nowhere"


def test_an_omni_takes_the_hidden_aiming_back() -> None:
    """A bearing that is hidden must not shape the map.

    Choose a Yagi, give it a bearing, then choose an omni: the boxes are
    hidden, and without this the bearing still bent the prediction.
    """
    body = _body(_code("planner.js"), "function showAiming")
    assert "setAimBox(bearing, '')" in body, "an omni keeps the bearing of the Yagi before it"
    assert "setAimBox(box, '')" in body, "an omni keeps the width of the Yagi before it"


def test_a_catalogue_width_does_not_pass_to_the_next_antenna() -> None:
    """The 12 dBi Yagi's 36 degrees is not the L-Com Yagi's width."""
    body = _body(_code("planner.js"), "function showAiming")
    assert "prefilledBeamwidth" in body, "a width the catalogue wrote reads as one somebody typed"


def test_a_shared_aimed_plan_shows_its_aiming() -> None:
    """A link carries the bearing but not the antenna.

    The boxes must then be visible, or a hidden bearing shapes the map.
    """
    apply = _body(_code("planner.js"), "async function applyShareLink")
    assert "revealLinkedAiming(filled)" in apply
