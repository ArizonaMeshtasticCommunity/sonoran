"""The antenna catalogue says where every figure came from (#111).

A newcomer picking an antenna is choosing a gain figure they cannot
check and a radiation pattern nobody mentions. The catalogue exists to
make both visible.

Every entry was read from the seller's product page on 2026-09-23 and
records the URL and the date. **None of it is measured.** Retail
listings in this band are known for optimistic numbers, for quoting dBd
as though it were dBi (dBi = dBd + 2.15), and for gain figures that
assume a ground plane the buyer will not have — which is why the field
is called `gain_dbi_claimed` and why these tests check the sourcing
rather than the values.

Two listings needed a caveat rather than a number, and both are the kind
of thing that gets quietly rounded away:

* the "5.8 dBi" omni's page actually says **"5.1 to 5.8 dBi"**
* the gooseneck's page gives its length as both 12 and 11.5 inches

The figure that decides whether a high-gain antenna helps is the
vertical beamwidth, not the gain: 12 degrees on the 10 dBi against 35 on
the 5.8. That is recorded, and said in words in `good_for`, because a
buyer who has never seen a radiation pattern will read "10 dBi" as
"best".
"""

import re

from sonoran.radio.antennas import (
    ANTENNAS,
    BAND_HIGH_MHZ,
    BAND_LOW_MHZ,
    BY_KEY,
    Antenna,
    covers_the_band,
)

# Anything selectable in a picker has to be one of these, because the
# prediction engine treats them all as omnidirectional.
OMNI_KINDS = {"stub", "whip", "gooseneck", "fiberglass_omni", "mobile_whip"}
DIRECTIONAL_KINDS = {"yagi"}
KINDS = OMNI_KINDS | DIRECTIONAL_KINDS


def test_there_is_a_catalogue_at_all() -> None:
    """The control: every test below is satisfied by an empty tuple."""
    assert len(ANTENNAS) >= 5, f"only {len(ANTENNAS)} antennas"


def test_every_figure_names_its_source_and_its_date() -> None:
    """A gain with no source is a rumour."""
    for antenna in ANTENNAS:
        assert antenna.url.startswith("https://"), f"{antenna.key} has no product link"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", antenna.checked), (
            f"{antenna.key} does not say when it was read: {antenna.checked!r}"
        )


def test_the_gain_field_says_it_is_a_claim() -> None:
    """Naming matters here more than usual.

    A field called `gain_dbi` invites somebody to treat a retailer's
    number as a measurement.
    """
    assert "gain_dbi_claimed" in Antenna.__dataclass_fields__
    assert "gain_dbi" not in Antenna.__dataclass_fields__


def test_no_gain_is_beyond_what_an_omni_can_do() -> None:
    """A bound, not a validation.

    A 915 MHz omni above ~12 dBi is either a stacked array the size of a
    person or a number that includes a ground plane the buyer will not
    have. Either way it should not enter the table unexamined.
    """
    for antenna in ANTENNAS:
        assert antenna.gain_dbi_claimed > 0.0, f"{antenna.key} claims no gain"
        ceiling = 12.0 if antenna.directional else 10.0
        assert antenna.gain_dbi_claimed <= ceiling, (
            f"{antenna.key} claims {antenna.gain_dbi_claimed} dBi, above the {ceiling} "
            f"expected of a {'directional' if antenna.directional else 'omnidirectional'} "
            f"antenna in this band"
        )


def test_every_antenna_covers_the_band_this_mesh_uses() -> None:
    """An antenna tuned elsewhere is not a choice worth offering."""
    for antenna in ANTENNAS:
        assert covers_the_band(antenna), (
            f"{antenna.key} covers {antenna.frequency_low_mhz}-"
            f"{antenna.frequency_high_mhz} MHz, not {BAND_LOW_MHZ}-{BAND_HIGH_MHZ}"
        )


def test_the_high_gain_omnis_record_their_beamwidth() -> None:
    """The number that decides whether the gain helps.

    Gain on an omni is bought by flattening the pattern. An entry above
    5 dBi without a beamwidth is the half of the story that sells the
    antenna and not the half that predicts it.
    """
    for antenna in ANTENNAS:
        if antenna.gain_dbi_claimed <= 5.0 or antenna.vertical_beamwidth_deg is not None:
            continue
        # Several real listings give a gain and no pattern at all. The
        # rule cannot be "state it" without inviting somebody to invent
        # a plausible number, which is worse than the gap. So the rule
        # is that the gap is declared where the buyer will see it.
        assert "PATTERN" in antenna.caveat.upper() or "BEAMWIDTH" in antenna.caveat.upper(), (
            f"{antenna.key} claims {antenna.gain_dbi_claimed} dBi, states no pattern, and "
            f"its caveat does not say so: {antenna.caveat!r}"
        )


def test_more_gain_means_a_narrower_pattern() -> None:
    """A sanity check on the physics, and on the transcription.

    Among the entries that state both, the ordering must hold: if a
    higher-gain omni claims a WIDER pattern, one of the two numbers was
    copied wrong.
    """
    stated = [a for a in ANTENNAS if a.vertical_beamwidth_deg is not None and not a.directional]
    # Compared pairwise rather than by sorting the list. Sorting made the
    # result depend on the ORDER of the catalogue wherever two antennas
    # claim the same gain -- two 8 dBi omnis with 15 and 25 degree
    # patterns both exist here, and a stable sort would have passed or
    # failed on which was typed first. Equal gain carries no claim.
    for a in stated:
        for b in stated:
            if a.gain_dbi_claimed <= b.gain_dbi_claimed:
                continue
            assert a.vertical_beamwidth_deg <= b.vertical_beamwidth_deg, (
                f"{a.key} claims more gain than {b.key} "
                f"({a.gain_dbi_claimed} vs {b.gain_dbi_claimed} dBi) and a WIDER pattern "
                f"({a.vertical_beamwidth_deg} vs {b.vertical_beamwidth_deg} deg); "
                f"one of those four numbers was copied wrong"
            )


def test_every_antenna_is_explained_in_words() -> None:
    """The catalogue is for somebody who has not bought one before."""
    for antenna in ANTENNAS:
        assert len(antenna.good_for) > 20, f"{antenna.key} has no plain-English note"


def test_every_kind_is_known_and_says_whether_it_must_be_aimed() -> None:
    """The engine takes one gain and no direction of its own.

    This test used to forbid Yagis outright, because one in this table
    would have drawn a map claiming the antenna was aimed at every point
    on it at once. Directional antennas are now supported, so the rule
    became the one that keeps that safe: a kind that must be aimed has
    to SAY so, because everything downstream -- the bearing box in the
    planner, the pattern applied to the raster -- switches on that flag
    and not on the kind string.
    """
    for antenna in ANTENNAS:
        assert antenna.kind in KINDS, f"{antenna.key} is a {antenna.kind}"
        expected = antenna.kind in DIRECTIONAL_KINDS
        assert antenna.directional is expected, (
            f"{antenna.key} is a {antenna.kind} but directional={antenna.directional}"
        )


def test_the_keys_are_unique_and_usable_in_a_form() -> None:
    assert len(BY_KEY) == len(ANTENNAS), "two antennas share a key"
    for key in BY_KEY:
        assert re.fullmatch(r"[a-z0-9.-]+", key), f"{key!r} is not form-safe"
