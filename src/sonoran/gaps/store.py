"""Where a gap assessment is kept: in the database (#351).

The gaps job used to write one JSON file per preset beside the coverage
runs, and the API read the files. It now writes these tables. See
`docs/DATABASE.md` 5B.

- `gaps_index`: when the job last ran, and over what window.
- `gaps_run`: one assessment of a preset (`scope` `assessment`), or the
  leaderboard counts of one more Statistics window (`scope` `board`,
  `asked_hours` 24 or 720, see `sonoran/gaps/boards.py`). `summary`
  holds the run's own fields: its window, thresholds, labels, caveats
  and counts.
- `gaps_node`: one row per node, in the order the job ranked them.
- `gaps_signal`: one row per node per signal. Its state, reason, value
  and unit are columns, and its evidence, whose shape is the signal's
  own, is `jsonb`.
- `gaps_trace_answer`: the traceroute counts of the reachable board.
- `gaps_siting`, `gaps_siting_area`, `gaps_siting_point` and
  `gaps_siting_candidate`: the siting answer.

**Nothing is computed per request.** The job writes the rows and the
API selects and filters them. `docs/ISSUES.md` 2.9 still holds: a gap
signal is never worked out while a page waits. A signal's sentence and
a candidate's sentence are words looked up for a stored reason, not a
finding.

**A run is replaced, never edited.** Each write deletes the run, whose
rows go with it (`ON DELETE CASCADE`), inserts the new one, and commits
once, so a reader sees the old run or the new one and never half of
each. The jobs role has SELECT, INSERT and DELETE on these tables and
no UPDATE.

**Names are read live.** A row does not store the node's name, short
name or role. A reader joins `node`, so a node renamed after the run
reads with its new name. The position stays as the job assessed it,
because the findings belong to that position.

**A node row names a real node.** `gaps_node.node_num` references
`node`. The job leaves out a row whose node has no record, and says so
in the log, so that key can never fail a whole run.

The documents these functions return have the shape the JSON files had,
so a reader written for the files reads them unchanged.
"""

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, exists, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.names import display_name, format_node_id
from sonoran.config import Settings
from sonoran.db.models import (
    GAPS_SCOPE_ASSESSMENT,
    GAPS_SCOPE_BOARD,
    GapsIndex,
    GapsNode,
    GapsRun,
    GapsSignal,
    GapsSiting,
    GapsSitingArea,
    GapsSitingCandidate,
    GapsSitingPoint,
    GapsTraceAnswer,
    Node,
)
from sonoran.gaps.boards import BOARD_WINDOW_HOURS, EVIDENCE_KEYS, TRACE_ANSWERS
from sonoran.gaps.signals import sentence_for
from sonoran.gaps.siting import Candidate, candidate_sentence
from sonoran.logging import get_logger
from sonoran.roles import role_name

logger = get_logger(__name__)

# What a preset name may look like before it is stored.
#
# Preset names come from our own table, so this is not a hole today. It
# was checked when the name became part of a file path, and it is still
# checked, because a key that cannot be checked is the shape of a hole.
PRESET_PATTERN = re.compile(r"^[A-Za-z]{1,32}$")

# The run key of a preset's assessment. Its window is
# `GAPS_WINDOW_HOURS`, not a window a page asks for.
ASSESSMENT_HOURS = 0

# The columns of an assessment row, in the order the old file wrote them
# after `node_id`, `display_name`, `role` and `preset`. `signals` comes
# last, from `gaps_signal`.
ROW_COLUMNS = (
    "latitude",
    "longitude",
    "position_confidence",
    "position_deviation_m",
    "is_mqtt_gateway",
    "mobile",
    "position_spread_km",
    "packets",
    "rf_packets",
    "ambiguous_packets",
    "active_hours",
    "rf_hours",
    "direct_gateways",
    "worst_state",
    "bad_count",
    "unknown_count",
)

# Set in a run's summary when the document it came from held no
# traceroute counts: a board file written before #293, imported once.
# The reachable board then says the answers were not counted yet, not
# that nobody qualified. Never served.
NO_TRACE_ANSWERS = "_no_trace_answers"


