"""The hardware catalogues reach the browser from one place (#111, #112).

The planner works out its link budget client-side, so the antenna and
cable tables have to get to it. They are defined once in `sonoran.radio`
and served from `/api/radio/*` rather than copied into JavaScript: two
tables of sourced figures drifting apart is worse than one HTTP call,
because neither copy would look wrong.

Verified by calling the handlers directly (they touch no database):

    cables at 915 MHz
      LMR-195   11.1   dB/100ft
      LMR-240    7.625 dB/100ft
      LMR-400    3.937 dB/100ft
    Cache-Control: public, max-age=86400
    antennas: 5, band 902.0-928.0
"""

import asyncio

from starlette.responses import Response

from sonoran.api.routes.radio import CACHE_SECONDS, antennas, cables
from sonoran.radio.cables import BY_KEY, db_per_100ft


def _cables(frequency: float = 915.0) -> dict:
    return asyncio.run(cables(Response(), frequency))


def test_the_cable_loss_is_worked_out_at_the_frequency_asked_for() -> None:
    """#112 asks for the planner's frequency, not a fixed 915."""
    low = {c["key"]: c["db_per_100ft"] for c in _cables(450)["cables"]}
    high = {c["key"]: c["db_per_100ft"] for c in _cables(2400)["cables"]}
    assert low["lmr-400"] < high["lmr-400"], "loss does not rise with frequency"


def test_the_served_figures_match_the_catalogue() -> None:
    """The endpoint must not be a second, drifting copy."""
    for row in _cables(915)["cables"]:
        expected = round(db_per_100ft(BY_KEY[row["key"]], 915), 3)
        assert row["db_per_100ft"] == expected, f"{row['key']} disagrees with the catalogue"


def test_the_datasheet_link_survives_to_the_client() -> None:
    """A figure a reader cannot check is a rumour, wherever it is shown."""
    for row in _cables()["cables"]:
        assert row["url"].startswith("https://")
        assert row["checked"]


def test_the_antenna_gain_keeps_the_name_that_says_it_is_a_claim() -> None:
    body = asyncio.run(antennas(Response()))
    assert body["antennas"], "no antennas served"
    for row in body["antennas"]:
        assert "gain_dbi_claimed" in row, (
            "the served field is not named as a claim, so a client may "
            "render a retailer's number as a measurement"
        )


def test_both_responses_say_they_may_be_cached() -> None:
    """Static data behind a deploy. Revalidating on every planner load
    would be a round trip for something that changes when somebody reads
    a datasheet."""
    for call in (lambda r: cables(r, 915.0), antennas):
        response = Response()
        asyncio.run(call(response))
        assert response.headers["Cache-Control"] == f"public, max-age={CACHE_SECONDS}"
