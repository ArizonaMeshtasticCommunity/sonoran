"""The "Relayed by" cell shows node names, not "[object HTMLButtonElement]".

Cases in `tests/unit/js/relay_cell_cases.mjs`, run with the shipped `el()`.
"""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "unit" / "js" / "relay_cell_cases.mjs"


def test_the_relay_cell_reads_as_names() -> None:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the relay cell cases went unchecked"
    done = subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert done.returncode == 0, done.stderr or done.stdout
