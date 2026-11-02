"""CI uses the same Python as the image that we ship.

`pyproject.toml` asks for Python 3.13 or newer, and gives no upper
limit. A microVM starts with no Python that `uv` can use, so `uv`
downloads the newest release. On 2026-11-02 that was CPython 3.15.2,
and `psycopg-binary` 3.3.4 has wheels for cp313 and cp314 only. So
`uv sync` failed in every job (sonoran run 40513955324).

`.python-version` tells `uv` which version to use. It must be the
version of the `python:` base image in the Dockerfile, so that CI tests
the Python that runs in production.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = re.compile(r"^FROM python:(\d+\.\d+)[-@:]", re.MULTILINE)


def _image_python() -> str:
    found = BASE.findall((ROOT / "Dockerfile").read_text(encoding="utf-8"))
    assert found, "the Dockerfile has no python: base image"
    assert len(set(found)) == 1, f"the Dockerfile names more than one Python: {found}"
    return found[0]


def test_the_python_version_is_pinned() -> None:
    path = ROOT / ".python-version"
    assert path.is_file(), "no .python-version, so uv takes the newest Python it can download"


def test_ci_uses_the_python_of_the_image() -> None:
    pinned = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert pinned == _image_python(), (
        f".python-version is {pinned}, the Dockerfile ships {_image_python()}"
    )


def test_the_pin_meets_requires_python() -> None:
    """Would be caught: a pin below what the project supports."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    floor = re.search(r'requires-python\s*=\s*">=(\d+)\.(\d+)"', pyproject)
    assert floor, "requires-python is not a plain >= floor"
    pinned = tuple(int(n) for n in (ROOT / ".python-version").read_text().strip().split("."))
    assert pinned >= (int(floor[1]), int(floor[2]))
