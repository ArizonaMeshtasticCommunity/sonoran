"""The address box on the planner, in the browser half (§6.5).

`test_geocode_endpoint.py` holds the server. This holds the page: what it
draws, what it refuses to draw, where it puts somebody else's text, and
the two layout rules that a search row added to a 21 rem column can break.

Measured in Chromium against this tree, 1500x1050, the seeded database
and a live lookup:

    typed "Flagstaff"   "One place found."
    one button          "Flagstaff, Coconino County, Arizona, United States"
    clicked it          lat 35.19875, lon -111.65182, site name
                        "Flagstaff, Coconino County"
    address bar         #planner?v=1&site_name=Flagstaff%2C%20Coconino...
    320 px, advanced    0 px of sideways scroll
    console             clean
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
RAW = (STATIC / "planner.js").read_text(encoding="utf-8")


def _code(text: str) -> str:
    """Source with its comments removed.

    A grep over raw source has produced a false pass in this repository
    four times, most memorably a check for `--set` that matched the
    comment forbidding it — and this file greps for `innerHTML`, a word
    that appears in the comments here explaining why it is not used.
    """
    stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in stripped.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


PLANNER = _code(RAW)


def _function(name: str) -> str:
    """One top-level function's body, from its line to the next declaration."""
    start = PLANNER.index(f"function {name}(")
    ends = [
        PLANNER.find(marker, start + 1)
        for marker in ("\nfunction ", "\nasync function ", "\nconst ", "\nlet ")
    ]
    return PLANNER[start : min(index for index in ends if index != -1)]


# --- what it draws -----------------------------------------------------


def test_the_box_is_on_the_page_and_labelled() -> None:
    """`test_every_control_has_a_name_that_is_not_a_placeholder` counts a
    label only when it wraps its control."""
    match = re.search(r"<label>([^<]*)\s*<input data-planner-address", HTML)
    assert match, "the address box is not inside a label"
    assert match.group(1).strip(), "the address box has no visible caption"


def test_it_stays_hidden_where_the_deployment_has_no_geocoder() -> None:
    """The rule the pickers already follow: a control that cannot work is
    worse than no control, and in the browser a 404 is silent."""
    assert '<div class="planner-find" data-planner-find hidden>' in HTML, (
        "the search row is drawn before anything has checked it can work"
    )
    body = _function("wireAddressSearch")
    assert "CONFIG.geocode && CONFIG.geocode.enabled" in body, (
        "nothing checks whether this deployment has the endpoint"
    )
    assert "if (!offered) return;" in body, "the row is revealed whatever the config said"
    assert "run.hidden = false;" in body, "the row is never revealed at all"
    # The order matters: revealed after the check, not before it.
    assert body.index("if (!offered) return;") < body.index("run.hidden = false;")


def test_the_button_carries_an_icon_and_keeps_its_text() -> None:
    """`aria-hidden="true"` on the svg means an icon-only button has no
    accessible name at all."""
    match = re.search(r"<button[^>]*data-planner-find-go[^>]*>(.*?)</button>", HTML, re.S)
    assert match, "the Find control is not a button"
    assert '<use href="#i-search"/>' in match.group(1), "the button has no icon"
    assert re.search(r"<span>[^<]+</span>", match.group(1)), (
        "the button is icon-only, so it has no accessible name"
    )
    assert '<symbol id="i-search"' in HTML, (
        "the icon is referenced but not in the sprite, so it renders as nothing at all"
    )


def test_the_icon_has_a_size() -> None:
    """An unsized inline `<svg>` is 300x150 and takes the page sideways.

    The `button .icon` rule exists for exactly this, and it is what the
    reflow journey caught the last time: the planner's own Copy link
    button measured 321 px inside a 320 px viewport.
    """
    rule = re.search(r"button \.icon \{([^}]*)\}", CSS)
    assert rule, "the rule that sizes an icon in a button is gone"
    assert "width" in rule.group(1) and "height" in rule.group(1)


# --- somebody else's text ----------------------------------------------


