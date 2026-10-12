"""Where a gap assessment is kept: in the database (#351).

The gaps job used to write one JSON file per preset beside the coverage
runs, and the API read the files. It now writes these tables:

- `gaps_index`: when the job last ran, and over what window.
- `gaps_run`: one assessment of a preset (`scope` `assessment`), or the
  leaderboard counts of one more Statistics window (`scope` `board`,
  `asked_hours` 24 or 720, see `sonoran/gaps/boards.py`). `summary`
  holds every top-level field the old file held except the rows.
- `gaps_node`: the rows, one per node, in the order the job ranked them.
- `gaps_trace_answer`: the traceroute counts of the reachable board.
- `gaps_siting` and `gaps_siting_candidate`: the siting answer.

**Nothing is computed per request.** The job writes the rows and the
API selects and filters them. `docs/ISSUES.md` 2.9 still holds: a gap
signal is never worked out while a page waits.

**A run is replaced, never edited.** Each write deletes the run's rows
and inserts the new ones, and commits once, so a reader sees the old run
or the new one and never half of each. The jobs role has SELECT, INSERT
and DELETE on these tables and no UPDATE.

**Names are read live.** A row does not store the node's name, short
name or role. A reader joins `node`, so a node renamed after the run
reads with its new name. The position stays as the job assessed it,
because the findings belong to that position.

The documents these functions return have the shape the JSON files had,
so a reader written for the files reads them unchanged.
"""

import re
from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, exists, func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.names import display_name, format_node_id
from sonoran.config import Settings
from sonoran.db.models import (
    GAPS_SCOPE_ASSESSMENT,
    GAPS_SCOPE_BOARD,
    GapsIndex,
    GapsNode,
    GapsRun,
    GapsSiting,
    GapsSitingCandidate,
    GapsTraceAnswer,
    Node,
)
from sonoran.gaps.boards import BOARD_WINDOW_HOURS, EVIDENCE_KEYS, TRACE_ANSWERS
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
# after `node_id`, `display_name`, `role` and `preset`.
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
    "signals",
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


# --- writing ------------------------------------------------------------


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

    node_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(rows):
        node_num = node_num_of(row.get("node_id"))
        if node_num is None:
            continue
        values: dict[str, Any] = {**key, "node_num": node_num, "rank": rank}
        for column in ROW_COLUMNS:
            if column in row:
                values[column] = row[column]
        node_rows.append(values)
    if node_rows:
        # One INSERT per distinct set of columns: an assessment row fills
        # every column and a board row only its counts.
        for columns in {tuple(sorted(values)) for values in node_rows}:
            same = [values for values in node_rows if tuple(sorted(values)) == columns]
            await session.execute(insert(GapsNode), same)

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
    for table in (GapsTraceAnswer, GapsNode, GapsRun):
        await session.execute(
            delete(table).where(
                table.preset == preset, table.scope == scope, table.asked_hours == asked
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
    for table in (GapsTraceAnswer, GapsNode, GapsRun):
        await session.execute(delete(table).where(table.preset.not_in(kept)))
    for siting_table in (GapsSitingCandidate, GapsSiting):
        await session.execute(delete(siting_table).where(siting_table.preset.not_in(kept)))
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
    listed = document.get("candidates")
    candidates = (
        [row for row in listed if isinstance(row, dict)] if isinstance(listed, list) else []
    )
    summary = {key: value for key, value in document.items() if key != "candidates"}
    await session.execute(delete(GapsSitingCandidate).where(GapsSitingCandidate.preset == preset))
    await session.execute(delete(GapsSiting).where(GapsSiting.preset == preset))
    await session.execute(
        insert(GapsSiting).values(
            preset=preset, generated_at=_when(document.get("generated_at")), summary=summary
        )
    )
    if candidates:
        await session.execute(
            insert(GapsSitingCandidate),
            [
                {
                    "preset": preset,
                    "position": position,
                    "area": _int(row.get("area")),
                    "candidate": row,
                }
                for position, row in enumerate(candidates)
            ],
        )
    await session.commit()
    return True


async def clear(session: AsyncSession) -> None:
    """Delete every assessment and siting answer. For a test, and a reset."""
    for table in (
        GapsTraceAnswer,
        GapsNode,
        GapsRun,
        GapsSitingCandidate,
        GapsSiting,
        GapsIndex,
    ):
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


def _assessment_row(
    preset: str, row: GapsNode, long_name: str | None, short_name: str | None, role: Any
) -> dict[str, object]:
    found: dict[str, object] = {
        "node_id": format_node_id(row.node_num),
        "display_name": display_name(row.node_num, long_name, short_name),
        "role": role_name(role),
        "preset": preset,
    }
    for column in ROW_COLUMNS:
        found[column] = getattr(row, column)
    return found


def _board_row(row: GapsNode, long_name: str | None, short_name: str | None) -> dict[str, object]:
    found: dict[str, object] = {
        "node_id": format_node_id(row.node_num),
        "display_name": display_name(row.node_num, long_name, short_name),
    }
    for column in EVIDENCE_KEYS:
        found[column] = getattr(row, column)
    return found


def _run_rows(preset: str, scope: str, asked: int) -> Select[Any]:
    return _named(
        select(GapsNode).where(
            GapsNode.preset == preset, GapsNode.scope == scope, GapsNode.asked_hours == asked
        )
    )


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
            _run_rows(preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS).order_by(GapsNode.rank)
        )
    ).all()
    document = _served(summary)
    if not summary.get(NO_TRACE_ANSWERS):
        document[TRACE_ANSWERS] = await _answers(
            session, preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS
        )
    document["nodes"] = [_assessment_row(preset, *row) for row in rows]
    return document


