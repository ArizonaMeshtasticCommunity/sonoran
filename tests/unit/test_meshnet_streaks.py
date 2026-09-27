"""Weekly check-in streaks: the arithmetic, at every boundary.

`docs/design/2026-09-26-ux-overhaul.md` §6.3. The plan puts the streak
server-side -- "it is a windowed aggregate over weeks and does not
belong in the browser" -- and there is a second reason it cannot live in
the browser: `api/chat/tagged` sends the display window only, capped at
`limit` messages, so a browser-computed run of 30 weeks would be
reported as however many weeks the reader happened to select. A streak
shortened by a UI control is a wrong claim about a person.

The plan also says why these cases are enumerated rather than sampled:
getting a streak wrong "is worse here than on any other page in the
brief, because it is about people rather than radios."

The rules being tested are written out in full above `_streak_as_of` in
`sonoran/api/routes/chat.py`. Numbered references below are to them.
"""

from datetime import UTC, datetime, timedelta

from sonoran.api.routes.chat import (
    STREAK_LOOKBACK_WEEKS,
    _check_in_weeks,
    _streak_as_of,
    _streaks_assessed,
    _week_roster,
    _week_start,
)

WEEK = timedelta(days=7)

#: A Monday, so the arithmetic below reads as weeks rather than as dates.
MONDAY = datetime(2026, 9, 21, tzinfo=UTC)

#: Far enough below every week used here that nothing touches the floor
#: unless a case means to.
DEEP_FLOOR = MONDAY - 200 * WEEK


def weeks(*offsets: int) -> frozenset[datetime]:
    """Check-in weeks, as offsets in weeks from `MONDAY`."""
    return frozenset(MONDAY + offset * WEEK for offset in offsets)


# --- rule 1: what a week is -------------------------------------------


def test_a_week_runs_monday_to_monday_in_utc() -> None:
    """The boundary is Monday 00:00 UTC, exclusive at the end."""
    assert _week_start(MONDAY) == MONDAY
    assert _week_start(MONDAY + timedelta(seconds=1)) == MONDAY
    assert _week_start(MONDAY + WEEK - timedelta(microseconds=1)) == MONDAY
    assert _week_start(MONDAY + WEEK) == MONDAY + WEEK
    # A Sunday 23:59 UTC message belongs to the week that is ending, and
    # a Monday 00:00 one to the week beginning. Those two messages are
    # ninety seconds apart and are two different check-ins.
    assert _week_start(MONDAY - timedelta(seconds=30)) == MONDAY - WEEK


def test_a_week_is_the_same_week_whatever_zone_the_row_arrives_in() -> None:
    """Arizona keeps MST, and MST Sunday evening is UTC Monday.

    A stamp is a moment, not a wall clock: 17:00 MST on Sunday is 00:00
    UTC on Monday, so it belongs to the week beginning. Getting this
    wrong would move a whole evening of check-ins into the previous
    week, which on a Sunday net is most of them.
    """
    mst = timedelta(hours=-7)
    sunday_evening = datetime(2026, 9, 20, 17, 0, tzinfo=UTC) - mst
    assert _week_start(sunday_evening) == MONDAY


# --- rule 2: twice in one week is one check-in ------------------------


def test_two_messages_in_one_week_are_one_week() -> None:
    """The unit is the week, not the message (rule 2).

    A node that posts on the Tuesday and again on the Saturday has a
    streak of 1, not 2. Counting messages here is the obvious bug and it
    inflates the number that people will compare with each other.
    """
    buckets = {
        (7, MONDAY): {"messages": 2, "first_seen": MONDAY, "last_seen": MONDAY},
    }
    assert _check_in_weeks(buckets) == {7: weeks(0)}
    assert _streak_as_of(weeks(0), MONDAY, DEEP_FLOOR) == (1, False)


def test_twice_in_one_week_does_not_reach_into_the_next() -> None:
    """Two messages this week are not a check-in for next week."""
    assert _streak_as_of(weeks(0), MONDAY + WEEK, DEEP_FLOOR) == (0, False)


# --- rule 3: a single week, and never a zero -------------------------


def test_a_single_week_is_a_streak_of_one() -> None:
    assert _streak_as_of(weeks(0), MONDAY, DEEP_FLOOR) == (1, False)


