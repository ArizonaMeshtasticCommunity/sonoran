"""The statistics journey waits for the charts, not for a number (#154).

The journey used `open(page, 'stats', 6000)` -- a fixed pause after
`load` -- and failed on a cold load of `#stats` while passing on later
runs in the same session. #83 wired this suite in as a merge gate, and a
gate that fails at random is a gate people switch off.

Measured against the dev instance, four fresh browser contexts:

    run 1   load 10661 ms   first sized canvas 12718 ms   (+2057)
    run 2   load  9012 ms   first sized canvas  9042 ms   (+30)
    run 3   load  9008 ms   first sized canvas  9011 ms   (+3)
    run 4   load  9284 ms   first sized canvas  9291 ms   (+7)

The gap a fixed pause has to cover varies by seventy times between a
cold run and a warm one, because the leaderboards on that page sit
behind a 900-second cache and the first request after a cold start does
the whole read.

The issue said explicitly not to fix it by raising the timeout: that
trades a fast flake for a slow one and is still a guess. Waiting for the
condition cannot flake on a slow cache and still fails when the charts
do not draw. Both controls were run:

    POSITIVE  3/3 pass, 3 charts in 9406 / 9815 / 9615 ms
    NEGATIVE  echarts stubbed out -> fails on timeout, as it must
"""

import re
from pathlib import Path

E2E = (Path(__file__).resolve().parents[2] / "tools" / "dev" / "e2e.js").read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    """Only the code counts.

    This is the second test in this repo to trip over it: the comment
    explaining why the OLD approach was wrong quotes the old approach,
    so a plain substring search finds the banned text in the very
    explanation of why it is banned, and the test fails against its own
    fix.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def _journey() -> str:
    start = E2E.index("'statistics draws its charts'")
    return _strip_comments(E2E[start : E2E.index("await journey(", start + 10)])


def test_it_does_not_wait_for_a_fixed_duration() -> None:
    body = _journey()
    assert "waitForTimeout" not in body, (
        "the statistics journey is back to a fixed pause, which is what "
        "made it flaky on a cold cache"
    )
    assert "open(page, 'stats'" not in body, (
        "it uses the shared `open` helper again, whose settle is a fixed waitForTimeout"
    )


def test_it_waits_for_the_charts_to_exist() -> None:
    assert "waitFor(page," in _journey(), (
        "the journey no longer waits for a condition, so it is either racing or pausing"
    )


def test_no_journey_waits_with_the_one_helper_the_csp_refuses() -> None:
    """This test used to REQUIRE the thing that broke CI.

    It asserted `waitForFunction`, which is what the first fix for #154
    used, and the e2e run went red on the deployed policy:

        EvalError: Refused to evaluate a string as JavaScript because
        'unsafe-eval' is not an allowed source of script in the following
        Content Security Policy directive: "script-src 'self'
        'nonce-...' 'wasm-unsafe-eval'".

    Playwright installs that poller with CDP `Runtime.evaluate`, which
    is a string. `page.evaluate` goes through `Runtime.callFunctionOn`
    and is allowed, which is what the `waitFor` helper in this file
    uses, and what the comment above it already said in prose before
    this journey ignored it.

    It is invisible locally: Playwright evaluates the predicate once
    before it polls, so on a warm cache the charts are already there
    and it never reaches the blocked path. Only the cold run this
    journey was written for hits it. Hence a test rather than a note.

    Comments are stripped first, because the explanation of why the
    call is banned has to be able to name it. That is the third time
    that has come up in this repo.
    """
    assert "waitForFunction" not in _strip_comments(E2E), (
        "a journey uses page.waitForFunction, which this dashboard's "
        "Content-Security-Policy refuses on any run where the condition "
        "is not already true -- use the waitFor helper"
    )


def test_it_requires_the_canvases_to_have_a_size() -> None:
    """A count alone passes on a chart nobody can see.

    ECharts inserts its canvas before it has measured the container, so
    a canvas can exist at zero size for a frame or two.
    """
    body = _journey()
    assert "width > 0" in body and "height > 0" in body, (
        "the journey counts canvases without checking they were sized, so "
        "it can pass on a chart that drew nothing"
    )


def test_it_still_fails_when_no_chart_draws() -> None:
    """The assertion is the point of the journey; waiting is not."""
    assert "must(drawn && count > 0, 'no chart was drawn')" in _journey(), (
        "the journey waits for charts but no longer asserts it found any, "
        "so a timeout is the only way it can fail"
    )


def test_a_wait_that_gave_up_is_not_a_pass() -> None:
    """`waitFor` RETURNS false on timeout; `waitForFunction` threw.

    That difference is easy to miss when swapping one for the other,
    and missing it turns a timeout into a journey that carries on and
    reports whatever it happens to find. The result has to be read.
    """
    body = _journey()
    assert "const drawn = await waitFor(" in body, "the wait's result is discarded"
    assert "drawn &&" in body, "the journey does not check whether the wait gave up"
