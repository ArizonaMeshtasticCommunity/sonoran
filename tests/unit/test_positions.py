"""Tests for what counts as a usable position.

A node with no fix still sends a position packet, and the numbers in it
put the node in the Gulf of Guinea. This rule keeps it off the map.
"""

import pytest

from sonoran.positions import NULL_ISLAND_MARGIN, clean, is_usable


class TestRealPlaces:
    """Anywhere a node in this mesh could actually be."""

    def test_phoenix(self) -> None:
        assert is_usable(33.45, -112.07)

    def test_a_node_just_outside_the_state(self) -> None:
        """Being outside Arizona is not a fault.

        A node near San Diego reaches this mesh over MQTT. Its position
        is real and must be kept.
        """
        assert is_usable(32.8466432, -116.785152)

    @pytest.mark.parametrize(
        ("lat", "lon"),
        [(90.0, 180.0), (-90.0, -180.0), (0.0, 180.0), (90.0, 0.0)],
    )
    def test_the_edges_of_the_earth_are_allowed(self, lat: float, lon: float) -> None:
        assert is_usable(lat, lon)


class TestNullIsland:
    """A position that is not a place."""

    def test_exactly_zero(self) -> None:
        assert not is_usable(0.0, 0.0)

    def test_the_bit_pattern_seen_in_live_data(self) -> None:
        """0.0262144 is 262144 over ten million, and 262144 is 2 ** 18.

        One node reached the map at this position on both axes. It is a
        field that was never written, not a coordinate.
        """
        assert not is_usable(0.0262144, 0.0262144)

    def test_just_inside_the_margin(self) -> None:
        assert not is_usable(0.49, -0.49)

    def test_just_outside_the_margin(self) -> None:
        """The margin is small, so real places just past it are kept."""
        assert is_usable(NULL_ISLAND_MARGIN + 0.01, NULL_ISLAND_MARGIN + 0.01)


class TestOneAxisOnly:
    """Both axes must be near zero, not either."""

    def test_the_equator_is_a_real_place(self) -> None:
        """A node on the equator in Africa is not Null Island."""
        assert is_usable(0.0, 32.58)

    def test_the_greenwich_meridian_is_a_real_place(self) -> None:
        assert is_usable(51.48, 0.0)


class TestMissingAndImpossible:
    @pytest.mark.parametrize(("lat", "lon"), [(None, None), (33.4, None), (None, -112.0)])
    def test_missing_values(self, lat: float | None, lon: float | None) -> None:
        assert not is_usable(lat, lon)

    @pytest.mark.parametrize(
        ("lat", "lon"),
        [(91.0, 0.0), (-91.0, 0.0), (33.4, 181.0), (33.4, -181.0)],
    )
    def test_off_the_earth(self, lat: float, lon: float) -> None:
        """A corrupt field can hold anything, including an impossible one."""
        assert not is_usable(lat, lon)


class TestClean:
    def test_it_keeps_a_real_position(self) -> None:
        assert clean(33.45, -112.07) == (33.45, -112.07)

    def test_it_drops_both_halves_together(self) -> None:
        """Half a position is worse than none: it still draws a marker."""
        assert clean(0.0262144, 0.0262144) == (None, None)
        assert clean(33.45, None) == (None, None)


# --- how precise a position must be to anchor a prediction -------------


def test_an_unknown_precision_is_treated_as_exact() -> None:
    """The decision this whole rule turns on.

    `ingest/handlers/position.py` writes

        "precision_bits": position.precision_bits or None,

    so a node that sent no precision field and a node that sent zero
    both arrive as NULL. The first is the ordinary case for a node
    heard directly over the radio, and it is full precision. Reading
    NULL as coarse would delete every such node from the map.
    """
    from sonoran.positions import is_precise_enough

    assert is_precise_enough(None)
    assert is_precise_enough(0)


def test_a_position_the_public_broker_fuzzed_cannot_anchor_a_site() -> None:
    """Map reporting defaults to 14 bits, about 1459 m."""
    from sonoran.positions import is_precise_enough

    assert not is_precise_enough(14)
    assert not is_precise_enough(10)


def test_the_finest_the_public_broker_sends_is_the_limit() -> None:
    """Sixteen bits is about 365 m, which is four terrain cells."""
    from sonoran.positions import MIN_SITE_PRECISION_BITS, is_precise_enough

    assert MIN_SITE_PRECISION_BITS == 16
    assert is_precise_enough(16)
    assert is_precise_enough(32)


def test_the_deviation_grows_as_the_precision_falls() -> None:
    """Each bit doubles the doubt."""
    from sonoran.positions import precision_deviation_m

    assert precision_deviation_m(None) is None
    coarse = precision_deviation_m(10)
    fine = precision_deviation_m(16)
    assert coarse is not None and fine is not None
    assert coarse > fine > 0.0
    assert precision_deviation_m(32) == 0.0
    # The two figures the Meshtastic documentation names.
    assert precision_deviation_m(14) == 1459.0
    assert precision_deviation_m(16) == 364.7
