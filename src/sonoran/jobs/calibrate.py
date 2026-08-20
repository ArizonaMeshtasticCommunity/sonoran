"""The calibration job.

The job asks the mesh how far the prediction is out, node by node, and
writes one correction for each.

It reads `neighbor_metrics`: a node reporting the neighbours it hears
itself, with an SNR. That is a real radio link between two real nodes.
`AGENTS.md` 9.5 is explicit that this is the source to use for the
signal of a link, and that a gateway observation is usually not one.

For each node that published a neighbour list, the job sets up the
engine once at that node and asks it about every candidate around it.
Setting the engine up is the slow part, so doing it once for each
listener and not once for each link is what makes this finish.

Two kinds of measurement come out of that:

- A neighbour the node reported. The residual is the SNR it reported
  against what the model said it would get.
- A candidate the model says it should have heard and the list does not
  name. That link is below the sensitivity of the preset, and by how
  much is unknown. It is a censored measurement, and leaving it out
  would flatter every node. See `sonoran/coverage/calibrate.py`.
"""

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings, get_settings
from sonoran.coverage import store
from sonoran.coverage.calibrate import (
    Calibration,
    LinkObservation,
    fit_offsets,
    residual_summary,
)
from sonoran.coverage.engine import EngineError, SplatInstance, SplatModule
from sonoran.coverage.params import EngineParams, erp_watts
from sonoran.db.models import NeighborMetrics, Node
from sonoran.db.session import make_engine, make_session_factory
from sonoran.jobs.coverage import ensure_terrain, read_page, tiles_around
from sonoran.logging import get_logger
from sonoran.positions import is_usable
from sonoran.radio.overrides import Overrides, load_overrides
from sonoran.radio.presets import ModemPreset, noise_floor_dbm, preset_for_channel
from sonoran.radio.resolve import RadioProfile, resolve_profile

logger = get_logger(__name__)

# How far apart two nodes may be and still count as a candidate link, in
# kilometres.
#
# Past this the model says nothing useful about a link that was never
# reported, because a hundred other things could explain the silence.
CANDIDATE_RANGE_KM = 40.0

# The most censored candidates to take for one listener.
#
# A listener in a crowded town has hundreds of nodes around it, and its
# silence about the far ones says less than its silence about the near
# ones. The nearest are kept.
MAX_CANDIDATES = 40


@dataclass(frozen=True)
class Peer:
    """One node the calibration may reason about."""

    node_id: str
    node_num: int
    latitude: float
    longitude: float
    profile: RadioProfile
    preset: ModemPreset


def _distance_km(first: Peer, second: Peer) -> float:
    """Return the distance between two nodes, in kilometres."""
    mean_lat = math.radians((first.latitude + second.latitude) / 2.0)
    north = (second.latitude - first.latitude) * 111.32
    east = (second.longitude - first.longitude) * 111.32 * math.cos(mean_lat)
    return math.hypot(north, east)


async def read_peers(
    session: AsyncSession, settings: Settings, overrides: Overrides
) -> dict[int, Peer]:
    """Return every node the calibration may reason about, by number."""
    since = datetime.now(UTC) - timedelta(hours=settings.coverage_active_hours)
    rows = await session.scalars(
        select(Node).where(Node.last_heard.is_not(None), Node.last_heard >= since)
    )
    peers: dict[int, Peer] = {}
    for node in rows.all():
        preset = preset_for_channel(node.last_channel)
        if preset is None or not is_usable(node.last_lat, node.last_lon):
            continue
        latitude, longitude = node.last_lat, node.last_lon
        if latitude is None or longitude is None:
            continue
        identifier = f"!{node.node_num:08x}"
        peers[node.node_num] = Peer(
            node_id=identifier,
            node_num=node.node_num,
            latitude=latitude,
            longitude=longitude,
            profile=resolve_profile(identifier, node.hw_model, overrides),
            preset=preset,
        )
    return peers


async def read_reports(session: AsyncSession, settings: Settings) -> dict[int, dict[int, float]]:
    """Return the best SNR each node reported for each neighbour.

    A node reports the same neighbour many times. The best reading is
    taken, because a poor one may be a collision rather than a path.
    """
    since = datetime.now(UTC) - timedelta(hours=settings.calibration_window_hours)
    rows = await session.scalars(
        select(NeighborMetrics).where(
            NeighborMetrics.time >= since, NeighborMetrics.snr.is_not(None)
        )
    )
    reports: dict[int, dict[int, float]] = {}
    for row in rows.all():
        if row.snr is None:
            continue
        heard = reports.setdefault(row.node_num, {})
        best = heard.get(row.neighbor_node_num)
        if best is None or row.snr > best:
            heard[row.neighbor_node_num] = float(row.snr)
    return reports


def _params(settings: Settings, listener: Peer) -> EngineParams:
    """Return the engine values for a run centred on a listener."""
    profile = listener.profile
    return EngineParams(
        latitude=listener.latitude,
        longitude=listener.longitude,
        tx_height_m=profile.antenna_height_m,
        rx_height_m=settings.coverage_rx_height_m,
        erp_watts=erp_watts(profile.tx_power_dbm, profile.antenna_gain_dbi, profile.cable_loss_db),
        radius_m=CANDIDATE_RANGE_KM * 1000.0,
    )


