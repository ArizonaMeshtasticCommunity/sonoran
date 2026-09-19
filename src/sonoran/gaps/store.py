"""Where a gap assessment is kept.

One file for each modem preset, beside the coverage runs:

    {coverage_cache_dir}/gaps/index.json
    {coverage_cache_dir}/gaps/{preset}.json

**Nothing is computed per request.** The job writes these files and the
API reads them and filters. That is not a preference. `docs/ISSUES.md`
2.9 is an open warning about a public endpoint doing per-row work while
the map refreshes it every 15 seconds, and the gap queries are heavier
than the one that warning is about.

**No new table in phase 1.** A JSON artefact needs no migration, no new
grant, and cannot be caught by the `ON CONFLICT DO UPDATE` trap in
`AGENTS.md` 9.2. If trend history is wanted later, a hypertable can be
added and this stays the serving path.

Each file is written to a temporary name and renamed over the old one,
so a reader never sees a torn file.
"""

import json
import re
from pathlib import Path

from sonoran.config import Settings
from sonoran.logging import get_logger

logger = get_logger(__name__)

INDEX_NAME = "index.json"

# What a preset name may look like before it becomes part of a path.
#
# Preset names come from our own table, so this is not a hole today. It
# is checked anyway, because a path built from a name is the shape of a
# hole and the check costs nothing. The same reasoning holds
# `STAMP_PATTERN` in `coverage/store.py`.
PRESET_PATTERN = re.compile(r"^[A-Za-z]{1,32}$")


def gaps_dir(settings: Settings) -> Path:
    """Return where the gap assessments are kept."""
    return Path(settings.coverage_cache_dir) / "gaps"


def preset_path(settings: Settings, preset: str) -> Path | None:
    """Return the file of one preset's assessment, or None for a bad name."""
    if not PRESET_PATTERN.fullmatch(preset):
        return None
    return gaps_dir(settings) / f"{preset}.json"


def _write_atomically(path: Path, document: dict[str, object]) -> None:
    """Write one JSON file so that no reader ever sees it half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=1), encoding="utf-8")
    temporary.replace(path)


def write_preset(settings: Settings, preset: str, document: dict[str, object]) -> Path | None:
    """Write one preset's assessment. Return where it went, or None."""
    path = preset_path(settings, preset)
    if path is None:
        logger.warning("refusing to write a gap assessment for the name %r", preset)
        return None
    _write_atomically(path, document)
    return path


def siting_path(settings: Settings, preset: str) -> Path | None:
    """Return the file of one preset's siting answer, or None.

    The siting half is kept in its own file, beside the per node one and
    never inside it. The two are written by different jobs on different
    clocks: the per node assessment is SQL and runs every half hour,
    while the siting half runs the engine and joins the coverage cycle.
    One file holding both would be rewritten by whichever job finished
    last, and half of it would always be stale.
    """
    if not PRESET_PATTERN.fullmatch(preset):
        return None
    return gaps_dir(settings) / f"siting-{preset}.json"


def write_siting(settings: Settings, preset: str, document: dict[str, object]) -> Path | None:
    """Write one preset's siting answer. Return where it went, or None."""
    path = siting_path(settings, preset)
    if path is None:
        logger.warning("refusing to write a siting answer for the name %r", preset)
        return None
    _write_atomically(path, document)
    return path


def read_siting(settings: Settings, preset: str) -> dict[str, object] | None:
    """Return one preset's siting answer, or None.

    None is a working state. The siting half runs inside the coverage
    cycle, so a box that has never finished a coverage run has no answer
    yet and the page says so.
    """
    path = siting_path(settings, preset)
    if path is None:
        return None
    return _read(path)


def write_index(settings: Settings, document: dict[str, object]) -> Path:
    """Write the list of presets that have an assessment.

    The index is written **after** every preset file, so a reader that
    follows it never finds a name with no file behind it.
    """
    path = gaps_dir(settings) / INDEX_NAME
    _write_atomically(path, document)
    return path


def read_index(settings: Settings) -> dict[str, object] | None:
    """Return the index, or None when the job has never run.

    None is a working state, not a fault. The page says the assessment
    has not been made yet, exactly as `/api/coverage` treats a missing
    run.
    """
    return _read(gaps_dir(settings) / INDEX_NAME)


def read_preset(settings: Settings, preset: str) -> dict[str, object] | None:
    """Return one preset's assessment, or None."""
    path = preset_path(settings, preset)
    if path is None:
        return None
    return _read(path)


def _read(path: Path) -> dict[str, object] | None:
    """Return one JSON document, or None when it cannot be read."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        logger.warning("cannot read %s: %s", path.name, error)
        return None
    return document if isinstance(document, dict) else None


def clear(settings: Settings) -> None:
    """Delete every assessment. For a test, and for a deployment reset."""
    root = gaps_dir(settings)
    if not root.is_dir():
        return
    for path in root.glob("*.json"):
        path.unlink(missing_ok=True)
