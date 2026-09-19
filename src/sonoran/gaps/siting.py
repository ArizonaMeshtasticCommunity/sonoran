"""Where one new node would help the most struggling nodes.

`signals.py` answers "which nodes are struggling". This module answers
the other half of the owner's question: **where would a 1 W node do the
most good**. The whole design is `docs/design/coverage-gaps.md` section
6; what runs is described in `docs/GAPS.md` 10.

The shape of the answer, and why it is that shape:

1. **Demand.** The nodes with a fault we can measure, deduplicated onto
   a 300 m grid so that five radios in one house do not outvote a ranch
   five miles out.
2. **Clusters.** Single linkage at 8 km. A cluster of one or two is not
   an area; it is a node, and the per node list already holds it.
3. **Candidates.** Two kinds. A node that is already standing there,
   read with the candidate radio instead of its own, and a place on the
   ground taken from terrain local maxima. **Never a blind grid**: a
   5 km grid over Arizona is about 27,000 candidates, which at the
   measured 18.4 core-seconds a site is roughly six core-days.
4. **A terrain screen** that is deliberately optimistic. It may pass a
   candidate the engine then rejects. It may never reject one the
   engine would have liked, because a pre-filter with false negatives
   throws the answer away in silence.
5. **The engine, on the top few only**, sampling each candidate's own
   raster at the demand points. Never a region grid: one is 88 MB and
   the question is a few dozen point lookups.

Three rules this module may never break:

- **No link is inferred from a gateway observation.** Nothing here
  reads an observation at all. The demand set is the per node
  assessment, which already obeys `AGENTS.md` 9.5 and 9.5.1, and every
  number this module adds comes from terrain and from the radio table.
- **One modem preset, always.** A node on Long fast cannot hear a node
  on Medium fast, so a site chosen for one says nothing about the
  other. `AGENTS.md` 9.7.
- **Three states.** A candidate standing on ground we hold no terrain
  for is `unknown`. It is never "no benefit", and its count of nodes
  served is `None` and never zero.

Nothing here touches the database, and nothing here predicts a position
or a measurement that was not reported.
"""

from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from sonoran.config import Settings
from sonoran.coverage.clutter import knife_edge_db, terminal_loss_db
from sonoran.coverage.params import DEFAULT_FREQUENCY_MHZ
from sonoran.coverage.sites import handheld_eirp_dbm
from sonoran.landcover.classes import is_diffracting
from sonoran.landcover.store import class_at, clutter_at
from sonoran.radio.hardware import STOCK_ANTENNA_GAIN_DBI
from sonoran.radio.presets import ModemPreset
from sonoran.radio.resolve import DEFAULT_CABLE_LOSS_DB
from sonoran.terrain.srtm import PAGE_SIZE, page_array, tile_name_of

# The three states, as everywhere else in this feature. There is no
# fourth and there is no score.
BAD = "bad"
OK = "ok"
UNKNOWN = "unknown"

# How a candidate was arrived at. It travels on every row, so that
# nobody can mistake the cheap answer for the expensive one.
METHOD_SCREEN = "terrain_screen"
METHOD_SPLAT = "splat"

# What kind of place a candidate is.
KIND_EXISTING = "existing_node"
KIND_GROUND = "ground"

# Metres in one degree of latitude. The same figure `coverage/grid.py`
# uses, so the two agree about how big a cell is.
METRES_PER_DEGREE = 111_320.0

# The step of the terrain grid, in metres. 1/1200 of a degree.
TERRAIN_STEP_M = METRES_PER_DEGREE / PAGE_SIZE

# The window a local maximum must be the highest cell of, in cells.
#
# Eleven cells is about 1.0 km, which is the figure the design names.
# It must be odd, so that the cell being judged is the middle of it.
MAXIMA_WINDOW_CELLS = 11

# The effective radius of the earth for a radio path, in metres.
#
# The standard 4/3 factor. A radio ray bends towards the ground in the
# lower atmosphere, and the usual way to account for it is to straighten
# the ray and curve the earth less. It is the same assumption the engine
# is given through `atmosphere_bending`.
EFFECTIVE_EARTH_RADIUS_M = 4.0 / 3.0 * 6_371_000.0

# The speed of light, in metres a second. For the Fresnel parameter.
SPEED_OF_LIGHT_M_S = 299_792_458.0

# How far around a demand point's cell to look when sampling a
# candidate's raster.
#
# One cell, which is about 90 m. This is `coverage.SAMPLE_REACH` and it
# is here for the same reason: the engine marks a cell covered when a
# radial passed through it, and the cells at the very start of a sweep
# can be missed. Copying the figure rather than importing it would let
# the two drift, so it is imported where it is used.
SAMPLE_REACH = 1

