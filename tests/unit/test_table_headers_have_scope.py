"""Column headers say they are column headers.

Measured on `#nodes` before the change: six `<th>`, none with a `scope`.
Implicit column scope usually resolves correctly, but "usually" is
decided by the assistive technology rather than by us (WCAG 1.3.1).

    live      th=6 without-scope=6
    patched   th=6 without-scope=0

`app.js` builds the sortable and non-sortable headers for every table on
the dashboard; `coverage.js` builds twelve of its own, which the first
version of this change missed entirely.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"


def _header_calls(name: str) -> list[str]:
    source = (STATIC / name).read_text(encoding="utf-8")
    # The window has to clear app.js's multi-line headers. At 200 it
    # matched only coverage.js's twelve, and the count assertion below
    # is what caught that -- without it this file would have reported
    # the whole app covered while checking one file.
    return re.findall(r"el\('th',\s*\{(.{0,400}?)\}", source, flags=re.S)


def test_every_header_built_anywhere_declares_column_scope() -> None:
    checked = 0
    for name in ("app.js", "coverage.js"):
        for options in _header_calls(name):
            checked += 1
            assert "scope: 'col'" in options, (
                f"a <th> in {name} is built without scope: {options.strip()[:70]!r}"
            )
    assert checked >= 14, (
        f"only {checked} header builders were found; the search missed some, "
        f"so a pass here would not mean much"
    )
