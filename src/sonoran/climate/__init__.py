"""The radio climate of a place, from the Köppen-Geiger map (#239).

ITM takes a radio climate, and it changes the prediction. This package
answers "which climate, here" from a crop of the Beck et al. (2023)
Köppen-Geiger map that ships inside it, and the table in `koppen.py`.

A place the crop does not cover has no answer. The caller then uses
`FALLBACK_CLIMATE` and must say so: a lookup that is confidently wrong
is worse than a default that is openly a default.

This package must never touch the database. It has the same rule as
`decode`, `crypto`, `terrain` and `landcover`.
"""

from dataclasses import dataclass

from sonoran.climate.koppen import BY_CODE, FALLBACK_CLIMATE, KOPPEN, KoppenClass, koppen_class
from sonoran.climate.store import CELLS_PER_DEGREE, CROP, PAGE_BYTES, koppen_at, page

# What a reader is told the climate came from.
SOURCE = "Köppen-Geiger 1991-2020, Beck et al. (2023), CC BY 4.0"


@dataclass(frozen=True)
class ClimateAnswer:
    """The radio climate for one place, and where it came from."""

    climate: str
    # None when the place has no class and the fallback was used.
    koppen: KoppenClass | None

    @property
    def known(self) -> bool:
        """Return true when the climate came from the map."""
        return self.koppen is not None

    def describe(self) -> str:
        """Return a short line that says where the climate came from."""
        if self.koppen is None:
            return f"not known here, using {FALLBACK_CLIMATE}"
        return f"Köppen {self.koppen.symbol}, from {SOURCE}"


def climate_at(latitude: float, longitude: float) -> ClimateAnswer:
    """Return the ITM radio climate for a place.

    Outside the crop, and where the map has no class, this returns
    `FALLBACK_CLIMATE` with `koppen` None. It never guesses a class.
    """
    found = koppen_class(koppen_at(latitude, longitude))
    if found is None:
        return ClimateAnswer(FALLBACK_CLIMATE, None)
    return ClimateAnswer(found.climate, found)


__all__ = [
    "BY_CODE",
    "CELLS_PER_DEGREE",
    "CROP",
    "FALLBACK_CLIMATE",
    "KOPPEN",
    "PAGE_BYTES",
    "SOURCE",
    "ClimateAnswer",
    "KoppenClass",
    "climate_at",
    "koppen_at",
    "page",
]
