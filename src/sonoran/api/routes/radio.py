"""The hardware catalogues, as the pages need them (#111, #112).

The planner works out its link budget in the browser, so the antenna and
cable tables have to reach it. They are defined once in `sonoran.radio`
and served from here rather than copied into JavaScript: two tables of
sourced figures drifting apart is a worse failure than one HTTP call,
because neither copy would look wrong.

Static data with no database behind it. It changes when somebody edits
the catalogue and a deploy ships it, which is why the responses say they
may be cached for a day.
"""

from dataclasses import asdict

from fastapi import APIRouter, Response

from sonoran.radio.antennas import ANTENNAS, BAND_HIGH_MHZ, BAND_LOW_MHZ
from sonoran.radio.cables import CABLES, db_per_100ft

router = APIRouter(prefix="/api/radio", tags=["radio"])

# A day. The figures move when somebody reads a datasheet, not on a
# timer, and a stale antenna gain for an hour is not a problem worth a
# revalidation round trip on every planner load.
CACHE_SECONDS = 86400


@router.get("/antennas")
async def antennas(response: Response) -> dict[str, object]:
    """Return the antenna catalogue.

    `gain_dbi_claimed` is named as it is on purpose: every figure is the
    maker's claim read off a product page, not a measurement. Anything
    rendering it should say so.
    """
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return {
        "band_low_mhz": BAND_LOW_MHZ,
        "band_high_mhz": BAND_HIGH_MHZ,
        "antennas": [asdict(antenna) for antenna in ANTENNAS],
    }


@router.get("/cables")
async def cables(response: Response, frequency_mhz: float = 915.0) -> dict[str, object]:
    """Return the cable catalogue, with loss worked out at a frequency.

    The loss is computed here rather than in the browser so the maker's
    formula lives in one place. `frequency_mhz` defaults to the middle
    of the US band; the planner passes its own.
    """
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return {
        "frequency_mhz": frequency_mhz,
        "cables": [
            asdict(cable) | {"db_per_100ft": round(db_per_100ft(cable, frequency_mhz), 3)}
            for cable in CABLES
        ],
    }