# How many terrain pages this module holds at once.
#
# A page is 2.88 MB as an array. Eight is about 23 MB and covers the
# ground of one cluster and everything a 30 km profile from it reaches.
PAGE_HOLD = 8


# What a siting suggestion cannot know, in the order the page shows
# them. Design section 6.7.
#
# **These are not decoration and they are not a disclaimer.** Every one
# of them is a fact about a real site that terrain cannot hold, and a
# recommendation that does not carry them is a lie by omission. They are
# served by the API so that the page cannot reword them.
SITING_CAVEATS: tuple[tuple[str, str], ...] = (
    (
        "land_is_invisible",
        "We cannot tell whether anybody owns this ground, can reach it, or is allowed "
        "to put anything on it. The tool names terrain. A human names a site.",
    ),
    (
        "no_power_or_backhaul",
        "We cannot tell whether there is power, a roof, a pole, a road, or an internet "
        "link for a gateway.",
    ),
    (
        "clutter_is_not_a_surface_model",
        "We cannot see a building between the site and a street. Clutter is charged as "
        "a correction at each end of a path, not as a model of what stands on the "
        "ground.",
    ),
    (
        "nobody_asked_the_owner",
        "We cannot tell whether the person at the other end wants a node on their roof.",
    ),
    (
        "demand_set_is_biased_to_existing_nodes",
        "The demand set can only hold people who already own a node and got it partly "
        "working. It cannot see the valley with nobody in it, or the neighbourhood "
        "where three people gave up, so it will always favour places that already half "
        "work.",
    ),
    (
        "prediction_is_uncalibrated",
        "The prediction runs on nameplate radio figures. The measured calibration was "
        "rejected as too far out to apply, so no correction is in it. A prediction is "
        "not a promise.",
    ),
    (
        "one_preset_only",
        "This is one modem preset. A site chosen for Long fast says nothing about a "
        "node on Medium fast, because the two cannot hear each other.",
    ),
)


# --------------------------------------------------------------- demand


@dataclass(frozen=True)
class DemandPoint:
    """One place that wants help, and the nodes standing in it.

    The position is the mean of the reported positions of its nodes. It
    invents nothing: every node in a cell is within 300 m of the others,
    which is finer than the 365 m the public broker ever relays.
    """

    latitude: float
    longitude: float
    node_ids: tuple[str, ...]
    names: tuple[str, ...]

    @property
    def node_count(self) -> int:
        """Return how many nodes stand in this cell."""
        return len(self.node_ids)


def is_demand(row: dict[str, object]) -> bool:
    """Return whether one assessed node belongs in the demand set.

    Design section 6.1. A node is demand when it has a fault we can
    measure and when a site could be chosen for it:

    - It must have a fault. A node we simply cannot measure is not a
      reason to build anything, and it is already in the unknown bucket
      of the per node page.
    - Its position must be exact. A position accurate to 2.9 km cannot
      be sited for, and a coarse one that was sited for would move the
      answer by more than the answer is worth.
    - It must not be mobile. A footprint drawn to serve a node that
      moves serves nobody tomorrow. That is the same reasoning
      `roles.py` uses to keep TRACKER out of the site sets.
    - It must not already be fine. A node that is inside the predicted
      usable map, that something on the air heard, and whose best
      measured link has margin, is a node with a different problem.
    """
    if int(_number(row.get("bad_count")) or 0) <= 0:
        return False
    if row.get("position_confidence") != "exact":
        return False
    if row.get("latitude") is None or row.get("longitude") is None:
        return False
    if bool(row.get("mobile")):
        return False
    return not _is_already_fine(row)


def _is_already_fine(row: dict[str, object]) -> bool:
    """Return whether a node is inside coverage, heard, and has margin."""
    found = row.get("signals")
    if not isinstance(found, dict):
        return False

    def state(name: str) -> str | None:
        signal = found.get(name)
        return str(signal.get("state")) if isinstance(signal, dict) else None

    inside = state("outside_predicted_usable") == OK
    margin = state("weak_best_link") == OK
    heard = (_number(row.get("rf_packets")) or 0) > 0
    return inside and margin and heard