def _valid(preset: str) -> bool:
    return bool(PRESET_PATTERN.fullmatch(preset))


def node_num_of(node_id: object) -> int | None:
    """Return the node number of a `!xxxxxxxx` node ID, or None."""
    if not isinstance(node_id, str) or not re.fullmatch(r"![0-9a-fA-F]{8}", node_id):
        return None
    return int(node_id[1:], 16)


def _nums(node_ids: object) -> list[int]:
    listed = node_ids if isinstance(node_ids, list | tuple) else []
    return [num for item in listed if (num := node_num_of(item)) is not None]


def _when(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


# --- writing ------------------------------------------------------------


async def _known(session: AsyncSession, nums: list[int]) -> set[int]:
    """Return which of these node numbers have a `node` record."""
    if not nums:
        return set()
    rows = await session.scalars(select(Node.node_num).where(Node.node_num.in_(nums)))
    return set(rows.all())


async def _write_run(
    session: AsyncSession, preset: str, scope: str, asked: int, document: dict[str, object]
) -> bool:
    """Replace one run with a document, and commit. Return False to refuse."""
    if not _valid(preset):
        logger.warning("refusing to write a gaps run for the name %r", preset)
        return False
    generated = _when(document.get("generated_at"))
    if generated is None:
        logger.warning("refusing to write a gaps run for %s with no generated_at", preset)
        return False

    listed = document.get("nodes")
    rows = [row for row in listed if isinstance(row, dict)] if isinstance(listed, list) else []
    answers = document.get(TRACE_ANSWERS)
    summary = {key: value for key, value in document.items() if key not in ("nodes", TRACE_ANSWERS)}
    if not isinstance(answers, list):
        summary[NO_TRACE_ANSWERS] = True

    key = {"preset": preset, "scope": scope, "asked_hours": asked}
    await _delete_run(session, preset, scope, asked)
    await session.execute(
        insert(GapsRun).values(
            **key,
            generated_at=generated,
            window_hours=_int(document.get("window_hours")),
            summary=summary,
        )
    )

    known = await _known(session, [num for row in rows if (num := node_num_of(row.get("node_id")))])
    node_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    left_out = 0
    for rank, row in enumerate(rows):
        node_num = node_num_of(row.get("node_id"))
        if node_num is None:
            continue
        if node_num not in known:
            left_out += 1
            continue
        values: dict[str, Any] = {**key, "node_num": node_num, "rank": rank}
        for column in ROW_COLUMNS:
            if column in row:
                values[column] = row[column]
        node_rows.append(values)
        signals = row.get("signals")
        for position, (name, signal) in enumerate(
            signals.items() if isinstance(signals, dict) else []
        ):
            if not isinstance(signal, dict) or not isinstance(signal.get("state"), str):
                continue
            evidence = signal.get("evidence")
            signal_rows.append(
                {
                    **key,
                    "node_num": node_num,
                    "signal": str(name),
                    "position": position,
                    "state": signal["state"],
                    "reason": str(signal.get("reason") or ""),
                    "value": _float(signal.get("value")),
                    "unit": signal.get("unit") if isinstance(signal.get("unit"), str) else None,
                    "evidence": evidence if isinstance(evidence, dict) else {},
                }
            )
    if left_out:
        logger.warning(
            "gaps run %s %s %s: %s rows left out, their node has no record yet",
            preset,
            scope,
            asked,
            left_out,
        )
    if node_rows:
        # One INSERT per distinct set of columns: an assessment row fills
        # every column and a board row only its counts.
        for columns in {tuple(sorted(values)) for values in node_rows}:
            same = [values for values in node_rows if tuple(sorted(values)) == columns]
            await session.execute(insert(GapsNode), same)
    if signal_rows:
        await session.execute(insert(GapsSignal), signal_rows)

    answer_rows: list[dict[str, Any]] = []
    for row in answers if isinstance(answers, list) else []:
        node_num = node_num_of(row.get("node_id")) if isinstance(row, dict) else None
        if node_num is None:
            continue
        answer_rows.append(
            {
                **key,
                "node_num": node_num,
                "requests": _int(row.get("requests")) or 0,
                "answered": _int(row.get("answered")) or 0,
                "senders": _int(row.get("senders")) or 0,
            }
        )
    if answer_rows:
        await session.execute(insert(GapsTraceAnswer), answer_rows)
    await session.commit()
    return True


async def _delete_run(session: AsyncSession, preset: str, scope: str, asked: int) -> None:
    """Delete one run. Its nodes, signals and counts go with it (CASCADE)."""
    await session.execute(
        delete(GapsRun).where(
            GapsRun.preset == preset, GapsRun.scope == scope, GapsRun.asked_hours == asked
        )
    )


async def write_preset(session: AsyncSession, preset: str, document: dict[str, object]) -> bool:
    """Replace one preset's assessment. Return False when it was refused."""
    return await _write_run(session, preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS, document)


async def write_boards(
    session: AsyncSession, preset: str, hours: int, document: dict[str, object]
) -> bool:
    """Replace one preset's leaderboard counts for one window, or refuse.

    `hours` is the window as the page names it, one of
    `BOARD_WINDOW_HOURS`. Any other number is refused, so a run cannot
    be stored under a window no page asks for.
    """
    if hours not in BOARD_WINDOW_HOURS:
        logger.warning("refusing to write leaderboard counts for %r over %r hours", preset, hours)
        return False
    return await _write_run(session, preset, GAPS_SCOPE_BOARD, hours, document)


async def write_index(session: AsyncSession, document: dict[str, object]) -> None:
    """Record when the job ran, and drop the presets it no longer assessed.

    Called **after** every preset is written, as the old index file was,
    so a reader that follows it never finds a preset with no rows. A
    preset that is not in `presets` any more loses its assessment, its
    board windows and its siting answer: the old files were left behind
    and kept answering for a mesh that had stopped.
    """
    generated = _when(document.get("generated_at"))
    window = _int(document.get("window_hours"))
    listed = document.get("presets")
    kept = [
        str(item["preset"])
        for item in (listed if isinstance(listed, list) else [])
        if isinstance(item, dict) and isinstance(item.get("preset"), str)
    ]
    await session.execute(delete(GapsRun).where(GapsRun.preset.not_in(kept)))
    await session.execute(delete(GapsSiting).where(GapsSiting.preset.not_in(kept)))
    await session.execute(delete(GapsIndex))
    if generated is not None and window is not None:
        await session.execute(
            insert(GapsIndex).values(id=1, generated_at=generated, window_hours=window)
        )
    await session.commit()


async def write_siting(session: AsyncSession, preset: str, document: dict[str, object]) -> bool:
    """Replace one preset's siting answer. Return False when it was refused."""
    if not _valid(preset):
        logger.warning("refusing to write a siting answer for the name %r", preset)
        return False
    areas = [row for row in _list(document.get("areas")) if isinstance(row, dict)]
    candidates = [row for row in _list(document.get("candidates")) if isinstance(row, dict)]
    summary = {key: value for key, value in document.items() if key not in ("areas", "candidates")}
    await session.execute(delete(GapsSiting).where(GapsSiting.preset == preset))
    await session.execute(
        insert(GapsSiting).values(
            preset=preset, generated_at=_when(document.get("generated_at")), summary=summary
        )
    )

    area_rows: list[dict[str, Any]] = []
    point_rows: list[dict[str, Any]] = []
    for item in areas:
        area = _int(item.get("area"))
        centroid = _list(item.get("centroid"))
        bounds = _list(item.get("bounds"))
        if area is None or len(centroid) != 2 or len(bounds) != 4:
            continue
        area_rows.append(
            {
                "preset": preset,
                "area": area,
                "point_count": _int(item.get("point_count")) or 0,
                "node_count": _int(item.get("node_count")) or 0,
                "node_nums": _nums(item.get("node_ids")),
                "centroid_lat": float(centroid[0]),
                "centroid_lon": float(centroid[1]),
                "south": float(bounds[0]),
                "west": float(bounds[1]),
                "north": float(bounds[2]),
                "east": float(bounds[3]),
                "width_km": _float(item.get("width_km")) or 0.0,
            }
        )
        for position, point in enumerate(_list(item.get("points"))):
            if not isinstance(point, dict):
                continue
            point_rows.append(
                {
                    "preset": preset,
                    "area": area,
                    "position": position,
                    "latitude": _float(point.get("latitude")) or 0.0,
                    "longitude": _float(point.get("longitude")) or 0.0,
                    "node_count": _int(point.get("node_count")) or 0,
                    "node_nums": _nums(point.get("node_ids")),
                    "names": [str(name) for name in _list(point.get("names"))],
                }
            )
    if area_rows:
        await session.execute(insert(GapsSitingArea), area_rows)
    if point_rows:
        await session.execute(insert(GapsSitingPoint), point_rows)

    candidate_rows: list[dict[str, Any]] = []
    for position, row in enumerate(candidates):
        area = _int(row.get("area"))
        latitude, longitude = _float(row.get("latitude")), _float(row.get("longitude"))
        if area is None or latitude is None or longitude is None:
            continue
        candidate_rows.append(
            {
                "preset": preset,
                "position": position,
                "kind": str(row.get("kind") or ""),
                "area": area,
                "latitude": latitude,
                "longitude": longitude,
                "elevation_m": _int(row.get("elevation_m")),
                "prominence_m": _int(row.get("prominence_m")),
                "node_num": node_num_of(row.get("node_id")),
                "method": str(row.get("method") or ""),
                "state": str(row.get("state") or ""),
                "screen_score": _int(row.get("screen_score")) or 0,
                "screen_unknown": _int(row.get("screen_unknown")) or 0,
                "newly_usable": _int(row.get("newly_usable")),
                "newly_usable_nodes": _nums(row.get("newly_usable_nodes")),
                "already_usable": _int(row.get("already_usable")) or 0,
                "baseline_unknown": _int(row.get("baseline_unknown")) or 0,
                "run_stamp": row.get("run_stamp")
                if isinstance(row.get("run_stamp"), str)
                else None,
                "reason": str(row.get("reason") or ""),
            }
        )
    if candidate_rows:
        await session.execute(insert(GapsSitingCandidate), candidate_rows)
    await session.commit()
    return True


def _list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


async def clear(session: AsyncSession) -> None:
    """Delete every assessment and siting answer. For a test, and a reset."""
    for table in (GapsRun, GapsSiting, GapsIndex):
        await session.execute(delete(table))
    await session.commit()


# --- reading ------------------------------------------------------------


async def read_index(session: AsyncSession) -> dict[str, object] | None:
    """Return the index, or None when the job has never run.

    None is a working state, not a fault. The page says the assessment
    has not been made yet, exactly as `/api/coverage` treats a missing
    run. The presets are the ones that hold an assessment, with the
    counts the old index file carried.
    """
    held = await session.scalar(select(GapsIndex).where(GapsIndex.id == 1))
    if held is None:
        return None
    rows = (
        await session.execute(
            select(GapsRun.preset, GapsRun.summary)
            .where(
                GapsRun.scope == GAPS_SCOPE_ASSESSMENT,
                GapsRun.asked_hours == ASSESSMENT_HOURS,
            )
            .order_by(GapsRun.preset)
        )
    ).all()
    presets = []
    for preset, summary in rows:
        summary = summary if isinstance(summary, dict) else {}
        presets.append(
            {
                "preset": preset,
                "label": summary.get("label"),
                "node_count": summary.get("assessed_count"),
                "needs_help_count": summary.get("needs_help_count"),
                "not_enough_evidence_count": summary.get("not_enough_evidence_count"),
            }
        )
    return {
        "generated_at": held.generated_at.isoformat(),
        "window_hours": held.window_hours,
        "presets": presets,
    }


async def assessed_presets(session: AsyncSession, settings: Settings) -> list[dict[str, object]]:
    """The assessed presets in the order a page should offer them.

    `settings.default_preset` leads, then the rest by node count (#177).
    It leads **only when it was assessed**: a preferred preset absent
    from the index would otherwise put an empty page at the top, which
    is a worse answer than the wrong preset.

    Why preferred rather than busiest, which this used to be: the
    busiest preset moves with the traffic, so the page a reader lands on
    changed underneath them. The one the community actually runs does
    not.

    Lives here, beside the index it reads, because two routes need the
    same order. A second copy of the sort is how the gaps page and the
    leaderboards drifted apart once already.
    """
    index = await read_index(session)
    listed = index.get("presets") if index else None
    items = [
        item
        for item in (listed if isinstance(listed, list) else [])
        if isinstance(item, dict) and isinstance(item.get("preset"), str)
    ]
    items.sort(key=lambda item: -_count(item, "node_count"))
    items.sort(key=lambda item: item.get("preset") != settings.default_preset)
    return items


def _count(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    return value if isinstance(value, int) else 0


def _served(summary: object) -> dict[str, object]:
    if not isinstance(summary, dict):
        return {}
    return {key: value for key, value in summary.items() if key != NO_TRACE_ANSWERS}


async def _summary(
    session: AsyncSession, preset: str, scope: str, asked: int
) -> dict[str, object] | None:
    if not _valid(preset):
        return None
    summary = await session.scalar(
        select(GapsRun.summary).where(
            GapsRun.preset == preset, GapsRun.scope == scope, GapsRun.asked_hours == asked
        )
    )
    return summary if isinstance(summary, dict) else None


async def read_summary(session: AsyncSession, preset: str) -> dict[str, object] | None:
    """Return one preset's assessment without its rows, or None."""
    summary = await _summary(session, preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS)
    return None if summary is None else _served(summary)


async def read_board_summary(
    session: AsyncSession, preset: str, hours: int
) -> dict[str, object] | None:
    """Return one preset's leaderboard window without its rows, or None.

    None is a working state. Until the job has written that window the
    boards serve the assessment and say it is not the page range.
    """
    if hours not in BOARD_WINDOW_HOURS:
        return None
    summary = await _summary(session, preset, GAPS_SCOPE_BOARD, hours)
    return None if summary is None else _served(summary)


def _named(statement: Select[Any]) -> Select[Any]:
    """Join `node` for the live name, short name and role of each row."""
    return statement.outerjoin(Node, Node.node_num == GapsNode.node_num).add_columns(
        Node.long_name, Node.short_name, Node.role
    )


def _run_where(preset: str, scope: str, asked: int) -> list[Any]:
    return [GapsNode.preset == preset, GapsNode.scope == scope, GapsNode.asked_hours == asked]


async def _signals(
    session: AsyncSession, preset: str, scope: str, asked: int, nums: list[int]
) -> dict[int, dict[str, object]]:
    """Return the signals of these nodes in one run, by node, in the job's order."""
    if not nums:
        return {}
    rows = await session.scalars(
        select(GapsSignal)
        .where(
            GapsSignal.preset == preset,
            GapsSignal.scope == scope,
            GapsSignal.asked_hours == asked,
            GapsSignal.node_num.in_(nums),
        )
        .order_by(GapsSignal.node_num, GapsSignal.position)
    )
    found: dict[int, dict[str, object]] = defaultdict(dict)
    for signal in rows.all():
        found[signal.node_num][signal.signal] = {
            "state": signal.state,
            "reason": signal.reason,
            "sentence": sentence_for(signal.reason, signal.value, signal.evidence),
            "value": signal.value,
            "unit": signal.unit,
            "evidence": dict(signal.evidence),
        }
    return found


async def _assessment_rows(
    session: AsyncSession, preset: str, rows: list[Any]
) -> list[dict[str, object]]:
    """Turn joined `gaps_node` rows into the rows the old file held."""
    signals = await _signals(
        session,
        preset,
        GAPS_SCOPE_ASSESSMENT,
        ASSESSMENT_HOURS,
        [row[0].node_num for row in rows],
    )
    found: list[dict[str, object]] = []
    for node, long_name, short_name, role in rows:
        item: dict[str, object] = {
            "node_id": format_node_id(node.node_num),
            "display_name": display_name(node.node_num, long_name, short_name),
            "role": role_name(role),
            "preset": preset,
        }
        for column in ROW_COLUMNS:
            item[column] = getattr(node, column)
        item["signals"] = signals.get(node.node_num, {})
        found.append(item)
    return found


def _board_row(row: GapsNode, long_name: str | None, short_name: str | None) -> dict[str, object]:
    found: dict[str, object] = {
        "node_id": format_node_id(row.node_num),
        "display_name": display_name(row.node_num, long_name, short_name),
    }
    for column in EVIDENCE_KEYS:
        found[column] = getattr(row, column)
    return found


async def _answers(
    session: AsyncSession, preset: str, scope: str, asked: int
) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            select(GapsTraceAnswer, Node.long_name, Node.short_name)
            .outerjoin(Node, Node.node_num == GapsTraceAnswer.node_num)
            .where(
                GapsTraceAnswer.preset == preset,
                GapsTraceAnswer.scope == scope,
                GapsTraceAnswer.asked_hours == asked,
            )
            .order_by(GapsTraceAnswer.node_num)
        )
    ).all()
    return [
        {
            "node_id": format_node_id(answer.node_num),
            "display_name": display_name(answer.node_num, long_name, short_name),
            "requests": answer.requests,
            "answered": answer.answered,
            "senders": answer.senders,
        }
        for answer, long_name, short_name in rows
    ]


