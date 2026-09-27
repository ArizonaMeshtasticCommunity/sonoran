"""The page's own structure: `<main>` must be inside `.shell`.

This exists because of a bug I shipped into a branch and nearly merged.

Rewriting the menu footer removed a `<div class="menu-field">` and left its
closing tag behind. One stray `</div>` closed `.shell` early, so `<main>`
became a child of `<body>` instead of a flex sibling of the sidebar. Every
unit test passed. Nothing looked wrong on screen at a glance.

What broke was `position: sticky` on the sidebar. A sticky element sticks
within its containing block, and with `<main>` outside the flex row,
`.shell` was only as tall as the viewport -- so the sticky range was zero
and the sidebar scrolled away. Measured in a real browser: `.shell` was
1050 px on the branch against 3732 px on main.

The e2e journey that covers this only measures after a planner prediction
completes, which had not happened in CI for at least four runs, so the
assertion was dormant. A structural check costs nothing and does not
depend on a prediction finishing.
"""

import re
from pathlib import Path

HTML = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "index.html"
).read_text(encoding="utf-8")


def _region(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def test_main_is_inside_the_shell() -> None:
    """The one assertion that would have caught it.

    Counted rather than parsed: between `.shell` opening and `<main>`, the
    div tags must leave exactly one open -- the shell itself. Zero means
    something closed it early and `<main>` is a sibling of the sidebar's
    parent instead of the sidebar.
    """
    region = _region(HTML, '<div class="shell">', '<main class="content"')
    opens = len(re.findall(r"<div\b", region))
    closes = len(re.findall(r"</div>", region))
    assert opens - closes == 1, (
        f"{opens} <div> and {closes} </div> before <main>, so the shell is "
        f"{'closed early' if opens - closes < 1 else 'left doubly open'} -- "
        "<main> will not be a flex sibling of the sidebar and the sticky "
        "sidebar loses its containing block"
    )


def test_the_sidebar_can_still_stick() -> None:
    """The properties the layout depends on, so a rewrite cannot drop them.

    `height` and `top` together are what make the gap impossible: a sticky
    box with no height, or no offset, does not stick.
    """
    css = re.sub(
        r"/\*.*?\*/",
        "",
        (
            Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8"),
        flags=re.S,
    )
    rule = css[css.index(".sidebar {") :]
    rule = rule[: rule.index("}")]
    assert "position: sticky" in rule, "the sidebar is no longer sticky"
    assert "top: 0" in rule, "a sticky box with no offset does not stick"
    assert "height: 100svh" in rule, "a sticky box with no height cannot leave a gap to measure"
    shell = css[css.index(".shell {") :]
    shell = shell[: shell.index("}")]
    assert "display: flex" in shell, "the shell is no longer the flex row the sidebar sticks in"


def test_every_page_section_is_closed() -> None:
    """The same class of error, one level out.

    An unclosed `<section class="page">` would nest the pages inside each
    other, and the router would show two at once.
    """
    opens = len(re.findall(r'<section class="page"', HTML))
    closes = len(re.findall(r"</section>", HTML))
    assert opens <= closes, f"{opens} page sections and only {closes} </section>"


def test_the_aside_and_the_shell_both_close() -> None:
    body = _region(HTML, '<div class="shell">', "</body>")
    for tag in ("aside", "main"):
        assert body.count(f"</{tag}>") >= 1, f"<{tag}> is never closed"
