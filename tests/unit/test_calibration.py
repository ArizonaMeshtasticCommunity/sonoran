"""Tests for correcting the prediction against measurements.

The test that matters is
`test_the_fit_recovers_planted_offsets_through_censoring`. It plants
offsets in made-up links, hides the links that fall below the
sensitivity of the preset, and asks the fit to find the offsets again.

That is the shape of the real problem. The mesh only reports links that
worked, so a fit that ignores the failures says every node is better
than it is, and a coverage map drawn from it promises reach that is not
there.
"""

import numpy as np
import pytest

from sonoran.coverage.calibrate import (
    MAX_TRUSTED_SPREAD_DB,
    MIN_COUNTERPARTIES,
    MIN_OBSERVATIONS,
    NOISE_SIGMA_DB,
    LinkObservation,
    fit_offsets,
    residual_summary,
    truncated_mean,
)
from sonoran.db.models import NeighborMetrics
from sonoran.jobs.calibrate import Peer, _matches_current_preset
from sonoran.radio.overrides import Overrides
from sonoran.radio.presets import preset_by_key
from sonoran.radio.resolve import resolve_profile


def _peer(node_num: int, preset_key: str) -> Peer:
    preset = preset_by_key(preset_key)
    assert preset is not None
    node_id = f"!{node_num:08x}"
    return Peer(
        node_id=node_id,
        node_num=node_num,
        latitude=33.4,
        longitude=-112.0,
        profile=resolve_profile(node_id, "RAK4631", Overrides({})),
        preset=preset,
    )


def test_a_report_cannot_cross_a_modem_preset() -> None:
    """The row records the preset used when the link was measured.

    A node can change preset during the calibration window. Its old
    report must not correct the new radio configuration.
    """
    peers = {1: _peer(1, "LONG_FAST"), 2: _peer(2, "LONG_FAST")}
    report = NeighborMetrics(
        node_num=1,
        neighbor_node_num=2,
        channel="LongFast",
        snr=-5.0,
    )
    assert _matches_current_preset(report, peers)

    report.channel = "MediumSlow"
    assert not _matches_current_preset(report, peers)

    report.channel = "Weather"
    assert not _matches_current_preset(report, peers)

    report.channel = "LongFast"
    peers[2] = _peer(2, "MEDIUM_SLOW")
    assert not _matches_current_preset(report, peers)


def _links(
    planted: dict[str, float],
    rng: np.random.Generator,
    per_pair: int = 6,
    noise_db: float = 2.0,
    cut_db: float | None = None,
) -> list[LinkObservation]:
    """Return made-up links between every pair of nodes.

    A link below `cut_db` is marked censored, which is what the mesh
    does to a link it never reports.
    """
    names = sorted(planted)
    observations: list[LinkObservation] = []
    for first in range(len(names)):
        for second in range(first + 1, len(names)):
            a, b = names[first], names[second]
            for _ in range(per_pair):
                truth = planted[a] + planted[b] + float(rng.normal(0.0, noise_db))
                if cut_db is not None and truth < cut_db:
                    observations.append(LinkObservation(a, b, cut_db, censored=True))
                else:
                    observations.append(LinkObservation(a, b, truth))
    return observations


def test_the_fit_recovers_planted_offsets() -> None:
    """With no censoring the fit is a plain least squares."""
    rng = np.random.default_rng(20260820)
    planted = {"!a": 4.0, "!b": -2.0, "!c": -6.0, "!d": 4.0}
    result = fit_offsets(_links(planted, rng, per_pair=12, noise_db=1.0))

    found = {fit.node_id: fit.offset_db for fit in result.nodes}
    for name, value in planted.items():
        assert found[name] == pytest.approx(value, abs=1.0)


def test_the_offsets_are_anchored_so_the_fit_has_one_answer() -> None:
    """Adding a constant to every offset adds twice it to every link.

    Without an anchor the fit drifts by a different amount every run,
    and a map redrawn each night would move for no reason.
    """
    rng = np.random.default_rng(7)
    result = fit_offsets(_links({"!a": 10.0, "!b": 6.0, "!c": 2.0}, rng, noise_db=0.5))
    assert sum(fit.offset_db for fit in result.nodes) == pytest.approx(0.0, abs=0.1)
    # What was taken out is reported rather than lost.
    assert result.model_bias_db == pytest.approx(12.0, abs=1.5)


def test_the_fit_recovers_planted_offsets_through_censoring() -> None:
    """The mesh only reports the links that worked.

    A fit that takes the survivors at face value says every node is
    better than it is. This is the test that stops that.
    """
    rng = np.random.default_rng(1312)
    planted = {"!a": 6.0, "!b": 0.0, "!c": -6.0, "!d": -3.0, "!e": 3.0}
    # A cut that hides roughly the weaker third of the links.
    links = _links(planted, rng, per_pair=40, noise_db=NOISE_SIGMA_DB, cut_db=-4.0)
    hidden = sum(1 for item in links if item.censored)
    assert hidden > 0, "the test must actually censor something"

    with_censoring = fit_offsets(links)
    survivors_only = fit_offsets([item for item in links if not item.censored])

    censored_error = max(abs(fit.offset_db - planted[fit.node_id]) for fit in with_censoring.nodes)
    naive_error = max(abs(fit.offset_db - planted[fit.node_id]) for fit in survivors_only.nodes)

    assert censored_error < naive_error, (
        "taking the censored links into account must beat ignoring them"
    )
    assert censored_error < 2.5