async def read_preset(session: AsyncSession, preset: str) -> dict[str, object] | None:
    """Return one preset's whole assessment, rows included, or None.

    The siting half reads this, and so does a reader that needs every
    row. A page that needs a few rows uses `node_rows` or `node_row`.
    """
    summary = await _summary(session, preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS)
    if summary is None:
        return None
    rows = (
        await session.execute(
            _named(
                select(GapsNode).where(*_run_where(preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS))
            ).order_by(GapsNode.rank)
        )
    ).all()
    document = _served(summary)
    if not summary.get(NO_TRACE_ANSWERS):
        document[TRACE_ANSWERS] = await _answers(
            session, preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS
        )
    document["nodes"] = await _assessment_rows(session, preset, list(rows))
    return document


async def read_boards(session: AsyncSession, preset: str, hours: int) -> dict[str, object] | None:
    """Return one preset's whole leaderboard window, rows included, or None."""
    if hours not in BOARD_WINDOW_HOURS:
        return None
    summary = await _summary(session, preset, GAPS_SCOPE_BOARD, hours)
    if summary is None:
        return None
    rows = (
        await session.execute(
            _named(select(GapsNode).where(*_run_where(preset, GAPS_SCOPE_BOARD, hours))).order_by(
                GapsNode.rank
            )
        )
    ).all()
    document = _served(summary)
    if not summary.get(NO_TRACE_ANSWERS):
        document[TRACE_ANSWERS] = await _answers(session, preset, GAPS_SCOPE_BOARD, hours)
    document["nodes"] = [
        _board_row(row, long_name, short_name) for row, long_name, short_name, _ in rows
    ]
    return document


