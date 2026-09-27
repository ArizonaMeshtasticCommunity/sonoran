"""The weekly check-in page: streaks, and what it says when it cannot tell.

`docs/design/2026-09-26-ux-overhaul.md` §6.3. The arithmetic is tested in
`test_meshnet_streaks.py`; the wording rules are exercised under node in
`tests/unit/js/meshnet_streak_cases.mjs`. What is pinned here is the
page: that it reads the rules from the shared module rather than growing
its own copy, that the module is loaded before the file that reads it,
and that the three empty states stay three different sentences.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import STATIC_DIR, create_app
from sonoran.config import Settings

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "unit" / "js" / "meshnet_streak_cases.mjs"


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """The source with comments stripped, so a rule cannot pass by being discussed."""
    text = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.S)
    return "\n".join(
        line
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("//")
    )


def test_the_comment_stripper_works() -> None:
    """Positive control. Without this, every assertion below could be vacuous."""
    code = _code("meshnet.js")
    assert "function streakWord" in code, "the stripper removed real code"
    assert "five bugs in this repository" not in code.lower(), "comments are leaking through"


def test_the_cases_pass_under_node() -> None:
    """The wording rules, exercised rather than read."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([str(node), str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_module_loads_before_the_page_that_reads_it() -> None:
    """`app.js` reads `window.SonoranMeshnet` at the top level of its section.

    Loaded the other way round the constant is `undefined` and every
    render of the page throws -- and a page that throws while rendering
    still looks like a page, which is how a live map shipped broken
    beside "23/23 journeys passed".
    """
    html = TestClient(create_app(Settings(_env_file=None))).get("/").text
    assert html.index('src="static/meshnet.js') < html.index('src="static/app.js')


def test_the_page_does_not_compute_a_streak_of_its_own() -> None:
    """The count comes from the server, not from the weeks on screen.

    A browser counting the weeks it was handed reports a 30-week run as
    however many weeks the reader selected -- 4, 8 or 26 -- and calls it
    a measurement. The plan puts the aggregate server-side for this
    reason (§6.3).
    """
    code = _code("app.js")
    section = code[code.index("PAGES.meshnet = async") :]
    section = section[: section.index("\n};")]
    assert "streak_weeks" not in section, "the page is deriving a streak instead of reading one"
    # And the whole check-in section, helpers included, reads the numbers
    # rather than counting weeks.
    whole = code[
        code.index("const MESHNET = window.SonoranMeshnet") : code.index("function redrawLiveTable")
    ]
    assert "MESHNET.streakWord" in whole
    assert "MESHNET.absenceWord" in whole
    for forbidden in ("+= 1", "++", "reduce("):
        assert forbidden not in whole, f"{forbidden} in the check-in section looks like arithmetic"


def test_the_page_never_renders_a_missing_count_as_a_number() -> None:
    """`Number(null)` is 0, and this page states counts about people.

    Every count on the page goes through `SonoranMeshnet.counted`, which
    answers null for anything that is not a whole number, or through
    `count()`, which draws a dash for null.
    """
    code = _code("meshnet.js")
    assert "Number.isInteger(value) ? value : null" in code
    # The three readers of a wire count all go through it.
    for reader in ("streakWord", "absenceWord", "weekWord", "messagesTruncated", "streakDetail"):
        body = code[code.index(f"function {reader}(") :]
        body = body[: body.index("\n  }")]
        assert "counted(" in body, f"{reader} reads a count without the guard"


def test_an_absence_is_worded_as_an_observation() -> None:
    """The plan's own risk: a node that was off must not read as "missed".

    The word is checked in the source as well as in the node cases,
    because this is the assertion somebody will break by "improving the
    copy" without opening the case file.
    """
    code = _code("meshnet.js")
    assert "No message found this week" in code
    assert "No message yet this week" in code
    assert "missed" not in code.lower(), "an absence is an observation, not a verdict"
    page = _code("app.js")
    section = page[page.index("function absenceRow(") :]
    section = section[: section.index("\n}")]
    assert "MESHNET.absenceWord" in section
    assert "missed" not in section.lower()


