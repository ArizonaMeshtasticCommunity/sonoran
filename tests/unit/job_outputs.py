"""An in-memory stand-in for the tables the background jobs write (#351).

The gaps job, the siting half and the calibration fit write tables, and
the API reads them through `sonoran.gaps.store` and the calibration
functions of `sonoran.coverage.store`. A unit test has no database. This
holds the documents in memory and answers every one of those functions
with the same shapes, so a route test can set a state and read a page.

The SQL itself is tested against a real database in
`tests/integration/test_job_outputs.py`. This file must stay a plain
copy of the documented behaviour, with no rule of its own.

Use the `job_outputs` fixture:

    def test_something(job_outputs: JobOutputs) -> None:
        job_outputs.write_index({"presets": [...]})
        job_outputs.write_preset("LongFast", {...})
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from sonoran.coverage import store as coverage_store
from sonoran.gaps import store
from sonoran.gaps.boards import BOARD_WINDOW_HOURS, EVIDENCE_KEYS, TRACE_ANSWERS


class JobOutputs:
    """The documents the jobs wrote, by run key."""

    def __init__(self) -> None:
        self.index: dict[str, object] | None = None
        self.runs: dict[tuple[str, int], dict[str, object]] = {}
        self.siting: dict[str, dict[str, object]] = {}
        self.calibration: dict[str, object] | None = None

    # --- what a test sets up ----------------------------------------------

    def write_index(self, document: dict[str, object]) -> None:
        listed = document.get("presets")
        self.index = {
            "generated_at": document.get("generated_at", datetime.now(UTC).isoformat()),
            "window_hours": document.get("window_hours", 168),
            "presets": list(listed) if isinstance(listed, list) else [],
        }

    def write_preset(self, preset: str, document: dict[str, object]) -> None:
        self.runs[(preset, store.ASSESSMENT_HOURS)] = dict(document)

    def write_boards(self, preset: str, hours: int, document: dict[str, object]) -> None:
        assert hours in BOARD_WINDOW_HOURS
        self.runs[(preset, hours)] = dict(document)

    def write_siting(self, preset: str, document: dict[str, object]) -> None:
        self.siting[preset] = dict(document)

    def write_calibration(self, document: dict[str, object]) -> None:
        self.calibration = dict(document)

    # --- what the code under test calls -----------------------------------

    def _summary(self, key: tuple[str, int]) -> dict[str, object] | None:
        document = self.runs.get(key)
        if document is None:
            return None
        return {k: v for k, v in document.items() if k not in ("nodes", TRACE_ANSWERS)}

    async def read_index(self, _session: Any) -> dict[str, object] | None:
        if self.index is None:
            return None
        presets = []
        for item in self.index["presets"]:  # type: ignore[union-attr]
            name = item.get("preset") if isinstance(item, dict) else None
            if not isinstance(name, str):
                continue
            # The index lists what was assessed. A test that wrote only an
            # index still sees its presets, as the old file did.
            presets.append(item)
        return {**self.index, "presets": presets}

    async def read_summary(self, _session: Any, preset: str) -> dict[str, object] | None:
        return self._summary((preset, store.ASSESSMENT_HOURS))

    async def read_board_summary(
        self, _session: Any, preset: str, hours: int
    ) -> dict[str, object] | None:
        return self._summary((preset, hours)) if hours in BOARD_WINDOW_HOURS else None

    async def read_preset(self, _session: Any, preset: str) -> dict[str, object] | None:
        document = self.runs.get((preset, store.ASSESSMENT_HOURS))
        return None if document is None else dict(document)

    async def read_boards(self, _session: Any, preset: str, hours: int) -> dict[str, object] | None:
        document = self.runs.get((preset, hours))
        return None if document is None else dict(document)

    def _rows(self, key: tuple[str, int]) -> list[dict[str, object]]:
        document = self.runs.get(key) or {}
        listed = document.get("nodes")
        return [row for row in listed if isinstance(row, dict)] if isinstance(listed, list) else []

    async def node_rows(
        self, _session: Any, preset: str, signal: str | None, state: str | None, limit: int
    ) -> tuple[int, list[dict[str, object]]]:
        rows = self._rows((preset, store.ASSESSMENT_HOURS))
        if signal is not None or state is not None:
            rows = [row for row in rows if _matches(row, signal, state)]
        return len(rows), rows[:limit]

    async def node_row(self, _session: Any, preset: str, node_num: int) -> dict[str, object] | None:
        for row in self._rows((preset, store.ASSESSMENT_HOURS)):
            if store.node_num_of(row.get("node_id")) == node_num:
                return row
        return None

    async def assessed_nodes(self, _session: Any, node_num: int) -> dict[str, dict[str, object]]:
        found = {}
        for preset, hours in sorted(self.runs):
            if hours != store.ASSESSMENT_HOURS:
                continue
            row = await self.node_row(None, preset, node_num)
            if row is not None:
                found[preset] = row
        return found

    async def node_nums(self, _session: Any, preset: str, state: str) -> set[int] | None:
        if (preset, store.ASSESSMENT_HOURS) not in self.runs:
            return None
        return {
            num
            for row in self._rows((preset, store.ASSESSMENT_HOURS))
            if row.get("worst_state") == state
            and (num := store.node_num_of(row.get("node_id"))) is not None
        }

    async def top_direct(
        self, _session: Any, preset: str, hours: int | None, limit: int
    ) -> list[dict[str, object]]:
        key = (preset, store.ASSESSMENT_HOURS if hours is None else hours)
        rows = [row for row in self._rows(key) if _count(row, "direct_gateways") > 0]
        rows.sort(key=lambda row: (-_count(row, "direct_gateways"), str(row.get("node_id"))))
        keys = ("node_id", "display_name", *EVIDENCE_KEYS)
        return [{k: row.get(k) for k in keys} for row in rows[:limit]]

    async def trace_answers(
        self, _session: Any, preset: str, hours: int | None
    ) -> list[dict[str, object]] | None:
        document = self.runs.get((preset, store.ASSESSMENT_HOURS if hours is None else hours))
        if document is None:
            return []
        listed = document.get(TRACE_ANSWERS)
        if not isinstance(listed, list):
            return None
        return [row for row in listed if isinstance(row, dict)]

    async def read_siting(self, _session: Any, preset: str) -> dict[str, object] | None:
        document = self.siting.get(preset)
        if document is None:
            return None
        return {k: v for k, v in document.items() if k != "candidates"}

    async def read_candidates(
        self, _session: Any, preset: str, area: int | None, limit: int
    ) -> tuple[int, list[dict[str, object]]]:
        listed = (self.siting.get(preset) or {}).get("candidates")
        rows = [row for row in listed if isinstance(row, dict)] if isinstance(listed, list) else []
        if area is not None:
            rows = [row for row in rows if row.get("area") == area]
        return len(rows), rows[:limit]

    async def read_calibration(self, _session: Any) -> dict[str, object] | None:
        return None if self.calibration is None else dict(self.calibration)

    async def calibration_offsets(self, _session: Any) -> dict[str, float]:
        return {} if self.calibration is None else coverage_store.offsets_of(self.calibration)


def _count(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    return value if isinstance(value, int) else 0


def _matches(row: dict[str, object], signal: str | None, state: str | None) -> bool:
    """The filters of `/api/gaps/nodes`, as `gaps.store._signal_filter` documents them."""
    holder = row.get("signals")
    if not isinstance(holder, dict):
        return False
    if signal is not None:
        found = holder.get(signal)
        if not isinstance(found, dict):
            return False
        return state is None or found.get("state") == state
    return any(isinstance(found, dict) and found.get("state") == state for found in holder.values())


GAPS_READS = (
    "read_index",
    "read_summary",
    "read_board_summary",
    "read_preset",
    "read_boards",
    "node_rows",
    "node_row",
    "assessed_nodes",
    "node_nums",
    "top_direct",
    "trace_answers",
    "read_siting",
    "read_candidates",
)


@pytest.fixture
def job_outputs(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobOutputs]:
    """Answer every read of the job outputs from memory, for one test."""
    held = JobOutputs()
    for name in GAPS_READS:
        monkeypatch.setattr(store, name, getattr(held, name))
    monkeypatch.setattr(coverage_store, "read_calibration", held.read_calibration)
    monkeypatch.setattr(coverage_store, "calibration_offsets", held.calibration_offsets)
    # The node routes import the function by name.
    from sonoran.api.routes import nodes

    monkeypatch.setattr(nodes, "calibration_offsets", held.calibration_offsets)
    yield held