def _signal_filter(signal: str | None, state: str | None) -> Any:
    """The SQL form of the signal and state filters of `/api/gaps/nodes`.

    With a signal and no state, a row that holds that signal matches,
    whatever its state. With a state and no signal, a row matches when
    **any** of its signals holds that state, which is how "show me the
    unknowns" is asked for.
    """
    where = [
        GapsSignal.preset == GapsNode.preset,
        GapsSignal.scope == GapsNode.scope,
        GapsSignal.asked_hours == GapsNode.asked_hours,
        GapsSignal.node_num == GapsNode.node_num,
    ]
    if signal is not None:
        where.append(GapsSignal.signal == signal)
    if state is not None:
        where.append(GapsSignal.state == state)
    return exists(select(GapsSignal.node_num).where(*where))


async def node_rows(
    session: AsyncSession,
    preset: str,
    signal: str | None,
    state: str | None,
    limit: int,
    after: int | None = None,
) -> tuple[int, list[dict[str, object]], int | None]:
    """Return how many rows match, one page of them worst first, and where the next starts.

    The order is the job's `rank`. `after` is the rank of the last row
    of the page before, and the third value is the `after` of the next
    page, or None when this is the last one. The filters select; they
    never recompute a signal.
    """
    where = _run_where(preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS)
    if signal is not None or state is not None:
        where.append(_signal_filter(signal, state))
    matched = await session.scalar(select(func.count()).select_from(GapsNode).where(*where)) or 0
    paged = [*where, GapsNode.rank > after] if after is not None else where
    rows = list(
        (
            await session.execute(
                _named(select(GapsNode).where(*paged)).order_by(GapsNode.rank).limit(limit + 1)
            )
        ).all()
    )
    following = rows[limit - 1][0].rank if len(rows) > limit else None
    return matched, await _assessment_rows(session, preset, rows[:limit]), following