def demand_points(rows: Sequence[dict[str, object]], settings: Settings) -> list[DemandPoint]:
    """Return the demand, deduplicated onto a grid of equal cells.

    **The deduplication is the part that matters.** Five radios in one
    house are one place that wants help, not five votes. Without it a
    single address would decide where the mesh puts its next node.

    The cell is `GAPS_DEMAND_CELL_M` across. Longitude is scaled by the
    cosine of one reference latitude for the whole set, rather than by
    each node's own, so that the grid is regular and two nodes on the
    same ground always land in the same cell.
    """
    wanted = [row for row in rows if is_demand(row)]
    if not wanted:
        return []

    latitudes = np.array([float(_number(row["latitude"]) or 0.0) for row in wanted])
    longitudes = np.array([float(_number(row["longitude"]) or 0.0) for row in wanted])
    reference = float(np.median(latitudes))
    step_lat = max(settings.gaps_demand_cell_m, 1) / METRES_PER_DEGREE
    step_lon = step_lat / max(np.cos(np.radians(reference)), 0.1)

    cells: dict[tuple[int, int], list[int]] = {}
    for index in range(len(wanted)):
        key = (
            int(np.floor(latitudes[index] / step_lat)),
            int(np.floor(longitudes[index] / step_lon)),
        )
        cells.setdefault(key, []).append(index)

    points: list[DemandPoint] = []
    for key in sorted(cells):
        members = cells[key]
        points.append(
            DemandPoint(
                latitude=float(np.mean(latitudes[members])),
                longitude=float(np.mean(longitudes[members])),
                node_ids=tuple(str(wanted[index].get("node_id", "")) for index in members),
                names=tuple(str(wanted[index].get("display_name", "")) for index in members),
            )
        )
    return points


# -------------------------------------------------------------- clusters


@dataclass(frozen=True)
class Cluster:
    """A neighbourhood that holds several places wanting help."""

    index: int
    points: tuple[DemandPoint, ...]

    @property
    def node_count(self) -> int:
        """Return how many nodes this cluster holds."""
        return sum(point.node_count for point in self.points)

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Return every node this cluster holds."""
        return tuple(node for point in self.points for node in point.node_ids)

    @property
    def centroid(self) -> tuple[float, float]:
        """Return the mean position of the demand points."""
        return (
            float(np.mean([point.latitude for point in self.points])),
            float(np.mean([point.longitude for point in self.points])),
        )

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Return south, west, north, east. The order Leaflet takes."""
        latitudes = [point.latitude for point in self.points]
        longitudes = [point.longitude for point in self.points]
        return (min(latitudes), min(longitudes), max(latitudes), max(longitudes))

    @property
    def width_km(self) -> float:
        """Return how far apart the two furthest demand points are."""
        if len(self.points) < 2:
            return 0.0
        latitudes = np.array([point.latitude for point in self.points])
        longitudes = np.array([point.longitude for point in self.points])
        spread = distance_km(latitudes[:, None], longitudes[:, None], latitudes, longitudes)
        return float(spread.max())


def cluster_demand(points: Sequence[DemandPoint], settings: Settings) -> list[Cluster]:
    """Group demand points into neighbourhoods, worst first.

    Single linkage at `GAPS_CLUSTER_LINK_KM`: two points are in the same
    cluster when a chain of steps no longer than that joins them. It is
    the right rule for a mesh, because a valley of struggling nodes is a
    chain and not a ball, and it needs no new dependency.

    A cluster of fewer than `GAPS_MIN_CLUSTER` points is dropped. It is
    not an area; it is a node, and the per node list already holds it.

    The order is by how many nodes a cluster holds, because that is what
    the owner asked to be able to see: the group of people one node
    would help the most.
    """
    if not points:
        return []
    latitudes = np.array([point.latitude for point in points])
    longitudes = np.array([point.longitude for point in points])
    near = distance_km(latitudes[:, None], longitudes[:, None], latitudes, longitudes) <= max(
        settings.gaps_cluster_link_km, 0.0
    )

    parent = list(range(len(points)))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for first, second in zip(*np.nonzero(np.triu(near, 1)), strict=True):
        one, two = find(int(first)), find(int(second))
        if one != two:
            parent[two] = one

    groups: dict[int, list[int]] = {}
    for index in range(len(points)):
        groups.setdefault(find(index), []).append(index)

    kept = [
        [points[index] for index in members]
        for members in groups.values()
        if len(members) >= max(settings.gaps_min_cluster, 1)
    ]
    # Worst first, and then by position so that two clusters of equal
    # size always come back in the same order.
    kept.sort(
        key=lambda members: (
            -sum(point.node_count for point in members),
            -len(members),
            members[0].latitude,
            members[0].longitude,
        )
    )
    limit = max(settings.gaps_max_clusters, 0)
    return [
        Cluster(index=number, points=tuple(members)) for number, members in enumerate(kept[:limit])
    ]


# --------------------------------------------------------------- terrain


