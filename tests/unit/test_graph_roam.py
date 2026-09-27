"""The mesh graph pans and zooms from the whole canvas (#233, after #223).

returnzork reported it with a picture and a red rectangle: inside that
rectangle the graph could be dragged, outside it nothing happened. The
rectangle was not arbitrary. ECharts gates a graph series' roam on the
bounding rect of what it DREW -- from the vendored build:

    setPointerChecker(function (e, x, y) {
      var o = a.getBoundingRect();
      o.applyTransform(a.transform);
      return o.contain(x, y) && !hT(e, n, t);
    })

`a` is the series group, so the region is the box around the outermost
nodes: "an invisible box that has corners of outlier nodes", exactly as
reported. No series option changes it, because the rect is computed in the
view rather than read from the option.

Measured before the fix: a drag inside the box moved the group from
(80,48) to (176,108); the same drag from the empty canvas moved nothing,
and the wheel did nothing there either. The report was about dragging;
zoom was broken in the same place, for the same reason, and is fixed with
it.

These cases exist because the fix reaches into private ECharts internals
(`_chartsViews`, `_controller`). That is a deliberate trade -- there is no
public way to widen the region -- and the risk is an ECharts upgrade
moving those names and the graph quietly going back to panning only in
the middle. A silent loss is the thing worth preventing, so this asserts
the shape of the fix and the vendored build still matching it.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def _widen_source() -> str:
    start = APP.index("function widenGraphRoam(")
    # To the start of the next top-level function.
    end = APP.index("\nfunction ", start + 10)
    return APP[start:end]


def test_the_fix_is_there() -> None:
    assert "function widenGraphRoam(" in APP, (
        "widenGraphRoam is gone, so the graph pans only inside the box around "
        "its nodes again (#233)"
    )


def test_it_is_applied_after_every_render() -> None:
    """Once is not enough.

    The graph view installs a fresh pointer checker every time it renders,
    inside `_updateController`. A fix applied only at init is undone by the
    next `setOption` -- and the graph page re-renders on a preset change, a
    window change, a channel tab and a search.
    """
    start = APP.index("function chart(target, option)")
    body = APP[start : start + 2000]
    assert "widenGraphRoam(instance)" in body, (
        "widenGraphRoam is never called from `chart()`, so it cannot survive a redraw"
    )
    assert "'finished'" in body, (
        "nothing re-applies the fix after the force layout finishes rendering"
    )


def test_it_composes_rather_than_replaces() -> None:
    """The original answer has to be honoured.

    ECharts' own checker carries a guard (`hT`) that stops a gesture
    starting on another component from being stolen by the graph. Replacing
    the checker with `() => true` would pan the graph when somebody drags a
    legend item -- verified on the running page: with the composed checker,
    a drag on a real legend item does not move the graph, while a drag on
    empty canvas does.
    """
    source = _widen_source()
    assert "original" in source, "the original checker is not consulted"
    assert re.search(r"if\s*\(\s*typeof original === 'function'\s*\)", source), (
        "the original checker is not called before the added case"
    )
    assert "findHover" in source, (
        "nothing checks whether something is drawn under the pointer, so the "
        "added case would also fire over the legend and over nodes"
    )


def test_it_cannot_wrap_itself_twice() -> None:
    """Re-applying on every render must not grow a chain.

    Without the marker, each redraw would wrap the previous wrapper: the
    original would be asked once per redraw, and a long-lived page would
    build a deeper chain every time the window changed.
    """
    source = _widen_source()
    assert "sonoranWidened" in source, "there is no marker, so the wrapper re-wraps itself"
    assert source.count("sonoranWidened") >= 2, (
        "the marker is set or checked but not both, so it cannot prevent a double wrap"
    )


def test_missing_internals_leave_the_chart_alone() -> None:
    """A graph that pans only in the middle beats a graph that throws.

    Every step into the internals is guarded, so an ECharts upgrade that
    renames them degrades to today's behaviour instead of breaking the page.
    """
    source = _widen_source()
    assert "Array.isArray(views)" in source, "the views list is used without checking it is one"
    assert "typeof controller.setPointerChecker !== 'function'" in source, (
        "the controller is used without checking it has the method"
    )
    assert source.count("catch") >= 2, (
        "the internals are read without catching, so a changed build throws on render"
    )


def test_the_vendored_build_still_gates_roam_this_way() -> None:
    """The reason the fix is needed, asserted against the vendored file.

    If an upgrade makes ECharts use the full canvas by itself, this fails
    and the workaround can be deleted -- which is the outcome to hope for.
    If the upgrade instead renames the internals, the cases above fail.
    Either way it is reported rather than silently lost.
    """
    echarts = (STATIC / "vendor" / "echarts.min.js").read_text(encoding="utf-8")
    assert "graphRoam" in echarts, "this is not the ECharts build these cases were written against"
    # The graph view's checker, still keyed on the drawn bounding rect.
    assert re.search(
        r"setPointerChecker\(\(function\([^)]*\)\{var \w+=\w+\.getBoundingRect\(\)",
        echarts,
    ), (
        "ECharts no longer gates roam on the drawn bounding rect. Re-check "
        "whether widenGraphRoam is still needed -- if the upgrade fixed it "
        "upstream, delete the workaround and these cases with it."
    )