def test_an_unfinished_week_is_not_a_broken_streak() -> None:
    """Rule 5, from the browser's side.

    `absenceWord` takes the in-progress flag precisely so the current
    week cannot be reported as a lapse. Dropping the argument would make
    every node look lapsed each Monday morning, and the page would still
    render.
    """
    code = _code("meshnet.js")
    assert "function absenceWord(entry, inProgress)" in code
    assert "tone: 'pending'" in code
    page = _code("app.js")
    assert "MESHNET.absenceWord(entry, inProgress)" in page
    assert "absenceRow(entry, week.in_progress)" in page


def test_the_three_empty_states_are_three_sentences() -> None:
    """ "Cannot tell", "nothing qualifies" and "this week is empty".

    Each is a different fact and none of them is a zero. The server
    distinguishes the first two with `streaks` and `text_storage`; the
    third is a week that is drawn rather than omitted.
    """
    code = _code("meshnet.js")
    assert "not being stored" in code
    assert "No check-in found" in code
    page = _code("app.js")
    assert "MESHNET.noAssessmentWord(data)" in page
    assert "No message carries ${data.tag}" in page


def test_the_week_range_is_formatted_on_the_boundary_it_is_counted_on() -> None:
    """A week boundary is a definition, not a moment somebody experienced.

    Every other stamp on the site is in the mesh's own zone, which is
    right for a time and wrong for this: Monday 00:00 UTC is Sunday 17:00
    in Arizona, so `DATE` drew the week beginning Monday 21 September as
    "Sep 20 - Sep 27" -- eight days wide, starting on a Sunday, for a
    week the server calls Monday to Sunday. Measured on the running page.
    """
    code = _code("app.js")
    assert "const WEEK_DATE = new Intl.DateTimeFormat(undefined, {" in code
    week = code[code.index("function meshnetWeek(") :]
    week = week[: week.index("\n}")]
    assert "WEEK_DATE.format" in week
    assert "DATE.format" not in week.replace("WEEK_DATE.format", ""), (
        "the week range is back on the local-time formatter"
    )
    # And the local weekday is derived rather than written, because
    # "Sunday at 5pm" is wrong for any deployment east of Greenwich.
    assert "const WEEK_LOCAL = new Intl.DateTimeFormat(undefined, {" in code
    assert "weekday: 'long'" in code


def test_the_page_says_how_far_the_runs_were_counted() -> None:
    """A run that reaches the floor of the read is a lower bound.

    The `+` is the whole difference between "52 weeks" and "at least 52
    weeks", and the note under the controls says where the read starts so
    the mark means something.
    """
    html = TestClient(create_app(Settings(_env_file=None))).get("/").text
    section = html[html.index('data-page="meshnet"') :]
    section = section[: section.index("</section>")]
    assert "data-meshnet-note" in section
    page = _code("app.js")
    assert "Runs are counted back to ${WEEK_DATE.format(new Date(data.streaks.floor_week))}" in page


def test_the_week_summary_can_wrap_at_320px() -> None:
    """A date range, a state and a count on one flex row.

    An e2e journey walks all fourteen pages at 320 px and fails on any
    sideways document scroll, and a flex row that cannot wrap is the
    usual way that happens. Measured at 320, 390, 834 and 1440: no
    sideways scroll at any of them.
    """
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    summary = css[css.index(".week > summary {") :]
    summary = summary[: summary.index("}")]
    assert "flex-wrap: wrap" in summary
    for row in (".check-in, .absence {", ".check-in > :first-child, .absence > :first-child {"):
        block = css[css.index(row) :]
        block = block[: block.index("}")]
        assert "wrap" in block or "min-width: 0" in block, f"{row} cannot shrink"