class Terrain:
    """Elevations read out of the terrain pages the coverage job caches.

    **This reads the cache. It never makes a page and never downloads
    one.** `terrain/srtm.py` is pinned bit-exact by a golden test, and
    `page_cell` there is the only reading of the page's cell order. See
    `AGENTS.md` 9.13.

    A tile that is not cached is not an error and is not flat ground. It
    is unknown, and `elevation` says so in its second return value. A
    candidate whose ground is unknown never reads as "no benefit".
    """

    def __init__(self, read_page: Callable[[str], bytes | None]) -> None:
        self._read_page = read_page
        self._held: OrderedDict[str, npt.NDArray[np.int16] | None] = OrderedDict()
        self.missing: set[str] = set()

    def page(self, name: str) -> npt.NDArray[np.int16] | None:
        """Return one page as a grid, or None when it is not held."""
        if name in self._held:
            self._held.move_to_end(name)
            return self._held[name]
        data = self._read_page(name)
        grid: npt.NDArray[np.int16] | None = None
        if data is not None:
            try:
                grid = page_array(data)
            except ValueError:
                grid = None
        if grid is None:
            self.missing.add(name)
        self._held[name] = grid
        while len(self._held) > PAGE_HOLD:
            self._held.popitem(last=False)
        return grid

    def elevation(
        self, latitudes: npt.NDArray[np.float64], longitudes: npt.NDArray[np.float64]
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
        """Return the elevation at each point, and whether it is known.

        An unknown point reads zero, and the mask beside it is false.
        **Never read the zero without the mask.** Sea level and "we hold
        no terrain here" are different answers, and only one of them is
        a fact.
        """
        latitudes = np.asarray(latitudes, dtype=np.float64)
        longitudes = np.asarray(longitudes, dtype=np.float64)
        out = np.zeros(latitudes.shape, dtype=np.float64)
        known = np.zeros(latitudes.shape, dtype=bool)

        floor_lat = np.floor(latitudes).astype(np.int64)
        floor_lon = np.floor(longitudes).astype(np.int64)
        rows = np.clip(
            np.rint((latitudes - floor_lat) * PAGE_SIZE).astype(np.int64), 0, PAGE_SIZE - 1
        )
        columns = np.clip(
            PAGE_SIZE - 1 - np.rint((longitudes - floor_lon) * PAGE_SIZE).astype(np.int64),
            0,
            PAGE_SIZE - 1,
        )

        pairs = np.stack([floor_lat.ravel(), floor_lon.ravel()], axis=1)
        for south, west in {(int(one), int(two)) for one, two in pairs}:
            grid = self.page(tile_name_of(south + 0.5, west + 0.5))
            if grid is None:
                continue
            here = (floor_lat == south) & (floor_lon == west)
            out[here] = grid[rows[here], columns[here]]
            known[here] = True
        return out, known


# The elevations over a box, the mask of what is known, and the
# latitude of each row and the longitude of each column.
Window = tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.bool_],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]


def window_elevations(
    terrain: Terrain, south: float, west: float, north: float, east: float
) -> Window:
    """Return the terrain over a box, on the 1/1200 degree lattice.

    Row 0 is the **north** edge and column 0 is the **west** edge, which
    is the order `coverage/grid.py` uses, so a reader who knows one
    knows the other.

    Returns the elevations, the mask of what is known, and the latitude
    and longitude of each row and column.
    """
    top = int(np.floor(north * PAGE_SIZE))
    bottom = int(np.ceil(south * PAGE_SIZE))
    left = int(np.ceil(west * PAGE_SIZE))
    right = int(np.floor(east * PAGE_SIZE))
    if top < bottom or right < left:
        empty = np.zeros((0, 0))
        return empty, np.zeros((0, 0), dtype=bool), np.zeros(0), np.zeros(0)

    latitudes = np.arange(top, bottom - 1, -1, dtype=np.float64) / PAGE_SIZE
    longitudes = np.arange(left, right + 1, dtype=np.float64) / PAGE_SIZE
    grid_lat, grid_lon = np.meshgrid(latitudes, longitudes, indexing="ij")
    elevations, known = terrain.elevation(grid_lat, grid_lon)
    return elevations, known, latitudes, longitudes


def _slide_max(values: npt.NDArray[np.float64], span: int, axis: int) -> npt.NDArray[np.float64]:
    """Return a sliding maximum along one axis, the same shape as given."""
    half = span // 2
    padded = np.pad(
        values, [(half, half) if index == axis else (0, 0) for index in range(2)], mode="edge"
    )
    windows = np.lib.stride_tricks.sliding_window_view(padded, span, axis=axis)
    return np.asarray(windows.max(axis=-1), dtype=np.float64)


