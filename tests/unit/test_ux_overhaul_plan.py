"""The UX overhaul plan points at things that exist.

`docs/design/2026-09-26-ux-overhaul.md` is a plan, not code, so nothing
enforces it. What CAN be enforced is that it does not send the next person
somewhere that is not there -- the mistake made twice in this session, once
in a comment about the assumed radio figures and once in a plan pointing at
a chat caption whose real form is a template.

These cases check the plan's factual claims about the current code. When an
item ships, its entry here should fail, because the string it named is
meant to be gone. That is the signal to update the plan rather than let it
drift into fiction.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "design" / "2026-09-26-ux-overhaul.md"
STATIC = ROOT / "src" / "sonoran" / "web" / "static"


def _all_frontend() -> str:
    parts = [(STATIC / "index.html").read_text(encoding="utf-8")]
    parts.extend(path.read_text(encoding="utf-8") for path in sorted(STATIC.glob("*.js")))
    return "\n".join(parts)


def test_the_plan_is_there_and_covers_every_phase() -> None:
    """The control: an empty file passes every case below."""
    text = PLAN.read_text(encoding="utf-8")
    assert len(text) > 8000, f"the plan is only {len(text)} bytes"
    for phase in ("Phase A", "Phase B", "Phase C", "Phase D", "Phase E"):
        assert phase in text, f"{phase} is missing"


def test_every_decision_for_will_has_a_recommendation() -> None:
    """A decision presented without one is a question, not a plan."""
    text = PLAN.read_text(encoding="utf-8")
    section = text[text.index("## 2. Decisions for Will") : text.index("## 3. Phase A")]
    headings = re.findall(r"^### (2\.\d+) ", section, re.M)
    assert len(headings) >= 4, f"only found {headings}"
    assert section.count("*(recommended)*") >= len(headings), (
        f"{len(headings)} decisions but only {section.count('*(recommended)*')} recommendations"
    )


@pytest.mark.parametrize(
    "quoted",
    [
        "Packet kinds",
        "Other kinds",
        "All kinds",
        "Every preset, any time",
        "Node plugged in by USB",
        "Open mesh-graph",
        "NODE_SEARCH_PAUSE_MS",
    ],
)
def test_each_string_the_plan_promises_to_change_exists(quoted: str) -> None:
    """A plan naming copy that is not there wastes the next person's time.

    When one of these ships, this case fails and the plan gets updated --
    which is the point. A plan whose claims are never rechecked becomes
    documentation of a codebase that no longer exists.
    """
    assert quoted in PLAN.read_text(encoding="utf-8"), f"the plan no longer mentions {quoted!r}"
    assert quoted in _all_frontend(), (
        f"the plan says to change {quoted!r} and it is not in the frontend"
    )


def test_the_chat_caption_is_named_as_the_template_it_is() -> None:
    """The one the brief quoted loosely.

    Will wrote "The newest 100 messages in the window, newest first." The
    real string is a template with a count in it, and that count is the
    number he wants moved beside the channel title -- so the string is not
    simply deleted. Named exactly in the plan for that reason.
    """
    plan = PLAN.read_text(encoding="utf-8")
    assert "count(messages.length)" in plan, "the plan quotes a string that does not exist"
    assert "count(messages.length)" in _all_frontend(), "the template itself is gone"


def test_the_plan_records_what_cannot_be_done_as_asked() -> None:
    """Three items in the brief are not straightforwardly possible.

    Each is a decision or a constraint rather than a task, and a plan that
    listed them as tasks would have somebody discover it mid-build.
    """
    plan = PLAN.read_text(encoding="utf-8")
    # Geocoding is blocked by our own CSP.
    assert "connect-src 'self'" in plan, "the CSP constraint on geocoding is not recorded"
    # There is no coordinate-to-climate data in this repo.
    assert "no dataset in this repo that maps a coordinate to" in plan, (
        "the radio climate limit is not recorded"
    )
    # The brief's auto-ack list omits three marks the code treats as acks.
    assert "automation-engine.md" in plan, "the auto-ack source is not cited"


def test_the_csp_claim_is_true() -> None:
    """The plan's one security claim, checked against the code.

    If `connect-src` ever gains a third-party origin, the geocoding item
    changes shape completely -- and so does the page's exposure.
    """
    app = (ROOT / "src" / "sonoran" / "api" / "app.py").read_text(encoding="utf-8")
    assert "connect-src" in app
    assert "\"connect-src 'self'; \"" in app, (
        "connect-src is no longer self-only; re-read the geocoding item"
    )


def test_the_overlap_with_tylers_open_issue_is_recorded() -> None:
    """#232 asks for part of this, and #233 touches one of these pages.

    Designing them twice is the waste this section exists to prevent.
    """
    plan = PLAN.read_text(encoding="utf-8")
    assert "#232" in plan and "#233" in plan
