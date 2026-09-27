"""The node page's packet timeline scrolls on by cursor (#259).

Will: "make it so as you scroll, it shows more and more packets vs having
to hit an older button."

The page half is checked here; the server half, that paging by `before`
returns exactly the one-page answer in every sort and that a packet
arriving between pages moves nothing, is in
`tests/integration/test_packet_cursor.py`. The e2e journey "the packet
timeline scrolls on by cursor" watches the requests a real scroll makes.

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
CASES = ROOT / "tests" / "unit" / "js" / "packet_paging_cases.mjs"


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
    assert node, "node is not on PATH, so the paging cases went unchecked"
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


def test_the_paging_cases_pass() -> None:
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_list_that_drew_duplicates_would_be_caught() -> None:
    done = _broken(
        "    if (!row || seen.has(packetRowKey(row))) continue;",
        "    if (!row) continue;",
    )
    assert done.returncode != 0
    assert "twice" in done.stderr, done.stderr


def test_an_identity_of_packet_id_alone_would_be_caught() -> None:
    """Two senders may use the same packet id (AGENTS.md 9.1)."""
    done = _broken(
        "  return `${row.from_node ?? ''}|${row.packet_id ?? ''}`;",
        "  return `${row.packet_id ?? ''}`;",
    )
    assert done.returncode != 0
    assert "two senders" in done.stderr, done.stderr


def test_a_full_page_treated_as_the_end_would_be_caught() -> None:
    done = _broken(
        "exhausted: served.length < pageSize };",
        "exhausted: served.length <= pageSize };",
    )
    assert done.returncode != 0
    assert "not the end" in done.stderr, done.stderr


def test_the_page_asks_by_cursor_and_never_by_offset() -> None:
    """The query builder names `before` and has no offset to send."""
    app = _code()
    query = app[app.index("function timelineQuery(") :][:600]
    assert "params.set('before', before)" in query
    assert "offset" not in query


def test_the_older_button_is_gone() -> None:
    app = _code()
    assert "text: 'Older'" not in app
    assert "text: 'Newer'" not in app