def test_ignoring_the_failures_is_optimistic_about_the_weakest_node() -> None:
    """Name the direction of the bias, not only its size.

    The node that fails most is the one whose failures are hidden most,
    so ignoring them flatters it the hardest.
    """
    rng = np.random.default_rng(99)
    planted = {"!good": 8.0, "!fine": 0.0, "!bad": -8.0}
    links = _links(planted, rng, per_pair=60, noise_db=NOISE_SIGMA_DB, cut_db=-6.0)

    naive = {
        fit.node_id: fit.offset_db
        for fit in fit_offsets([item for item in links if not item.censored]).nodes
    }
    assert naive["!bad"] > planted["!bad"], "the survivors flatter the worst node"


def test_a_censored_link_is_filled_in_below_its_limit() -> None:
    """A link that failed did not sit exactly at the limit.

    Most failures are well below it, so filling in the limit itself
    would understate every one of them.
    """
    assert truncated_mean(0.0) < 0.0
    assert truncated_mean(-10.0) < -10.0
    # Far above the mean the cut hides almost nothing.
    assert truncated_mean(40.0) == pytest.approx(0.0, abs=0.1)


def test_a_node_with_thin_evidence_is_not_used() -> None:
    """One chatty neighbour is one opinion, not forty."""
    many_from_one = [LinkObservation("!a", "!b", 5.0) for _ in range(40)]
    result = fit_offsets(many_from_one)
    for fit in result.nodes:
        assert fit.observations >= MIN_OBSERVATIONS
        assert fit.counterparties < MIN_COUNTERPARTIES
        assert not fit.is_usable
    assert result.usable() == {}


def test_a_node_with_enough_evidence_is_used() -> None:
    rng = np.random.default_rng(5)
    result = fit_offsets(_links({"!a": 3.0, "!b": 0.0, "!c": -3.0, "!d": 0.0}, rng, per_pair=4))
    usable = result.usable()
    assert set(usable) == {"!a", "!b", "!c", "!d"}


def test_a_node_the_offset_does_not_explain_says_so() -> None:
    """A large spread means the one number is not the whole story."""
    rng = np.random.default_rng(3)
    tidy = fit_offsets(_links({"!a": 2.0, "!b": 0.0, "!c": -2.0}, rng, per_pair=20, noise_db=0.5))
    messy = fit_offsets(_links({"!a": 2.0, "!b": 0.0, "!c": -2.0}, rng, per_pair=20, noise_db=12.0))
    assert max(fit.residual_spread_db for fit in tidy.nodes) < max(
        fit.residual_spread_db for fit in messy.nodes
    )


def test_no_measurements_is_a_working_state() -> None:
    """A new deployment has none. It must not be a fault."""
    result = fit_offsets([])
    assert result.nodes == []
    assert result.usable() == {}
    assert residual_summary([])["count"] == 0


def test_only_censored_measurements_do_not_raise() -> None:
    links = [LinkObservation("!a", "!b", -5.0, censored=True) for _ in range(4)]
    summary = residual_summary(links)
    assert summary["censored"] == 4
    fit_offsets(links)


def test_the_summary_says_how_far_the_model_is_out() -> None:
    """A mean far from zero is a model problem, not a node problem."""
    links = [LinkObservation("!a", "!b", 6.0), LinkObservation("!a", "!c", 4.0)]
    summary = residual_summary(links)
    assert summary["mean_db"] == pytest.approx(5.0)
    assert summary["count"] == 2


def test_a_fit_the_measurements_do_not_agree_about_is_not_applied() -> None:
    """Auto-adjustment must not adjust on noise.

    A wide scatter means one number for each node does not describe the
    mesh. The map must keep its nameplate figures rather than move on a
    fit of nothing. A database of made-up rows fits at over thirty dB.
    """
    rng = np.random.default_rng(11)
    noise = fit_offsets(
        _links({"!a": 0.0, "!b": 0.0, "!c": 0.0, "!d": 0.0}, rng, per_pair=30, noise_db=40.0)
    )
    assert noise.residual_spread_db > MAX_TRUSTED_SPREAD_DB
    assert not noise.is_trusted
    assert noise.usable() == {}, "no node may be corrected on a fit this wide"
    # The fit is still reported, so somebody can see why.
    assert noise.nodes


def test_a_fit_the_measurements_agree_about_is_applied() -> None:
    rng = np.random.default_rng(12)
    tidy = fit_offsets(
        _links({"!a": 4.0, "!b": 0.0, "!c": -4.0, "!d": 0.0}, rng, per_pair=30, noise_db=3.0)
    )
    assert tidy.is_trusted
    assert set(tidy.usable()) == {"!a", "!b", "!c", "!d"}


def test_the_scatter_is_measured_on_reported_links_only() -> None:
    """A filled in link was invented from the fit.

    Counting it would flatter the fit with its own guesses, and a fit
    made mostly of silence would always look tidy.
    """
    rng = np.random.default_rng(13)
    links = _links({"!a": 3.0, "!b": 0.0, "!c": -3.0}, rng, per_pair=30, noise_db=4.0, cut_db=0.0)
    assert any(item.censored for item in links)
    result = fit_offsets(links)
    assert result.residual_spread_db > 0.0


def test_a_node_whose_whole_case_is_silence_is_not_corrected() -> None:
    """Silence is evidence, but it must not be the only evidence.

    A node with nothing but silent links is being told it is worse than
    predicted with nothing to argue back. The silence may be a duty
    cycle, a collision, or a node that was switched off.
    """
    silent_only = [
        LinkObservation("!quiet", f"!peer{index}", -5.0, censored=True) for index in range(9)
    ]
    talking = [LinkObservation("!loud", f"!peer{index}", 2.0) for index in range(9)]
    result = fit_offsets(silent_only + talking)
    fits = {fit.node_id: fit for fit in result.nodes}

    assert fits["!quiet"].reported == 0
    assert not fits["!quiet"].is_usable
    assert "!quiet" not in result.usable()

    assert fits["!loud"].reported == 9
    assert fits["!loud"].is_usable