async def node_row(session: AsyncSession, preset: str, node_num: int) -> dict[str, object] | None:
    """Return one node's assessment row on one preset, or None."""
    rows = (
        await session.execute(
            _named(
                select(GapsNode).where(
                    *_run_where(preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS),
                    GapsNode.node_num == node_num,
                )
            )
        )
    ).all()
    found = await _assessment_rows(session, preset, list(rows))
    return found[0] if found else None


async def node_nums(session: AsyncSession, preset: str, state: str) -> set[int] | None:
    """Return the nodes whose worst state is `state` on one preset.

    None means no assessment has been written for that preset, which is
    a different answer from an empty set.
    """
    if await _summary(session, preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS) is None:
        return None
    rows = await session.scalars(
        select(GapsNode.node_num).where(
            *_run_where(preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS),
            GapsNode.worst_state == state,
        )
    )
    return set(rows.all())


async def assessed_nodes(session: AsyncSession, node_num: int) -> dict[str, dict[str, object]]:
    """Return one node's assessment row on every preset that assessed it, by preset."""
    presets = await session.scalars(
        select(GapsNode.preset).where(
            GapsNode.scope == GAPS_SCOPE_ASSESSMENT,
            GapsNode.asked_hours == ASSESSMENT_HOURS,
            GapsNode.node_num == node_num,
        )
    )
    found: dict[str, dict[str, object]] = {}
    for preset in presets.all():
        row = await node_row(session, preset, node_num)
        if row is not None:
            found[preset] = row
    return found


