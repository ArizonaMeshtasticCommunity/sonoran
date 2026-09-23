"""Adapter loss, from the makers' own datasheets (#112).

#112 asks whether "0.1 to 0.5 dB per adapter" is realistic. Four
Mini-Circuits parts, read on 2026-09-23, put a number on it:

    SM-SM50+   SMA-M to SMA-M   0.05 dB   DC-18 GHz typ.
    SF-SF50+   SMA-F to SMA-F   0.1 dB    DC-18 GHz typ.
    SF-SM50+   SMA-F to SMA-M   0.1 dB    DC-18 GHz typ.
    NM-SM50+   N-M to SMA-M     0.1 dB    DC-18 GHz typ.

So the bottom of the range is the published typical over the whole
band, and at 915 MHz -- the bottom five per cent of it -- the true
figure is under that. The top of the range, 0.5 dB, is five times a
good adapter's whole-band typical.

I had recorded this as unsourceable. That was a statement about the
four pages I happened to try, all of which either refused an automated
fetch or published VSWR with no insertion loss. It read as a fact about
the world.
"""

import math

import pytest

from sonoran.radio.adapters import (
    ADAPTERS,
    BY_KEY,
    UNSPECIFIED,
    mismatch_loss_db,
    total_loss_db,
)


def test_every_adapter_says_where_its_figure_came_from() -> None:
    for adapter in ADAPTERS:
        assert adapter.url.startswith("https://"), f"{adapter.key} has no datasheet link"
        assert adapter.checked, f"{adapter.key} does not say when it was read"
        assert adapter.insertion_loss_db is not None, f"{adapter.key} carries no figure"


def test_the_published_figures_answer_the_question_the_issue_asked() -> None:
    """#112's range is right at the bottom and wrong at the top.

    This is the finding, held as a test so that editing the catalogue
    down to something that no longer supports it fails here.
    """
    published = [a.insertion_loss_db for a in ADAPTERS if a.insertion_loss_db is not None]
    assert max(published) <= 0.1, (
        f"an adapter in the catalogue now claims more than 0.1 dB "
        f"({max(published)}), which would change the answer to #112"
    )
    assert min(published) < 0.1, "no adapter beats the top of the range, so it is not a range"


def test_the_mismatch_arithmetic_is_the_standard_one() -> None:
    """Checked against the closed form rather than a remembered table."""
    for vswr in (1.05, 1.12, 1.3, 1.5, 2.0, 3.0):
        reflection = (vswr - 1) / (vswr + 1)
        expected = -10 * math.log10(1 - reflection**2)
        assert mismatch_loss_db(vswr) == pytest.approx(expected)


def test_a_perfect_match_costs_nothing_and_an_impossible_one_does_not_raise() -> None:
    assert mismatch_loss_db(1.0) == 0.0
    assert mismatch_loss_db(0.5) == 0.0


def test_when_the_mismatch_dominates_and_when_it_does_not() -> None:
    """The claim in `cables.py` was half right, so it is pinned here.

    "On cheap adapters the mismatch loss dominates the insertion loss"
    is true of a poor part and false of a good one. The crossover is
    around VSWR 1.25 against a 0.05 dB insertion loss.
    """
    good = BY_KEY["minicircuits-sm-sm50"]
    assert good.vswr is not None
    assert mismatch_loss_db(good.vswr) < good.insertion_loss_db, (
        "the best adapter in the catalogue now loses more to mismatch than "
        "to insertion, which would make the note in cables.py unqualified"
    )
    # A poor adapter, of the kind that comes in a bag with no paperwork.
    assert mismatch_loss_db(1.5) > 3 * 0.05


def test_an_adapter_nobody_has_measured_carries_no_number() -> None:
    """The most dangerous default this file could have is 0.1.

    An unknown part would look measured, and unknown parts are exactly
    the ones whose VSWR is worst. None has to survive all the way out.
    """
    assert UNSPECIFIED.insertion_loss_db is None
    assert total_loss_db(UNSPECIFIED) is None
    assert UNSPECIFIED not in ADAPTERS, "the unmeasured adapter is in the sourced catalogue"


