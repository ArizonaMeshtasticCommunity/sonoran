"""The single-key shortcuts can be turned off, and F cannot (#147 item 2).

`map-watch.js` binds F, T, E, 1, 2 and Space with no modifier. For a
speech-input user a stray recognised word is a keypress, so a page that
acts on single characters is a page that acts on things they did not
mean. WCAG 2.1.4 accepts any one of three remedies: require a modifier,
allow remapping, or allow turning them off.

**Turning them off is the one taken, and that was a product call.**
Requiring a modifier would quietly ruin what watch mode is for — it is a
wall-display mode and one-handed keys are most of why it is pleasant.
Remapping is a great deal of machinery for five keys nobody has asked to
rebind. An off switch costs nothing to anyone who does not need it. The
reasoning is recorded on #147 and in the code.

**F is exempt and stays bound**, because it is the only way out of
fullscreen by keyboard and a user who cannot leave is worse off than one
who never had the shortcut.

Measured in a headless browser, with the stored preference set before
any script ran:

    setting=null  F enters: true  T: traffic -> traces  (fired)    F leaves: true
    setting=on    F enters: true  T: traffic -> traces  (fired)    F leaves: true
    setting=off   F enters: true  T: traffic -> traffic (ignored)  F leaves: true
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
WATCH = (STATIC / "map-watch.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def _handler() -> str:
    start = WATCH.index("document.addEventListener('keydown'")
    return WATCH[start : WATCH.index("if (key === 't'", start)]


def test_there_is_a_switch_at_all() -> None:
    assert "sonoran.watchShortcuts" in WATCH, "nothing stores the preference"


def test_f_is_checked_before_the_switch_is() -> None:
    """The exemption, expressed as ordering.

    If the gate ran first, turning the shortcuts off would strand a
    keyboard user in fullscreen.
    """
    body = _handler()
    assert "if (!shortcutsOn()) return;" in body, "the gate is not in the handler"
    assert body.index("key === 'f'") < body.index("if (!shortcutsOn())"), (
        "the off switch is tested before F, so turning the shortcuts off "
        "removes the only keyboard way out of fullscreen"
    )


def test_the_switch_is_reachable_in_the_page() -> None:
    """A mechanism nobody can find is not a mechanism."""
    assert "data-watch-shortcuts" in HTML, "the control is not in the page"
    assert re.search(r"<label[^>]*watch-shortcut-toggle", HTML), (
        "the checkbox has no label, so it is unnamed to a screen reader"
    )


def test_the_control_is_wired_to_the_store() -> None:
    assert "shortcutBox.checked = shortcutsOn()" in WATCH, (
        "the control does not show the stored state, so it can say 'on' while the shortcuts are off"
    )
    assert "setShortcuts(shortcutBox.checked)" in WATCH, "changing it stores nothing"


def test_storage_refusing_does_not_lose_the_feature() -> None:
    """Private browsing and blocked site data must not break the map."""
    start = WATCH.index("const shortcutsOn")
    body = WATCH[start : start + 700]
    assert "catch" in body and "return true" in body, (
        "a browser that refuses localStorage gets an exception or loses the shortcuts entirely"
    )


def test_the_declarations_come_before_their_use() -> None:
    """A temporal dead zone here is a runtime crash, not a syntax error.

    The first draft declared these below the wiring that calls them;
    `node --check` passes on that and the page throws on load.
    """
    assert WATCH.index("const shortcutsOn") < WATCH.index("shortcutBox.checked = shortcutsOn()")
    assert WATCH.index("const shortcutsOn") < WATCH.index("if (!shortcutsOn()) return;")
