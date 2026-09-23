"""The map's single-key shortcuts stay out of the way while you type.

`map-watch.js` binds F, T, E, 1, 2 and Space with no modifier. The guard
skipped them when focus was on an `INPUT`, `SELECT` or `TEXTAREA` -- but
those three tags are not the whole set of places a person types.

A `contenteditable` region takes text exactly like a textarea and has
none of those tag names, so every one of those keys reached the map
instead of the text. Typing the word "fete" in one would have toggled
fullscreen twice and stepped the height.

`isContentEditable` is inherited, so it is true inside a nested element
of an editable region as well as on the region itself -- which is what
makes it the right property to read rather than the attribute.

This is only the narrow half of WCAG 2.1.4. The rest of it -- that these
shortcuts have no modifier and no off switch at all -- is a product
decision tracked on #147, and is deliberately not addressed here.
"""

from pathlib import Path

WATCH = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "map-watch.js"
).read_text(encoding="utf-8")


def _guard() -> str:
    """The block between the keydown handler and the first bound key."""
    start = WATCH.index("document.addEventListener('keydown'")
    return WATCH[start : WATCH.index("if (key === 'f'", start)]


def test_an_editable_region_swallows_the_shortcuts() -> None:
    guard = _guard()
    assert "isContentEditable" in guard, (
        "the shortcut guard checks only INPUT/SELECT/TEXTAREA, so every "
        "single-key shortcut fires while somebody types in a "
        "contenteditable region"
    )


def test_the_tag_names_are_still_covered() -> None:
    """The new check is in addition to the old one, not instead of it.

    An `<input>` is not `isContentEditable`, so dropping the tag list
    would reopen the original hole.
    """
    guard = _guard()
    for tag in ("INPUT", "SELECT", "TEXTAREA"):
        assert tag in guard, f"{tag} is no longer guarded"


def test_the_guard_runs_before_any_key_is_bound() -> None:
    """A guard after the first `if (key === ...)` guards nothing."""
    start = WATCH.index("document.addEventListener('keydown'")
    body = WATCH[start:]
    assert body.index("isContentEditable") < body.index("if (key === 'f'"), (
        "the contenteditable check sits after a key is already handled"
    )