def test_a_week_with_no_check_in_has_no_run_ending_there() -> None:
    """Rule 3: there is no streak of 0, so the caller is told there is none.

    The zero returned here is a programming answer for "you asked about
    a week this node was not in". It is never rendered: `_week_roster`
    only asks about weeks it found the node in, and the page renders a
    missing streak as words rather than as a number.
    """
    assert _streak_as_of(weeks(0, 1), MONDAY - WEEK, DEEP_FLOOR) == (0, False)
    assert _streak_as_of(frozenset(), MONDAY, DEEP_FLOOR) == (0, False)


# --- rule 4: a gap ends it -------------------------------------------


def test_a_gap_ends_the_streak() -> None:
    """Weeks -4, -3, then nothing at -2, then -1 and 0.

    The run as of week 0 is 2. Counting every week the node ever
    appeared in would say 4, which is the bug this case exists for.
    """
    present = weeks(-4, -3, -1, 0)
    assert _streak_as_of(present, MONDAY, DEEP_FLOOR) == (2, False)
    # And the run that ended before the gap is still readable as of its
    # own last week.
    assert _streak_as_of(present, MONDAY - 3 * WEEK, DEEP_FLOOR) == (2, False)


def test_a_later_message_does_not_bridge_a_gap_backwards() -> None:
    """A check-in in week 0 says nothing about week -2 (rule 4)."""
    assert _streak_as_of(weeks(-3, -2, 0), MONDAY, DEEP_FLOOR) == (1, False)


def test_a_long_unbroken_run_counts_every_week() -> None:
    present = weeks(*range(-9, 1))
    assert _streak_as_of(present, MONDAY, DEEP_FLOOR) == (10, False)


# --- rule 5: the week in progress ------------------------------------


def test_an_in_progress_week_does_not_break_a_run() -> None:
    """The case the design turns on (rule 5).

    A node that checked in for four weeks and has not yet posted this
    week is on a live run of 4. Walking back from the current week would
    report 0, which is what makes every node look broken on a Monday
    morning -- the reason this is a named boundary rather than an
    incidental one.
    """
    present = weeks(-4, -3, -2, -1)
    assert _streak_as_of(present, MONDAY, DEEP_FLOOR) == (0, False), "not in this week"
    assert _streak_as_of(present, MONDAY - WEEK, DEEP_FLOOR) == (4, False)


def test_an_in_progress_week_is_counted_once_the_check_in_lands() -> None:
    """Already checked in this week: the week counts, nothing provisional."""
    assert _streak_as_of(weeks(-1, 0), MONDAY, DEEP_FLOOR) == (2, False)


def test_an_in_progress_week_is_never_counted_before_it_is_earned() -> None:
    """The other half of rule 5.

    The run through last week is 4, and it stays 4 until a message
    arrives. Adding one for the week in progress would show a 5 that
    nobody has done.
    """
    length, _ = _streak_as_of(weeks(-4, -3, -2, -1), MONDAY - WEEK, DEEP_FLOOR)
    assert length == 4


# --- the floor: a run we cannot see the start of ---------------------


def test_a_run_that_reaches_the_floor_is_a_lower_bound() -> None:
    """`streak_at_least`, which the page draws as "5+" rather than "5"."""
    floor = MONDAY - 4 * WEEK
    present = weeks(-4, -3, -2, -1, 0)
    assert _streak_as_of(present, MONDAY, floor) == (5, True)


def test_a_run_that_stops_above_the_floor_is_measured() -> None:
    """A real gap inside the read is evidence, not blindness."""
    floor = MONDAY - 6 * WEEK
    present = weeks(-4, -3, -2, -1, 0)
    assert _streak_as_of(present, MONDAY, floor) == (5, False)


def test_the_lookback_reaches_past_the_display_window() -> None:
    """A streak is longer than the window a reader happened to choose."""
    assert STREAK_LOOKBACK_WEEKS >= 52


# --- the roster a week hands to the page -----------------------------


def bucket(node: int, offset: int, messages: int = 1) -> tuple[tuple[int, datetime], dict]:
    """One aggregate entry, shaped as `_weekly_check_ins` returns it."""
    week = MONDAY + offset * WEEK
    return ((node, week), {"messages": messages, "first_seen": week, "last_seen": week})


def roster(buckets: dict, week: datetime, floor: datetime = DEEP_FLOOR) -> tuple[list, list]:
    by_node = _check_in_weeks(buckets)
    # Shaped as `resolve_names` returns it, so this exercises the same
    # lookup the endpoint does rather than a convenient stand-in.
    names: dict[int, dict[str, str | None]] = {
        node: {"display_name": f"node {node}"} for node in by_node
    }
    return _week_roster(week=week, buckets=buckets, by_node=by_node, names=names, floor=floor)


