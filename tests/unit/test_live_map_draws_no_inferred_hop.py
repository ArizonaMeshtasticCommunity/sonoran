"""The live map draws hop COUNT, never an inferred hop (#47).

#47 asks whether the map should draw the hops a message actually took,
and offers three answers. The decision, recorded here because a
decision with no tripwire under it gets quietly reversed:

**Option 1 — hop count only. Shipped, and it already was.** The count
reaches the reader in words (`"3 hops"` / `"hops not recorded"`), in
the firehose column, and as the bow of the arc, with the legend saying
so. No new line is drawn, so no line can be wrong.

**Option 3 — relayer attribution from `relay_node_num`. Declined**, on
the numbers in the issue: Meshtastic's `relay_node` carries only the
LOW BYTE of the relayer's node number. Measured on production over
7 days, 131,052 rows, **every value under 256** — 1,164 nodes heard
across 237 distinct low bytes, **4.91 candidates per byte on average
and 19 in the worst case.** The byte alone resolves about 3% of nodes.

AGENTS.md 9.5 is the reason that is not a starting point to refine: a
gateway observation is not a radio link, and **a speculative hop drawn
between the wrong pair of nodes is worse than no line at all, because
people plan antennas from this map.**

What would change the answer: upstream carrying a full relayer id, or
a measured narrowing — same modem preset, heard recently, plausibly in
range of both ends — that collapses the candidate set to one for a
useful share of packets. The issue says that has to be measured before
anything is drawn, and it has not been.

So this file is the tripwire. `relay_node_num` and `next_hop_node_num`
are stored (`db/models.py`) and reach no route and no map today. If
somebody exposes them, they meet this test and its reasoning first.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "src" / "sonoran" / "api" / "routes"
STATIC = ROOT / "src" / "sonoran" / "web" / "static"


def test_the_stored_columns_still_exist() -> None:
    """The control.

    Every assertion below says "this field is absent from the API". If
    the column were renamed or dropped, they would all pass while
    checking nothing.
    """
    models = (ROOT / "src" / "sonoran" / "db" / "models.py").read_text(encoding="utf-8")
    assert "relay_node_num" in models, "the column this test is about is gone from the model"
    assert "next_hop_node_num" in models


def test_no_route_exposes_the_ambiguous_relayer() -> None:
    """One low byte names 4.91 nodes on average and 19 at worst.

    Exposing it is not wrong in itself — a page that showed "relayed by
    one of these 19" would be honest. Exposing it *quietly*, so the
    next person draws a line from it, is the failure this guards.
    """
    for path in sorted(ROUTES.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "relay_node_num" not in source, (
            f"{path.name} exposes relay_node_num. It is the LOW BYTE of a "
            f"node number: 4.91 candidates on average, 19 at worst. Read "
            f"#47 before drawing anything from it — a hop between the wrong "
            f"pair of nodes is worse than no line, because people plan "
            f"antennas from this map (AGENTS.md 9.5)."
        )


def test_the_live_map_draws_nothing_from_a_relayer_guess() -> None:
    for name in ("map-live.js", "app.js"):
        source = (STATIC / name).read_text(encoding="utf-8")
        assert "relay_node" not in source, (
            f"{name} references a relayer field; the live map must draw hop "
            f"COUNT and never an inferred hop (#47)"
        )


def test_the_hop_count_still_reaches_the_reader_in_words() -> None:
    """Option 1 is what was shipped, so it is what must not regress.

    The bow of the arc carries it too, but a shape is not a sentence:
    somebody who cannot compare two curves still needs the number.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "hops not recorded" in app, (
        "the map no longer distinguishes 'no hops recorded' from 'zero "
        "hops', which are very different claims about a packet"
    )
    assert "${packet.min_hops} hop" in app, "the hop count is no longer written out"


def test_a_self_upload_is_not_counted_as_zero_hops() -> None:
    """AGENTS.md 9.5.1, and the reason the count is trustworthy at all.

    A sender uploading its own transmission carries
    `hop_start == hop_limit`, so it reads as zero hops. Folding that in
    made a relayed packet print "0 hops" — which asserts the two nodes
    were in range when nothing showed it.
    """
    source = (STATIC / "map-live.js").read_text(encoding="utf-8")
    assert "event.from.node_id !== event.gateway.node_id" in source, (
        "a self-upload's hop count is folded into the minimum again, so a "
        "relayed packet can print '0 hops' and claim a direct link"
    )
