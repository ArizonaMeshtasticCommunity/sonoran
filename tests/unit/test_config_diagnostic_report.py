"""A privacy-safe report when the config checker breaks (#119).

> "Today, when the checker breaks on a real config, we never find out."

The reader is the only person who can tell us, and they will not paste
a stack trace they cannot read, or a config they should not share. So
on failure the page offers a report built from a fixed whitelist of
non-sensitive scalars, prints it in full, and sends nothing.

**Upstream's `diagnostics.js` is imported, not reimplemented.** Its
privacy model is a whitelist: the report is assembled field by field
and there is no code path that copies a caller-supplied object
wholesale, so a future caller passing a config by mistake still cannot
leak one. Reimplementing that would mean reimplementing the guarantee,
and a blacklist written from memory is how PSKs end up in bug reports.

Verified in a browser, with a **planted secret** in the uploaded file —
`PSK_SHOULD_NEVER_APPEAR_1PG7OiApB1nwvP`, inside a file called
`my-node.cfg`:

    panel hidden before a failure:  true
    panel hidden after a failure:   false
    report contains the secret:     false
    report contains the file name:  false

and the report the reader sees:

    AZ Meshtastic Config Checker — diagnostic report
    tool version: v3.1.0
    browser: Chrome 145 / macOS
    generated: 2026-09-23T17:39:36Z
    NOTE: no config contents, channel names, keys, or input data
    #1 ... step=parse Error: Unable to decode binary file. ...
    [redacted] error: invalid wire type 4 [ext=.cfg size=66B]

The secret being present in the input is what makes its absence from
the report mean something.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
CHECK = (STATIC / "config-check.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_the_report_comes_from_upstreams_whitelist_module() -> None:
    assert "from './vendor/config-checker/js/diagnostics.js'" in CHECK, (
        "the diagnostics module is not imported, so either the feature is "
        "gone or somebody has rewritten the privacy guarantee by hand"
    )
    assert "new Diagnostics()" in CHECK


def test_the_failing_step_is_named_from_the_fixed_enum() -> None:
    """Free text in the step field would be a second way to leak.

    Upstream's `STEPS` is a frozen enum and `buildEntry` falls back to
    `unknown` for anything else, which is the property being used here.
    """
    assert "STEPS.PARSE" in CHECK, "the parse failure no longer records a named step"
    assert "STEPS" in CHECK.split("import")[1] or "STEPS }" in CHECK


def test_nothing_is_recorded_until_something_breaks() -> None:
    """The panel is for a reader who has hit a bug, nobody else."""
    assert "data-config-diagnostics hidden" in HTML
    assert "hideDiagnostics(page);" in CHECK, (
        "a previous failure's report stays on the page across a new upload"
    )


def test_the_whole_report_is_shown_before_it_can_be_copied() -> None:
    """#119: "a preview of exactly what will be copied".

    The only thing that makes "this contains nothing private" credible
    is being able to read it, so it is printed in full rather than
    summarised or hidden behind a disclosure.
    """
    start = HTML.index("data-config-diagnostics hidden")
    panel = HTML[start : HTML.index("</div>", HTML.index("data-config-diagnostics-copy"))]
    assert "<pre data-config-diagnostics-text>" in panel, "the report is not shown in full"
    assert panel.index("data-config-diagnostics-text") < panel.index(
        "data-config-diagnostics-copy"
    ), "the copy button comes before the preview, so it can be pressed unread"


def test_a_broken_reporter_does_not_replace_the_bug() -> None:
    """The diagnostics path is wrapped.

    If building the report threw, the reader would lose the
    plain-English message explaining what actually went wrong — a bug
    reporter that eats the bug.
    """
    start = CHECK.index("function recordFailure(")
    body = CHECK[start : CHECK.index("\n}", start)]
    assert "try {" in body and "catch" in body


def test_the_copy_control_says_what_the_browser_did() -> None:
    """Same rule as the planner's copy control.

    `navigator.clipboard` is refused outside a secure context and by
    permission policy. Claiming success there leaves somebody pasting
    nothing into a bug report.
    """
    start = CHECK.index("function drawDiagnostics(")
    body = CHECK[start:]
    body = body[: body.index("\n}\n")]
    assert "The browser refused" in body, (
        "a refused clipboard write is reported as success, so the reader "
        "pastes nothing and never knows"
    )


def test_the_vendored_module_is_not_modified() -> None:
    """It is pinned to an upstream commit and watched by vendor-pin.yml.

    Editing it here would be invisible to that check and lost on the
    next bump.
    """
    module = (STATIC / "vendor" / "config-checker" / "js" / "diagnostics.js").read_text(
        encoding="utf-8"
    )
    assert "sonoran" not in module.lower(), (
        "the vendored diagnostics module mentions this project, so it has "
        "been edited locally rather than imported"
    )
