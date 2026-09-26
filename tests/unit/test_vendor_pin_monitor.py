"""The vendored-pin monitor must not pass when it checked nothing.

`tools/check_config_checker_pin.sh` exits 0 current, 1 upstream moved,
2 could not run. The workflow used to translate 2 into a green run, on
the reasoning that being unable to reach upstream is not evidence
anything is wrong.

That reasoning inverted the job's purpose. The question it answers is
"is the vendored copy current", and "could not check" is not a no --
it is *I do not know*. An unknown reported as success is a monitor
that has stopped working while still looking healthy.

It was measured, not imagined. The first real run (dispatched by hand,
2026-09-26) printed `cannot read the upstream head` and reported
success, because `GITHUB_TOKEN` is scoped to this repository and the
upstream config-checker repo is a different private one. The steady
state was green and blind.

These cases read the workflow with its comments removed. A comment
explaining a rule reads exactly like the rule, and that has produced a
false pass in this repository more than once -- including a check for
`--set` that matched the comment forbidding it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "vendor-pin.yml"
SCRIPT = ROOT / "tools" / "check_config_checker_pin.sh"


def _steps() -> str:
    """The workflow's shell, with YAML comment lines dropped."""
    text = WORKFLOW.read_text(encoding="utf-8")
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


def test_the_comment_stripper_works() -> None:
    """Positive control: the cases below are worthless without it."""
    body = _steps()
    assert "check_config_checker_pin.sh" in body, "the stripper removed real content"
    assert "the wrong test" not in body, "comment text is leaking through"


def test_a_check_that_could_not_run_does_not_pass() -> None:
    """The bug itself. `exit 0` under status 2 is the false green."""
    body = _steps()
    assert "exit 0" not in body, (
        "the monitor still has a path that reports success; if it cannot "
        "reach upstream it must not claim the pin is current"
    )


def test_it_says_what_is_needed_to_fix_it() -> None:
    """A red that does not say what to do gets switched off.

    The cause is specific and not guessable from "check failed":
    `GITHUB_TOKEN` cannot read a different private repository.
    """
    body = _steps()
    assert "::error::" in body, "an unknown result is not reported as an error"
    assert "token" in body.lower(), "the message does not name what is missing"


def test_upstream_having_moved_still_fails() -> None:
    """The non-regression half: status 1 must keep failing.

    A fix that made everything red, or everything green, would satisfy
    the case above while destroying the distinction the script draws.
    """
    body = _steps()
    assert 'exit "$status"' in body, (
        "status 1 no longer propagates, so upstream moving would go unreported"
    )


def test_the_script_still_distinguishes_the_three_outcomes() -> None:
    """The exit contract the workflow depends on, read from the script.

    If the script stopped using 2 for "could not run", the workflow's
    branch would be dead code and the monitor would silently go back to
    being unable to tell the two failures apart.
    """
    text = re.sub(r"^\s*#.*$", "", SCRIPT.read_text(encoding="utf-8"), flags=re.M)
    for code in ("exit 0", "exit 1", "exit 2"):
        assert code in text, f"the script no longer uses `{code}`"
