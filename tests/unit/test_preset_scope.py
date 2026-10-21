"""Every page says whether the global preset applies to it (#232).

Tyler's second point on #232: "dim filters that are not applicable to the
page you're one [sic] (such as node name/number on the gaps page)". The
site has one global filter -- the preset -- so the faithful version is to
say when the page in view ignores it.

Saying that is a CLAIM, and these cases exist because three different ways
of working it out automatically each got a page wrong:

- diffing the API requests between the two presets said `coverage` ignores
  it, when coverage obeys it completely (`state.preset` drives the tile
  URL, the node overlay, the legend and the summary). It measured as inert
  only because that instance had no published coverage run, so the path
  never ran;
- grepping each page function for the store said `stats` ignores it, and
  the leaderboards read it from another function;
- looking for which modules mention the store says `chat` ignores it, and
  chat filters its sections client-side.

Getting it wrong on coverage would tell somebody the preset is doing
nothing while it decides which mesh their map shows. So each page declares,
and the case below fails when a new page does not.

Since #383 the menu has no preset switch (Will: "the settings to be the
only place to change the presets"). The same lists now decide which pages
carry a line under their heading that names the preset and links to
Settings.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def _set(name: str) -> set[str]:
    match = re.search(rf"const {name} = new Set\(\[(.*?)\]\)", APP, re.S)
    assert match, f"{name} is gone"
    return set(re.findall(r"'([a-z]+)'", match.group(1)))


def _declared_pages() -> set[str]:
    return set(re.findall(r"^PAGES\.(\w+) = ", APP, re.M))


def test_every_page_is_classified_exactly_once() -> None:
    """The case that makes the note trustworthy.

    A page missing from both lists defaults to "the preset applies", which
    is the safe direction but still a guess; a page in both is a
    contradiction. Either way somebody has to decide, and this says so by
    name rather than letting the note be quietly wrong.
    """
    pages = _declared_pages()
    applies = _set("PRESET_PAGES")
    free = _set("PRESET_FREE_PAGES")

    missing = pages - applies - free
    assert not missing, (
        f"these pages do not say whether the preset applies to them: {sorted(missing)}. "
        "Add each to PRESET_PAGES or PRESET_FREE_PAGES -- the note beside the "
        "switch is a claim about what the reader is looking at, so it cannot be guessed."
    )
    both = applies & free
    assert not both, f"these pages are in both lists: {sorted(both)}"
    unknown = (applies | free) - pages
    assert not unknown, f"these are classified but are not pages: {sorted(unknown)}"


def test_coverage_is_on_the_right_side() -> None:
    """Named, because this is the one a measurement got wrong.

    `state.preset` drives `api/coverage/tiles/<stamp>/<preset>/…`, the node
    overlay, the legend and the summary. A run-less instance makes it look
    inert, which is how it ended up in the wrong column of a comment on the
    issue before being corrected.
    """
    assert "coverage" in _set("PRESET_PAGES"), (
        "coverage was moved to the preset-free list. It obeys the preset -- check "
        "`drawPresets` and the tiles URL in coverage.js before changing this."
    )
    coverage = (STATIC / "coverage.js").read_text(encoding="utf-8")
    assert "preferredPreset" in coverage, (
        "coverage no longer consults the menu's preset, so this classification is stale"
    )


def test_chat_and_stats_are_on_the_right_side() -> None:
    """The two the other two instruments got wrong."""
    applies = _set("PRESET_PAGES")
    assert "chat" in applies, "chat asks the server for one preset (#313)"
    assert "stats" in applies, "the leaderboards are drawn per preset"


def test_the_single_subject_pages_are_preset_free() -> None:
    """One node, one packet, one link, one traceroute.

    The thing is already chosen, so there is nothing for a preset to narrow.
    """
    free = _set("PRESET_FREE_PAGES")
    for name in ("node", "packet", "link", "traceroute"):
        assert name in free, f"{name} shows one subject; the preset has nothing to narrow"


def test_the_note_exists_and_is_kept_in_step() -> None:
    # Called from `render`, which runs on every page change, so the note
    # cannot describe the page the reader just left.
    assert "function drawPresetScope" in APP, "nothing writes the note"
    start = APP.index("async function render(name)")
    assert "drawPresetScope(name)" in APP[start : start + 400], (
        "the note is not updated when the page changes"
    )


def _scope_body() -> str:
    # The note's maker and its writer, read together.
    pattern = (
        r"function presetScopeNote\(page\) \{(.*?)\nfunction drawPresetScope\(name\) \{(.*?)\n\}"
    )
    match = re.search(pattern, APP, re.S)
    assert match, "presetScopeNote or drawPresetScope is gone"
    return match.group(1) + match.group(2)


def test_the_note_is_on_the_page_not_in_the_menu() -> None:
    """Will (#383): the presets are changed on the Settings page only.

    The note sat under the menu's switch. With the switch gone a reader
    still has to be able to tell which preset a page shows and where to
    change it (AGENTS.md 3B), so the note moved onto the page, under its
    heading, and it links to Settings.
    """
    html = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
    menu = html[html.index('<div class="site-menu"') : html.index("</aside>")]
    assert "data-preset-scope" not in menu, "the preset note is still in the menu"
    body = _scope_body()
    assert "page-head" in body, "the note is not placed under the page heading"
    assert "href: '#settings'" in body, "the note does not link to the Settings page"
    assert "Change" in body and "in Settings" in body, "the note does not say where to change it"


def test_a_one_preset_page_says_which_preset_it_shows() -> None:
    """Coverage and gaps draw one preset under "All" or several.

    The words are the ones in the issue thread: "Showing Medium Fast.
    This page shows one preset at a time." The planner is not given the
    note, because its own "Modem preset" box names the preset it opens
    on, and the reader may change that box without changing the site's.
    """
    body = _scope_body()
    # "preset" is its own element, so its glossary button sits beside it.
    assert "Showing ${" in body and "This page shows one `, word('preset')," in body
    assert "' at a time. '" in body
    assert "SonoranPreset.single()" in body, "the note does not name the preset drawn"
    assert "name === 'planner'" in body or "'planner'" in body, (
        "the planner would get a note that its own preset box can contradict"
    )


def test_the_preset_free_pages_get_no_note() -> None:
    """With no switch in view, "Not used on this page" explains nothing."""
    assert "Not used on this page." not in APP, (
        "a page the preset does not reach still says so, beside no control"
    )


def test_it_is_a_quiet_note() -> None:
    """It explains the page, so it must not read as a warning."""
    assert ".preset-scope" in CSS, "the note has no styling"
    scope = re.search(r"\.preset-scope\s*\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
    assert scope, "the note rule is gone"
    assert "var(--muted)" in scope.group(1), (
        "the note is not muted, so it reads as a warning rather than an aside"
    )
