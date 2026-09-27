"""The planner's boxes read and accept the reader's units (#246).

The rest of the site reads in feet and miles by default. The planner's
four typed boxes -- the two antenna heights, the clutter height and the
range -- asked for metres and kilometres, so a reader who reads feet
everywhere else typed metres here, or typed feet into a metres box.

The boxes now follow the units setting. What does NOT follow it:

* The form value. Heights are metres and the range is kilometres inside
  the page, and the engine is given feet from those metres by
  `toEngineParams`, as before. `docs/PLANNER.md` 4 records that confusing
  the two overstates every antenna by 3.28 times.
* The share link. It carries metres, so a link predicts the same thing
  for every reader, whatever each of them has chosen.

The conversion happens at the box and nowhere else, and an untouched box
is never converted back. That is the part that makes the round trip
lossless: 6 m shows as 19.69 ft, and 19.69 ft is 6.0015 m, so a page that
re-read its own display would move the antenna by 1.5 mm and a link
passed on by an imperial reader would stop being the link it was. Each
box holds the metric value beside the text it wrote, and uses it until
the reader types something else.

`tests/unit/js/planner_units_cases.mjs` exercises the arithmetic. The test
below runs the real engine on what those cases hand it.

Measured in Chromium on this instance, imperial (the default), Advanced:

    opens on               Antenna height (ft) 9.84, Height (ft) 3.28,
                           Clutter height (ft) 0, Range (mi) 18.64
    type 20 ft, 6 mi       address carries tx_height=6.096, radius=9.656064
    that link, metric      boxes 6.096 m, 9.656064 km; labels (m), (km)
    switch to metric       the same boxes read 6.096 and 9.656064, in place

`Length (ft)` on the cable box is not one of these: cable is sold in feet
and the catalogue's figures are per 100 ft.
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from sonoran.coverage.engine import PAGE_SIZE, SplatModule
from sonoran.coverage.params import EngineParams

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
CASES = ROOT / "tests" / "unit" / "js" / "planner_units_cases.mjs"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
PARAMS = (STATIC / "planner-params.js").read_text(encoding="utf-8")
RAW = (STATIC / "planner.js").read_text(encoding="utf-8")
PLANNER = "\n".join(
    line
    for line in re.sub(r"/\*.*?\*/", "", RAW, flags=re.S).splitlines()
    if (s := line.strip()) and not s.startswith("//")
)

# The boxes a reader types a height or a distance into, and the kind of
# unit each one follows.
TYPED = {
    "tx_height": "height",
    "rx_height": "height",
    "clutter_height": "height",
    "radius": "distance",
}


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    return node


def test_the_cases_pass_under_node() -> None:
    """The conversions and the round trips, exercised rather than read."""
    done = subprocess.run([_node(), str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


class _AsTheBrowserSends:
    """The engine inputs `toEngineParams` made, in `splat_create` order.

    `EngineParams` converts metres itself. The point here is to run what
    the planner page hands its worker, so these are passed through as
    they came.
    """

    def __init__(self, sent: dict[str, Any]) -> None:
        self.sent = sent
        self.resolution_ippd = int(sent["resolutionIppd"])

    def to_arguments(self) -> tuple[float | int, ...]:
        """Sixteen values, typed as the engine declares them (`AGENTS.md` 9.16.1).

        JSON has one number type, so a latitude of 34 arrives as a whole
        number and `wasmtime` refuses it where the engine wants `f64`.
        """
        p = self.sent
        whole = {"radioClimate", "polarization", "resolutionIppd"}
        order = (
            "lat lon txAltFeet rxAltFeet frequencyMhz erpWatts groundDielectric "
            "groundConductivity atmosphereBending radioClimate polarization conf rel "
            "clutterHeightM radiusKm resolutionIppd"
        ).split()
        return tuple(int(p[key]) if key in whole else float(p[key]) for key in order)


def _made_up_page(index: int) -> bytes:
    """The made-up terrain `test_coverage_engine.py` uses, so hills exist."""
    heights = (np.arange(PAGE_SIZE * PAGE_SIZE, dtype=np.int64) * 7 + index * 101) % 900
    return heights.astype("<i2").tobytes()


def _predict(module: SplatModule, sent: dict[str, Any]) -> str:
    """Run one prediction and return the hash of both rasters."""
    instance = module.instance()
    try:
        with instance.run(cast(EngineParams, _AsTheBrowserSends(sent))) as run:
            for index in range(len(run.pages())):
                run.load_page(index, _made_up_page(index))
            run.run_all_radials()
            run.rasterize()
            raster = run.raster()
    finally:
        instance.close()
    digest = hashlib.sha256()
    digest.update(raster.signal)
    digest.update(raster.mask)
    return digest.hexdigest()


def test_a_link_predicts_the_same_in_either_unit_system() -> None:
    """The measured claim: the same map, not just the same label.

    Every scenario's engine input comes from the browser code, and each
    is run through the engine. The two controls must come out different,
    or an equal pair would prove nothing: one reads the rounded display
    back (6 m becomes 6.0015 m, 10 km becomes 9.994 km) and one hands
    feet on as metres (3.28 times).
    """
    done = subprocess.run(
        [_node(), str(CASES), "--emit"], capture_output=True, text=True, check=True
    )
    sent = json.loads(done.stdout)
    module = SplatModule()
    # Identical inputs are run once. Their maps are then equal by
    # construction, which is what equal inputs mean anyway.
    runs: dict[str, str] = {}
    maps = {}
    for name, params in sent.items():
        key = json.dumps(params, sort_keys=True)
        if key not in runs:
            runs[key] = _predict(module, params)
        maps[name] = runs[key]

    assert maps["typed_in_feet"] == maps["typed_in_metres"], (
        "20 ft typed and 6.096 m typed predict different maps"
    )
    assert maps["feet_link_opened_in_metric"] == maps["typed_in_feet"], (
        "a link made in feet predicts something else when opened in metric"
    )
    assert maps["metres_link_opened_in_imperial"] == maps["metres_link_opened_in_metric"], (
        "a link made in metres predicts something else when opened in imperial"
    )
    assert maps["metres_link_reparsed_in_imperial"] != maps["metres_link_opened_in_metric"], (
        "the engine cannot see the rounded display read back, so the equal "
        "maps above do not show the round trip is exact"
    )
    assert maps["feet_read_as_metres"] != maps["typed_in_feet"], (
        "feet read as metres drew the same map, so the equal maps above prove nothing"
    )


def test_every_typed_box_names_the_unit_it_follows() -> None:
    """The label says the reader's unit, and planner.js sets it."""
    for name, kind in TYPED.items():
        match = re.search(
            rf"<label>[^<]*\(<span data-planner-unit=\"(\w+)\">(\w+)</span>\) "
            rf"<input data-planner=\"{name}\"",
            HTML,
        )
        assert match, f"{name} does not carry a unit word the page can change"
        assert match.group(1) == kind, f"{name} follows {match.group(1)}, not {kind}"
        # The word in the page is the default setting's, before planner.js runs.
        assert match.group(2) == {"height": "ft", "distance": "mi"}[kind]
    assert re.search(r"\((m|km)\) <input data-planner=", HTML) is None, (
        "a planner box still names a fixed metric unit"
    )


