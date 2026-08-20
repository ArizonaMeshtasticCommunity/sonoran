"""Correcting the prediction against what the mesh measured.

A prediction starts from a hardware model and a guess. The mesh knows
better: it hears its own links every day. This module compares the two
and works out how far each node is from its nameplate.

The result is one number for each node, in dB. A node that is measured
9 dB below its nameplate has a worse antenna than we assumed, a lower
mast, less power, or a mixture that no measurement can separate. The
map only needs the total.

## Where the measurements come from

`neighbor_metrics` is the source. A node reports the neighbours it
hears itself, with an SNR. That is a real radio link between two real
nodes. `AGENTS.md` 9.5 says to use it, and it is right: only about five
percent of gateway observations are direct links, and `packet_seen` can
only ever record MQTT gateways, so a gateway-only view would calibrate
a handful of nodes and call it a mesh.

Traceroute carries a per-hop SNR as well and is the obvious next
source. It is left out here because the only correct reading of a
traceroute row lives in `sonoran/api/traces.py`, and the jobs process
does not import the api package. Moving that reading to a shared module
is the work to do before adding it.

## The model

For a link from node i to node j:

    observed - predicted  =  a_i + a_j + noise

One offset for each node, appearing at both ends. That is deliberate.
A wrong antenna gain or a wrong mast height helps or hurts the same
amount whichever end transmits, so a single per-node number describes
both directions. Fitting a separate transmit and receive offset would
double the parameters and halve the evidence behind each one.

Adding a constant to every offset adds twice that to every residual, so
the offsets are only fixed once their sum is. They are anchored at zero
and whatever is left over is reported as one bias for the whole model.

## Why the obvious fit is wrong

The mesh only reports links that worked. Fitting to those alone says
every node is better than it is, because the failures are invisible.
That bias points the wrong way for a coverage map: it draws reach that
is not there.

So a link that should have been heard and was not is evidence too. When
a node publishes a neighbour list, the nodes it left out are nodes it
did not hear. Where the model says it should have, that is a left
censored measurement: the true value is below the sensitivity of the
preset, and we do not know by how much.

`fit_offsets` takes both. It is the expectation step of a censored
regression: a censored link is filled in with the mean of the truncated
normal it must have come from, the offsets are fitted again, and the
two repeat until they stop moving. It needs no library beyond numpy and
`math.erf`.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from sonoran.logging import get_logger

logger = get_logger(__name__)

# How many rounds of filling in and fitting to run.
#
# The fit moves very little after a handful. Twenty is a ceiling, not a
# target, and the loop leaves early when nothing changes.
MAX_ROUNDS = 20

# When to stop: the largest change to any offset, in dB.
TOLERANCE_DB = 0.01

# The spread of the noise on one measurement, in dB.
#
# A LoRa SNR reading and a terrain model disagree by a lot. Eight dB is
# a working figure for the width of that disagreement, and it is only
# used to fill in a censored link, so a wrong value moves the answer
# slowly rather than breaking it.
NOISE_SIGMA_DB = 8.0

# How much evidence a node needs before its offset is used.
#
# Both must hold. One chatty neighbour reporting forty times is one
# opinion, not forty, which is why the second test counts the
# counterparties and not the links.
MIN_OBSERVATIONS = 6
MIN_COUNTERPARTIES = 3

# How many links a node must have that really worked.
#
# A silent link is evidence, and it is the evidence that stops the fit
# flattering everybody. But a node whose whole case is silence is being
# told it is worse than predicted with nothing to argue back. Two
# working links is a low bar and it keeps that from happening.
MIN_REPORTED = 2

# How much scatter a fit may leave and still be believed, in dB.
#
# The offsets explain a link only if the measurements agree about it.
# When what is left over is this wide, one number for each node is not
# describing the mesh, and the map must keep its nameplate figures
# rather than move on a fit of noise.
#
# Twenty dB is generous. A model and a LoRa SNR reading disagree by a
# lot, and this is not a test of the model. It is a guard against a fit
# that means nothing at all: a database of made-up rows fits at over
# thirty, and a mesh in the desert should be well under twenty.
MAX_TRUSTED_SPREAD_DB = 20.0


@dataclass(frozen=True)
class LinkObservation:
    """One measured link, against what the model expected of it.

    `residual_db` is positive when the mesh did better than the model
    said it would.

    `censored` marks a link the model expected and the mesh did not
    report. Its residual is then an upper bound: the truth is at or
    below it.
    """

    transmitter: str
    receiver: str
    residual_db: float
    censored: bool = False


@dataclass
class NodeFit:
    """What the measurements say about one node."""

    node_id: str
    offset_db: float
    observations: int
    counterparties: int
    censored: int
    # How many of the observations are links that really worked.
    reported: int
    # The spread of what is left after the offset is applied. A large
    # value means the offset does not explain this node.
    residual_spread_db: float

    @property
    def is_usable(self) -> bool:
        """Return true when there is enough evidence to use this."""
        return (
            self.observations >= MIN_OBSERVATIONS
            and self.counterparties >= MIN_COUNTERPARTIES
            and self.reported >= MIN_REPORTED
        )


@dataclass
class Calibration:
    """The whole fit."""

    # The bias of the model itself, in dB, once the nodes are anchored.
    # A large value says the prediction is wrong everywhere, which is a
    # question about the model and not about any node.
    model_bias_db: float
    nodes: list[NodeFit] = field(default_factory=list)
    rounds: int = 0
    # What the measurements still disagree by, once the offsets are
    # applied, in dB.
    residual_spread_db: float = 0.0

    @property
    def is_trusted(self) -> bool:
        """Return true when this fit is worth applying at all.

        A wide scatter means one number for each node does not describe
        the mesh. Applying it would move the map on noise, so the map
        keeps its nameplate figures instead.
        """
        return self.residual_spread_db <= MAX_TRUSTED_SPREAD_DB

    def usable(self) -> dict[str, float]:
        """Return the offsets a prediction may use.

        Empty when the fit as a whole is not trusted, whatever any one
        node looks like on its own.
        """
        if not self.is_trusted:
            return {}
        return {fit.node_id: fit.offset_db for fit in self.nodes if fit.is_usable}


def _normal_pdf(value: float) -> float:
    """Return the standard normal density at a value."""
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _normal_cdf(value: float) -> float:
    """Return the standard normal distribution at a value."""
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def truncated_mean(limit: float, sigma: float = NOISE_SIGMA_DB) -> float:
    """Return the mean of a normal known only to be below a limit.

    `limit` is how far the cut sits above the mean, in units of dB. The
    answer is how far below the mean the truth sits on average.

    This is what fills in a link the mesh should have reported and did
    not. Treating such a link as if it sat exactly at the limit would
    understate every failure, because most of them are well below it.
    """
    if sigma <= 0.0:
        return min(limit, 0.0)
    z = limit / sigma
    denominator = _normal_cdf(z)
    # Far below the mean the ratio is numerically unstable and the
    # answer is very close to the limit itself.
    if denominator < 1e-9:
        return limit
    return -sigma * (_normal_pdf(z) / denominator)


def fit_offsets(
    observations: list[LinkObservation],
    max_rounds: int = MAX_ROUNDS,
) -> Calibration:
    """Return the per-node offsets the measurements imply.

    Every offset is anchored so they sum to zero. What is left over is
    reported as the bias of the model itself.
    """
    if not observations:
        return Calibration(model_bias_db=0.0)

    names = sorted({name for item in observations for name in (item.transmitter, item.receiver)})
    index = {name: position for position, name in enumerate(names)}
    count = len(names)

    # One row for each link, with a one at each end of it. The last row
    # anchors the sum of the offsets at zero, so the fit has one answer
    # rather than a line of them.
    rows = np.zeros((len(observations) + 1, count), dtype=np.float64)
    for row, item in enumerate(observations):
        rows[row, index[item.transmitter]] += 1.0
        rows[row, index[item.receiver]] += 1.0
    rows[-1, :] = 1.0

    measured = np.array([item.residual_db for item in observations], dtype=np.float64)
    censored = np.array([item.censored for item in observations], dtype=bool)

    filled = measured.copy()
    offsets = np.zeros(count, dtype=np.float64)
    rounds = 0

    for attempt in range(1, max_rounds + 1):
        target = np.append(filled, 0.0)
        solved, *_ = np.linalg.lstsq(rows, target, rcond=None)
        # Anchor the offsets exactly.
        #
        # The last row of the matrix asks for a sum of zero, but it is
        # one equation among hundreds and the fit trades it away. Taking
        # the mean off afterwards is exact, and it costs nothing: the
        # model is a_i + a_j, so moving every offset by the same amount
        # only moves the bias by twice it, which is where it belongs.
        solved = solved - float(np.mean(solved))
        moved = float(np.max(np.abs(solved - offsets))) if count else 0.0
        offsets = solved

        rounds = attempt
        if not censored.any():
            break

        # Fill in each censored link with the mean of the values it
        # could have taken, given where the model put it.
        predicted = rows[:-1] @ offsets
        limits = measured[censored] - predicted[censored]
        filled[censored] = predicted[censored] + np.array(
            [truncated_mean(float(limit)) for limit in limits]
        )
        rounds = attempt
        if moved < TOLERANCE_DB:
            break

    left_over = filled - rows[:-1] @ offsets
    bias = float(np.mean(left_over))
    # Measure the scatter on the links that were really reported. A
    # filled in link was invented from the fit, so counting it would
    # flatter the fit with its own guesses.
    reported = left_over[~censored]
    spread = float(np.std(reported)) if reported.size else 0.0

    fits: list[NodeFit] = []
    for name, position in index.items():
        mine = [item for item in observations if name in (item.transmitter, item.receiver)]
        others = {item.receiver if item.transmitter == name else item.transmitter for item in mine}
        left = [
            item.residual_db - offsets[index[item.transmitter]] - offsets[index[item.receiver]]
            for item in mine
            if not item.censored
        ]
        fits.append(
            NodeFit(
                node_id=name,
                offset_db=round(float(offsets[position]), 2),
                observations=len(mine),
                counterparties=len(others),
                censored=sum(1 for item in mine if item.censored),
                reported=sum(1 for item in mine if not item.censored),
                residual_spread_db=round(float(np.std(left)), 2) if left else 0.0,
            )
        )

    fits.sort(key=lambda fit: fit.node_id)
    result = Calibration(
        model_bias_db=round(bias, 2),
        nodes=fits,
        rounds=rounds,
        residual_spread_db=round(spread, 2),
    )
    logger.info(
        "calibration fitted %s nodes from %s links in %s rounds, "
        "model bias %.1f dB, scatter %.1f dB%s",
        sum(1 for fit in fits if fit.is_usable),
        len(observations),
        rounds,
        bias,
        spread,
        "" if result.is_trusted else " (too wide to use)",
    )
    if not result.is_trusted:
        logger.warning(
            "the calibration scatter is %.1f dB, above %.0f, so no node is corrected",
            spread,
            MAX_TRUSTED_SPREAD_DB,
        )
    return result


def residual_summary(observations: list[LinkObservation]) -> dict[str, float]:
    """Return how far the model is from the measurements, before any fit.

    This is the number that says whether the model is worth correcting
    at all. A mean far from zero is a model problem, not a node problem.
    """
    if not observations:
        return {"count": 0.0, "mean_db": 0.0, "spread_db": 0.0, "censored": 0.0}
    values: npt.NDArray[np.float64] = np.array(
        [item.residual_db for item in observations if not item.censored], dtype=np.float64
    )
    if not values.size:
        return {
            "count": float(len(observations)),
            "mean_db": 0.0,
            "spread_db": 0.0,
            "censored": float(len(observations)),
        }
    return {
        "count": float(len(observations)),
        "mean_db": round(float(np.mean(values)), 2),
        "spread_db": round(float(np.std(values)), 2),
        "censored": float(sum(1 for item in observations if item.censored)),
    }
