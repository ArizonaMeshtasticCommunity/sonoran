"""Where a node is, for a map that draws other nodes beside it (beta-sonoran#412).

The packet page draws the sender and the gateways that uploaded it, and
the node page draws the neighbors a node reports. Both need a position
for nodes other than the one the page is about, and neither endpoint
carried one: #103 left the neighbor lines out for exactly that reason.

`resolve_places` is the one reading. It applies the same two rules the
node map already applies to the node itself:

* a position that is not a real place is no position
  (`sonoran.positions.is_usable`), so a node with no fix is left off the
  map rather than drawn in the ocean off West Africa;
* a position its owner rounded is `coarse` (`position_confidence`, with
  `MIN_SITE_PRECISION_BITS`), so the page can draw it hollow (#96).

These run against a stand-in session, as `test_neighbours_are_named.py`
does. The integration half is in `tests/integration/test_api.py`.
"""

from typing import Any

import pytest

from sonoran.api.places import resolve_places
from sonoran.positions import MIN_SITE_PRECISION_BITS

EXACT = 9801
ROUNDED = 9802
NO_FIX = 9803
NULL_ISLAND = 9804
NO_PRECISION_FIELD = 9805
BROADCAST = 0xFFFFFFFF


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    """Enough of an `AsyncSession` to answer one select on `node`."""

    def __init__(self, rows: list[tuple[int, float | None, float | None, int | None]]) -> None:
        self._rows = rows
        self.queries = 0

    async def execute(self, statement: Any) -> _Result:
        self.queries += 1
        return _Result(list(self._rows))


ROWS = [
    (EXACT, 33.4484, -112.074, 32),
    (ROUNDED, 33.45, -112.07, MIN_SITE_PRECISION_BITS - 3),
    (NO_FIX, None, None, None),
    (NULL_ISLAND, 0.0, 0.0, 32),
    (NO_PRECISION_FIELD, 33.5, -112.1, None),
]


@pytest.mark.asyncio
async def test_an_exact_position_is_returned_as_exact() -> None:
    places = await resolve_places(_Session(ROWS), [EXACT])
    assert places[EXACT] == {"lat": 33.4484, "lon": -112.074, "confidence": "exact"}


@pytest.mark.asyncio
async def test_a_rounded_position_says_it_is_rounded() -> None:
    """A rounded position is drawn hollow, so the page must be told."""
    places = await resolve_places(_Session(ROWS), [ROUNDED])
    assert places[ROUNDED]["confidence"] == "coarse", (
        "a position rounded below MIN_SITE_PRECISION_BITS came back as exact, "
        "so the map would draw it as a point it is not"
    )


@pytest.mark.asyncio
async def test_a_missing_precision_field_is_exact() -> None:
    """The ordinary case for a node heard over the radio (positions.py)."""
    places = await resolve_places(_Session(ROWS), [NO_PRECISION_FIELD])
    assert places[NO_PRECISION_FIELD]["confidence"] == "exact"


@pytest.mark.asyncio
async def test_a_node_with_no_real_position_is_left_out() -> None:
    """No fix, and the 0,0 a node with no fix often sends, are not places."""
    places = await resolve_places(_Session(ROWS), [NO_FIX, NULL_ISLAND])
    assert NO_FIX not in places, "a node with no position was given one"
    assert NULL_ISLAND not in places, "a node at 0,0 would be drawn off West Africa"


@pytest.mark.asyncio
async def test_nothing_to_place_asks_the_database_nothing() -> None:
    """The broadcast address and a missing number are not nodes."""
    session = _Session(ROWS)
    assert await resolve_places(session, [None, BROADCAST]) == {}
    assert session.queries == 0, "an empty lookup still queried the node table"


@pytest.mark.asyncio
async def test_only_the_nodes_asked_for_come_back() -> None:
    """The packet page sends every key it gets to the browser.

    The stand-in answers with every row whatever was asked, as a query
    that lost its filter would, so a node not asked for must still be
    left out.
    """
    places = await resolve_places(_Session(ROWS), [EXACT])
    assert set(places) == {EXACT}, f"nodes not asked for came back: {sorted(places)}"
