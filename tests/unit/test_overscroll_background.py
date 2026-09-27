"""The colour behind the page is the page's colour, in both themes (#253).

On an iPad, scrolling up past the top of any page showed a band about
25 px tall. That is the rubber-band overscroll: Safari shows what lies
behind the document, and tints the strip above it with `theme-color`.
Measured in WebKit with iPad descriptors before the change:

    html          transparent in both themes (only `body` carried --bg)
    theme-color   #17100b in both themes, so wrong in the light one

These tests pin all three colours -- `html`, `body` and `theme-color` --
to the same `--bg` token, so they cannot drift apart again. The e2e
journey "the colour behind the page is the page colour" measures the
computed values in a browser, including after a theme switch.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
TOKEN = re.compile(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;")


def _rule(selector: str) -> str:
    """The declarations of the first top-level rule for `selector`."""
    match = re.search(rf"^{re.escape(selector)}\s*\{{(.*?)^\}}", CSS, flags=re.S | re.M)
    assert match, f"app.css has no top-level `{selector}` rule"
    return match.group(1)


def _tokens(opening: str) -> dict[str, str]:
    start = CSS.index(opening)
    return dict(TOKEN.findall(CSS[start : CSS.index("\n}", start)]))


DARK_BG = _tokens(":root {")["bg"]
LIGHT_BG = _tokens(':root[data-theme="light"] {')["bg"]


def _declared_background(selector: str) -> str | None:
    """What `background` the rule sets, with comments taken out first."""
    body = re.sub(r"/\*.*?\*/", "", _rule(selector), flags=re.S)
    found = re.search(r"(?<![\w-])background(?:-color)?\s*:\s*([^;]+);", body)
    return found.group(1).strip() if found else None


def test_the_root_carries_the_page_colour() -> None:
    """`html` must paint --bg itself, not rely on borrowing `body`'s."""
    assert _declared_background("html") == "var(--bg)", (
        "`html` does not set its background to var(--bg), so the area an "
        "iPad shows during overscroll is not pinned to the page colour"
    )


def test_the_body_and_the_root_use_one_token() -> None:
    """Two tokens would be two colours the first time either moved."""
    assert _declared_background("body") == _declared_background("html"), (
        "`html` and `body` set different backgrounds, so an overscroll can "
        "show a band of one against the other"
    )


def test_the_theme_colour_is_the_page_colour() -> None:
    """The pre-paint script writes each theme's --bg, as literals, into theme-color."""
    literals = re.search(
        r"setAttribute\('content',\s*light\s*\?\s*'(#[0-9a-fA-F]{6})'\s*:\s*'(#[0-9a-fA-F]{6})'\)",
        INDEX,
    )
    assert literals, "the pre-paint script no longer sets theme-color from the theme"
    light, dark = (value.lower() for value in literals.groups())
    assert light == LIGHT_BG.lower(), f"light theme-color {light} is not the light --bg {LIGHT_BG}"
    assert dark == DARK_BG.lower(), f"dark theme-color {dark} is not the dark --bg {DARK_BG}"
    fallback = re.search(r'<meta name="theme-color" content="(#[0-9a-fA-F]{6})"', INDEX)
    assert fallback and fallback.group(1).lower() == DARK_BG.lower(), (
        "the theme-color written in the markup is not the dark --bg"
    )


def test_the_meta_stands_before_the_script_that_sets_it() -> None:
    """A script cannot find an element the parser has not reached yet."""
    head = INDEX[: INDEX.index("</head>")]
    assert head.index('<meta name="theme-color"') < head.index("<script"), (
        "theme-color comes after the pre-paint script, so the script finds "
        "nothing and the fixed dark value stays on a light page"
    )


def test_a_theme_switch_updates_the_theme_colour() -> None:
    """Otherwise the strip keeps the old theme until the next reload."""
    start = APP.index("function applyTheme(mode) {")
    body = APP[start : APP.index("\n}\n", start)]
    assert 'meta[name="theme-color"]' in body and "'--bg'" in body, (
        "applyTheme no longer reads --bg for theme-color"
    )
    assert re.search(r"\.setAttribute\('content',\s*colour\)", body), (
        "applyTheme reads --bg but never writes it into theme-color"
    )
