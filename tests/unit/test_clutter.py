"""Tests for the terminal clutter loss.

The model is ITU-R P.2108-1 section 3.1, the height gain terminal
correction. It replaced the clutter the engine takes, which raises the
ground and therefore answers with a cliff: nothing at all while the
antenna clears the clutter, and forty to seventy dB once it does not.

`test_the_engine_clutter_is_a_cliff` in `test_coverage_engine.py`
measures that, so the reason this module exists is recorded as a
number and not only as a claim.
"""

import math
from itertools import pairwise

import pytest

from sonoran.coverage.clutter import STREET_WIDTH_M, loss_by_class, terminal_loss_db
from sonoran.coverage.params import DEFAULT_FREQUENCY_MHZ as FREQUENCY
from sonoran.landcover.classes import CLASSES

# --- the boundary the recommendation names ------------------------------


@pytest.mark.parametrize("height", [9.0, 9.1, 30.0, 1000.0])
def test_a_terminal_at_or_above_the_clutter_takes_nothing(height: float) -> None:
    """P.2108: "If h >= R then Ah = 0". An antenna above the roofs sees
    over them."""
    assert terminal_loss_db(9.0, height, FREQUENCY, True) == 0.0
    assert terminal_loss_db(9.0, height, FREQUENCY, False) == 0.0


def test_bare_ground_costs_nothing_at_any_height() -> None:
    """There is nothing to be under."""
    assert terminal_loss_db(0.0, 1.5, FREQUENCY, True) == 0.0
    assert terminal_loss_db(0.0, 1.5, FREQUENCY, False) == 0.0


# --- the two forms ------------------------------------------------------


def test_the_diffraction_form_matches_the_recommendation() -> None:
    """Worked by hand from P.2108-1 equations (1), (2a), (2c) to (2g).

    A 1.5 m handheld in 9 m built-up clutter at 906.875 MHz.
    """
    ghz = FREQUENCY / 1000.0
    h_dif = 9.0 - 1.5
    theta = math.degrees(math.atan(h_dif / STREET_WIDTH_M))
    nu = 0.342 * math.sqrt(ghz) * math.sqrt(h_dif * theta)
    shifted = nu - 0.1
    expected = 6.9 + 20.0 * math.log10(math.sqrt(shifted**2 + 1.0) + shifted) - 6.03

    assert terminal_loss_db(9.0, 1.5, FREQUENCY, True) == pytest.approx(expected, abs=1e-9)
    # And the figure that comes out, so a reader can see the size of it.
    assert terminal_loss_db(9.0, 1.5, FREQUENCY, True) == pytest.approx(17.74, abs=0.01)


def test_the_ground_form_matches_the_recommendation() -> None:
    """P.2108-1 equations (2b) and (2f). Open country, not buildings."""
    ghz = FREQUENCY / 1000.0
    k_h2 = 21.8 + 6.2 * math.log10(ghz)
    expected = -k_h2 * math.log10(1.5 / 2.0)

    assert terminal_loss_db(2.0, 1.5, FREQUENCY, False) == pytest.approx(expected, abs=1e-9)
    assert terminal_loss_db(2.0, 1.5, FREQUENCY, False) == pytest.approx(2.69, abs=0.01)


def test_a_building_costs_more_than_open_ground_of_the_same_height() -> None:
    """The two forms are not interchangeable. See P.2108 Table 3."""
    diffracting = terminal_loss_db(9.0, 1.5, FREQUENCY, True)
    ground = terminal_loss_db(9.0, 1.5, FREQUENCY, False)
    assert diffracting > ground > 0.0


# --- the shape ----------------------------------------------------------


def test_the_loss_is_a_curve_and_not_a_cliff() -> None:
    """The whole reason this module exists.

    The engine's own clutter charges nothing until the antenna drops
    below the clutter and then takes off sixty dB. A model has to move
    smoothly, or a node one metre shorter than its neighbour loses its
    whole footprint.
    """
    heights = [x / 4.0 for x in range(2, 37)]
    losses = [terminal_loss_db(9.0, h, FREQUENCY, True) for h in heights]

    # It never rises as the antenna rises.
    assert all(a >= b for a, b in pairwise(losses))
    # And no single quarter metre costs more than a couple of dB.
    steps = [a - b for a, b in pairwise(losses)]
    assert max(steps) < 2.0, "a step this large is a cliff"


def test_the_loss_is_bounded_by_something_a_radio_could_survive() -> None:
    """Every class, at the height the map is drawn for."""
    for cover in CLASSES.values():
        loss = terminal_loss_db(cover.clutter_height_m, 1.5, FREQUENCY, cover.diffracting)
        assert 0.0 <= loss < 40.0, cover.name


def test_a_taller_antenna_is_never_charged_more() -> None:
    for cover in CLASSES.values():
        low = terminal_loss_db(cover.clutter_height_m, 1.5, FREQUENCY, cover.diffracting)
        high = terminal_loss_db(cover.clutter_height_m, 12.0, FREQUENCY, cover.diffracting)
        assert high <= low, cover.name


# --- the lookup table ---------------------------------------------------


def test_the_table_answers_for_every_class() -> None:
    table = loss_by_class(1.5, FREQUENCY)
    assert len(table) == 256
    for code, cover in CLASSES.items():
        expected = terminal_loss_db(cover.clutter_height_m, 1.5, FREQUENCY, cover.diffracting)
        assert table[code] == round(expected), cover.name


def test_land_with_no_cover_data_is_charged_nothing() -> None:
    """A guess at clutter that is not there would move every prediction
    for no reason. The page says it has no clutter data instead."""
    assert loss_by_class(1.5, FREQUENCY)[0] == 0


def test_a_town_costs_the_handheld_more_than_scrub() -> None:
    """The finding this replaced: over Arizona, which is mostly scrub,
    the old rule charged nothing anywhere and the map said buildings
    were accounted for."""
    table = loss_by_class(1.5, FREQUENCY)
    assert table[50] > table[20] >= 0, "built-up must cost more than shrubland"
    assert table[10] > table[50], "tree cover is taller than a two storey street"
