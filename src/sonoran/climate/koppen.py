"""The Köppen-Geiger classes, and the ITM radio climate each one is given.

ITM (Longley-Rice) takes one of seven radio climates. They come from the
CCIR, and each is named after the place that typifies it. NTIA Report
TR-82-100 (Hufford, Longley and Kissick, 1982), Table 4:

    1  Equatorial (Congo)
    2  Continental Subtropical (Sudan)
    3  Maritime Subtropical (West Coast of Africa)
    4  Desert (Sahara)
    5  Continental Temperate
    6  Maritime Temperate, over land (United Kingdom and continental west coasts)
    7  Maritime Temperate, over sea

The climate sets the curves of long-term variability in time. It does
not move the median loss. TR-82-100 section 5 says the climates "have
not been mapped out as various zones throughout the world", and that the
authors' "preference is to use the Continental Temperate climate unless
there are clear indications to choose another". It also says: "For
land-mobile services in the United States, the Continental Temperate
climate is nearly always chosen."

Köppen-Geiger is a map of temperature and rain. ITM's climates are not
on any map. So this table is a judgement for each class, and the rule
is the one TR-82-100 gives: continental temperate, unless the class is
a clear indication of another. The clear indications are:

- a dry class (B), which is the Sahara's own group: desert;
- a wet tropical class with no real dry season (Af, Am), which is the
  Congo's: equatorial;
- a tropical class with a long dry season (Aw), which is the savanna of
  the Sudan belt: continental subtropical.

**No class here is ever given a maritime climate.** The maritime
climates turn on "prevailing winds [that] carry moist maritime air
inland" (TR-82-100 section 5), and a Köppen class says nothing about
how far a place is from the sea: Csb is the coast of California and
also a mountain in the middle of Arizona. The shipped crop is inland
everywhere, so this costs nothing here. A deployment on a coast needs a
second input, distance to the sea, and must not reuse this table as it
stands.

Each class appears exactly once. `tests/unit/test_climate.py` pins it.
`docs/PLANNER.md` 4.3 holds the same table for a reader.
"""

from dataclasses import dataclass

# The climate when a place has no class. It is what the planner has
# always assumed, so a place outside the data predicts as it did before.
FALLBACK_CLIMATE = "desert"

# Reasons shared by a whole group. A class with its own judgement call
# has its own reason below.
_DRY = (
    "Köppen calls it dry: evaporation exceeds rain. That is the Sahara's "
    "group, which is ITM's desert type."
)
_TEMPERATE = (
    "TR-82-100 uses continental temperate unless there is a clear "
    "indication of another, and nearly always for land-mobile in the "
    "United States. Nothing in this class is such an indication."
)
_COLD = (
    "A large land mass with cold winters and warm summers. TR-82-100 "
    "describes continental temperate as 'extremes of temperature and "
    "pronounced diurnal and seasonal changes'."
)
_POLAR = (
    "The CCIR describes a polar climate but gives no curves for it, so "
    "ITM has none. TR-82-100's default, continental temperate, applies."
)


@dataclass(frozen=True)
class KoppenClass:
    """One Köppen-Geiger class, and the ITM climate it is given."""

    # The number in the source raster, from its `legend.txt`.
    code: int
    symbol: str
    name: str
    # A key of `coverage/params.py` CLIMATE_CODES.
    climate: str
    reason: str


