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

import itertools
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
    """Reachable by exactly one route, and that route is in the menu.

    This asserted `data-nav="settings"` was somewhere in the document,
    which was true of the nav entry Will asked to be removed AND of the
    footer link that replaced it -- so it would have passed on the
    duplicate and on either half of it alone. The link's own properties
    are held in `test_nav_and_global_preset.py`; what matters here is
    that the page this file is about can still be got to at all.
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-page="settings"' in html
    rendered = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    menu = rendered[rendered.index('<div class="site-menu"') : rendered.index("</aside>")]
    assert menu.count('href="#settings"') == 1, (
        f"{menu.count('href="#settings"')} routes to the settings page in the menu; "
        "one is the design and two is the duplicate Will reported"
    )
    assert rendered.count('href="#settings"') == 1, "something outside the menu also links there"
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


# --- the page Will asked to be cut back (2026-09-26) -----------------
#
# > "I think we need to clean up the settings page. You have a lot of
# > extra information in there and I am not sure if all the [text] is
# > needed. Be critical and improve that page."
#
# The rule these cases hold is one sentence: a line stays only if it says
# something the control beside it cannot. Every case below asserts against
# the page with HTML comments stripped, because the comments that record
# each cut quote the cut sentence -- searching the raw file would find the
# explanation of a removal and read it as the removal not having happened.


def _rendered() -> str:
    """index.html as a browser would see it: no comments."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


def _settings_section() -> str:
    page = _rendered()
    start = page.index('data-page="settings"')
    return page[start : page.index("</section>", start)]


def test_the_comment_stripper_leaves_the_page_itself() -> None:
    """Positive control for the three cases below.

    Without it, a stripper that ate the whole section would make every
    "this sentence is gone" assertion pass on an empty string.
    """
    section = _settings_section()
    assert section.count('data-setting="') == 3, "the stripper took the controls with the comments"
    assert "Sensors report in Celsius" in section, "the stripper took the prose as well"
    assert "Be critical" not in section, "comments are leaking through"


def test_no_line_on_the_page_restates_the_buttons_beside_it() -> None:
    """The two sentences that were the controls, written out.

    "Miles and feet, or kilometres and metres" is both option labels in
    order -- a reader who can see the control has read it already. The
    appearance line was worse than redundant: it explained an option
    called "System" while the button next to it says "Follow my device".
    """
    section = _settings_section()
    assert "Miles and feet, or kilometres and metres" not in section, (
        "the distance line still lists the two buttons under it"
    )
    assert "follows what your device is set to" not in section, (
        "the appearance line still explains an option by a name that is not on the screen"
    )
    assert "It is the default, and the one worth keeping" not in section, (
        "the appearance line still argues for an option instead of describing it; which one is "
        "chosen is in the control, and why it is the default is in settings.js"
    )
    assert 'because "530 ft" beats' not in section, (
        "the reason the small-unit threshold exists is still on the page; it belongs beside "
        "SMALL_UNIT_LIMIT in units.js, which is where somebody changing it will look"
    )


def test_what_a_control_cannot_say_is_still_said() -> None:
    """The other half, and the one that makes the cuts safe to keep.

    Each of these is a fact with nowhere else to live:

    * short distances read in the small unit in BOTH systems, so "530 ft"
      after choosing miles is the setting working rather than ignoring you;
    * the mesh reports Celsius and this converts it, which is what a
      reader comparing a node against their own thermometer needs;
    * "Follow my device" keeps following -- app.js reloads the page on a
      `prefers-color-scheme` change, so the site turns dark at sunset
      with the device. The label alone reads as a one-off.
    * the settings never leave this browser, which is also why a phone
      and a laptop disagree about them.
    """
    section = _settings_section()
    assert "Short distances read in feet or metres either way" in section
    assert "Sensors report in Celsius" in section
    assert re.search(r"changes with your device", section), (
        "nothing says the appearance choice keeps following the device"
    )
    assert "sent nowhere" in section and "another device" in section, (
        "the page no longer says where the settings live, so a reader whose phone and laptop "
        "disagree has been told nothing"
    )


