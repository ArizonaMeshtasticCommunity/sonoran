"""The planner reads the radio climate from the site (#239).

`tests/unit/js/planner_climate_cases.mjs` exercises the browser code
against the shipped data. This file runs it, and holds the shapes the
page needs: where the climate is shown, and that Simple uses it.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
CASES = ROOT / "tests" / "unit" / "js" / "planner_climate_cases.mjs"
PLANNER = (STATIC / "planner.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_the_cases_pass_under_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([str(node), str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


def _body(name: str) -> str:
    start = PLANNER.index(f"function {name}(")
    return PLANNER[start : PLANNER.index("\n}\n", start)]


def test_every_run_answers_the_climate_before_the_engine() -> None:
    """A coverage run and a single link both go through `siteClimate`.

    `toEngineParams` throws on `auto`, so a path that skipped this would
    fail loudly rather than predict on a guess. This pins that both paths
    ask first.
    """
    for name in ("runCoverage", "runLink"):
        body = _body(name)
        assert "siteClimate(" in body, f"{name} does not read the site's climate"
        assert body.index("siteClimate(") < body.index("toEngineParams("), name


def test_the_page_asks_for_a_square_and_never_for_a_point() -> None:
    """The planner sends no site to the server (PLANNER.md 2)."""
    assert "api/climate/page/" in PLANNER
    assert "api/climate/classes" in PLANNER
    assert "api/climate?" not in PLANNER


def test_the_climate_is_said_beside_the_result_in_simple_too() -> None:
    """The summary carries the line, and the summary is shown in both modes."""
    assert "climateLine(state.climate)" in _body("writeSummary")
    assert "describeClimate(" in _body("climateLine")
    assert "data-planner-climate-note" in HTML


def test_the_auto_choice_is_offered_first_in_advanced() -> None:
    body = _body("wirePlanner")
    assert "CLIMATE_AUTO" in body