KOPPEN: tuple[KoppenClass, ...] = (
    KoppenClass(
        1,
        "Af",
        "Tropical, rainforest",
        "equatorial",
        "Hot and wet all year. That is the Congo, ITM's equatorial type.",
    ),
    KoppenClass(
        2,
        "Am",
        "Tropical, monsoon",
        "equatorial",
        "Hot and wet with only a short dry season. Nearer the Congo than the Sudan.",
    ),
    KoppenClass(
        3,
        "Aw",
        "Tropical, savannah",
        "continental_subtropical",
        "Hot, with a long dry season. That is the savanna of the Sudan belt, "
        "ITM's continental subtropical type.",
    ),
    KoppenClass(4, "BWh", "Arid, desert, hot", "desert", _DRY + " Phoenix, Yuma."),
    KoppenClass(5, "BWk", "Arid, desert, cold", "desert", _DRY + " Winslow, Tuba City, Page."),
    KoppenClass(
        6,
        "BSh",
        "Arid, steppe, hot",
        "desert",
        "Judgement call. Steppe is dry, but less dry than desert, and the Sahel "
        "between the Sahara and the Sudan is BSh. Given desert because Köppen "
        "still calls it dry. Tucson airport is BSh.",
    ),
    KoppenClass(
        7,
        "BSk",
        "Arid, steppe, cold",
        "desert",
        "Judgement call. Cold steppe has the wide temperature swings of "
        "continental temperate and the dryness of desert. Given desert, "
        "because the dryness is what Köppen classifies it by. Holbrook, "
        "Sedona, Sierra Vista and Prescott airport are BSk.",
    ),
    KoppenClass(
        8,
        "Csa",
        "Temperate, dry summer, hot summer",
        "continental_temperate",
        "Judgement call. Mediterranean: the CCIR names it but ITM has no curves "
        "for it. On a coast it would be maritime, which Köppen cannot tell. "
        "Inland, as at Prescott, Payson, Show Low and Williams, it is "
        "continental temperate.",
    ),
    KoppenClass(
        9,
        "Csb",
        "Temperate, dry summer, warm summer",
        "continental_temperate",
        "Judgement call, as for Csa. Inland, continental temperate. Mount Lemmon is Csb.",
    ),
    KoppenClass(
        10,
        "Csc",
        "Temperate, dry summer, cold summer",
        "continental_temperate",
        "As for Csa. Not in the shipped crop.",
    ),
    KoppenClass(
        11,
        "Cwa",
        "Temperate, dry winter, hot summer",
        "continental_temperate",
        _TEMPERATE,
    ),
    KoppenClass(
        12,
        "Cwb",
        "Temperate, dry winter, warm summer",
        "continental_temperate",
        _TEMPERATE,
    ),
    KoppenClass(
        13,
        "Cwc",
        "Temperate, dry winter, cold summer",
        "continental_temperate",
        _TEMPERATE,
    ),
    KoppenClass(
        14,
        "Cfa",
        "Temperate, no dry season, hot summer",
        "continental_temperate",
        _TEMPERATE,
    ),
    KoppenClass(
        15,
        "Cfb",
        "Temperate, no dry season, warm summer",
        "continental_temperate",
        _TEMPERATE + " On a west coast it would be maritime, which Köppen cannot tell.",
    ),
    KoppenClass(
        16,
        "Cfc",
        "Temperate, no dry season, cold summer",
        "continental_temperate",
        _TEMPERATE,
    ),
    KoppenClass(17, "Dsa", "Cold, dry summer, hot summer", "continental_temperate", _COLD),
    KoppenClass(
        18,
        "Dsb",
        "Cold, dry summer, warm summer",
        "continental_temperate",
        _COLD + " Flagstaff, Alpine and Greer are Dsb.",
    ),
    KoppenClass(19, "Dsc", "Cold, dry summer, cold summer", "continental_temperate", _COLD),
    KoppenClass(20, "Dsd", "Cold, dry summer, very cold winter", "continental_temperate", _COLD),
    KoppenClass(21, "Dwa", "Cold, dry winter, hot summer", "continental_temperate", _COLD),
    KoppenClass(22, "Dwb", "Cold, dry winter, warm summer", "continental_temperate", _COLD),
    KoppenClass(23, "Dwc", "Cold, dry winter, cold summer", "continental_temperate", _COLD),
    KoppenClass(24, "Dwd", "Cold, dry winter, very cold winter", "continental_temperate", _COLD),
    KoppenClass(25, "Dfa", "Cold, no dry season, hot summer", "continental_temperate", _COLD),
    KoppenClass(
        26,
        "Dfb",
        "Cold, no dry season, warm summer",
        "continental_temperate",
        _COLD,
    ),
    KoppenClass(27, "Dfc", "Cold, no dry season, cold summer", "continental_temperate", _COLD),
    KoppenClass(
        28,
        "Dfd",
        "Cold, no dry season, very cold winter",
        "continental_temperate",
        _COLD,
    ),
    KoppenClass(29, "ET", "Polar, tundra", "continental_temperate", _POLAR),
    KoppenClass(30, "EF", "Polar, frost", "continental_temperate", _POLAR),
)

BY_CODE: dict[int, KoppenClass] = {item.code: item for item in KOPPEN}


def koppen_class(code: int | None) -> KoppenClass | None:
    """Return the class with this number, or None."""
    if code is None:
        return None
    return BY_CODE.get(code)
