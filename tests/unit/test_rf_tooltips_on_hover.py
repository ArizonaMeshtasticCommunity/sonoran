"""The RF map builds a tooltip when you hover one, not for every contact.

`drawThings` and `drawStations` clear their layer and rebuild it on every
Live refresh, and each marker was handed a fully built tooltip -- five to
eight elements from `el()` -- whether or not anybody ever hovered it.

Unlike the planner and coverage maps, this one is on a POLL, and the
endpoint it draws from is capped at 5,000 rows
(`api/rf/latest?minutes=...&limit=5000`), so the ceiling is roughly
30,000 elements per refresh.

Measured in a headless browser with 1,000 synthetic ADS-B rows served to
`/api/rf/latest`, counting every `document.createElement` from before any
page script ran:

    live      1001 markers drawn   6129 elements
    patched   1001 markers drawn    121 elements   (-98%)

The equal marker count is the positive control: it proves the synthetic
rows actually reached `drawThings` in both arms. An earlier run of this
harness returned 58 elements for both arms because the mock wrapped the
rows in an object while the page reads the response as a bare array --
two silent arms and no control, which proves nothing.

Opening a tooltip afterwards produced identical content in both arms.
The relative time inside it is now computed on hover rather than frozen
at draw, so it is fresher than before.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
RF = (STATIC / "rf.js").read_text(encoding="utf-8")
LEAFLET = (STATIC / "vendor" / "leaflet.js").read_text(encoding="utf-8")


def test_every_bindtooltip_is_given_a_function() -> None:
    """A built node as the argument is the eager version, by definition."""
    found = 0
    for call in re.finditer(r"\.?bindTooltip\(\s*(.{0,24})", RF, flags=re.S):
        found += 1
        head = call.group(1).lstrip()
        assert head.startswith("()") or head.startswith("function"), (
            f"rf.js passes built content to bindTooltip ({head!r}); on a map "
            f"that redraws every poll that is a tooltip per contact per refresh"
        )
    assert found >= 2, "expected the aircraft and station tooltips to still be here"


def test_the_vendored_leaflet_resolves_function_content() -> None:
    """Tooltip and Popup share one `_updateContent`, and this is it.

    There is exactly one definition of it in the bundle, on DivOverlay,
    which both extend. If a vendor bump drops the function branch, every
    lazy tooltip and popup opens blank and no test of our own source
    would notice.
    """
    assert len(re.findall(r"_updateContent:function", LEAFLET)) == 1
    assert re.search(r'"function"\s*==\s*typeof\s+this\._content', LEAFLET), (
        "the vendored Leaflet no longer evaluates function overlay content"
    )


def test_the_rows_that_feed_the_map_are_still_capped() -> None:
    """The saving is per row, so the row count is the thing that bounds it."""
    assert "limit=5000" in RF, (
        "the RF map's row cap moved or went away; the per-refresh cost is "
        "proportional to it, so a change here changes the ceiling"
    )
