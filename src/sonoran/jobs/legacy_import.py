"""Import the JSON files that came before #351, once.

Before #351 the gaps job, the siting half and the calibration fit wrote
JSON files beside the coverage runs:

    {coverage_cache_dir}/gaps/index.json
    {coverage_cache_dir}/gaps/{preset}.json
    {coverage_cache_dir}/gaps/boards-{preset}-{hours}.json
    {coverage_cache_dir}/gaps/siting-{preset}.json
    {coverage_cache_dir}/calibration.json

Those files are in a Docker volume, so the migration cannot read them.
Without this, every page that reads them would be empty after a deploy
until each job ran again: up to half an hour for the gaps page, a whole
coverage cycle for the siting answer, and a day for the calibration. A
coverage run made in that day would also predict without the measured
corrections.

So the jobs process runs this once at start. It imports a kind of file
**only when its tables are empty**, so it can never overwrite a newer
run, and running it again does nothing. It leaves the files where they
are: a rollback to the code before #351 then still finds them.
"""

import json
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings
from sonoran.coverage import store as coverage_store
from sonoran.db.models import CoverageCalibration, GapsRun, GapsSiting
from sonoran.gaps import store
from sonoran.gaps.boards import BOARD_WINDOW_HOURS
from sonoran.logging import get_logger

logger = get_logger(__name__)


def _gaps_dir(settings: Settings) -> Path:
    return Path(settings.coverage_cache_dir) / "gaps"


def _read(path: Path) -> dict[str, object] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


async def _empty(session: AsyncSession, column: object) -> bool:
    return not await session.scalar(select(exists(select(column))))  # type: ignore[call-overload]


async def import_gaps(session: AsyncSession, settings: Settings) -> list[str]:
    """Import the old gaps files when no gaps run is held. Return what was read."""
    if not await _empty(session, GapsRun.preset):
        return []
    root = _gaps_dir(settings)
    index = _read(root / "index.json")
    if index is None:
        return []
    listed = index.get("presets")
    names = [
        str(item["preset"])
        for item in (listed if isinstance(listed, list) else [])
        if isinstance(item, dict) and isinstance(item.get("preset"), str)
    ]
    imported: list[str] = []
    for name in names:
        if not store.PRESET_PATTERN.fullmatch(name):
            continue
        document = _read(root / f"{name}.json")
        if document is not None and await store.write_preset(session, name, document):
            imported.append(f"gaps/{name}.json")
        for hours in BOARD_WINDOW_HOURS:
            held = _read(root / f"boards-{name}-{hours}.json")
            if held is not None and await store.write_boards(session, name, hours, held):
                imported.append(f"gaps/boards-{name}-{hours}.json")
    await store.write_index(session, index)
    return imported


async def import_siting(session: AsyncSession, settings: Settings) -> list[str]:
    """Import the old siting files when no siting answer is held."""
    if not await _empty(session, GapsSiting.preset):
        return []
    imported: list[str] = []
    root = _gaps_dir(settings)
    for path in sorted(root.glob("siting-*.json")) if root.is_dir() else []:
        name = path.stem.removeprefix("siting-")
        if not store.PRESET_PATTERN.fullmatch(name):
            continue
        document = _read(path)
        if document is not None and await store.write_siting(session, name, document):
            imported.append(f"gaps/{path.name}")
    return imported


async def import_calibration(session: AsyncSession, settings: Settings) -> list[str]:
    """Import the old calibration file when no fit is held."""
    if not await _empty(session, CoverageCalibration.id):
        return []
    document = coverage_store.read_calibration_file(settings)
    if document is None or not await coverage_store.write_calibration_document(session, document):
        return []
    return [coverage_store.CALIBRATION_NAME]


async def run_once(session: AsyncSession, settings: Settings) -> list[str]:
    """Import every kind of old file whose tables are empty. Return what was read.

    A failure is logged and does not stop the jobs process: the next run
    of each job writes the tables anyway.
    """
    imported: list[str] = []
    for step in (import_gaps, import_siting, import_calibration):
        try:
            imported += await step(session, settings)
        except Exception:
            await session.rollback()
            logger.exception("could not import the old files of %s", step.__name__)
    if imported:
        logger.info("imported %s files from before #351: %s", len(imported), ", ".join(imported))
    return imported