async def read_boards(session: AsyncSession, preset: str, hours: int) -> dict[str, object] | None:
    """Return one preset's whole leaderboard window, rows included, or None."""
    if hours not in BOARD_WINDOW_HOURS:
        return None
    summary = await _summary(session, preset, GAPS_SCOPE_BOARD, hours)
    if summary is None:
        return None
    rows = (
        await session.execute(_run_rows(preset, GAPS_SCOPE_BOARD, hours).order_by(GapsNode.rank))
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
    if signal is not None and state is not None:
        return GapsNode.signals[signal]["state"].astext == state
    if signal is not None:
        return GapsNode.signals.has_key(signal)
    each = func.jsonb_each(GapsNode.signals).table_valued("key", "value").alias("each")
    return exists(select(literal(1)).select_from(each).where(each.c.value["state"].astext == state))


async def node_rows(
    session: AsyncSession,
    preset: str,
    signal: str | None,
    state: str | None,
    limit: int,
) -> tuple[int, list[dict[str, object]]]:
    """Return how many rows match, and the first `limit` of them, worst first.

    The order is the job's `rank`. The filters select; they never
    recompute a signal.
    """
    where = [
        GapsNode.preset == preset,
        GapsNode.scope == GAPS_SCOPE_ASSESSMENT,
        GapsNode.asked_hours == ASSESSMENT_HOURS,
    ]
    if signal is not None or state is not None:
        where.append(_signal_filter(signal, state))
    matched = await session.scalar(select(func.count()).select_from(GapsNode).where(*where)) or 0
    rows = (
        await session.execute(
            _named(select(GapsNode).where(*where)).order_by(GapsNode.rank).limit(limit)
        )
    ).all()
    return matched, [_assessment_row(preset, *row) for row in rows]


async def node_row(session: AsyncSession, preset: str, node_num: int) -> dict[str, object] | None:
    """Return one node's assessment row on one preset, or None."""
    found = (
        await session.execute(
            _run_rows(preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS).where(
                GapsNode.node_num == node_num
            )
        )
    ).first()
    return None if found is None else _assessment_row(preset, *found)


async def node_nums(session: AsyncSession, preset: str, state: str) -> set[int] | None:
    """Return the nodes whose worst state is `state` on one preset.

    None means no assessment has been written for that preset, which is
    a different answer from an empty set.
    """
    if await _summary(session, preset, GAPS_SCOPE_ASSESSMENT, ASSESSMENT_HOURS) is None:
        return None
    rows = await session.scalars(
        select(GapsNode.node_num).where(
            GapsNode.preset == preset,
            GapsNode.scope == GAPS_SCOPE_ASSESSMENT,
            GapsNode.asked_hours == ASSESSMENT_HOURS,
            GapsNode.worst_state == state,
        )
    )
    return set(rows.all())


async def assessed_nodes(session: AsyncSession, node_num: int) -> dict[str, dict[str, object]]:
    """Return one node's assessment row on every preset that assessed it, by preset."""
    rows = (
        await session.execute(
            _named(
                select(GapsNode).where(
                    GapsNode.scope == GAPS_SCOPE_ASSESSMENT,
                    GapsNode.asked_hours == ASSESSMENT_HOURS,
                    GapsNode.node_num == node_num,
                )
            )
        )
    ).all()
    return {row[0].preset: _assessment_row(row[0].preset, *row) for row in rows}


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
            _run_rows(preset, scope, asked)
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
    """Return one preset's siting answer without its candidates, or None.

    None is a working state. The siting half runs inside the coverage
    cycle, so a box that has never finished a coverage run has no answer
    yet and the page says so.
    """
    if not _valid(preset):
        return None
    summary = await session.scalar(select(GapsSiting.summary).where(GapsSiting.preset == preset))
    return summary if isinstance(summary, dict) else None


async def read_candidates(
    session: AsyncSession, preset: str, area: int | None, limit: int
) -> tuple[int, list[dict[str, object]]]:
    """Return how many candidates match, and the first `limit` of them, best first."""
    where = [GapsSitingCandidate.preset == preset]
    if area is not None:
        where.append(GapsSitingCandidate.area == area)
    matched = (
        await session.scalar(select(func.count()).select_from(GapsSitingCandidate).where(*where))
        or 0
    )
    rows = await session.scalars(
        select(GapsSitingCandidate.candidate)
        .where(*where)
        .order_by(GapsSitingCandidate.position)
        .limit(limit)
    )
    return matched, [row for row in rows.all() if isinstance(row, dict)]


async def is_empty(session: AsyncSession) -> bool:
    """Return true when no gaps run and no siting answer is held."""
    held = await session.scalar(
        select(exists(select(GapsRun.preset)) | exists(select(GapsSiting.preset)))
    )
    return not held
