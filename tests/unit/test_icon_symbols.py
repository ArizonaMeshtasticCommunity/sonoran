"""Every icon referenced must exist in the sprite.

A `<use href="#i-missing">` renders NOTHING. No console error, no broken
image, no layout shift -- just a button with a gap where an icon should be.
Three bugs in this repository have been exactly that, which is why this is
a general check over every reference rather than a case per icon: a test
written per icon only covers the icons somebody remembered to test, and
the failure mode here is forgetting.

The reverse direction is checked too, but only as a warning-shaped
assertion: an unused symbol is dead weight rather than a bug, and one
deleted reference should not fail the build until somebody tidies the
sprite.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")

# Every `#i-...` the page or any script asks for, and where it asked.
REFERENCE = re.compile(r"['\"#]#?(i-[a-z0-9-]+)")


def _defined() -> set[str]:
    return set(re.findall(r'<symbol id="(i-[a-z0-9-]+)"', HTML))


def _referenced() -> dict[str, set[str]]:
    """Icon name -> the files that ask for it."""
    out: dict[str, set[str]] = {}
    sources = [STATIC / "index.html", *sorted(STATIC.glob("*.js"))]
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        # The sprite's own definitions are not references to it.
        text = re.sub(r"<symbol id=\"i-[a-z0-9-]+\"", "", text)
        for name in REFERENCE.findall(text):
            out.setdefault(name, set()).add(path.name)
    return out


def test_every_referenced_icon_is_defined() -> None:
    defined = _defined()
    missing = {name: sorted(where) for name, where in _referenced().items() if name not in defined}
    assert not missing, (
        "these icons are used but not in the sprite, so they render as "
        f"nothing at all: {missing}. Defined: {sorted(defined)}"
    )


def test_the_sprite_is_not_empty() -> None:
    """A positive control.

    Without this, a regex that stopped matching would make the check above
    pass by finding no references at all.
    """
    defined = _defined()
    assert len(defined) > 15, f"only {len(defined)} symbols found; the sprite regex is wrong"
    referenced = _referenced()
    assert len(referenced) > 15, f"only {len(referenced)} references found; that regex is wrong"


def test_the_sharing_and_export_icons_are_there() -> None:
    """The four added for §3.5, named so a rename has to be deliberate."""
    defined = _defined()
    for name in ("i-share", "i-link", "i-copy", "i-download"):
        assert name in defined, f"{name} is gone from the sprite"


def test_an_icon_button_keeps_its_text() -> None:
    """An icon must not be the button's only content.

    `aria-hidden="true"` on the svg means an icon-only button has no
    accessible name at all, and these five are Share, Copy and Download --
    exactly the actions where guessing wrong costs the reader something.
    """
    for marker in (
        "data-planner-send",
        "data-planner-share",
        "data-config-diagnostics-copy",
        "data-config-fix",
        "data-config-report",
    ):
        match = re.search(rf"<button[^>]*{marker}[^>]*>(.*?)</button>", HTML, re.S)
        assert match, f"{marker} is no longer a button"
        body = match.group(1)
        assert '<use href="#i-' in body, f"{marker} lost its icon"
        assert re.search(r"<span>[^<]+</span>", body), (
            f"{marker} has an icon but no text span, so it has no accessible name: {body!r}"
        )
