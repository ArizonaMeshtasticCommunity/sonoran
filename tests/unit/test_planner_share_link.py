"""The planner share link, and the parts of it text can prove.

There is no JavaScript test runner here, so the behaviour of the encoder
and the reader is asserted in the browser by `tools/dev/e2e.js`. What is
worth pinning in Python is the drift: a field added to the form and not
to the link, a bound left off a number that goes into the engine, a
router that stops splitting the settings off the page name. Each of
those is quiet -- the page keeps working and the link keeps opening, it
just carries less than it says it does.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
PARAMS = (STATIC / "planner-params.js").read_text(encoding="utf-8")
PLANNER = (STATIC / "planner.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
DOC = (Path(__file__).resolve().parents[2] / "docs" / "PLANNER.md").read_text(encoding="utf-8")


def _block(text: str, opening: str) -> str:
    """The body of one `const NAME = {` or `[` declaration."""
    start = text.index(opening) + len(opening)
    end = text.index("\n};" if opening.rstrip().endswith("{") else "\n];", start)
    return text[start:end]


def _default_names() -> list[str]:
    return re.findall(r"^\s{2}(\w+):", _block(PARAMS, "const DEFAULTS = {"), re.M)


def _share_names() -> list[str]:
    return re.findall(r"'(\w+)'", _block(PARAMS, "const SHARE_FIELDS = ["))


def test_the_link_carries_every_field_the_form_has() -> None:
    """A field the link forgets is a setting that silently does not travel.

    The page still opens and the map still draws, on the receiver's
    default rather than on the sender's value, and nothing says so. The
    hardware templates under #104 will add device, antenna and cable
    here, and they have to be in both lists on the same day.
    """
    missing = sorted(set(_default_names()) - set(_share_names()))
    assert not missing, f"DEFAULTS has {missing}, which no share link carries"
    extra = sorted(set(_share_names()) - set(_default_names()))
    assert not extra, f"the share link writes {extra}, which the form has no default for"


def test_the_form_and_the_link_agree_on_which_fields_exist() -> None:
    """`FIELDS` in planner.js is what the form reads and fills.

    The link adds `preset`, which is a control on the page but is not in
    that list, because the preset is read through its own handler. Every
    other name must match, or one of the two is reading a field that the
    other does not know about.
    """
    form = set(re.findall(r"'(\w+)'", _block(PLANNER, "const FIELDS = [")))
    assert set(_share_names()) - form == {"preset"}, (
        f"the link and the form disagree: {sorted(set(_share_names()) - form)}"
    )
    forgotten = sorted(form - set(_share_names()))
    assert not forgotten, f"the form has {forgotten} and the link does not"


def test_every_number_in_a_link_has_a_bound() -> None:
    """These numbers go straight into the WebAssembly engine.

    A link is a string anybody can edit, so an unbounded number is a
    number the engine is asked to work with. The three fields that are a
    choice from a list, and the site name, are checked another way.
    """
    bounded = set(re.findall(r"^\s{2}(\w+): \[", _block(PARAMS, "const SHARE_BOUNDS = {"), re.M))
    choices = set(re.findall(r"^\s{2}(\w+):", _block(PARAMS, "const SHARE_CHOICES = {"), re.M))
    unbounded = sorted(set(_share_names()) - bounded - choices - {"site_name"})
    assert not unbounded, f"no bound on {unbounded}"


def test_the_range_ceiling_is_the_engine_s_own() -> None:
    """150 km is what the compiled page region reaches (`MAX_RADIUS_METRES`).

    Writing 150 here instead would leave two numbers to keep together,
    and the one in the link is the one nobody would think to change.
    """
    bounds = _block(PARAMS, "const SHARE_BOUNDS = {")
    assert "radius: [0.1, MAX_RADIUS_METRES / 1000]" in bounds, (
        "the range ceiling in a share link is not taken from MAX_RADIUS_METRES"
    )


def test_the_router_splits_the_settings_off_the_page_name() -> None:
    """`#planner?v=1&lat=…` is not a page name.

    Without the split, `PAGES` has no entry for the whole string, the
    router falls back to the dashboard, and every shared link opens on
    the wrong page — the same quiet failure AGENTS.md 9.14 describes for
    a reload on `#planner`.
    """
    assert "location.hash.slice(1) || 'dashboard').split('?')[0]" in APP, (
        "the router does not split a query off the fragment"
    )


def test_the_address_is_rewritten_without_re_entering_the_page() -> None:
    """`history.replaceState`, not `location.hash =`.

    Writing the hash fires `hashchange`, the router runs, and the
    planner is re-rendered on every committed edit. It also fills the
    back button with one entry per keystroke.
    """
    assert "history.replaceState" in PLANNER, "the planner does not keep the address up to date"
    assert not re.search(r"location\.hash = ", PLANNER), (
        "the planner writes location.hash, which re-enters the router"
    )


def test_the_link_is_offered_and_can_be_read_without_the_clipboard() -> None:
    """`navigator.clipboard` is undefined outside a secure context.

    Measured `undefined` on a plain-http instance, which is how this
    dashboard is usually reached, so this is the common path and not an
    edge. The link goes on the page either way, in a box that already
    has focus, and the status line says which happened.
    """
    assert "data-planner-share>" in INDEX, "there is no Copy link control"
    assert "data-planner-share-box" in INDEX and "data-planner-share-url" in INDEX
    assert "window.isSecureContext ? navigator.clipboard : null" in PLANNER, (
        "the clipboard is read without checking the context first"
    )
    assert "input.select()" in PLANNER, "the fallback box is not selected for the reader"
    # The share sheet is a phone thing. A button for an API the browser
    # does not have is worse than no button.
    assert "typeof navigator.share === 'function'" in PLANNER
    assert "data-planner-send hidden" in INDEX, "the share button is not hidden by default"


def test_the_share_box_cannot_take_the_page_sideways() -> None:
    """A link is one unbreakable string of about 120 characters.

    A flex item's floor is its content, so without `min-width: 0` the
    row cannot shrink and the document scrolls in two dimensions at
    320 px, which is WCAG 2.2 SC 1.4.10 Reflow.
    """
    start = CSS.index(".planner-share input {")
    rule = CSS[start : CSS.index("}", start)]
    assert "min-width: 0" in rule, "the share link box has no shrink floor"


def test_the_docs_describe_the_link_and_stop_denying_it_exists() -> None:
    """`docs/PLANNER.md` said a plan could not be linked to."""
    assert "cannot be saved or linked to" not in DOC, (
        "PLANNER.md still says a plan cannot be linked to"
    )
    assert "#planner?v=1" in DOC, "PLANNER.md does not show the link format"
    for name in _share_names():
        assert name in DOC, f"PLANNER.md does not name {name} in the link"
