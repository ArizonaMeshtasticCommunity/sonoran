"""The chat page keeps what it loaded, and the table view pages too (#297).

Will: the overview count leaves tapbacks out; there is no "Load older"
button, older messages load as you scroll; and the table view loads more
on scroll as well, because it stopped at 100 rows.

The count is checked against a real database in
`tests/integration/test_chat_overview_one_query.py`. The paging itself is
driven in a browser by the e2e journey "the chat table pages on as you
scroll". These pin the pure half and the wiring.

Every behaviour case is broken here once, because a check only ever seen
passing is not evidence that it can fail.
"""

import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "sonoran" / "web" / "static" / "app.js"
CASES = ROOT / "tests" / "unit" / "js" / "chat_paging_cases.mjs"


@contextmanager
def _temporarily(path: Path, text: str) -> Iterator[None]:
    original = path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _run() -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the chat paging cases went unchecked"
    return subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT)


def _broken(old: str, new: str) -> subprocess.CompletedProcess[str]:
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(old, new)
    assert broken != source, f"{old!r} has moved; this control checks nothing"
    with _temporarily(MODULE, broken):
        return _run()


def _code() -> str:
    """`app.js` with comments stripped, so prose cannot answer for code."""
    text = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def _function(code: str, name: str) -> str:
    start = code.index(f"function {name}(")
    end = code.index("\n}", start)
    return code[start:end]


def test_the_chat_paging_cases_pass() -> None:
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_key_made_from_the_moving_default_would_be_caught() -> None:
    """The bug itself: the key held `now - 7 days`, which never matched twice."""
    done = _broken(
        "  if (!addressRange) return `${scope}|default`;",
        "  if (!addressRange) return `${scope}|${Date.now()}`;",
    )
    assert done.returncode != 0
    assert "one key across redraws" in done.stderr, done.stderr


def test_a_full_page_merged_under_the_old_rows_would_be_caught() -> None:
    done = _broken(
        "  if (served.length >= pageSize) return { rows: served, restarted: true };",
        "",
    )
    assert done.returncode != 0
    assert "leave a hole" in done.stderr, done.stderr


def test_the_page_keys_on_the_address_not_the_range_in_force() -> None:
    page = _function(_code(), "chatChannelPage")
    assert "chatKey(channel, chatRangeFromAddress(), menuPreset())" in page, (
        "the key is made from the range in force again, whose start moves every call"
    )


def test_the_table_view_asks_for_more_at_its_foot() -> None:
    """No button (Will): the table loads its next page as its foot nears."""
    code = _code()
    watch = _function(code, "chatWatchTableFoot")
    assert "IntersectionObserver" in watch
    assert "chatLoadOlder(page)" in watch
    assert "chatWatchTableFoot(page)" in _function(code, "chatDrawTable")
    assert "chatDrawTable(page)" in _function(code, "chatChannelPage")
    older = _function(code, "chatLoadOlder")
    assert "chatView === 'table'" in older, "loading older still gives up without a scroller"


def test_there_is_no_load_older_button() -> None:
    """Will: "No load older, should just load them as you scroll."."""
    code = _code()
    assert "Load older" not in code


def test_the_cursor_is_the_row_s_own_timestamp() -> None:
    """`seen_at` holds microseconds; a Date would round the cursor to ms."""
    older = _function(_code(), "chatLoadOlder")
    assert "before: oldest.seen_at" in older
    assert "new Date(oldest.seen_at)" not in older


def test_the_view_switch_keeps_the_range() -> None:
    """Chat -> Table must land on the same rows, under the same key."""
    code = _code()
    start = code.index("for (const button of $$('[data-chat-view-choice]'))")
    switch = code[start : start + 600]
    assert "location.hash.indexOf('?')" in switch, "the view switch drops the range"
