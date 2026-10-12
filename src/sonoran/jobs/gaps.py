"""The coverage gaps job.

It measures which nodes the mesh is not carrying well and writes one
file for each modem preset. It predicts nothing and it runs no engine:
every signal is a SQL aggregate over packets the database already holds.

**One assessment for each preset, always.** A node on Long fast cannot
hear a node on Medium fast, so a merged answer would invite a reader to
fix a gap between two radios that have no way to reach each other. A
node active on two presets gets two independent assessments and appears
twice. See `AGENTS.md` 9.7.

## Why this is its own task and not part of the coverage cycle

`jobs/scheduler.py::service` runs tasks with `asyncio.gather`, so tasks
run beside each other on their own clocks, and only calibration and
coverage share one clock in `_coverage_cycle`. A task that uses the
SPLAT engine must join that cycle rather than stand beside it, or it is
free to run during a coverage build and take the box's last core.

This job uses no engine. It is SQL and a few thousand dictionary
operations, it finishes in well under a second on the development
database, and it wants to run every 30 minutes rather than every 6
hours. So it is its own `Task`, which is what the design specifies for
phase 1. The engine work of phase 3 is the part that must join
`_coverage_cycle`.

## The leaderboard windows (#294)

The run also writes the leaderboard counts for the Statistics windows
the assessment does not hold: 24 h and 30 d by default. That is two
aggregate reads and one traceroute read (#293) for each preset and
window that is due, and a 30 d read is due once in six hours. See
`sonoran/gaps/boards.py` and `docs/GAPS.md` 6.1 and 6.2.
"""

import asyncio
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api import traces
from sonoran.api.names import display_name, format_node_id
from sonoran.config import Settings, get_settings
from sonoran.coverage import store as coverage_store
from sonoran.db.models import Node
from sonoran.db.session import make_engine, make_session_factory
from sonoran.gaps import boards, signals, store
from sonoran.gaps.signals import BAD, OK, UNKNOWN
from sonoran.logging import configure_logging, get_logger
from sonoran.radio.presets import ModemPreset, preset_for_channel
from sonoran.roles import SITE_SET_INFRASTRUCTURE, role_name

logger = get_logger(__name__)


def read_coverage(settings: Settings, preset: ModemPreset) -> signals.CoverageLevels:
    """Return the published run's level at each node, for one preset.

    The site set is **always** the infrastructure one. That is the
    narrow answer, and it is the only map that describes coverage a
    fixed node holds open. The wider map predicts from client nodes,
    which are mostly houses that move. See `AGENTS.md` 9.26 and 9.27.

    `is_diagnostic` is read from the manifest's top level, which is the
    infrastructure map's own flag, never from `site_sets`.
    """
    manifest = coverage_store.read_manifest(settings)
    document = coverage_store.read_node_levels(settings)
    if manifest is None or document is None:
        return signals.CoverageLevels()

    presets = document.get("presets")
    for_preset = presets.get(preset.name) if isinstance(presets, dict) else None
    if not isinstance(for_preset, dict):
        # The run published no map for this preset. Unknown, not clear.
        return signals.CoverageLevels(
            stamp=_as_str(document.get("stamp")),
            is_diagnostic=bool(manifest.get("is_diagnostic")),
        )

    site_sets = for_preset.get("site_sets")
    holder = site_sets.get(SITE_SET_INFRASTRUCTURE) if isinstance(site_sets, dict) else None
    threshold = for_preset.get("threshold_level")
    levels: dict[str, dict[str, int]] = {}
    if isinstance(holder, dict):
        for key, value in holder.items():
            if isinstance(value, dict):
                levels[str(key)] = {
                    str(layer): int(level)
                    for layer, level in value.items()
                    if isinstance(level, int)
                }
    return signals.CoverageLevels(
        stamp=_as_str(document.get("stamp")),
        site_set=SITE_SET_INFRASTRUCTURE,
        is_diagnostic=bool(manifest.get("is_diagnostic")),
        available=True,
        threshold_level=int(threshold) if isinstance(threshold, int) else 0,
        levels=levels,
    )