async def top_direct(
    session: AsyncSession, preset: str, hours: int | None, limit: int
) -> list[dict[str, object]]:
    """Return the rows heard directly by the most gateways, most first.

    `hours` None reads the assessment, a number reads that board window.
    Ties go by node number, which is the order of the node IDs.
    """
    scope, asked = (
        (GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS) if hours is None else (GAPS_SCOPE_BOARD, hours)
    )
    rows = (
        await session.execute(
            _named(select(GapsNode).where(*_run_where(preset, scope, asked)))
            .where(GapsNode.direct_gateways > 0)
            .order_by(GapsNode.direct_gateways.desc(), GapsNode.node_num)
            .limit(limit)
        )
    ).all()
    return [_board_row(row, long_name, short_name) for row, long_name, short_name, _ in rows]


async def trace_answers(
    session: AsyncSession, preset: str, hours: int | None
) -> list[dict[str, object]] | None:
    """Return the traceroute counts of a run, or None when it has none.

    None is not an empty list. No run means nothing was assessed, which
    is an empty list as before. A run imported from a file written
    before #293 holds no counts, so its board says the answers were not
    counted yet, rather than that nobody qualified.
    """
    scope, asked = (
        (GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS) if hours is None else (GAPS_SCOPE_BOARD, hours)
    )
    summary = await _summary(session, preset, scope, asked)
    if summary is None:
        return []
    if summary.get(NO_TRACE_ANSWERS):
        return None
    return await _answers(session, preset, scope, asked)