def test_the_total_is_both_halves_and_not_just_the_published_one() -> None:
    adapter = BY_KEY["minicircuits-sm-sm50"]
    assert adapter.vswr is not None
    total = total_loss_db(adapter)
    assert total is not None
    assert total == pytest.approx(adapter.insertion_loss_db + mismatch_loss_db(adapter.vswr))
    assert total > adapter.insertion_loss_db, "the mismatch term vanished"


def test_an_adapter_with_no_published_vswr_is_not_charged_a_made_up_one() -> None:
    adapter = BY_KEY["minicircuits-sf-sf50"]
    assert adapter.vswr is None
    assert total_loss_db(adapter) == adapter.insertion_loss_db


def test_three_adapters_cost_about_as_much_as_a_length_of_cable() -> None:
    """What a planner should take from this, in units it already has.

    I guessed the wrong way round writing this test: I assumed three
    adapters would be lost in the noise against a foot of RG-58, and
    they are not. Measured at 915 MHz, three N-to-SMA adapters cost
    0.300 dB, which is

        1.4 ft of RG-58        3.9 ft of LMR-240        7.6 ft of LMR-400

    so on a good cable they are worth about two metres of run, and on a
    bad one about half a metre. Small, but not nothing, and the better
    the cable the more the adapters matter in proportion -- which is
    the opposite of the intuition that says a good cable makes the rest
    irrelevant.
    """
    from sonoran.radio.cables import BY_KEY as CABLE
    from sonoran.radio.cables import db_per_100ft

    three = 3 * (total_loss_db(BY_KEY["minicircuits-nm-sm50"]) or 0.0)
    assert three == pytest.approx(0.300, abs=0.001)
    equivalent = {
        key: three / (db_per_100ft(CABLE[key], 915) / 100)
        for key in ("belden-8259-rg58", "lmr-240", "lmr-400")
    }
    assert equivalent["belden-8259-rg58"] == pytest.approx(1.4, abs=0.1)
    assert equivalent["lmr-240"] == pytest.approx(3.9, abs=0.1)
    assert equivalent["lmr-400"] == pytest.approx(7.6, abs=0.1)
    assert equivalent["lmr-400"] > equivalent["belden-8259-rg58"], (
        "the better cable no longer makes the adapters matter more, which "
        "is the whole point of quoting it this way"
    )


# -------------------------------------------------------- the endpoint


def test_the_endpoint_serves_the_unmeasured_adapter_with_a_null() -> None:
    """The null is the point, so it is asserted rather than assumed.

    A page that renders `total_loss_db` has to be able to tell "we know
    this costs nothing measurable" from "nobody has said what this
    costs". If the endpoint substituted 0 here, both would render as
    0 and the distinction would be gone before the browser saw it.
    """
    from fastapi.testclient import TestClient

    from sonoran.api.app import create_app
    from sonoran.config import Settings

    with TestClient(create_app(Settings(_env_file=None))) as client:
        body = client.get("/api/radio/adapters").json()

    rows = {row["key"]: row for row in body["adapters"]}
    assert rows, "the endpoint returned no adapters"
    # The control: a sourced adapter does carry a number, so a null
    # below means "unpublished" and not "the endpoint is broken".
    assert rows["minicircuits-sm-sm50"]["total_loss_db"] > 0
    assert rows["unspecified"]["total_loss_db"] is None
    assert rows["unspecified"]["insertion_loss_db"] is None


def test_the_endpoint_can_be_cached_like_the_other_catalogues() -> None:
    from fastapi.testclient import TestClient

    from sonoran.api.app import create_app
    from sonoran.config import Settings

    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/api/radio/adapters")
    assert "max-age=86400" in response.headers["cache-control"]
