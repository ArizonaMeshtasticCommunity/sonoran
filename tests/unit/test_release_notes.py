"""tools/release.py: the notes it drafts. No network, no git, no GitHub."""

import re
from datetime import datetime

from tools.release import (
    Issue,
    PullRequest,
    latest_tag,
    next_tag,
    pr_section,
    referenced_numbers,
    render_changelog,
    render_notes,
    section_of,
)

DAY = datetime(2026, 9, 26, 12, 0)
REPO = "ArizonaMeshtasticCommunity/sonoran"
CLOSING = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b\W*#\d", re.IGNORECASE)


def test_the_first_release_of_a_day_has_no_suffix():
    assert next_tag([], DAY) == "v2026.09.26"
    assert next_tag(["v2026.09.25", "v2026.09.25.2"], DAY) == "v2026.09.26"


def test_a_second_release_on_the_same_day_counts_up():
    assert next_tag(["v2026.09.26"], DAY) == "v2026.09.26.2"
    assert next_tag(["v2026.09.26", "v2026.09.26.2"], DAY) == "v2026.09.26.3"


def test_the_latest_tag_is_ordered_by_date_and_suffix_not_by_text():
    tags = ["v2026.09.26.10", "v2026.09.26.9", "v2026.09.25", "not-a-release"]
    assert latest_tag(tags) == "v2026.09.26.10"
    assert latest_tag(["not-a-release"]) is None


def test_a_pr_is_sorted_by_its_prefix_and_a_security_label_wins():
    assert section_of(PullRequest(1, "feat: a map", "x")) == "New features"
    assert section_of(PullRequest(2, "fix(api): a leak", "x")) == "Fixes"
    assert section_of(PullRequest(3, "Something plain", "x")) == "Other"
    assert section_of(PullRequest(4, "fix: csp", "x", labels=["security"])) == "Security"


def test_the_template_sections_are_read_without_their_comments():
    body = "## Summary\nx\n## Release notes\n<!-- hint -->\nMaps load faster.\n## Thanks\n@a"
    assert pr_section(body, "Release notes") == "Maps load faster."
    assert pr_section(body, "Missing") == ""


def test_an_issue_mentioned_in_passing_is_not_named_in_the_release():
    body = "Background: see #149 and #157.\n## Issues\nPart of #62\n"
    pr = PullRequest(10, "fix: gaps page (#177)", "x", body=body)
    assert referenced_numbers(pr) == [177, 62]


def test_a_reopened_issue_is_worked_on_not_done():
    """PR #226 still links to #117 as closed, and #117 was reopened."""
    pr = PullRequest(226, "test: firmware diff", "rancur", closes=[117])
    issues = {117: Issue(117, "USB write", "someone", is_open=True)}
    notes = render_notes("v2026.09.26", None, [pr], issues, REPO)
    assert "Done: #117" not in notes
    assert "Worked on: #117" in notes
    assert "0 issues" not in notes and "issues closed" not in notes


def test_the_notes_thank_reporters_authors_and_helpers_but_not_shared_accounts():
    body = "## Thanks\nTested by @tester on a T-Beam.\n"
    prs = [
        PullRequest(242, "fix: graph panning", "rancur", body=body, closes=[233]),
        PullRequest(229, "fix: APRS icons", "logans-stuff"),
    ]
    issues = {233: Issue(233, "Node graph scrolling", "returnzork")}
    notes = render_notes("v2026.09.26", "v2026.09.25", prs, issues, REPO)
    assert "- Reported: @returnzork" in notes
    assert "- Code: @logans-stuff" in notes
    assert "- Tested and helped: @tester" in notes
    assert "@rancur" not in notes
    assert "Done: #233 Node graph scrolling (reported by @returnzork)" in notes
    assert "compare/v2026.09.25...v2026.09.26" in notes


def test_the_notes_never_use_a_closing_keyword_beside_a_number():
    """A pasted release body must not close an issue on merge."""
    prs = [PullRequest(5, "fix: a thing", "a", closes=[1]), PullRequest(6, "feat: b (#2)", "b")]
    issues = {1: Issue(1, "one", "r"), 2: Issue(2, "two", "s", is_open=True)}
    notes = render_notes("v2026.09.26", None, prs, issues, REPO)
    assert not CLOSING.search(notes), CLOSING.search(notes)


def test_the_changelog_keeps_its_own_headings_on_top():
    text = render_changelog(
        [
            {
                "tagName": "v2026.09.26",
                "publishedAt": "2026-09-26T20:00:00Z",
                "body": "### Fixes\n- a",
            }
        ]
    )
    assert "## v2026.09.26 — 2026-09-26" in text
    assert "#### Fixes" in text
