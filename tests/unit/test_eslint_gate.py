"""The frontend is linted for undefined names, and the lint cannot go stale (#248).

`node --check` does no scope analysis, so a reference to a deleted name
passed it and threw in the browser. Six did in one session. These cases
hold the two things that make the ESLint gate worth having:

1. CI actually runs it, over the right directory.
2. The shared global names are DERIVED from the source, not listed. A list
   keeps a deleted name and waves its stale callers through, which is the
   exact bug the gate exists to catch.

Both were proven on the real code when the gate went in: re-adding the
#243 router line that used the deleted `chatLimit` and `CHAT_STEP` failed
with both names, and renaming `el` in app.js failed every other file that
calls it.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
CONFIG = (ROOT / "eslint.config.mjs").read_text(encoding="utf-8")
MANIFEST = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))


def test_ci_runs_eslint_over_the_frontend() -> None:
    assert MANIFEST["scripts"]["lint"] == "eslint src/sonoran/web/static"
    assert "npm run lint" in CI, "CI does not lint the frontend"


def test_eslint_runs_inside_the_existing_lint_job() -> None:
    """Every job here runs on a community member's own hardware.

    A job of its own would be one more runner allocation on every push and
    pull request, for a check that takes seconds.
    """
    lint = CI[CI.index("  lint:") : CI.index("  typecheck:")]
    assert "npm run lint" in lint, "ESLint moved out of the lint job into a job of its own"


def test_the_versions_are_pinned() -> None:
    tools = MANIFEST["devDependencies"]
    for name in ("eslint", "globals"):
        assert re.fullmatch(r"\d+\.\d+\.\d+", tools[name]), f"{name} is not pinned exactly"


def test_no_undef_is_an_error() -> None:
    assert re.search(r"'no-undef':\s*'error'", CONFIG), "no-undef is not an error"


def test_the_shared_names_are_derived_not_listed() -> None:
    """The case that keeps the gate honest.

    The config must read the scripts' own declarations on every run. If
    someone replaces that with a literal list of names, a deleted function
    stays on the list and every stale call to it passes.
    """
    assert "matchAll" in CONFIG and "readFileSync" in CONFIG, (
        "eslint.config.mjs no longer derives the shared globals from the source"
    )
    # The derived set is what the classic scripts are linted with.
    assert "...shared" in CONFIG, "the derived names are not given to the linter"
    # And the IIFE publishers are included, which the first version missed.
    assert r"^\s*window\." in CONFIG, (
        "`window.X =` inside an IIFE is not derived, so every SonoranLabels "
        "caller would look undefined"
    )


def test_vendored_and_generated_code_is_left_alone() -> None:
    for name in ("vendor/**", "meshtastic-serial-proto.js", "meshtastic-static.js"):
        assert name in CONFIG, f"{name} is linted, and it is not ours to fix"
