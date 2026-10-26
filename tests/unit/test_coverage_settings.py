"""The coverage settings panel (#334).

Will asked for one settings button at the top right of the coverage
page, with every choice about the map behind it, and for the defaults to
be the map Logan and Tyler asked for in #315: precise positions only,
routers and repeaters, the uplink layer.

The rules themselves (the defaults, the count, the reset, the address
and the storage) are pure functions in `coverage-settings.js`, and
`js/coverage_settings_cases.mjs` runs them under node. These tests pin
the markup, the wiring and the public embed.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
CASES = ROOT / "tests" / "unit" / "js" / "coverage_settings_cases.mjs"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _html() -> str:
    """The page with its comments taken out, so a note cannot pass a test."""
    return re.sub(r"<!--.*?-->", "", _read("index.html"), flags=re.S)


def _head() -> str:
    html = _html()
    start = html.index("page-head", html.index('data-page="coverage"'))
    return html[start : html.index('id="coverage-options"', start)]


def _panel() -> str:
    html = _html()
    start = html.index('id="coverage-options"')
    return html[start : html.index('<div class="map-shell">', start)]


def test_the_rules_pass_under_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([str(node), str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS the default map is precise only" in done.stdout
    assert "all cases passed" in done.stdout


def test_the_head_holds_one_settings_button_with_a_gear() -> None:
    head = _head()
    assert head.count("<button") == 1, "the head holds more than the settings button"
    button = head[head.index("<button") : head.index("</button>")]
    assert "data-options-open" in button
    assert 'aria-controls="coverage-options"' in button
    assert '<use href="#i-settings"/>' in button
    assert 'data-options-word="Settings"' in button
    assert "data-options-count" in button
    # Opening the panel fetches nothing. Without this the shared
    # `.toggle` handler in app.js drew the whole page again on each open.
    assert "data-no-refresh" in button
    assert '<symbol id="i-settings"' in _read("index.html")
    for moved in ("data-coverage-layers", "data-coverage-siteset", "<select"):
        assert moved not in head, f"{moved} is still in the page head"


def test_every_choice_is_in_the_panel() -> None:
    panel = _panel()
    for control in (
        "data-coverage-siteset",
        "data-coverage-approx",
        "data-coverage-approx-note",
        "data-coverage-layers",
        "data-coverage-views",
        "data-coverage-opacity",
        "data-coverage-roles",
        "data-coverage-heard",
        "data-coverage-moving",
        "data-coverage-circles",
        "data-coverage-reset",
    ):
        assert control in panel, f"{control} is not in the settings panel"
    assert "Include approximate positions" in panel
    assert "Reset to default" in panel


def test_the_approximate_toggle_starts_off() -> None:
    box = re.search(r"<input[^>]*data-coverage-approx[^>]*>", _panel())
    assert box, "no approximate toggle"
    assert "checked" not in box.group(0)


def test_last_heard_starts_at_any_time() -> None:
    panel = _panel()
    heard = panel[
        panel.index("data-coverage-heard") : panel.index(
            "</select>", panel.index("data-coverage-heard")
        )
    ]
    assert re.search(r'<option value="any" selected>', heard)
    assert [value for value in re.findall(r'value="([^"]+)"', heard)] == ["any", "24h", "7d"]


def test_moving_nodes_say_which_roles_stand_for_them() -> None:
    """The page has no measure of movement, only the role. It says so."""
    assert "Tracker and TAK tracker" in _panel()
    assert "const MOVING_ROLES = ['TRACKER', 'TAK_TRACKER'];" in _read("coverage-settings.js")


def test_a_map_the_run_did_not_compute_is_never_offered() -> None:
    """With the server flag off, the toggle is disabled and says why."""
    script = _read("coverage.js")
    assert (
        "'Not computed on this server. An operator can turn it on with '\n"
        "    + 'COVERAGE_INCLUDE_APPROXIMATE.'"
    ) in script
    block = script.split("function drawApproximate(")[1].split("\n  }\n")[0]
    assert "box.disabled = !state.approximateAvailable;" in block
    assert "note.textContent = NOT_COMPUTED;" in block


def test_the_legend_and_the_stats_say_which_map_is_shown() -> None:
    html = _html()
    legend = html[html.index("data-coverage-legend ") :]
    assert "data-coverage-legend-map" in legend[: legend.index("</div>")]
    assert html.index("data-coverage-which") < html.index("data-coverage-stats")
    block = _read("coverage.js").split("function drawWhich(")[1].split("\n  }\n")[0]
    assert "SETTINGS.mapWords(baseLabel(), state.approximate, state.floor)" in block


def test_the_map_choices_go_in_the_address_without_a_history_entry() -> None:
    script = _read("coverage.js")
    block = script.split("function writeAddress(")[1].split("\n  }\n")[0]
    assert "history.replaceState(null, '', hash)" in block
    assert "SETTINGS.toHash(settingsNow())" in block


def test_the_settings_rules_load_before_the_page() -> None:
    text = TestClient(create_app(Settings(_env_file=None))).get("/").text
    assert text.index("static/coverage-settings.js") < text.index("static/coverage.js")


def test_the_badge_counts_settings_not_controls() -> None:
    """Three hidden roles are one filter, so the page gives the count."""
    app = _read("app.js")
    block = app.split("function optionsChanged(")[1].split("\n}\n")[0]
    assert "panel.dataset.optionsChanged" in block
    assert "'data-options-changed'" in app.split("function wireOptions(")[1].split("\n}\n")[0]
    assert "panel.dataset.optionsChanged = String(" in _read("coverage.js")


def test_the_public_embed_has_no_settings_and_no_approximate_option() -> None:
    """The public embed shows the precise infrastructure map and nothing
    else (AGENTS.md 9.25, 9.27). The panel is the dashboard's alone."""
    for name in ("embed-coverage.html", "embed-coverage.js"):
        text = _read(name).lower()
        for word in ("data-options", "settings", "approx", "site_set", "siteset"):
            assert word not in text, f"{name} carries {word!r}"
    page = _read("embed-coverage.html")
    assert "coverage-settings.js" not in page
    assert 'src="../static/coverage.js' not in page
