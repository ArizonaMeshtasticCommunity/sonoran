"""The node page on a desktop screen (#193).

Seven items were reported against `#node/!698282d0` on one page. Five
are covered here; items 3 (Health under Device) and 6 (a live-map link
to one node) are larger and deliberately left.

The fifth, item 7, is not cosmetic. Both "Furthest node" tiles showed
`-` above "None with an exact position." for a node that **26 nodes
hear and which hears 48**. Checked against the running instance:

    position: false, coarse_excluded: 1167,
    furthest_heard_by: null, furthest_heard: null

No distance exists because that node's *own* position is rounded, so
every pair is excluded by the #55 rule. "None with an exact position"
is true and reads as "nobody hears it".
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"


def _code(name: str) -> str:
    """Return a static file with its comments removed.

    Every source-text assertion in this repository has to answer the
    same question: is it reading the code, or a comment that mentions
    the code? Searching raw source has produced a false pass here four
    times, most memorably a check for `--set` that found the comment
    forbidding it.

    Both comment forms, which the first version of this helper got
    wrong: it stripped only `//`, and the `/* ... */` blocks written
    for exactly these changes then satisfied the assertions below. The
    control caught it, which is the reason the control is here.

    `//` is removed only from a line that *starts* with it, never
    mid-line. Splitting on `//` anywhere would cut every URL in the
    file in half, and a truncated string is a different false result
    rather than a fixed one.
    """
    text = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def test_the_comment_stripper_works() -> None:
    """Positive control for `_code`, which every case below leans on."""
    app = _code("app.js")
    assert "function nodeStyle" in app, "the stripper removed real code"
    assert "* A gateway wears a bright ring" not in app, "block comments leak through"


# --- item 4: Yes and No --------------------------------------------


def test_yes_and_no_are_capitalised() -> None:
    """`Licensed: no` reads as prose; it is a value in a list (#193.4).

    Changed in the `yesNo` helper rather than at the call sites, so
    every page agrees. The assertion names the helper for that reason.
    """
    app = _code("app.js")
    assert "'Yes' : 'No'" in app
    assert "'yes' : 'no'" not in app, "the lower-case pair is still somewhere"


# --- item 5: one count, not two ------------------------------------


def test_an_expanding_list_does_not_say_its_count_twice() -> None:
    """ "View all 26 nodes" and "21 more" were one fact, told twice.

    The button carries the total, so the span beside it was removed
    from both helpers. Site-wide, which the issue intends.
    """
    app = _code("app.js")
    # Scoped to the two shared helpers. A `<details>` elsewhere folds
    # extra reaction chips behind "+3 more", which is a disclosure with
    # no button beside it naming the total -- a different control, and
    # not what this issue is about. The first version of this assertion
    # searched the whole file and caught that instead.
    for helper in ("function expandingList", "function expandingTable"):
        start = app.index(helper)
        body = app[start : app.index("\n}", start)]
        assert "} more`" not in body, f"{helper} still prints a second count"


def test_the_button_still_carries_the_total() -> None:
    """The half that keeps the removal honest.

    Deleting the span is only correct because the button already says
    "View all N". If that ever stopped being true, the count would be
    gone from the page entirely.
    """
    app = _code("app.js")
    assert "View all" in app, "nothing tells the reader how many there are"


# --- item 7: say why there is no distance --------------------------


def test_a_rounded_position_says_so_instead_of_only_none() -> None:
    """The tile must name the reason, not just report absence."""
    app = _code("app.js")
    assert "Its own position is rounded, so no distance can be measured." in app


def test_the_reason_is_chosen_from_the_node_and_not_guessed() -> None:
    """It reads `routes.position`, the field the API actually sends.

    Verified against the running instance: `/api/nodes/.../routes`
    returns `position: false` for this node. A sentence keyed on
    anything else -- an empty list, a null distance -- would also fire
    when the *other* ends were rounded, which is a different cause and
    a different sentence.
    """
    app = _code("app.js")
    assert "routes.position === false" in app


def test_the_other_reason_survives() -> None:
    """A node with an exact position keeps the original wording.

    Without this, the fix could have replaced one blanket sentence with
    another blanket sentence.
    """
    app = _code("app.js")
    assert "'None with an exact position.'" in app


# --- items 1 and 2: one column, even gaps --------------------------


def test_the_node_page_panels_share_the_grids_width() -> None:
    """Health and the map are bare panels and ran past the grids.

    `.grid` caps at 100rem and centres; those two did not, so past
    1600 px the page had two different left edges.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "[data-node-body] > .panel" in css
    assert "max-width: 100rem" in css


def test_the_cap_is_scoped_to_the_node_page() -> None:
    """The Map and Planner pages must not gain a cap (#70).

    `app.css` says maps are deliberately NOT capped, because #70 asked
    for the map to fill its container. That was those pages. This one
    is a panel among panels. Scoping is the whole reason this is safe,
    so it is asserted rather than assumed.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    # The cap lives on the rule that matches EVERY direct child. Naming
    # `.panel` was not enough: `.grid` carries `margin-inline: auto`,
    # which in a flex column makes an item shrink-to-fit rather than
    # stretch, so the summary row measured 1438 px wide at left 494
    # while the panels below reached 1600 at left 413 -- the very
    # mismatch #193.1 reported, still there after the first fix.
    body = css[css.index("[data-node-body] > * {") :]
    rule = body[: body.index("}")]
    assert "max-width" in rule
    # Scoped: never a bare `.panel`, which would cap the Map and
    # Planner pages that #70 deliberately left uncapped.
    assert "\n.panel {" not in css or "max-width: 100rem" not in css.split("\n.panel {")[1][:200]


def test_every_gap_on_the_node_page_comes_from_one_value() -> None:
    """Measured gaps were 16 px, 0 px, 0 px, 16 px (#193.2).

    Panels that touch are panels relying on their own margins. One
    `gap` on the column gives every block the same separation.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    block = css[css.index("[data-node-body] {") :]
    rule = block[: block.index("}")]
    assert "flex" in rule
    assert "gap:" in rule


# --- #200: "View all" must only be said when it is all -------------


def test_a_capped_list_does_not_offer_to_show_all() -> None:
    """ "View all 25 messages" on a node that sent 1,184 (#200).

    `expandingList` names its button from `items.length`, and several
    endpoints cap what they send. `AGENTS.md` 9.19: a row limit must
    not decide what the page says exists.
    """
    app = _code("app.js")
    assert "Show the ${items.length} newest ${noun}" in app
    assert "Show the ${rows.length} newest ${noun}" in app, "the table helper was missed"


def test_the_uncapped_case_still_says_view_all() -> None:
    """The non-regression half.

    Most callers are not capped -- the routes tables and the gateway
    table send whole lists -- and those must keep the wording they had.
    A fix that renamed every button would be a different wrong answer.
    """
    app = _code("app.js")
    assert "View all ${items.length} ${noun}" in app
    assert "View all ${rows.length} ${noun}" in app


def test_the_messages_panel_compares_the_count_with_the_list() -> None:
    """It must decide from the API's measured count, not from a guess.

    `detail.messages.count` is measured by the endpoint;
    `detail.messages.recent` is capped at 25. Comparing them is the
    only thing on the page that can tell a short list from a cut one.
    A heuristic -- "if the list is exactly 25" -- would be wrong for a
    node that really sent 25.
    """
    app = _code("app.js")
    assert "(detail.messages.count || 0) > messages.length" in app


def test_the_heading_still_shows_the_true_total() -> None:
    """The true count must stay visible somewhere.

    The button now says "the 25 newest", so the heading is the only
    place left that says 1,184. Removing it would trade one wrong
    number for no number.
    """
    app = _code("app.js")
    assert "count(detail.messages.count)" in app
