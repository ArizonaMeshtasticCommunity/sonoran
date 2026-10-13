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

Getting it wrong on coverage would tell somebody the switch is doing
nothing while it decides which mesh their map shows. So each page declares,
and the case below fails when a new page does not.
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
    assert "data-preset-scope" in HTML, "there is nowhere to say the preset is unused"
    assert "function drawPresetScope" in APP, "nothing writes the note"
    # Called from `render`, which runs on every page change, so the note
    # cannot describe the page the reader just left.
    start = APP.index("async function render(name)")
    assert "drawPresetScope(name)" in APP[start : start + 400], (
        "the note is not updated when the page changes"
    )


def test_it_is_a_note_and_not_a_disabled_control() -> None:
    """The switch is global, so it is never inoperable.

    A dimmed radio group says "you cannot change this", which is false: the
    reader can change it here and it takes effect on the page they go to
    next. Irrelevant and inoperable are different sentences, and only one of
    them is true.
    """
    assert ".preset-scope" in CSS, "the note has no styling"
    scope = re.search(r"\.preset-scope\s*\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
    assert scope, "the note rule is gone"
    assert "var(--muted)" in scope.group(1), (
        "the note is not muted, so it reads as a warning rather than an aside"
    )
    switch = re.search(r"function drawPresetScope\(name\) \{(.*?)\n\}", APP, re.S)
    assert switch and "disabled" not in switch.group(1), (
        "the switch is being disabled. It is global: it always works and always "
        "takes effect where it applies, so disabling it states something untrue."
    )