def _as_str(value: object) -> str | None:
    """Return a string, or None."""
    return value if isinstance(value, str) else None


async def _read_nodes(session: AsyncSession, wanted: set[int]) -> dict[int, Node]:
    """Return the stored record of each node we have evidence for."""
    if not wanted:
        return {}
    rows = await session.scalars(select(Node).where(Node.node_num.in_(wanted)))
    return {node.node_num: node for node in rows.all()}


async def assess_preset(
    session: AsyncSession,
    settings: Settings,
    preset: ModemPreset,
    channels: Sequence[str],
    hours: int | None = None,
) -> dict[str, object]:
    """Return the whole assessment of one preset, ready to be written."""
    since, until = signals.window_bounds(settings, hours)
    window_hours = round((until - since).total_seconds() / 3600)

    evidence = await signals.read_evidence(session, settings, channels, since, until)
    gateways = await signals.read_gateways(session, channels, since, until)
    answers = await signals.read_trace_answers(session, channels, since, until)
    nodes = await _read_nodes(session, set(evidence) | set(answers))
    coverage = read_coverage(settings, preset)
    gateways_active = len(gateways)

    rows: list[dict[str, object]] = []
    counts: dict[str, dict[str, int]] = {
        name: {BAD: 0, OK: 0, UNKNOWN: 0} for name in signals.SIGNAL_ORDER
    }
    needs_help = 0
    not_enough_evidence = 0
    unpredicted = 0

    for node_num, found in evidence.items():
        node = nodes.get(node_num)
        latitude = node.last_lat if node else None
        longitude = node.last_lon if node else None
        bits = node.last_position_precision_bits if node else None
        confidence, deviation = signals.position_confidence(
            latitude, longitude, bits, settings.coverage_min_precision_bits
        )

        assessed = signals.assess(
            found, settings, preset, gateways_active, coverage, confidence, deviation
        )
        for name, signal in assessed.items():
            counts[name][signal.state] += 1

        bad_count = sum(1 for signal in assessed.values() if signal.state == BAD)
        unknown_count = sum(1 for signal in assessed.values() if signal.state == UNKNOWN)
        if bad_count:
            needs_help += 1
        elif unknown_count:
            # Not healthy. Unmeasured, which is a different answer and
            # gets its own section on the page.
            not_enough_evidence += 1
        if signals.reached_but_unpredicted(assessed, found):
            unpredicted += 1

        rows.append(
            {
                "node_id": format_node_id(node_num),
                "display_name": display_name(
                    node_num,
                    node.long_name if node else None,
                    node.short_name if node else None,
                ),
                "role": role_name(node.role if node else None),
                "preset": preset.name,
                # The position is reported as it is stored. Nothing here
                # invents one, and a node with none gets nulls.
                "latitude": latitude if confidence != "none" else None,
                "longitude": longitude if confidence != "none" else None,
                "position_confidence": confidence,
                "position_deviation_m": deviation,
                "is_mqtt_gateway": found.is_mqtt_gateway,
                "mobile": signals.is_mobile(found, settings),
                "position_spread_km": (
                    None if found.position_spread_km is None else round(found.position_spread_km, 2)
                ),
                "packets": found.packets,
                "rf_packets": found.rf_packets,
                "ambiguous_packets": found.ambiguous_packets,
                "active_hours": found.active_hours,
                "rf_hours": found.rf_hours,
                "direct_gateways": found.direct_gateways,
                "worst_state": signals.worst_state(assessed),
                "bad_count": bad_count,
                "unknown_count": unknown_count,
                "signals": {name: signal.as_dict() for name, signal in assessed.items()},
            }
        )

    # Sorted here, once, so that every reader gets the same order and no
    # page has to hold a copy of the rule. Worst first.
    rows.sort(key=signals.rank_key)

    return {
        "available": True,
        "preset": preset.name,
        "label": preset.label,
        "channels": sorted(channels),
        "window_hours": window_hours,
        "generated_at": datetime.now(UTC).isoformat(),
        "gateways_active": gateways_active,
        "node_count": len(set(nodes) & set(evidence)),
        "assessed_count": len(rows),
        "coverage": {
            "stamp": coverage.stamp,
            "site_set": coverage.site_set,
            "is_diagnostic": coverage.is_diagnostic,
            "available": coverage.available,
            "threshold_level": coverage.threshold_level,
        },
        "signals": counts,
        "signal_labels": dict(signals.SIGNAL_LABELS),
        "signal_order": list(signals.SIGNAL_ORDER),
        "needs_help_count": needs_help,
        "not_enough_evidence_count": not_enough_evidence,
        "reached_but_unpredicted_count": unpredicted,
        "caveats": [{"key": key, "text": text} for key, text in signals.CAVEATS],
        # The reachable leaderboard's counts (#293). Not node rows: a node
        # can be traced on this preset and send nothing else on it.
        boards.TRACE_ANSWERS: answer_rows(answers, nodes),
        "thresholds": {
            "min_packets": settings.gaps_min_packets,
            "min_active_hours": settings.gaps_min_active_hours,
            "rf_ratio_bad": settings.gaps_rf_ratio_bad,
            "margin_bad_db": settings.gaps_margin_bad_db,
            "min_neighbour_reports": settings.gaps_min_neighbour_reports,
            "mobile_spread_km": settings.gaps_mobile_spread_km,
        },
        "nodes": rows,
    }


