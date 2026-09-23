"""A hint sits on the column it explains (#99).

There is no JavaScript test runner here, so these hold the shapes a
browser pass measured. Each one failed against the code before the
change. What was measured, and where:

* Against the deployed instance at ``http://203.0.113.10:8200`` with
  this tree's ``app.js`` and ``app.css`` served in place of its own.
  On the firehose, 4 of 9 columns carry a control; on the dashboard,
  all 4 summary tiles do. No ``.hint-notes`` block is left anywhere.
* The panel is not clipped by ``.table-wrap``: the Uploads panel
  reached 41 CSS px past the wrap's right edge and was still fully
  inside the viewport. The same on the fallback path.
* Keyboard: Enter opened it, Escape closed it, Space opened it, a
  second Space closed it. Opening another closed the first. A click
  outside closed it.
* At 320 CSS px the panel spanned 8..312 of 320 and carried the whole
  Uploads sentence.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
E2E_PATH = Path(__file__).resolve().parents[2] / "tools" / "dev" / "e2e.js"
E2E = E2E_PATH.read_text(encoding="utf-8")


def test_the_block_under_the_table_is_gone() -> None:
    """#99: it repeated every heading on a page that is already long.

    The sentences did not go with it. They moved onto the headings.
    """
    assert "hint-notes" not in APP, "the old notes block is still built"
    assert "hint-notes" not in CSS, "the old notes block still has styles"
    assert "What these ${noun} mean" not in APP


def test_a_hint_opens_from_the_keyboard_and_not_only_on_hover() -> None:
    """A `title` cannot be reached by a finger or by a keyboard, and
    that is why the disclosure existed in the first place. A `<button>`
    with `aria-expanded` can be reached by both.
    """
    start = APP.index("function fitHint(")
    body = APP[start : APP.index("function placeHint(")]
    assert "type: 'button', class: 'hint-open'," in body, "the control is not a button"
    assert "'aria-expanded': 'false'," in body
    assert "'aria-controls': id," in body
    assert "'aria-label': name," in body, "the control has no accessible name"


def test_no_hint_is_left_in_a_title_attribute() -> None:
    """Two copies of one sentence drift, and a native tooltip opening
    on hover over a heading that now has its own control is one
    affordance too many. Measured: 0 `th[title]` on the firehose.
    """
    assert "title: column.hint || null," not in APP, "a column heading still has a title"
    assert "title: hint || null," not in APP, "a summary tile still has a title"
    # The sentence itself still travels, in the attribute the control
    # is built from.
    assert APP.count("'data-hint': column.hint || null,") == 2
    assert "'data-hint': hint || null," in APP


def test_the_panel_escapes_the_table_s_sideways_scroll() -> None:
    """`.table-wrap` is `overflow-x: auto`, so a panel drawn inside it
    is cut at the wrap's edge. Measured: the panel reached 41 px past
    that edge and stayed on the screen.

    A popover draws in the top layer, which no ancestor's `overflow`
    can clip. Where there is no popover API, `position: fixed` escapes
    a plain `overflow` ancestor as well.
    """
    assert "const POPOVER = 'popover' in HTMLElement.prototype;" in APP
    assert "panel.setAttribute('popover', 'auto')" in APP
    start = CSS.index(".hint-pop {")
    body = CSS[start : CSS.index(".hint-pop[hidden]")]
    assert "position: fixed;" in body, "the fallback panel would be clipped by the table"
    assert "inset: auto;" in body, (
        "the user-agent rule that centres a popover in the viewport is not undone"
    )


def test_the_panel_fits_a_320_px_screen() -> None:
    """WCAG 2.2 SC 1.4.10 Reflow. The table itself is excepted; a
    control beside it is not, and neither is a panel over it.
    """
    start = CSS.index(".hint-pop {")
    body = CSS[start : CSS.index(".hint-pop[hidden]")]
    assert "width: min(22rem, calc(100vw - 1rem));" in body
    assert "placeHint" in APP, "nothing keeps the panel inside the viewport"


def test_escape_and_a_tap_outside_close_it_on_every_browser() -> None:
    """WCAG 2.2 SC 1.4.13 asks that content be dismissible.

    An auto popover is closed by Escape and by a tap outside without
    any code here. Where the API is missing, this file does both, and
    those listeners are not installed where the browser already does
    the work.
    """
    start = APP.index("if (!POPOVER) {")
    body = APP[start:]
    assert "event.key === 'Escape'" in body[:400]
    assert "closest('.hint-pop, .hint-open')" in body[:600]


def test_the_exact_wire_values_did_not_get_lost() -> None:
    """The old block carried "Exact values here:" — the distinct
    protocol values a column holds, which had no copy outside `title`
    at all. They moved onto the column that holds them.
    """
    start = APP.index("function hintBody(")
    body = APP[start : APP.index("function fitHint(")]
    assert "'Exact values here: '" in body
    assert "${value.text} = ${value.exact}" in body
    assert "function exactValues(table, th)" in APP


def test_a_hint_is_not_written_in_the_protocol_s_words() -> None:
    """#99 named this one: "Hop start minus hop limit" is how the
    number is worked out, not what it means to a reader.
    """
    # The phrase itself is still in the file, in the comment that says
    # why it was taken out of the hint. It is the hint that must not
    # carry it.
    assert "hint: 'Hop start minus hop limit" not in APP
    assert "How many times this packet was relayed before a gateway uploaded it." in APP


def test_the_phone_journey_walks_the_control_that_replaced_the_block() -> None:
    """The journey is the same question — can a finger reach what a
    column means — asked of the new control. It must still demand the
    Uploads sentence and an exact protocol value.
    """
    start = E2E.index("'a phone can read what a column means'")
    body = E2E[start : start + 3000]
    assert ".hint-open" in body, "the journey does not open the new control"
    assert "uploaded this packet to MQTT" in body
    assert "TELEMETRY_APP|POSITION_APP|NODEINFO_APP" in body
    assert "runs off the screen" in body, "nothing checks the panel fits the phone"