def test_the_roster_reports_who_checked_in_with_their_run() -> None:
    buckets = dict([bucket(1, -1), bucket(1, 0), bucket(2, 0, messages=3)])
    checked_in, not_seen = roster(buckets, MONDAY)
    assert [entry["streak_weeks"] for entry in checked_in] == [2, 1]
    assert [entry["node_id"] for entry in checked_in] == ["!00000001", "!00000002"]
    assert not_seen == []
    # Rule 2 again, through the roster: three messages, one week.
    assert checked_in[1]["message_count"] == 3
    assert checked_in[1]["streak_weeks"] == 1


def test_a_first_ever_check_in_says_so_rather_than_showing_a_one() -> None:
    """A run of 1 is either a beginning or a restart, and they read differently."""
    checked_in, _ = roster(dict([bucket(1, 0)]), MONDAY)
    assert checked_in[0]["first_ever"] is True

    buckets = dict([bucket(1, -3), bucket(1, 0)])
    checked_in, _ = roster(buckets, MONDAY)
    assert checked_in[0]["streak_weeks"] == 1
    assert checked_in[0]["first_ever"] is False, "a restart after a gap is not a beginning"


def test_only_last_weeks_participants_are_listed_as_not_seen() -> None:
    """The narrowest rule that answers the page's question (rule 6).

    Node 1 checked in last week and not this one, so it is listed. Node
    2 last checked in three weeks ago; it is not listed, because "no
    message found this week" about somebody who stopped taking part in
    August would be noise dressed up as news.
    """
    buckets = dict([bucket(1, -1), bucket(2, -3), bucket(3, 0)])
    checked_in, not_seen = roster(buckets, MONDAY)
    assert [entry["node_id"] for entry in checked_in] == ["!00000003"]
    assert [entry["node_id"] for entry in not_seen] == ["!00000001"]
    assert not_seen[0]["streak_weeks"] == 1, "the run that ended, as of last week"


def test_not_seen_carries_the_run_that_is_at_stake() -> None:
    """So the page can say what is at stake rather than only that it is."""
    buckets = dict([bucket(1, -5), bucket(1, -4), bucket(1, -3), bucket(1, -2), bucket(1, -1)])
    _, not_seen = roster(buckets, MONDAY)
    assert not_seen[0]["streak_weeks"] == 5


def test_the_roster_field_is_named_for_what_was_observed() -> None:
    """Rule 6: `not_seen`, never `missed`.

    A node may have been off, out of range, or its message may not have
    been stored. The name of the field is the first place that either
    gets respected or quietly thrown away.
    """
    checked_in, not_seen = roster(dict([bucket(1, -1)]), MONDAY)
    assert checked_in == []
    entry = not_seen[0]
    assert set(entry) == {"node_id", "display_name", "streak_weeks", "streak_at_least"}


# --- rule 7: nothing to compute from --------------------------------


def test_no_rows_and_no_text_storage_is_not_an_assessment() -> None:
    """The plan's own **[found]** risk, and the reason `streaks` can be null.

    `store_text_messages` can be off, in which case no message body is
    ever kept and there will never be a check-in to find. A page that
    drew everybody at zero would be reporting a configuration as a
    community that stopped turning up.
    """
    assert _streaks_assessed({}, keeping_text=False) is False


def test_text_storage_on_and_no_rows_is_an_assessment() -> None:
    """Measured, and the answer is nothing. A real finding, and it says so."""
    assert _streaks_assessed({}, keeping_text=True) is True


def test_rows_found_settle_it_whatever_the_setting_says_now() -> None:
    """Storage may have been switched off after the messages were stored.

    The runs computed from rows that exist are real, so the notice about
    storage must not appear over the top of them.
    """
    assert _streaks_assessed(dict([bucket(1, 0)]), keeping_text=False) is True


def test_a_week_nobody_was_in_is_empty_on_both_sides() -> None:
    """Two weeks after the last check-in: nothing to report either way.

    Not a list of everybody with a zero. `check_in_count` will be 0 and
    the page says "no check-in found", which is a measurement; a roster
    of zeroes would be a verdict on every node in the database.
    """
    checked_in, not_seen = roster(dict([bucket(1, -2)]), MONDAY)
    assert checked_in == []
    assert not_seen == []
