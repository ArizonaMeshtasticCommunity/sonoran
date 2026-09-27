"""No element id is also a page's address (#270).

The pages are addressed by fragment: `#map`, `#nodes`, `#stats`. A
browser that loads an address with a fragment scrolls to the element
whose id is that fragment. The live map's box was `<div id="map">`, so
every visit to `#map` scrolled the page down to the box: 235 px on an
iPhone, 277 px measured again in WebKit at 390 px, with the page head
and all seven map controls above the top of the screen. Nothing in the
code asked for that scroll, which is why it could not be found by
looking for `scrollTo`.

The e2e journey "the map page opens at its top" measures the scroll in
a browser. This test names the cause, so a new page or a new id that
repeats it fails here first.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"


def _page_names() -> set[str]:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    return set(re.findall(r"^PAGES\.([A-Za-z]+) = ", script, flags=re.M))


def _ids() -> set[str]:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return set(re.findall(r'\sid="([^"]+)"', html))


def test_the_page_list_is_read() -> None:
    """A regex that finds nothing would pass the test below for nothing."""
    names = _page_names()
    assert {"map", "nodes", "firehose", "stats", "dashboard"} <= names


def test_no_element_id_is_a_page_address() -> None:
    clash = sorted(_page_names() & _ids())
    assert not clash, (
        f"an element id is also a page's address: {clash}. Loading that "
        f"address scrolls the page to the element. Rename the id."
    )


def test_the_live_map_box_is_the_one_leaflet_mounts() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="live-map"' in (STATIC / "index.html").read_text(encoding="utf-8")
    assert "L.map('live-map'" in script