def build_observations(
    settings: Settings,
    peers: dict[int, Peer],
    reports: dict[int, dict[int, float]],
) -> list[LinkObservation]:
    """Return every measurement the mesh offers, reported and silent.

    Terrain is read page by page from the disk cache. Holding the whole
    region would cost more than a hundred megabytes in a process that
    also runs the engine. See `docs/COVERAGE.md` 9.2.
    """
    observations: list[LinkObservation] = []

    with SplatModule().instance() as instance:
        _fill(settings, peers, reports, instance, observations)
    return observations


def _fill(
    settings: Settings,
    peers: dict[int, Peer],
    reports: dict[int, dict[int, float]],
    instance: SplatInstance,
    observations: list[LinkObservation],
) -> None:
    """Add every measurement one engine instance can make.

    One instance serves every listener. An instance owns a linear
    memory that grows to the largest run it has made, so making a new
    one for each listener would grow a new heap each time. See
    `AGENTS.md` 9.16.4.
    """
    for listener_num, heard in sorted(reports.items()):
        listener = peers.get(listener_num)
        if listener is None:
            continue

        # Everything on the same preset and close enough that silence
        # about it means something.
        candidates = [
            peer
            for peer in peers.values()
            if peer.node_num != listener_num
            and peer.preset.key == listener.preset.key
            and _distance_km(listener, peer) <= CANDIDATE_RANGE_KM
        ]
        candidates.sort(key=lambda peer: _distance_km(listener, peer))
        reported = {num for num in heard if num in peers}
        silent = [peer for peer in candidates if peer.node_num not in reported][:MAX_CANDIDATES]
        wanted = [peer for peer in candidates if peer.node_num in reported] + silent
        if not wanted:
            continue

        floor = noise_floor_dbm(listener.preset)
        threshold = listener.preset.sensitivity_dbm
        # The power the run was set up with, so a path loss can be
        # recovered from the field the engine reports.
        listener_eirp = listener.profile.effective_eirp_dbm

        try:
            with instance.run(_params(settings, listener)) as run:
                for index, ref in enumerate(run.pages()):
                    page = read_page(settings, ref.tile_name)
                    if page is not None:
                        run.load_page(index, page)

                for peer in wanted:
                    try:
                        link = run.point_to_point(
                            peer.latitude, peer.longitude, peer.profile.antenna_height_m
                        )
                    except EngineError:
                        continue
                    if link.itm_errno > 0:
                        # The model complained about this path. Its
                        # answer is not evidence about a node.
                        continue

                    # The loss does not care which end transmits, so the
                    # run centred on the listener gives the loss of the
                    # link the other way round as well.
                    loss_db = listener_eirp - link.dbm
                    predicted = peer.profile.effective_eirp_dbm - loss_db

                    if peer.node_num in reported:
                        measured = floor + heard[peer.node_num]
                        observations.append(
                            LinkObservation(
                                transmitter=peer.node_id,
                                receiver=listener.node_id,
                                residual_db=measured - predicted,
                            )
                        )
                    elif predicted > threshold:
                        # The model said this would be heard and the
                        # list does not name it, so the truth is at or
                        # below the limit.
                        observations.append(
                            LinkObservation(
                                transmitter=peer.node_id,
                                receiver=listener.node_id,
                                residual_db=threshold - predicted,
                                censored=True,
                            )
                        )
        except EngineError as error:
            logger.warning("the engine refused a run at %s: %s", listener.node_id, error)


async def run_once(session: AsyncSession, settings: Settings) -> Calibration | None:
    """Fit the calibration and write it. Return None with no evidence."""
    overrides = load_overrides(settings.radio_overrides_path)
    peers = await read_peers(session, settings, overrides)
    reports = await read_reports(session, settings)
    if not reports:
        logger.info("no neighbour reports in the window, so no calibration")
        return None

    wanted: set[str] = set()
    for num in reports:
        peer = peers.get(num)
        if peer is not None:
            wanted.update(_tiles_for(peer))
    held = await ensure_terrain(settings, sorted(wanted))
    logger.info("%s of %s terrain tiles are held", len(held), len(wanted))

    observations = await asyncio.to_thread(build_observations, settings, peers, reports)
    summary = residual_summary(observations)
    logger.info(
        "calibration read %s links, %s of them silent, model out by %.1f dB",
        int(summary["count"]),
        int(summary["censored"]),
        summary["mean_db"],
    )
    if not observations:
        return None

    calibration = fit_offsets(observations)
    store.write_calibration(settings, calibration, summary)
    return calibration


def _tiles_for(peer: Peer) -> set[str]:
    """Return the terrain tiles one listener needs."""
    from sonoran.coverage.sites import Site

    stand_in = Site(
        node_id=peer.node_id,
        node_num=peer.node_num,
        display_name=peer.node_id,
        latitude=peer.latitude,
        longitude=peer.longitude,
        profile=peer.profile,
        preset=peer.preset,
        clutter_height_m=0.0,
    )
    return tiles_around(stand_in, CANDIDATE_RANGE_KM)


async def main() -> None:
    """Make one calibration run."""
    settings = get_settings()
    if not settings.calibration_enabled:
        logger.info("the calibration job is turned off")
        return
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await run_once(session, settings)
    finally:
        await engine.dispose()


def observation_count(observations: Sequence[LinkObservation]) -> int:
    """Return how many measurements a fit had. Used by the tests."""
    return len(observations)