def test_the_boxes_convert_through_sonoran_units() -> None:
    """`heightToM` is the conversion on the way in, and the only one."""
    assert "units.heightToM(" in PARAMS
    assert "units.distanceToKm(" in PARAMS
    for name in TYPED:
        assert f"  {name}: " in PARAMS[PARAMS.index("const UNIT_BOXES") :][:300], (
            f"{name} is not one of the boxes that follow the setting"
        )


def test_the_form_reads_and_writes_the_boxes_through_the_conversion() -> None:
    """Each path in and out of a unit box goes through `planner-params.js`."""
    fill = PLANNER[PLANNER.index("function fillForm(") :][:800]
    assert "SonoranPlannerParams.toBox(" in fill, "fillForm writes a box without converting"
    assert "boxHeld[name] = { shown" in fill, "fillForm does not hold the value it wrote"
    read = PLANNER[PLANNER.index("function readForm(") :][:1400]
    assert "boxValue(name)" in read, "readForm reads a unit box without converting"
    share = PLANNER[PLANNER.index("function readShareValues(") :][:700]
    assert "boxValue(name)" in share, "the share link reads a unit box as it is shown"


def test_the_share_link_still_carries_metres() -> None:
    """The link is metric for everybody. See `docs/PLANNER.md` 5.1."""
    assert "const FORM_DEFAULTS = { ...DEFAULTS, radius: DEFAULTS.radius / 1000 };" in PARAMS
    assert "request.radius = request.radius * 1000;" in PLANNER, (
        "the range is no longer read as kilometres"
    )


def test_the_boxes_follow_the_units_setting() -> None:
    """The settings page can change it in another tab."""
    assert "SonoranSettings.onChange(() => showUnitBoxes())" in PLANNER
    assert "holdTyped(name);" in PLANNER, (
        "a typed box is not held on change, so a units switch would re-read it in the new units"
    )


def test_the_metres_echo_is_gone() -> None:
    """It said "this box is in metres", which is no longer true."""
    assert "data-planner-hint" not in HTML
    assert "showHeightHints" not in RAW


def test_the_cable_length_is_not_treated_as_a_units_setting_field() -> None:
    """Cable is sold in feet and `radio/cables.py` is per 100 ft."""
    assert "<label>Length (ft) <input data-cable-length" in HTML, (
        "the cable length changed units; the catalogue is still per 100 ft"
    )
    assert "const FEET_PER_100 = 100;" in PLANNER
    assert "cable" not in PARAMS[PARAMS.index("const UNIT_BOXES") :][:200]
