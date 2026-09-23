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

import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Response

from sonoran.radio.adapters import ADAPTERS, UNSPECIFIED, total_loss_db
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


@router.get("/adapters")
async def adapters(response: Response) -> dict[str, object]:
    """Return the adapter catalogue, with the mismatch term included.

    `total_loss_db` is insertion plus mismatch, because a datasheet's
    insertion loss is only half of what an adapter costs and the half
    it leaves out is the one that grows on cheap parts.

    **`total_loss_db` is null for the unspecified adapter, and that
    null has to survive to the page.** An adapter nobody has published
    figures for costs an unknown amount; rendering it as 0, or as the
    catalogue average, would make a guess look like a measurement.
    """
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return {
        "adapters": [
            asdict(adapter) | {"total_loss_db": total_loss_db(adapter)}
            for adapter in (*ADAPTERS, UNSPECIFIED)
        ],
    }


# Snapshotted, not fetched. `tools/dev/board_catalogue.py` writes this
# from https://api.meshtastic.org/resource/deviceHardware, and #110 is
# explicit that the list must not be pulled at page load: a planner that
# stops working because somebody else's endpoint is down is worse than
# one whose board list is a week old.
_BOARDS = Path(__file__).resolve().parents[2] / "radio" / "boards.json"


@router.get("/boards")
async def boards(response: Response) -> dict[str, object]:
    """Return the boards the flasher offers, with what we know of their radios.

    **`profile_is_exact` is the field that matters.** 54 of the 117
    boards have a hand-written RF profile; the other 63 get a family
    rule, which reads the chipset from the name and assumes the rest.
    Both carry figures, because a picker showing nothing for two thirds
    of the catalogue would be less useful and no more honest than one
    that shows the rule's answer and says it is the rule's answer.

    Anything rendering this must pass that distinction on. A transmit
    power presented as fact when it was guessed from a board name is the
    kind of wrong that a coverage map makes look authoritative.
    """
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    rows = json.loads(_BOARDS.read_text(encoding="utf-8"))
    return {
        "source": "https://api.meshtastic.org/resource/deviceHardware",
        "exact": sum(1 for row in rows if row["profile_is_exact"]),
        "boards": rows,
    }
