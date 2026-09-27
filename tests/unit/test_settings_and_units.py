"""The settings store and the units formatter (Phase A).

`docs/design/2026-09-26-ux-overhaul.md` §3.1 and §3.2. Nine later items in
the brief read from these two, so what they refuse matters more than what
they do.

Three decisions worth knowing before changing anything here:

* **`localStorage`, not cookies.** Will asked for cookies; decided against
  in §2.3. A cookie rides on every request including every map tile, and
  the server never reads any of this -- units convert in the browser and
  the API keeps SI.
* **The theme keeps its own key.** `index.html` applies it before paint so
  the page does not flash the wrong colours, and every reader who has
  already chosen has it stored there. Moving it into the blob would mean
  parsing JSON before paint, or resetting everybody.
* **The API is not converted.** `distance_km` and `"unit": "km"` stay.
  Converting server-side would make every cached response
  unit-dependent, and `docs/PLANNER.md` records that confusing the
  planner's internal metres with feet overstates every antenna by 3.28x.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
CASES = ROOT / "tests" / "unit" / "js" / "settings_units_cases.mjs"


def _code(name: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("//")
    )


def test_the_comment_stripper_works() -> None:
    """Positive control."""
    code = _code("units.js")
    assert "function distanceFromKm" in code, "the stripper removed real code"
    assert "overstates every antenna" not in code, "comments are leaking through"


def test_the_cases_pass_under_node() -> None:
    """The behaviour, exercised rather than read."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([str(node), str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_store_loads_before_the_formatter_that_reads_it() -> None:
    """Plain scripts, so this is load order."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="static/settings.js') < html.index('src="static/units.js'), (
        "units.js loads first and would see no settings"
    )
    assert html.index('src="static/units.js') < html.index('src="static/app.js'), (
        "app.js loads before the formatter it uses"
    )


def test_a_missing_distance_is_not_zero() -> None:
    """The fifth instance of one bug shape in this repository.

    `Number(null)` is 0 and 0 is finite, so a missing distance rendered as
    "0 ft" -- which claims two nodes are on top of each other when we do
    not know where one of them is. The others were #149 (an unmeasured
    link called weak), #157 (portnum 0 both real and a sentinel), #197
    (role 0 is CLIENT, stored as NULL) and #190 (an absent telemetry field
    read as a reading of zero).
    """
    code = _code("units.js")
    body = code[code.index("function num(value)") :]
    body = body[: body.index("\n  }")]
    assert "value === null" in body, "null is no longer refused before the conversion"
    assert "value === ''" in body, "an empty string is no longer refused"
    # And the half that keeps it honest.
    assert "Number.isFinite" in body, "a real zero would be refused too"


def test_the_api_is_not_asked_to_convert() -> None:
    """Units are a display choice and must not reach the data layer.

    If a route ever starts answering in the reader's units, every cached
    response becomes unit-dependent and the planner's internal metres
    become ambiguous.
    """
    for name in ("units.js", "settings.js"):
        code = _code(name)
        assert "fetch(" not in code, f"{name} talks to the server"
        assert "api/" not in code, f"{name} names an endpoint"


def test_the_planners_own_metres_are_left_alone() -> None:
    """`PLANNER.md`: confusing these overstates every antenna by 3.28x.

    The planner converts metres to feet for the engine. That is arithmetic
    into a model, not a label for a reader, and the units setting must not
    reach it. Asserted by absence: the formatter is not imported there.
    """
    planner = _code("planner-params.js")
    assert "SonoranUnits" not in planner, (
        "the units formatter reached planner-params, where metres are the engine's input"
    )


def test_the_theme_stays_where_the_boot_script_looks() -> None:
    """Moving it would flash the wrong colours, or reset everybody."""
    settings = _code("settings.js")
    assert "const THEME_KEY = 'sonoran.theme'" in settings
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "localStorage.getItem('sonoran.theme')" in html, (
        "the pre-paint script no longer reads the key the store writes"
    )


def test_every_setting_has_a_default_and_a_closed_set_of_values() -> None:
    """A stored value outside the set is what puts the site somewhere no
    control can reach and the reader cannot undo."""
    settings = _code("settings.js")
    block = settings[settings.index("const FIELDS = {") : settings.index("};")]
    for name in ("units", "temperature", "theme"):
        assert f"{name}: {{ values:" in block, f"{name} has no declared values"
    assert block.count("fallback:") == 3, "a setting has no default"


def test_the_settings_page_exists_and_is_reachable() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-page="settings"' in html
    assert 'data-nav="settings"' in html
    app = _code("app.js")
    assert "PAGES.settings" in app, "the page is in the markup and never rendered"


def test_the_settings_page_is_checked_at_phone_width() -> None:
    """Will's bar includes working on a phone.

    The e2e's 320 px sweep names its pages explicitly, so a new page is
    only covered if it is added to that list -- otherwise the sweep passes
    while never looking at it.
    """
    e2e = (ROOT / "tools" / "dev" / "e2e.js").read_text(encoding="utf-8")
    sweep = e2e[e2e.index("every page reflows at 320 CSS px") :]
    sweep = sweep[: sweep.index("must(")]
    assert "'settings'" in sweep, "the settings page is not in the 320px sweep"


def test_the_options_come_from_the_store() -> None:
    """The page cannot offer a value the store would refuse."""
    app = _code("app.js")
    body = app[app.index("function drawSettingChoice") :]
    body = body[: body.index("\nfunction ")]
    assert "SonoranSettings.options(name)" in body, "the page hardcodes its own options"