async def run_once(session: AsyncSession, settings: Settings) -> list[str]:
    """Make one assessment of every preset and write it. Return the names.

    An empty list is a working state, not a fault. A new deployment has
    no traffic yet, and a deployment whose channels name no preset has
    nothing this job can honestly say.
    """
    since, until = signals.window_bounds(settings)
    channels = await signals.read_preset_channels(session, since, until)
    if not channels:
        logger.info("no channel named a modem preset, so there is no gap assessment to make")
        store.write_index(
            settings,
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "window_hours": settings.gaps_window_hours,
                "presets": [],
            },
        )
        return []

    written: list[str] = []
    index: list[dict[str, object]] = []
    for name, names in sorted(channels.items()):
        preset = preset_for_channel(name)
        if preset is None:
            continue
        document = await assess_preset(session, settings, preset, names)
        if store.write_preset(settings, preset.name, document) is None:
            continue
        written.append(preset.name)
        index.append(
            {
                "preset": preset.name,
                "label": preset.label,
                "node_count": document["assessed_count"],
                "needs_help_count": document["needs_help_count"],
                "not_enough_evidence_count": document["not_enough_evidence_count"],
            }
        )
        logger.info(
            "gaps, preset %s: %s nodes assessed, %s need help, %s not enough evidence",
            preset.name,
            document["assessed_count"],
            document["needs_help_count"],
            document["not_enough_evidence_count"],
        )

    # The index is written last, so a reader that follows it never finds
    # a preset name with no file behind it.
    store.write_index(
        settings,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "window_hours": settings.gaps_window_hours,
            "presets": index,
        },
    )

    # After the index, so a slow or failed board read never holds back the
    # assessment the gaps page and the node page read. A board without its
    # file serves the assessment and says so.
    await write_board_windows(
        session, settings, {name: names for name, names in channels.items() if name in written}
    )
    return written


def board_rows(
    evidence: dict[int, signals.NodeEvidence], nodes: dict[int, Node]
) -> list[dict[str, object]]:
    """Return one leaderboard row for each node: its name and its counts.

    The keys are the ones the assessment rows use, so the leaderboard
    ranks either with the same function.
    """
    rows: list[dict[str, object]] = []
    for node_num, found in sorted(evidence.items()):
        node = nodes.get(node_num)
        row: dict[str, object] = {
            "node_id": format_node_id(node_num),
            "display_name": display_name(
                node_num, node.long_name if node else None, node.short_name if node else None
            ),
        }
        rows.append(row | {key: getattr(found, key) for key in boards.EVIDENCE_KEYS})
    return rows