async def read_siting(session: AsyncSession, preset: str) -> dict[str, object] | None:
    """Return one preset's siting answer with its areas and without its candidates.

    None is a working state. The siting half runs inside the coverage
    cycle, so a box that has never finished a coverage run has no answer
    yet and the page says so.
    """
    if not _valid(preset):
        return None
    summary = await session.scalar(select(GapsSiting.summary).where(GapsSiting.preset == preset))
    if not isinstance(summary, dict):
        return None
    areas = (
        await session.scalars(
            select(GapsSitingArea)
            .where(GapsSitingArea.preset == preset)
            .order_by(GapsSitingArea.area)
        )
    ).all()
    points = (
        await session.scalars(
            select(GapsSitingPoint)
            .where(GapsSitingPoint.preset == preset)
            .order_by(GapsSitingPoint.area, GapsSitingPoint.position)
        )
    ).all()
    by_area: dict[int, list[dict[str, object]]] = defaultdict(list)
    for point in points:
        by_area[point.area].append(
            {
                "latitude": point.latitude,
                "longitude": point.longitude,
                "node_count": point.node_count,
                "node_ids": [format_node_id(num) for num in point.node_nums],
                "names": list(point.names),
            }
        )
    return summary | {
        "areas": [
            {
                "area": area.area,
                "point_count": area.point_count,
                "node_count": area.node_count,
                "node_ids": [format_node_id(num) for num in area.node_nums],
                "centroid": [area.centroid_lat, area.centroid_lon],
                "bounds": [area.south, area.west, area.north, area.east],
                "width_km": area.width_km,
                "points": by_area.get(area.area, []),
            }
            for area in areas
        ]
    }