def _slide_all(values: npt.NDArray[np.bool_], span: int, axis: int) -> npt.NDArray[np.bool_]:
    """Return whether every cell of a sliding window is true."""
    half = span // 2
    padded = np.pad(
        values,
        [(half, half) if index == axis else (0, 0) for index in range(2)],
        mode="constant",
        constant_values=False,
    )
    windows = np.lib.stride_tricks.sliding_window_view(padded, span, axis=axis)
    return np.asarray(windows.all(axis=-1), dtype=bool)


@dataclass(frozen=True)
class HighPoint:
    """One place the ground stands above what is around it."""

    latitude: float
    longitude: float
    elevation_m: float
    prominence_m: float


def local_maxima(
    terrain: Terrain,
    bounds: tuple[float, float, float, float],
    settings: Settings,
) -> list[HighPoint]:
    """Return the high ground inside a box, highest first.

    A cell qualifies when it is the highest of a window about a
    kilometre across **and** stands `GAPS_MIN_PROMINENCE_M` above the
    median of that window. The median is the second test on purpose: the
    highest cell of a flat plain is still the highest cell, and it is
    not a site.

    Cells whose window is not entirely known are not offered. A window
    half filled with "we hold no terrain here" would read as a hill
    standing over nothing.

    Then the list is thinned to `GAPS_CANDIDATE_SPACING_KM` apart,
    keeping the highest, so that one ridge does not fill every slot with
    sixty cells of itself.
    """
    south, west, north, east = bounds
    elevations, known, latitudes, longitudes = window_elevations(terrain, south, west, north, east)
    span = MAXIMA_WINDOW_CELLS
    if elevations.shape[0] < span or elevations.shape[1] < span:
        return []

    highest = _slide_max(_slide_max(elevations, span, 0), span, 1)
    whole = _slide_all(_slide_all(known, span, 0), span, 1)
    peaks = (elevations >= highest) & whole
    rows, columns = np.nonzero(peaks)
    if not rows.size:
        return []

    # The median costs a full window for each cell, so it is taken only
    # at the cells that already passed the cheap test. On a real window
    # those are a few hundred cells out of half a million.
    half = span // 2
    found: list[HighPoint] = []
    for row, column in zip(rows, columns, strict=True):
        top, bottom = max(0, row - half), min(elevations.shape[0], row + half + 1)
        left, right = max(0, column - half), min(elevations.shape[1], column + half + 1)
        middle = float(np.median(elevations[top:bottom, left:right]))
        prominence = float(elevations[row, column]) - middle
        if prominence < settings.gaps_min_prominence_m:
            continue
        found.append(
            HighPoint(
                latitude=float(latitudes[row]),
                longitude=float(longitudes[column]),
                elevation_m=float(elevations[row, column]),
                prominence_m=prominence,
            )
        )

    found.sort(key=lambda point: (-point.elevation_m, point.latitude, point.longitude))
    return thin(found, settings.gaps_candidate_spacing_km, settings.gaps_candidates_per_cluster)


def thin(points: Sequence[HighPoint], spacing_km: float, limit: int) -> list[HighPoint]:
    """Return the points no two of which stand closer than a distance.

    The list must already be in the order to prefer. The first point is
    always kept, and a later one is kept only when it stands clear of
    everything kept before it.
    """
    kept: list[HighPoint] = []
    for point in points:
        if len(kept) >= max(limit, 0):
            break
        if any(
            distance_km(point.latitude, point.longitude, other.latitude, other.longitude)
            < spacing_km
            for other in kept
        ):
            continue
        kept.append(point)
    return kept


# ---------------------------------------------------------- the screen


@dataclass(frozen=True)
class CandidateRadio:
    """The radio a candidate site is read with.

    **Every one of these is an assumption and the page prints all
    four.** The owner said "a 1 W node", so the power is 30 dBm, the
    height is the attic or roof node that `CLIENT_BASE` is defined for,
    and the antenna comes from the stock figures in `radio/hardware.py`
    rather than from a new number invented here.
    """

    tx_power_dbm: float
    antenna_gain_dbi: float
    cable_loss_db: float
    height_m: float

    @property
    def eirp_dbm(self) -> float:
        """Return the power leaving the antenna, in dBm."""
        return self.tx_power_dbm + self.antenna_gain_dbi - self.cable_loss_db


