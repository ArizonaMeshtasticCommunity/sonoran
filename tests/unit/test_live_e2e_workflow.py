"""The live walk cannot gate a pull request, and is inert for now (#150).

#83 wired the e2e journeys into CI against seeded data, which is right
for a merge gate. But the bug that started that work needed a real
leaderboard row with a long detail line to overflow, and seeded data is
tidy. The same shape recurred all session: a node named `Z1PPY<<3`, 148
nodes spanning Alaska to Mexico, 79 telemetry rows dated in the future.
None of it is reproducible from a fixture.

So there is a second workflow that walks the deployed instance. Two
properties matter enough to pin:

1. **It must never gate a pull request.** Real data changes underneath
   it, so a red run means "go and look", not "this PR is bad". A job
   that fails somebody's unrelated PR gets switched off within a week —
   which is the reasoning already written into `vendor-pin.yml`.
2. **It is switched off.** The repository's Actions budget was exhausted
   on 2026-09-23, so shipping a job that starts running nightly is the
   wrong thing this week. The schedule is present as a comment, so
   enabling it is one line.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / ".github" / "workflows" / "live-e2e.yml"
RAW = PATH.read_text(encoding="utf-8")
# PyYAML reads the `on:` key as the boolean True.
FLOW = yaml.safe_load(RAW)
TRIGGERS = FLOW.get("on") or FLOW.get(True)


def test_it_does_not_run_on_a_pull_request_or_a_push() -> None:
    """The one property that must never change."""
    for trigger in ("pull_request", "pull_request_target", "push"):
        assert trigger not in TRIGGERS, (
            f"the live walk runs on {trigger}, so a change in real data can "
            f"fail somebody's unrelated pull request"
        )


def test_it_is_not_scheduled_yet() -> None:
    """Inert until the Actions budget resets."""
    assert "schedule" not in TRIGGERS, (
        "the live walk is scheduled; the repository's Actions budget was "
        "exhausted on 2026-09-23, so this should stay manual until that is "
        "sorted out"
    )
    assert "workflow_dispatch" in TRIGGERS, "it cannot be run at all"


def test_the_intended_cadence_is_recorded_rather_than_dropped() -> None:
    """Turning it on should be one line, not a rediscovery."""
    assert "cron:" in RAW, (
        "the intended schedule is not written down anywhere, so whoever "
        "enables this has to invent a cadence"
    )


def test_a_missing_target_is_not_a_failure() -> None:
    """Not knowing where the instance is is not evidence it is broken.

    The same distinction `vendor-pin.yml` makes between "could not
    check" and "check failed".
    """
    assert "::warning::no instance configured" in RAW, (
        "an unconfigured instance fails the run, which reports a problem "
        "with the deployment when the problem is with the workflow"
    )


def test_it_reports_through_one_issue_rather_than_many() -> None:
    """A new issue every night is the same as no issue at all."""
    assert "issuesAndPullRequests" in RAW, "it does not look for an existing issue"
    assert "state: 'closed'" in RAW, (
        "nothing ever closes the issue, so it stays open after the problem "
        "is fixed and stops meaning anything"
    )


def test_it_runs_where_the_other_jobs_run() -> None:
    """Self-hosted, on Logan's hardware, since #169-#171 moved them all.

    A job on `ubuntu-latest` in this repo would be both inconsistent and
    queued behind a runner label nothing else uses.
    """
    assert FLOW["jobs"]["walk"]["runs-on"] == ["self-hosted", "sonoran-microvm"], (
        "the live walk runs on a different runner from every other job in this repository"
    )


def test_it_asks_for_no_more_permission_than_it_needs() -> None:
    assert FLOW["permissions"] == {"contents": "read", "issues": "write"}, (
        f"the live walk's permissions grew: {FLOW['permissions']}"
    )
