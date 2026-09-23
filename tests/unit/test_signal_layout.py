"""A fifth graph layout, arranged by signal rather than geography (#71).

Logan: *"work to divide graph based on gps, snr etc"*. The GPS half was
already four layouts. This is the SNR half.

**Why it could not be built until now.** `Edge.snr` held the NEWEST
reading and discarded the rest, so clustering on it would have
clustered on whichever hop happened to be measured last. It is a median
now, which is what made this worth drawing.

**How it works, with no new algorithm.** ECharts maps an edge's `value`
across the `edgeLength` range — a larger value draws a shorter edge. So
handing it the link's SNR makes nodes that hear each other well sit
close, and the clusters that fall out are the mesh's communities rather
than its map. That is option 3 of the three readings on #71, and it
reaches option 2's answer without a clustering pass.

**`value` is set for this layout only**, which is the property most
worth holding. #71's own option 1 names the failure: a 45 km link with
a good SNR drawn shorter than a 2 km link with a poor one puts nodes in
the wrong place. On `ground` or `spread` that would be a lie about
where a node is.

Verified in a browser on 1,995 real links:

    spread   echarts layout=none    weighted 0/1995
    signal   echarts layout=force   weighted 1995/1995   e.g. 7.82, 9.72, 9.09
    free     echarts layout=force   weighted 0/1995
    signal   (again) weighted 1995/1995

No page errors, one canvas drawn in every case.
"""

from pathlib import Path

APP = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "app.js"
).read_text(encoding="utf-8")
HTML = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "index.html"
).read_text(encoding="utf-8")


def test_the_layout_is_offered() -> None:
    assert '<option value="signal">' in HTML


def test_only_the_signal_layout_weights_its_edges() -> None:
    """The geographic layouts must not be pulled out of shape.

    This is the whole reason #71's option 1 was rejected in the issue
    text, and the same trap applies to a weighted force run over
    geographic seeds.
    """
    start = APP.index("links: data.links.map((link) => ({")
    body = APP[start : APP.index("})),", start)]
    assert "layout === 'signal' ? { value: signalWeight(link.snr) } : {}" in body, (
        "edge weights are no longer conditional on the signal layout, so "
        "the geographic layouts are being distorted by signal strength"
    )


def test_it_is_a_force_layout_and_takes_no_geographic_seed() -> None:
    """Seeding it from positions would make it a geographic layout
    wearing a signal hat: the clusters would mostly reproduce the map.
    """
    assert "layout === 'force-geo' || layout === 'signal'" in APP, (
        "the signal layout no longer solves with force, so the weights do nothing"
    )
    assert "layout === 'free' || layout === 'signal'" in APP, (
        "the signal layout is seeded from geography, so its clusters "
        "reproduce the map rather than the signal"
    )


def test_an_unmeasured_link_is_not_treated_as_a_bad_one() -> None:
    """Unmeasured is not the same as poor, and this is where they
    would silently merge.

    The floor is a small POSITIVE pull, not zero: an edge of zero
    weight draws at full length, which says "unrelated" about a pair
    that demonstrably talk to each other.
    """
    start = APP.index("function signalWeight(")
    body = APP[start : APP.index("\n}", start)]
    assert "if (snr == null) return 1;" in body, (
        "a link with no SNR reading no longer gets the floor weight; it is "
        "either being dropped or scored as though it were measured badly"
    )
    assert "Math.max(SIGNAL_FLOOR" in body, "the weight is no longer clamped"


def test_the_weight_rises_with_signal_and_never_reaches_zero() -> None:
    """The two properties the layout depends on, read off the source.

    A non-monotonic weight would cluster the wrong nodes; a zero would
    push a real link to full length.
    """
    start = APP.index("const SIGNAL_FLOOR")
    body = APP[start : APP.index("function signalWeight(", start)]
    assert "SIGNAL_FLOOR = -20" in body and "SIGNAL_CEILING = 12" in body
    weight = APP[APP.index("function signalWeight(") :][:600]
    assert "1 + ((clamped - SIGNAL_FLOOR)" in weight, (
        "the weight no longer starts at 1, so the worst-measured link can "
        "reach zero pull and be drawn as though it did not exist"
    )