def _candidate(
    row: GapsSitingCandidate, long_name: str | None, short_name: str | None
) -> dict[str, object]:
    """One candidate in the shape `Candidate.as_dict` gives."""
    sentence = candidate_sentence(
        Candidate(
            kind=row.kind,
            cluster=row.area,
            latitude=row.latitude,
            longitude=row.longitude,
            screen_score=row.screen_score,
            newly_usable=row.newly_usable,
            reason=row.reason,
        )
    )
    return {
        "kind": row.kind,
        "area": row.area,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "elevation_m": row.elevation_m,
        "prominence_m": row.prominence_m,
        "node_id": None if row.node_num is None else format_node_id(row.node_num),
        "display_name": (
            None if row.node_num is None else display_name(row.node_num, long_name, short_name)
        ),
        "method": row.method,
        "state": row.state,
        "screen_score": row.screen_score,
        "screen_unknown": row.screen_unknown,
        "newly_usable": row.newly_usable,
        "newly_usable_nodes": [format_node_id(num) for num in row.newly_usable_nodes],
        "already_usable": row.already_usable,
        "baseline_unknown": row.baseline_unknown,
        "run_stamp": row.run_stamp,
        "reason": row.reason,
        "sentence": sentence,
    }


async def read_candidates(
    session: AsyncSession,
    preset: str,
    area: int | None,
    limit: int,
    after: int | None = None,
) -> tuple[int, list[dict[str, object]], int | None]:
    """Return how many candidates match, one page of them best first, and where the next starts.

    `after` is the position of the last candidate of the page before,
    and the third value is the `after` of the next page, or None.
    """
    where = [GapsSitingCandidate.preset == preset]
    if area is not None:
        where.append(GapsSitingCandidate.area == area)
    matched = (
        await session.scalar(select(func.count()).select_from(GapsSitingCandidate).where(*where))
        or 0
    )
    paged = [*where, GapsSitingCandidate.position > after] if after is not None else where
    rows = list(
        (
            await session.execute(
                select(GapsSitingCandidate, Node.long_name, Node.short_name)
                .outerjoin(Node, Node.node_num == GapsSitingCandidate.node_num)
                .where(*paged)
                .order_by(GapsSitingCandidate.position)
                .limit(limit + 1)
            )
        ).all()
    )
    following = rows[limit - 1][0].position if len(rows) > limit else None
    return matched, [_candidate(*row) for row in rows[:limit]], following


async def run_stamp(session: AsyncSession, preset: str) -> str | None:
    """Return when one preset's assessment was made, for a page cursor."""
    found = await session.scalar(
        select(GapsRun.generated_at).where(
            GapsRun.preset == preset,
            GapsRun.scope == GAPS_SCOPE_ASSESSMENT,
            GapsRun.asked_hours == ASSESSMENT_HOURS,
        )
    )
    return None if found is None else found.isoformat()


async def siting_stamp(session: AsyncSession, preset: str) -> str | None:
    """Return when one preset's siting answer was made, for a page cursor."""
    found = await session.scalar(select(GapsSiting.generated_at).where(GapsSiting.preset == preset))
    return None if found is None else found.isoformat()
