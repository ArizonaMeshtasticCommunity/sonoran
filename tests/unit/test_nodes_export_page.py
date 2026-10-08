"""The Nodes page exports what it shows (#350).

The behaviour cases in `js/nodes_export_cases.mjs` run the pure parts
under node. Each claim is also mutated here, because a check only ever
seen passing is not evidence that it can fail.
"""

import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sonoran.api import export

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
MODULE = STATIC / "app.js"
INDEX = STATIC / "index.html"
CASES = ROOT / "tests" / "unit" / "js" / "nodes_export_cases.mjs"


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
    assert node, "node is not on PATH, so the export cases went unchecked"
    return subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT)


def _function(name: str) -> str:
    source = MODULE.read_text(encoding="utf-8")
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}", start)]


def test_the_cases_pass() -> None:
    done = _run()
    assert done.returncode == 0, done.stderr


def test_a_filter_left_behind_would_be_caught() -> None:
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "for (const key of ['limit', 'offset', 'cursor']) params.delete(key);",
        "for (const key of ['limit', 'offset', 'cursor', 'role']) params.delete(key);",
    )
    assert broken != source
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when the role filter is dropped"
    assert "role" in done.stderr


def test_the_paging_carried_into_the_file_would_be_caught() -> None:
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace(
        "for (const key of ['limit', 'offset', 'cursor']) params.delete(key);",
        "for (const key of ['offset']) params.delete(key);",
    )
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when the file keeps a page limit"
    assert "limit" in done.stderr


def test_a_column_missing_from_the_file_would_be_caught() -> None:
    source = MODULE.read_text(encoding="utf-8")
    broken = source.replace("export: 'role', ", "", 1)
    assert broken != source
    with _temporarily(MODULE, broken):
        done = _run()
    assert done.returncode != 0, "the cases pass when a drawn column is not exported"


def test_the_page_and_the_server_name_the_same_columns() -> None:
    """The page's keys, in drawn order, are the server's default order."""
    keys = tuple(re.findall(r"export: '(\w+)'", _function("nodeColumns")))
    assert keys == export.DEFAULT_COLUMNS


def test_the_file_is_built_from_the_query_the_table_shows() -> None:
    """Not from the controls: a typed search waits for its pause."""
    body = _function("exportNodes")
    assert "nodeShownQuery || nodeQuery(page)" in body
    loader = _function("loadNodes")
    reset = loader[loader.index("if (reset) {") :]
    reset = reset[: reset.index("\n  }")]
    assert "nodeShownQuery = nodeQuery(page);" in reset, "the shown query is not recorded"


def test_a_refusal_is_shown_and_the_buttons_come_back() -> None:
    body = _function("exportNodes")
    assert "answer.detail" in body, "the server's sentence about the ceiling is not shown"
    finally_ = body[body.index("} finally {") :]
    assert "nodeExporting = false" in finally_
    assert "'aria-disabled', 'false'" in finally_


def test_the_control_is_in_the_page() -> None:
    html = re.sub(r"<!--.*?-->", "", INDEX.read_text(encoding="utf-8"), flags=re.S)
    nodes = html[html.index('data-page="nodes"') :]
    nodes = nodes[: nodes.index("</section>")]
    head = nodes[: nodes.index("data-node-filters")]
    assert "data-node-export" in head, "the export is not in the Nodes page head"
    for fmt in ("csv", "json"):
        assert f'data-node-export-format="{fmt}"' in head
    assert 'role="status" data-node-export-status' in head
    wiring = MODULE.read_text(encoding="utf-8")
    assert "$$('[data-node-export-format]')" in wiring
