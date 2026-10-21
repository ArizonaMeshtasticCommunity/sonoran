"""Full screen for every chart (#100).

There is no JavaScript test runner here, so these hold the shapes that
a browser pass measured. Each assertion below failed against the code
before the change and passes after it. What was measured, and where:

* Against a deployed test instance with
  ``app.js`` and ``app.css`` served from this tree. Five charts on the
  node page, three on statistics, one on the dashboard and one on the
  graph page each got a control. Entering took the dashboard chart's
  canvas from 556 to 1476 CSS px wide and leaving put it back at 556.
* The keyboard pass: Space on the control opened it, Escape left it,
  and the focus came back to the control that opened it.
* The same pass with ``requestFullscreen`` rejecting, which is what
  iOS Safari does: the overlay still covered 1500x1050 and Escape
  still left.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
WATCH = (STATIC / "map-watch.js").read_text(encoding="utf-8")


def test_every_chart_gets_the_control_from_one_place() -> None:
    """The helper adds it, so no call site can forget.

    There are eleven `chart(...)` call sites. Ten of them are a panel
    with a heading and a box; adding a control at each one would be ten
    chances to leave a chart behind.
    """
    start = APP.index("function chart(target, option)")
    body = APP[start : APP.index("function chartEmpty")]
    assert "fitChartExpand(target)" in body, (
        "the chart helper does not give its chart a full-screen control"
    )


def test_the_control_is_a_button_and_not_an_anchor() -> None:
    """Space must work, and on an anchor it does not.

    `map-watch.js` used to build its control as `<a role="button">`,
    and measured on the deployed instance: focus it, press Space, and
    `SonoranWatch.isOn()` was still false. Enter worked. That bug must
    not be copied here.

    It has since been fixed (#147), so the second assertion below is now
    a consistency check rather than a note about a known difference:
    both controls are real buttons and both should stay that way.
    """
    start = APP.index("function fitChartExpand")
    body = APP[start:]
    assert "el('button', {\n    type: 'button', class: 'chart-expand'" in body, (
        "the full-screen control is not a real button"
    )
    # The other control that had this bug. It was an anchor when this
    # test was written; the assertion was inverted when #147 fixed it,
    # which is exactly what the note here asked whoever fixed it to do.
    assert "L.DomUtil.create('button'" in WATCH, (
        "map-watch's control went back to an anchor; Space stops working "
        "there and the comment in fitChartExpand stops being true"
    )


def test_leaving_gives_the_focus_back_to_the_control() -> None:
    """WCAG 2.4.3. `wireNav` already does this for the menu.

    Without it the focus falls to the body and a keyboard reader starts
    again at the top of a long page.
    """
    start = APP.index("async function leaveChartStage")
    body = APP[start : APP.index("document.addEventListener('fullscreenchange'")]
    assert "opener.focus()" in body, "the focus is not given back"
    assert "opener.isConnected" in body, (
        "a detached opener is focused, which moves the focus to the body"
    )


def test_both_directions_measure_the_chart_again() -> None:
    """ECharts measures its container once and never again on its own.

    A chart that grew to the full screen without `resize` draws at the
    old size in the corner of the overlay.
    """
    assert "function redrawChart(box, zoomed)" in APP
    assert "instance.resize()" in APP[APP.index("function redrawChart") :][:400]
    enter = APP[APP.index("async function enterChartStage") :]
    assert "redrawChart(box, true)" in enter[: enter.index("async function leaveChartStage")]
    leave = APP[APP.index("async function leaveChartStage") :]
    assert "redrawChart(box, false)" in leave[:1600], "leaving never redraws"


def test_the_zoom_is_only_added_where_there_is_a_range_to_zoom() -> None:
    """Measured on statistics: 2 `dataZoom` on Daily activity and on the
    hourly chart, 0 on Hardware models.

    Hardware models is a horizontal bar chart whose x axis is a count.
    A zoom on a count axis hides bars instead of showing a range, and
    the graph page has no axis at all.
    """
    start = APP.index("function chartZoomOption")
    body = APP[start : APP.index("function redrawChart")]
    assert "if (type !== 'time' && type !== 'category') return option;" in body, (
        "the zoom control is added to charts that have no range to zoom"
    )


def test_the_overlay_does_not_need_the_fullscreen_api() -> None:
    """iOS Safari refuses `requestFullscreen` on an arbitrary element.

    `map-watch.js` learned this first. The overlay is fixed to the
    viewport in CSS on both paths, so the API only ever adds the
    browser's own chrome going away.
    """
    start = CSS.index(".chart-stage {")
    body = CSS[start : CSS.index(".chart-stage[hidden]")]
    assert "position: fixed; inset: 0;" in body, (
        "the overlay relies on the Fullscreen API, which iOS Safari refuses"
    )


def test_an_empty_chart_keeps_no_control() -> None:
    """`chartEmpty` turns a chart into a sentence.

    The control is a sibling of the box, because ECharts owns
    everything inside it, so it outlives the chart unless it is taken
    away here. A "Full screen" button over one line of prose is a
    button that opens nothing.
    """
    start = APP.index("function chartEmpty")
    body = APP[start : APP.index("const CHART_BASE")]
    assert "tools.classList.contains('chart-tools')" in body
    assert "tools.remove()" in body
