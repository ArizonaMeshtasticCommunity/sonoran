"""Coax loss computed from the makers' own coefficients (#112).

The planner has one "Cable loss (dB)" box and a newcomer has no way to
know what to put in it. The difference is not small: at 915 MHz, 30 ft
of LMR-400 is **1.18 dB** and the same run of LMR-195 is **3.33 dB**.

Every figure came off the manufacturer's datasheet, with the link and
the date recorded. That mattered more than usual here. A web search for
these numbers returned:

    LMR-195  "~3.5 dB per 100 ft"    datasheet: 11.1
    LMR-240  "~2.2 dB per 100 ft"    datasheet:  7.6

Both wrong by about three times, in the direction that makes a link look
workable when it is not. #112 asked for datasheets and not forum posts,
and this is why.

Loss is computed rather than looked up, from the formula Times Microwave
prints beside each table:

    dB per 100 ft = k * sqrt(f_MHz) + m * f_MHz

so the planner can ask at its own frequency instead of assuming 915.
"""

import math

import pytest

from sonoran.radio.cables import (
    BY_KEY,
    CABLES,
    FEET_PER_METRE,
    db_per_100ft,
    loss_db,
)

# The printed tables, transcribed from the datasheet pages read on
# 2026-09-23. These are the check on the coefficients, not decoration.
PRINTED: dict[str, dict[int, float]] = {
    "lmr-240": {
        30: 1.3,
        50: 1.7,
        150: 3.0,
        220: 3.7,
        450: 5.3,
        900: 7.6,
        1500: 9.9,
        1800: 10.9,
        2000: 11.5,
        2500: 12.9,
    },
    "lmr-400": {
        30: 0.7,
        50: 0.9,
        150: 1.5,
        220: 1.9,
        450: 2.7,
        900: 3.9,
        1500: 5.1,
        1800: 5.7,
        2000: 6.0,
        2500: 6.8,
    },
}


@pytest.mark.parametrize("key", sorted(PRINTED))
def test_the_formula_reproduces_the_table_it_came_from(key: str) -> None:
    """The coefficients and the table are on the same datasheet page.

    If they disagree, one of the two was transcribed wrong — which is
    the realistic failure here, not the physics.
    """
    cable = BY_KEY[key]
    for frequency, printed in PRINTED[key].items():
        computed = db_per_100ft(cable, frequency)
        assert abs(computed - printed) < 0.05, (
            f"{cable.name} at {frequency} MHz: formula gives {computed:.3f}, "
            f"its own datasheet table prints {printed}"
        )


def test_every_cable_records_where_its_figures_came_from() -> None:
    for cable in CABLES:
        assert cable.url.startswith("https://"), f"{cable.key} has no datasheet link"
        assert cable.checked, f"{cable.key} does not say when it was read"


def test_the_ordering_that_makes_the_catalogue_useful() -> None:
    """Thicker cable loses less. If that inverts, a figure is wrong."""
    ordered = sorted(CABLES, key=lambda c: c.outer_diameter_in)
    losses = [db_per_100ft(c, 915) for c in ordered]
    assert losses == sorted(losses, reverse=True), (
        f"loss does not fall as the cable gets thicker: "
        f"{[(c.name, round(db_per_100ft(c, 915), 2)) for c in ordered]}"
    )


def test_loss_rises_with_frequency() -> None:
    for cable in CABLES:
        if cable.k == 0.0 and cable.m == 0.0:
            continue  # flat by design; see the next test
        assert db_per_100ft(cable, 450) < db_per_100ft(cable, 915) < db_per_100ft(cable, 2400)


def test_a_cable_with_no_printed_formula_stays_flat_rather_than_guessing() -> None:
    """LMR-195's datasheet page gave the table and no formula.

    A curve fitted through one point would be indistinguishable from a
    sourced one, so it returns the printed 900 MHz figure at every
    frequency instead.
    """
    cable = BY_KEY["lmr-195"]
    assert cable.k == 0.0 and cable.m == 0.0
    assert db_per_100ft(cable, 450) == db_per_100ft(cable, 2400) == 11.1


def test_a_run_of_no_length_costs_nothing() -> None:
    for cable in CABLES:
        assert loss_db(cable, 0, 915) == 0.0
        assert loss_db(cable, -1, 915) == 0.0


def test_the_worked_example_in_the_docstring_holds() -> None:
    """30 ft, the length the planner's prose talks about."""
    thirty_feet_m = 30 / FEET_PER_METRE
    assert loss_db(BY_KEY["lmr-400"], thirty_feet_m, 915) == pytest.approx(1.18, abs=0.02)
    assert loss_db(BY_KEY["lmr-195"], thirty_feet_m, 915) == pytest.approx(3.33, abs=0.02)


def test_the_formula_is_the_one_the_datasheets_print() -> None:
    """Guards the shape, not just the output."""
    cable = BY_KEY["lmr-400"]
    expected = cable.k * math.sqrt(915) + cable.m * 915
    assert db_per_100ft(cable, 915) == pytest.approx(expected)
