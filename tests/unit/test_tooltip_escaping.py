"""A node's name is chosen by whoever owns the radio, so it is never HTML.

Two libraries this dashboard ships take tooltip content as a string and
set `innerHTML` with it:

- Leaflet 1.9.4 `_updateContent`: ``if ("string" == typeof e) t.innerHTML = e``
- ECharts 5.5.1 tooltip:          ``if (U(t)) o.innerHTML = t + a``

Both were being handed a template literal with a node's `display_name`
interpolated into it, so a node named ``<img src=x onerror=...>`` ran
script on this origin. That origin is not a cheap one to lose: the
Config check page holds Web Serial, so script here can reach a radio
plugged into the reader's machine.

The fix is to hand those libraries a DOM node instead, built so every
value lands through `textContent`. These tests hold that line. They are
source checks rather than behaviour checks because the behaviour lives
in a browser, and a source check is what stops the *next* tooltip from
reintroducing the shape.

Both assertions were watched failing against the code before the fix.
"""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"

# The files we write. `vendor/` is somebody else's code and is checked
# by reading it, not by editing it.
OURS = sorted(p for p in STATIC.glob("*.js"))


def _strip_comments(source: str) -> str:
    """Drop block and line comments so prose about a trap is not a hit."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", source)


@pytest.mark.parametrize("path", OURS, ids=lambda p: p.name)
def test_bind_tooltip_is_never_handed_a_template_literal(path: Path) -> None:
    """`bindTooltip` with a backtick string is an innerHTML sink.

    Leaflet renders a string as HTML. Passing an element is the whole
    fix, so the argument must not start a template literal.
    """
    source = _strip_comments(path.read_text())
    offenders = re.findall(r"bindTooltip\(\s*`[^`]*`", source)
    assert not offenders, (
        f"{path.name}: bindTooltip is given a template literal "
        f"{offenders!r}. Leaflet sets innerHTML from a string, and these "
        f"strings carry a node name. Build the tooltip as an element."
    )


@pytest.mark.parametrize("path", OURS, ids=lambda p: p.name)
def test_a_tooltip_formatter_never_returns_interpolated_markup(path: Path) -> None:
    """An ECharts `formatter` must not return a string containing markup.

    The string branch is the only one that injects; returning an element
    is safe. So a `return` inside a formatter that both opens a tag and
    interpolates a value is the shape we refuse.
    """
    source = _strip_comments(path.read_text())
    offenders = []
    for match in re.finditer(r"formatter:\s*\(", source):
        # Read to the end of the formatter's own body, roughly: the next
        # line that closes it at the same indent. Good enough to catch a
        # returned template literal, which is all we are looking for.
        body = source[match.start() : match.start() + 4000]
        for literal in re.findall(r"return\s+(`[^`]*`(?:\s*\+\s*`[^`]*`)*)", body):
            if "${" in literal and re.search(r"<[a-zA-Z/]", literal):
                offenders.append(literal[:120])
    assert not offenders, (
        f"{path.name}: a tooltip formatter returns interpolated markup "
        f"{offenders!r}. ECharts sets innerHTML from a returned string. "
        f"Return an element built with textContent instead."
    )


def test_the_helpers_that_replace_those_strings_use_text_nodes() -> None:
    """The replacements must not quietly become innerHTML themselves."""
    app = (STATIC / "app.js").read_text()
    gaps = (STATIC / "gaps.js").read_text()

    assert "function tooltipLines(" in app, "app.js lost its tooltip helper"
    assert "function nameTooltip(" in gaps, "gaps.js lost its tooltip helper"

    body = app[app.index("function tooltipLines(") :][:900]
    assert "createTextNode" in body, "tooltipLines must put values in as text"
    assert "innerHTML" not in body, "tooltipLines must never set innerHTML"

    body = gaps[gaps.index("function nameTooltip(") :][:600]
    assert "textContent" in body, "nameTooltip must put the name in as text"
    assert "innerHTML" not in body, "nameTooltip must never set innerHTML"
