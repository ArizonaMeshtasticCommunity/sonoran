"""No page carries a preset line under its heading (Will, 2026-10-22).

#398 made the Settings page the only place to change the presets (part of
#383), and put one line under the heading of every page the preset
narrows: "Preset: Medium Fast · Change in Settings", or "Showing Medium
Fast. This page shows one preset at a time. Change it in Settings".

Will, on seeing it: "I think it looks really good but I think putting
"Preset: i Medium Fast · Change in Settings" on the top of every page is
excessive. Can you remove it from the header of every page?"

So the line is gone, with everything that existed only to write it: the
writer, the per-page lists that decided which line a page got, the
`data-preset-shown` reports the map, the graph and coverage made for it,
and its style. The rest of #398 stays: the menu has no preset switch,
Settings is the only control, and a page with nothing to show says to
choose another preset "in Settings".
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def _bare(path: Path) -> str:
    """The file without its comments, so a note about history is not a hit."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        return re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    if path.suffix == ".js":
        text = re.sub(r"(?m)^\s*//.*$", "", text)
    return text


def _front_end() -> dict[str, str]:
    # Ours, not the vendored tools under vendor/, keyed by path so two
    # files with one name cannot hide each other.
    files = sorted(
        path
        for path in STATIC.rglob("*")
        if path.suffix in {".js", ".html", ".css"}
        and "vendor" not in path.relative_to(STATIC).parts
    )
    assert (STATIC / "app.js") in files, f"app.js is not under {STATIC}"
    return {str(path.relative_to(STATIC)): _bare(path) for path in files}


def test_no_page_has_a_preset_line() -> None:
    """Will: "Can you remove it from the header of every page?"."""
    for name, text in _front_end().items():
        for mark in ("data-preset-scope", "preset-scope", "presetScopeNote", "drawPresetScope"):
            assert mark not in text, f"{name} still writes the preset line ({mark})"


def test_no_page_says_the_line_s_words() -> None:
    """Both forms of the line, in the words #398 gave them."""
    for name, text in _front_end().items():
        for words in (
            "Change in Settings",
            "Change it in Settings",
            "This page shows one ",
            "Showing ${SonoranLabels.presetLabel(",
        ):
            assert words not in text, f"{name} still says {words!r}"


def test_pages_no_longer_report_the_preset_they_drew() -> None:
    """The map, the graph and coverage set `data-preset-shown` only for the line."""
    for name, text in _front_end().items():
        assert "presetShown" not in text, f"{name} still reports the preset it drew"
        assert "data-preset-shown" not in text, f"{name} still reads the preset report"


def test_nothing_is_left_that_only_the_line_used() -> None:
    """The lists that decided which line a page got had no other reader."""
    for name in (
        "PRESET_PAGES",
        "PRESET_FREE_PAGES",
        "ONE_PRESET_PAGES",
        "LINK_PRESET_PAGES",
        "presetAppliesTo",
    ):
        assert not re.search(rf"\b{name}\b", APP), f"{name} is left with no reader"


def test_render_draws_the_page_and_nothing_above_it() -> None:
    start = APP.index("async function render(name)")
    body = APP[start : APP.index("\n}\n", start)]
    assert "await PAGES[name](page)" in body, "render no longer draws the page"
    assert "Preset" not in body, "render still writes something about the preset"


def test_settings_is_still_where_the_preset_is_changed() -> None:
    """What #398 decided and Will kept: one control, on the Settings page."""
    assert "function drawPresetBoxes" in APP, "the Settings page has no preset boxes"
    assert "Choose another in Settings." in APP, (
        "an empty page no longer says where to choose another preset"
    )


def test_the_preset_free_pages_get_no_note() -> None:
    """With no switch in view, "Not used on this page" explains nothing."""
    assert "Not used on this page." not in APP, (
        "a page the preset does not reach still says so, beside no control"
    )
