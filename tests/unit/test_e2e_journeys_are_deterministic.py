"""Two e2e journeys that failed now and then (#354).

Both failed on branches that did not touch the code they test, and both
passed on a re-run. A gate that fails at random costs a CI run on
self-hosted hardware each time, and people learn to re-run it.

1. "the firehose says how many packets arrived above you (#280)" built
   its made packets from `rows[0]` of each answer. When the newest real
   row changed between two polls, the made packets took new keys and
   every one counted as new: "9 new" where 4 was right. Reproduced on
   purpose with a stub that puts a new real row on top at each poll:
   "6 new" where 3 was right. With the fix, the same stub gives 4.

2. "chart and checker libraries load only where used (#277)" waited for
   `networkidle` before it left the node page. Playwright fires that
   event once for each document and then answers at once, and the node
   page asks for its signal and packets only after it has drawn the
   history. A long history drew for more than 500 ms with no request
   open, the event fired, and the journey left while the two requests
   were in flight. Reproduced 3 of 3 with a heavy history and those two
   answers held for 3 s; clean in 4 of 4 runs with the fix.

A browser run cannot see these rules, so these tests hold them.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E2E = (ROOT / "tools" / "dev" / "e2e.js").read_text(encoding="utf-8")
APP = (ROOT / "src" / "sonoran" / "web" / "static" / "app.js").read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    """Only the code counts: the comments quote the old approach."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def _journey(title: str) -> str:
    start = E2E.index(title)
    return _strip_comments(E2E[start : E2E.index("await journey(", start + 10)])


FIREHOSE = "'the firehose says how many packets arrived above you (#280)'"
LIBRARIES = "'chart and checker libraries load only where used (#277)'"


def test_the_firehose_stub_reads_the_real_rows_once() -> None:
    body = _journey(FIREHOSE)
    assert "base = { rows" in body, "the stub no longer keeps the first answer"
    assert "...base.rows]" in body, "a poll is built from that poll's own rows again"
    assert "...rows]" not in body, "a poll is built from that poll's own rows again"


def test_a_made_packet_has_the_same_key_on_every_poll() -> None:
    body = _journey(FIREHOSE)
    assert "packet_key: `${base.node}:${990000000 + n}`" in body, (
        "a made packet's key no longer comes from the node captured once, "
        "so a change in the newest real row changes the count"
    )
    assert "new Date().toISOString()" not in body, "a made packet's time changes between polls"


def test_the_libraries_journey_does_not_wait_for_networkidle() -> None:
    assert "networkidle" not in _journey(LIBRARIES), (
        "networkidle fires once for each document, so the wait can return "
        "while the node page's late requests are in flight"
    )


def test_it_waits_for_the_page_to_finish_its_own_render() -> None:
    body = _journey(LIBRARIES)
    assert "waitFor(page, () => !loading && !timelinePaging.busy" in body
    for name in ("'nodes'", "name", "'node'"):
        assert f"await settle({name});" in body, f"the journey leaves {name} without settling"


def test_a_wait_that_gave_up_is_not_a_pass() -> None:
    body = _journey(LIBRARIES)
    assert "must(await waitFor(page, () => !loading" in body, "the wait's result is discarded"
    assert ".catch(() => {})" not in body, "a timed-out wait is swallowed again"


def test_the_names_it_reads_exist_in_the_page() -> None:
    assert re.search(r"^let loading = false;$", APP, re.M)
    assert re.search(r"^let timelinePaging = \{[^}]*\bbusy: false\b", APP, re.M)


def test_the_wait_outlasts_the_page_request_timeout() -> None:
    """A hung request is then ended by the page, and its abort is reported."""
    page = int(re.search(r"^const REQUEST_TIMEOUT_MS = (\d+);$", APP, re.M).group(1))
    wait = re.search(r"!timelinePaging\.busy, (\d+)\)", _journey(LIBRARIES))
    assert wait and int(wait.group(1)) > page


def test_an_abort_is_still_counted_everywhere() -> None:
    """The fix is a wait, never a filter: a real abort must still fail."""
    assert "ERR_ABORTED" not in _strip_comments(E2E)