@dataclass(frozen=True)
class ScreenResult:
    """What the cheap model says about one candidate.

    `served` holds the index of each demand point the screen predicts
    it would **newly** reach. `unknown_points` counts the ones it could
    not judge because the terrain under the path is not held. A
    candidate that judged nothing at all is `unknown`, never "serves
    nobody".

    `margin_db` carries every demand point, judged or not, and is used
    only to break a tie in the ranking. **It is not served by the API
    and it must never be drawn.** It is the output of a model that
    charges four things and ignores everything else, and a decibel
    figure beside a place on a map reads as a prediction.
    """

    served: tuple[int, ...]
    margin_db: tuple[float, ...]
    unknown_points: int
    known: bool

    @property
    def state(self) -> str:
        """Return the state of this candidate. Three, as ever."""
        if not self.known:
            return UNKNOWN
        return OK if self.served else BAD

    @property
    def comfort_db(self) -> float:
        """Return the median margin over the points it would reach.

        A tie break, and nothing else. Two candidates that reach the
        same seven places are not equally good, and this is the cheapest
        way to say which of them reaches them with room to spare.
        """
        if not self.served:
            return 0.0
        return float(np.median([self.margin_db[index] for index in self.served]))


def screen(
    terrain: Terrain,
    settings: Settings,
    preset: ModemPreset,
    latitude: float,
    longitude: float,
    radio: CandidateRadio,
    demand: Sequence[DemandPoint],
    already_usable: frozenset[int] = frozenset(),
) -> ScreenResult:
    """Return which demand points a candidate would **newly** reach.

    **This screen is deliberately optimistic, and that is the whole
    rule.** A pre-filter may pass a candidate the engine then rejects,
    because the engine gets the last word on the few that reach it. It
    may never reject one the engine would have liked, because nothing
    downstream can recover a candidate that was thrown away here.

    So it charges exactly four things and nothing more:

    1. Free space loss over the great circle distance.
    2. The terminal clutter correction at both ends, which is the same
       `coverage/clutter.py` the map uses.
    3. **One** knife edge, for the single worst obstruction on the path.
       Adding a second edge, or a terrain fit, is how a screen starts
       rejecting real sites.
    4. Nothing else. No ground reflection, no atmospheric loss, no
       statistical fade margin.

    The earth is curved under the path at the usual 4/3 radius, because
    leaving it flat would hide every obstruction on a long path and make
    the screen optimistic in a way that is simply wrong rather than
    deliberately generous.

    The two directions are compared separately and **the weaker one
    decides, for this one candidate, before anything is combined**. That
    is `AGENTS.md` 9.24, and it holds here for the same reason: a place
    a node can shout to but cannot hear back from is not covered.

    `already_usable` names the demand points the published coverage run
    already reaches. They are left out of the score, because the
    question is what a new node would **add**. A candidate that reaches
    only places that already work has added nothing, however good its
    view is.

    It is not ITM and it must never be drawn on a map. It produces a
    ranking, and a ranking only.
    """
    if not demand:
        return ScreenResult((), (), 0, True)

    here_lat = np.array([latitude])
    here_lon = np.array([longitude])
    _ground, ground_known = terrain.elevation(here_lat, here_lon)
    if not bool(ground_known[0]):
        return ScreenResult((), (), len(demand), False)

    target_lat = np.array([point.latitude for point in demand])
    target_lon = np.array([point.longitude for point in demand])
    distances_m = distance_km(latitude, longitude, target_lat, target_lon) * 1000.0

    steps = int(max(2, np.ceil(float(distances_m.max()) / TERRAIN_STEP_M) + 1))
    fraction = np.linspace(0.0, 1.0, steps)
    # Linear in latitude and longitude. Over 30 km the departure from
    # the great circle is under a metre, which is a hundredth of the
    # 90 m cell the terrain is sampled on.
    path_lat = latitude + fraction[None, :] * (target_lat[:, None] - latitude)
    path_lon = longitude + fraction[None, :] * (target_lon[:, None] - longitude)
    profile, profile_known = terrain.elevation(path_lat, path_lon)

    along = fraction[None, :] * distances_m[:, None]
    remaining = distances_m[:, None] - along
    bulge = along * remaining / (2.0 * EFFECTIVE_EARTH_RADIUS_M)
    surface = profile + bulge

    transmit_m = profile[:, 0] + radio.height_m
    receive_m = profile[:, -1] + settings.coverage_rx_height_m
    line = transmit_m[:, None] + fraction[None, :] * (receive_m - transmit_m)[:, None]
    clearance = line - surface
    # The two ends are the antennas themselves and are never their own
    # obstruction.
    inner = clearance[:, 1:-1]
    worst = inner.min(axis=1) if inner.shape[1] else np.zeros(len(demand))
    worst_at = inner.argmin(axis=1) + 1 if inner.shape[1] else np.zeros(len(demand), dtype=int)

    wavelength_m = SPEED_OF_LIGHT_M_S / (DEFAULT_FREQUENCY_MHZ * 1e6)
    rows = np.arange(len(demand))
    d1 = np.maximum(along[rows, worst_at], 1.0)
    d2 = np.maximum(distances_m - d1, 1.0)
    obstruction_m = -worst
    nu = obstruction_m * np.sqrt(2.0 * (d1 + d2) / (wavelength_m * d1 * d2))
    edge_db = np.array([knife_edge_db(float(value)) for value in nu])

    free_space_db = (
        32.44
        + 20.0 * np.log10(np.maximum(distances_m / 1000.0, 1e-3))
        + 20.0 * np.log10(DEFAULT_FREQUENCY_MHZ)
    )
    here_clutter = terminal_loss_db(
        clutter_at(settings, latitude, longitude),
        radio.height_m,
        DEFAULT_FREQUENCY_MHZ,
        is_diffracting(class_at(settings, latitude, longitude)),
    )
    there_clutter = np.array(
        [
            terminal_loss_db(
                clutter_at(settings, point.latitude, point.longitude),
                settings.coverage_rx_height_m,
                DEFAULT_FREQUENCY_MHZ,
                is_diffracting(class_at(settings, point.latitude, point.longitude)),
            )
            for point in demand
        ]
    )

    loss_db = free_space_db + edge_db + here_clutter + there_clutter
    downlink_dbm = radio.eirp_dbm + settings.coverage_rx_gain_dbi - loss_db
    node_antenna_db = radio.antenna_gain_dbi - radio.cable_loss_db
    uplink_dbm = handheld_eirp_dbm(settings) + node_antenna_db - loss_db
    # The weaker direction, of this one candidate, before anything is
    # combined. `AGENTS.md` 9.24.
    weaker = np.minimum(downlink_dbm, uplink_dbm)
    margin = weaker - preset.sensitivity_dbm

    judged = profile_known.all(axis=1)
    fresh = np.ones(len(demand), dtype=bool)
    for index in already_usable:
        if 0 <= index < len(demand):
            fresh[index] = False
    reached = judged & fresh & (margin >= 0.0)
    return ScreenResult(
        served=tuple(int(index) for index in np.nonzero(reached)[0]),
        margin_db=tuple(round(float(value), 1) for value in margin),
        unknown_points=int(np.count_nonzero(~judged)),
        known=bool(judged.any()),
    )


