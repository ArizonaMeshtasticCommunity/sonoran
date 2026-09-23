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
    Cable,
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


def test_thicker_loses_less_within_one_construction() -> None:
    """Diameter predicts loss inside a family, and NOT across families.

    The first version of this compared every cable by diameter and broke
    the moment Belden's RG-8X was added: at 0.242 in it loses
    10.78 dB/100ft against LMR-240's 7.62 at 0.240 in. That is not a
    transcription error -- it is the point of LMR. Foam dielectric and a
    bonded foil shield beat braid at the same size.

    So the check is per maker, which is where the rule actually holds,
    and the cross-family comparison is recorded here as the thing a
    reader should not assume.
    """
    by_maker: dict[str, list[Cable]] = {}
    for cable in CABLES:
        by_maker.setdefault(cable.maker, []).append(cable)
    checked = 0
    for maker, family in by_maker.items():
        if len(family) < 2:
            continue
        checked += 1
        ordered = sorted(family, key=lambda c: c.outer_diameter_in)
        losses = [db_per_100ft(c, 915) for c in ordered]
        assert losses == sorted(losses, reverse=True), (
            f"{maker}: loss does not fall as the cable gets thicker: "
            f"{[(c.name, round(db_per_100ft(c, 915), 2)) for c in ordered]}"
        )
    assert checked >= 2, f"only {checked} families had enough cables to check"


def test_loss_rises_with_frequency() -> None:
    """True for anything with a formula OR a table.

    Only the one cable with neither is exempt, and it is named rather
    than detected, so adding a third source of figures fails here
    instead of quietly skipping.
    """
    for cable in CABLES:
        if not cable.k and not cable.m and not cable.table:
            assert cable.key == "lmr-195", f"{cable.key} has no figures to rise"
            continue
        assert db_per_100ft(cable, 450) < db_per_100ft(cable, 915) < db_per_100ft(cable, 1000)


def test_a_printed_table_is_interpolated_between_its_own_points() -> None:
    """Belden prints a table and no formula, so 915 MHz is between rows.

    #112 asks for exactly this -- "where a datasheet only gives 900 MHz
    and 1 GHz, interpolate, and record that you did".
    """
    cable = BY_KEY["belden-8259-rg58"]
    assert cable.table, "the table is gone, so this is measuring nothing"
    at_900 = db_per_100ft(cable, 900)
    at_1000 = db_per_100ft(cable, 1000)
    at_915 = db_per_100ft(cable, 915)
    assert at_900 == 21.1, "the printed 900 MHz row is not returned exactly"
    assert at_1000 == 22.8, "the printed 1000 MHz row is not returned exactly"
    assert at_900 < at_915 < at_1000, f"915 MHz fell outside its own rows: {at_915}"


def test_beyond_the_table_the_nearest_printed_row_is_used() -> None:
    """A datasheet says nothing about frequencies it does not list.

    Extrapolating past the last row would produce a number that looks
    exactly as sourced as the ones inside it.
    """
    cable = BY_KEY["belden-8259-rg58"]
    assert db_per_100ft(cable, 5000) == 22.8
    assert db_per_100ft(cable, 0.1) == 0.4


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