def test_a_place_name_never_reaches_an_innerhtml_sink() -> None:
    """The name comes from a third-party geocoder.

    #81 was a stored node name reaching an innerHTML sink, and the policy
    that let the handler run has since been tightened — but a page that
    puts remote text into markup is a page waiting for the next one.
    `el`'s `text` key is `textContent`.
    """
    body = _function("showFound")
    assert "text: place.name" in body, "the name is not set as text"
    for sink in ("innerHTML", "html:", "insertAdjacentHTML", "outerHTML"):
        assert sink not in body, f"a place name reaches {sink}"


def test_a_missing_coordinate_is_dropped_rather_than_predicted_from() -> None:
    """`Number(undefined)` is NaN and `Number(null)` is 0.

    A name with no coordinate would put a latitude of 0 into the form,
    which is a real place in the Atlantic. Five bugs in this repository
    have been a value meaning ABSENT sharing storage with a real one.
    """
    body = _function("findPlace")
    assert "Number.isFinite(Number(place.lat))" in body, "a place with no latitude is accepted"
    assert "Number.isFinite(Number(place.lon))" in body


def test_the_site_name_is_shortened_but_the_list_is_not() -> None:
    """A geocoder answers with the whole chain of administrative names.

    The button shows all of it, because that is how a reader tells two
    answers apart. The Site name box gets two parts, because it travels in
    a share link where `SHARE_NAME_LIMIT` would cut it mid-county.
    """
    assert "function siteLabel(name)" in PLANNER
    assert "setSite(place.lat, place.lon, siteLabel(place.name))" in PLANNER, (
        "the whole chain of names goes into the site box and then into the link"
    )
    assert "text: place.name" in _function("showFound"), "the list was shortened too"


# --- what it says ------------------------------------------------------


def test_a_failure_says_what_to_do_instead() -> None:
    """The endpoint answers 429 when a budget is spent, and the reader can
    always click the map."""
    body = _function("findPlace")
    assert "Click the map instead" in body, "a failed lookup leaves the reader with nothing to do"


def test_nothing_found_is_not_reported_as_a_failure() -> None:
    """A place outside the region is a real answer: there is no terrain
    here to predict over, so it could not be used anyway."""
    body = _function("findPlace")
    assert "Nothing of that name was found in this region" in body


def test_a_failed_lookup_is_not_retried() -> None:
    """A retry from here would spend somebody else's turn at the
    upstream's one request a second."""
    body = _function("findPlace")
    assert "setTimeout" not in body and "retry" not in body.lower(), (
        "the lookup retries, which spends the shared rate budget"
    )


def test_the_list_is_cleared_once_a_place_is_chosen() -> None:
    """Left up, the next thing the reader clicks moves the site they have
    just chosen."""
    body = _function("showFound")
    chosen = body[body.index("onclick:") :]
    assert "box.hidden = true;" in chosen, "the list stays up after a choice"


# --- the layout --------------------------------------------------------


def test_the_row_can_shrink_to_a_phone() -> None:
    """A flex item's floor is its content, and a text box carries a
    placeholder.

    Without `min-width: 0` the row cannot shrink and the whole document
    scrolls sideways at 320 px, which is WCAG 2.2 SC 1.4.10 Reflow. The
    share-link box on this same page carries the same line for the same
    reason.
    """
    rule = re.search(r"\.planner-find label \{([^}]*)\}", CSS)
    assert rule, "the search row's label has no rule of its own"
    assert "min-width: 0" in rule.group(1), (
        "the row cannot shrink below its content, so the page scrolls sideways at 320 px"
    )


def test_the_results_wrap_rather_than_stretching_the_form() -> None:
    """A geocoder's `display_name` is four commas deep, and the form is a
    21 rem column."""
    rule = re.search(r"\.planner-find-results button \{([^}]*)\}", CSS, re.S)
    assert rule, "the result buttons have no rule"
    assert "white-space: normal" in rule.group(1), "a long place name will not wrap"


def test_the_enter_key_works() -> None:
    """There is no `<form>` here, so Enter in a lone text box does nothing
    at all — which reads as a broken control."""
    body = _function("wireAddressSearch")
    assert "'keydown'" in body and "'Enter'" in body
    assert "preventDefault" in body