def answer_rows(
    answers: dict[int, traces.Answers], nodes: dict[int, Node]
) -> list[dict[str, object]]:
    """Return one row for each node traced: its name, traceroutes and answers.

    Every node traced is written, under the floor or not. The floor is
    the leaderboard's to apply, so it can say how many it left out.
    """
    rows: list[dict[str, object]] = []
    for node_num, found in sorted(answers.items()):
        node = nodes.get(node_num)
        rows.append(
            {
                "node_id": format_node_id(node_num),
                "display_name": display_name(
                    node_num, node.long_name if node else None, node.short_name if node else None
                ),
                "requests": found.requests,
                "answered": found.answered,
                "senders": found.senders,
            }
        )
    return rows


async def write_board_windows(
    session: AsyncSession, settings: Settings, channels: dict[str, list[str]]
) -> list[tuple[str, int]]:
    """Write the leaderboard counts for each Statistics window that is due.

    `channels` maps each preset this run assessed to its channel names.
    Only those presets get a board file: a board borrows the assessment's
    list of presets and never adds one.

    A window longer than the assessment's reads its own channel names,
    because a spelling used three weeks ago belongs in a 30 day count.
    Return the (preset, window) pairs written.
    """
    now = datetime.now(UTC)
    written: list[tuple[str, int]] = []
    for asked in boards.extra_windows(settings):
        hours = boards.window_hours(settings, asked)
        due = [
            preset
            for preset in sorted(channels)
            if boards.is_due(store.read_boards(settings, preset, asked), hours, now)
        ]
        if not due:
            continue
        since, until = signals.window_bounds(settings, hours)
        wider = (
            await signals.read_preset_channels(session, since, until)
            if hours > settings.gaps_window_hours
            else {}
        )
        for preset in due:
            started = time.monotonic()
            names = sorted(set(channels[preset]) | set(wider.get(preset, [])))
            evidence = await signals.read_reach_evidence(session, names, since, until)
            answers = await signals.read_trace_answers(session, names, since, until)
            nodes = await _read_nodes(session, set(evidence) | set(answers))
            document: dict[str, object] = {
                "preset": preset,
                "channels": names,
                "window_hours": hours,
                "generated_at": datetime.now(UTC).isoformat(),
                "nodes": board_rows(evidence, nodes),
                boards.TRACE_ANSWERS: answer_rows(answers, nodes),
            }
            if store.write_boards(settings, preset, asked, document) is not None:
                written.append((preset, asked))
                # The time is logged because it is the cost #294 added to
                # this job, and it can only be measured on live data.
                logger.info(
                    "gaps boards, preset %s: %s nodes over %s hours in %.2f s",
                    preset,
                    len(evidence),
                    hours,
                    time.monotonic() - started,
                )
    return written


async def main() -> None:
    """Make one gap assessment."""
    settings = get_settings()
    if not settings.gaps_enabled:
        logger.info("the coverage gaps job is turned off")
        return
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            written = await run_once(session, settings)
            logger.info("wrote a gap assessment for %s presets", len(written))
    finally:
        await engine.dispose()


def run() -> None:
    """Make one gap assessment and stop. The console entry point.

    The scheduler makes one every `GAPS_INTERVAL_MINUTES`. This is the
    other half of that, matching `sonoran-coverage-once`: one run, now,
    so an operator bringing a box up does not have to wait for the timer.

        sonoran-gaps-once

    The logging is set up here because nothing else in the process does
    it. Without it the command runs and prints not one line.
    """
    configure_logging(get_settings().log_level)
    asyncio.run(main())