# -------------------------------------------------------------- the row


@dataclass
class Candidate:
    """One place a node could go, and what it would do for the demand.

    `method` says how it was arrived at. `state` is the three-state
    answer and never a score. `newly_usable` is **None** when the state
    is `unknown`, and never zero: a candidate standing on terrain we do
    not hold has not been judged.
    """

    kind: str
    cluster: int
    latitude: float
    longitude: float
    elevation_m: float | None = None
    prominence_m: float | None = None
    node_id: str | None = None
    display_name: str | None = None
    method: str = METHOD_SCREEN
    state: str = UNKNOWN
    screen_score: int = 0
    screen_unknown: int = 0
    newly_usable: int | None = None
    newly_usable_nodes: tuple[str, ...] = ()
    already_usable: int = 0
    baseline_unknown: int = 0
    run_stamp: str | None = None
    reason: str = "not_screened"
    margin_db: tuple[float, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        """Return the candidate as the API serves it."""
        return {
            "kind": self.kind,
            "area": self.cluster,
            "latitude": round(self.latitude, 5),
            "longitude": round(self.longitude, 5),
            "elevation_m": None if self.elevation_m is None else round(self.elevation_m),
            "prominence_m": None if self.prominence_m is None else round(self.prominence_m),
            "node_id": self.node_id,
            "display_name": self.display_name,
            "method": self.method,
            "state": self.state,
            "screen_score": self.screen_score,
            "screen_unknown": self.screen_unknown,
            "newly_usable": self.newly_usable,
            "newly_usable_nodes": list(self.newly_usable_nodes),
            "already_usable": self.already_usable,
            "baseline_unknown": self.baseline_unknown,
            "run_stamp": self.run_stamp,
            "reason": self.reason,
            "sentence": candidate_sentence(self),
        }


# What the page says for each machine reason. The words are written
# here, beside the rule that sets them, exactly as `signals.py` does it.
# The front end never rewords a finding.
CANDIDATE_REASONS: dict[str, str] = {
    "screened_only": (
        "A cheap terrain screen says this site would reach {screen_score} of the places "
        "that want help. It is a ranking and not a prediction: the engine did not run "
        "here."
    ),
    "confirmed_by_engine": (
        "The engine predicts that a node here would bring {newly_usable} of the places "
        "that want help inside usable coverage, which they are not in today."
    ),
    "engine_found_nothing": (
        "The engine ran here and found that it would bring nothing new inside usable coverage."
    ),
    "no_terrain": (
        "We hold no terrain for this ground, so nothing was judged. That is not the "
        "same as no benefit."
    ),
    "engine_refused": (
        "The engine would not run here, so nothing was judged. That is not the same as no benefit."
    ),
    "not_screened": "This candidate was not judged.",
    "screen_found_nothing": (
        "A cheap terrain screen says this site would reach none of the places that want help."
    ),
}


def candidate_sentence(candidate: "Candidate") -> str:
    """Return the sentence a candidate's reason stands for."""
    template = CANDIDATE_REASONS.get(candidate.reason)
    if template is None:
        return candidate.reason
    return template.format(
        screen_score=candidate.screen_score,
        newly_usable=candidate.newly_usable if candidate.newly_usable is not None else "unknown",
    )


# ------------------------------------------------------------- geometry


def distance_km(
    first_lat: float | npt.NDArray[np.float64],
    first_lon: float | npt.NDArray[np.float64],
    second_lat: float | npt.NDArray[np.float64],
    second_lon: float | npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Return the great circle distance between two places, in km.

    The haversine formula, over a spherical earth. It is accurate to
    about half a percent, which over 30 km is 150 m, and every use of it
    here is either a clustering distance of kilometres or a path length
    that then meets a 90 m terrain grid.
    """
    radius_km = 6371.0088
    lat1 = np.radians(np.asarray(first_lat, dtype=np.float64))
    lon1 = np.radians(np.asarray(first_lon, dtype=np.float64))
    lat2 = np.radians(np.asarray(second_lat, dtype=np.float64))
    lon2 = np.radians(np.asarray(second_lon, dtype=np.float64))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    inner = np.sin(delta_lat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lon / 2) ** 2
    return np.asarray(2 * radius_km * np.arcsin(np.sqrt(np.clip(inner, 0.0, 1.0))))


def grow_bounds(
    bounds: tuple[float, float, float, float], by_km: float
) -> tuple[float, float, float, float]:
    """Return a box grown by a distance on every side."""
    south, west, north, east = bounds
    lat_pad = by_km * 1000.0 / METRES_PER_DEGREE
    middle = (south + north) / 2.0
    lon_pad = lat_pad / max(np.cos(np.radians(middle)), 0.1)
    return (south - lat_pad, west - lon_pad, north + lat_pad, east + lon_pad)


def _number(value: object) -> float | None:
    """Return a number, or None when the value is not one."""
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def candidate_radio(settings: Settings) -> CandidateRadio:
    """Return the radio every candidate is read with.

    The antenna gain and the cable loss come from the existing stock
    figures rather than from a number invented for this feature, so a
    candidate is read with the same radio the rest of the project
    assumes for a node nobody has described.
    """
    return CandidateRadio(
        tx_power_dbm=settings.gaps_candidate_tx_power_dbm,
        antenna_gain_dbi=STOCK_ANTENNA_GAIN_DBI,
        cable_loss_db=DEFAULT_CABLE_LOSS_DB,
        height_m=settings.gaps_candidate_height_m,
    )


def ground_candidates(terrain: Terrain, cluster: Cluster, settings: Settings) -> list[Candidate]:
    """Return the places on the ground worth looking at near a cluster.

    From terrain, and never from a site database, because there is no
    site database. Design section 6.3, kind B.
    """
    bounds = grow_bounds(cluster.bounds, settings.gaps_search_radius_km)
    return [
        Candidate(
            kind=KIND_GROUND,
            cluster=cluster.index,
            latitude=point.latitude,
            longitude=point.longitude,
            elevation_m=point.elevation_m,
            prominence_m=point.prominence_m,
        )
        for point in local_maxima(terrain, bounds, settings)
    ]


def existing_candidates(cluster: Cluster, rows: Iterable[dict[str, object]]) -> list[Candidate]:
    """Return the nodes already standing inside a cluster.

    Design section 6.3, kind A, and the cheapest real answer this
    feature has: "if the node at this address went to 1 W on a 9 m mast
    it would bring in seven of the eleven" needs no land, no permission
    and no new site.

    A node with a coarse or missing position is not offered, for the
    same reason it is not drawn on the map: a candidate is a claim about
    a place.
    """
    south, west, north, east = cluster.bounds
    found: list[Candidate] = []
    for row in rows:
        if row.get("position_confidence") != "exact" or bool(row.get("mobile")):
            continue
        latitude = _number(row.get("latitude"))
        longitude = _number(row.get("longitude"))
        if latitude is None or longitude is None:
            continue
        if not (south <= latitude <= north and west <= longitude <= east):
            continue
        found.append(
            Candidate(
                kind=KIND_EXISTING,
                cluster=cluster.index,
                latitude=latitude,
                longitude=longitude,
                node_id=str(row.get("node_id") or ""),
                display_name=str(row.get("display_name") or ""),
            )
        )
    return found