def test_the_page_names_options_that_are_actually_on_the_screen() -> None:
    """The failure the appearance line actually had.

    It called the option "System", which is its stored VALUE; the button
    reads "Follow my device". Anything the prose puts in bold is taken to
    be an option label and checked against the words app.js draws, so the
    two cannot drift again.
    """
    section = _settings_section()
    labels = re.findall(r"<strong>([^<]+)</strong>", section)
    assert labels, "no option is named in the prose; this case would pass on an empty page"
    words = _code("app.js")
    block = words[words.index("const SETTING_WORDS = {") :]
    block = block[: block.index("};")]
    for label in labels:
        assert f"'{label}'" in block, (
            f"the page calls an option {label!r}, which is not a word app.js draws: {block}"
        )


def test_every_panel_on_the_page_holds_a_control() -> None:
    """A fourth panel held two paragraphs about `localStorage` and nothing
    to press, which is both the wordiness Will objected to and the reason
    the grid had a lone box on a second row.

    Asserted structurally rather than by name: a prose panel added back
    under any heading fails this, and the facts worth keeping have a home
    -- the page's own subtitle for the reader, settings.js for whoever
    changes the code.
    """
    section = _settings_section()
    # Sliced from one `.panel` to the next rather than matched with a
    # closing tag: a panel holding a `<p>` closes with `</p></div>` and one
    # holding a control closes with `</div></div>`, so a regex written for
    # either shape reads the other as part of its neighbour -- which is how
    # the first draft of this case passed a prose panel put back on purpose.
    opens = [m.start() for m in re.finditer(r'<div class="panel">', section)]
    assert len(opens) == 3, f"{len(opens)} panels found; the page has three settings"
    bounds = [*opens, len(section)]
    for start, end in itertools.pairwise(bounds):
        panel = section[start:end]
        assert "data-setting=" in panel, (
            f"a panel on the settings page has no control in it: {panel[:160]!r}"
        )


def test_the_panels_are_one_row_that_lines_up() -> None:
    """Will asked for the page to look finished, not just to read shorter.

    Three things were wrong and all three are CSS:

    * `.grid.two` is `auto-fit`, so the column count came out of the
      viewport -- three across and an orphan below at 1500 px;
    * `.sub` is styled by `.page-head .sub` only, so inside a panel the
      prose fell back to body size and body colour and was louder than
      both the heading above it and the control below it;
    * the controls sat wherever their panel's prose left them, at three
      different heights across the row.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    grid = css[css.index('.page[data-page="settings"] .grid {') :]
    grid = grid[: grid.index("}")]
    assert "max-width" in grid, "the three cards stretch across the whole of a wide screen"
    assert "repeat(3," in css[css.index('.page[data-page="settings"] .grid {') :][:600], (
        "the column count is still left to the viewport, which is what put a panel on a row alone"
    )
    assert '.page[data-page="settings"] .settings-choice { margin-top: auto; }' in css, (
        "the controls no longer line up across the row"
    )
    sub = css[css.index('.page[data-page="settings"] .panel .sub {') :]
    sub = sub[: sub.index("}")]
    assert "var(--muted)" in sub and "font-size" in sub, (
        "the panel prose is body text again, louder than the control it explains"
    )


def test_the_options_stay_side_by_side() -> None:
    """A wrapping flex row broke between the options, not inside them.

    "Miles and feet" and "Kilometres and metres" are long enough that the
    ROW broke in a three-column page, so one control was two rows tall
    while the two beside it were one -- three shapes for three controls
    that behave identically. A grid row cannot break, so the labels wrap
    inside their own buttons instead.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    # Anchored at the start of a line. `.settings-choice {` is a substring
    # of the page-scoped `.page[data-page="settings"] .settings-choice {`
    # rule, which is the one that came back first and holds two words.
    rule = css[css.index("\n.settings-choice {") :]
    rule = rule[: rule.index("}")]
    assert "display: grid" in rule, "the options are in a wrapping flex row again"
    assert "grid-auto-flow: column" in rule, "the options are not in one row"
    option = css[css.index("\n.settings-option {") :]
    option = option[: option.index("}")]
    assert "white-space: nowrap" not in option, (
        "a label that cannot wrap forces its column wide, which is what broke the row"
    )
