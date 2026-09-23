"""The 915 MHz antennas people on this mesh actually buy (#111).

A newcomer picking an antenna is choosing a gain figure they cannot
check and a radiation pattern nobody mentions. This is the catalogue
behind that choice.

**Every figure here is the maker's claim, copied from the product page,
with the page and the date it was read.** None of it is measured, and
the distinction matters: retail listings for this band are known for
optimistic numbers, for quoting dBd as though it were dBi (dBi = dBd +
2.15), and for a "gain" that assumes a ground plane the buyer will not
have. `gain_dbi_claimed` is named to say so. Nothing here should be
treated as a measurement, and the calibration job's figures beat all of
it.

The one number here that is not a headline is `vertical_beamwidth_deg`,
and it is the one that decides whether a high-gain antenna helps. Gain
on an omni is bought by flattening the pattern: the 10 dBi Backcountry
claims a **12-degree** vertical beamwidth against the 8 dBi's 25 and the
5.8 dBi's 35. On a rooftop in town that is free range. On a peak aiming
down into a valley it is a way to transmit past everybody -- which is
why `good_for` says so in words rather than leaving a buyer to infer it
from a number they have never seen before.

The prediction engine (SPLAT!) takes ONE gain value and assumes an
omnidirectional pattern. Every antenna here is an omni, which is why
they are here and Yagis and panels are not: adding a directional
antenna to this table without giving the engine an azimuth and a
beamwidth would draw a map that claims the antenna is aimed at every
point on it at once. That decision belongs in `docs/PLANNER.md` before
the first Yagi is added.

Stock antennas are not repeated here. `hardware.py` already models them
per board, and two tables disagreeing about the same antenna is worse
than one.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Antenna:
    """One antenna a person can buy, as its seller describes it."""

    key: str
    name: str
    maker: str
    # The maker's claim, not a measurement. See the module docstring.
    gain_dbi_claimed: float
    connector: str
    # stub | whip | gooseneck | fiberglass_omni
    kind: str
    frequency_low_mhz: float
    frequency_high_mhz: float
    outdoor: bool
    # Degrees. None where the listing does not state it.
    vertical_beamwidth_deg: float | None
    length_in: float | None
    # Plain English, for somebody who has never bought an antenna.
    good_for: str
    url: str
    checked: str
    # Anything about the figure a buyer should know. Empty when there is
    # nothing to say.
    caveat: str = ""


# Read from the product pages on the dates given. Re-read them before
# trusting a figure that matters: listings change without notice, and
# nothing here is a contract.
ANTENNAS: tuple[Antenna, ...] = (
    Antenna(
        key="meshtac-whip-2.5",
        name="MESHTAC 2.5 dBi soft flexible whip",
        maker="Rokland",
        gain_dbi_claimed=2.5,
        connector="SMA male",
        kind="whip",
        frequency_low_mhz=902,
        frequency_high_mhz=928,
        outdoor=False,
        vertical_beamwidth_deg=None,
        length_in=7.8,
        good_for="Carrying around. Bends without breaking, so it suits a handheld.",
        url="https://store.rokland.com/products/2-5-dbi-sma-male-915-mhz-soft-flexible-whip-antenna-for-t-beam-t-echo-other-lora",
        checked="2026-09-23",
        caveat=(
            "Listed as a dipole; close to the 2.15 dBi of a half-wave dipole, which is plausible."
        ),
    ),
    Antenna(
        key="meshtac-gooseneck-4",
        name="MESHTAC gooseneck tactical, 4 dBi",
        maker="Rokland",
        gain_dbi_claimed=4.0,
        connector="SMA male",
        kind="gooseneck",
        frequency_low_mhz=902,
        frequency_high_mhz=928,
        outdoor=False,
        vertical_beamwidth_deg=None,
        length_in=12.0,
        good_for="A portable node you want to stand up and aim upright.",
        url="https://store.rokland.com/products/meshtac-gooseneck-tactical-antenna-4-dbi-gain-sma-male-915-mhz-flexible-for-meshtastic-lora",
        checked="2026-09-23",
        caveat="The page gives the length as both 12 and 11.5 inches; 12 is used here.",
    ),
    Antenna(
        key="rokland-omni-5.8",
        name="5.8 dBi N-male omni, outdoor",
        maker="Rokland",
        gain_dbi_claimed=5.8,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=860,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=35.0,
        length_in=31.75,
        good_for="A first outdoor antenna. Forgiving: the widest pattern of the three omnis here.",
        url="https://store.rokland.com/products/5-8-dbi-n-male-omni-outdoor-915-mhz-antenna-large-profile-32-height-for-helium-rak-miner-2-nebra-indoor-bobcat",
        checked="2026-09-23",
        caveat=(
            "The listing gives a RANGE, '5.1 to 5.8 dBi'. The top of it is "
            "recorded here; assume the bottom."
        ),
    ),
    Antenna(
        key="rokland-omni-8",
        name="8 dBi low profile N-female omni, outdoor",
        maker="Rokland",
        gain_dbi_claimed=8.0,
        connector="N female",
        kind="fiberglass_omni",
        frequency_low_mhz=900,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=25.0,
        length_in=25.2,
        good_for="A rooftop in town, reaching out across flat ground.",
        url="https://store.rokland.com/products/8-dbi-omni-outdoor-915mhz-fiberglass-antenna-for-lora-halow-application",
        checked="2026-09-23",
        caveat=("N FEMALE, unlike the others here. Check which end your cable has."),
    ),
    Antenna(
        key="rokland-backcountry-10",
        name="10 dBi Backcountry Rural N-male omni, outdoor",
        maker="Rokland",
        gain_dbi_claimed=10.0,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=900,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=12.0,
        length_in=45.0,
        good_for=(
            "Flat open country, where everything you want to reach is near your own height. "
            "A poor choice on a peak: the pattern is 12 degrees tall and the valley is below it."
        ),
        url="https://store.rokland.com/products/10-dbi-backcountry-n-male-omni-outdoor-helium-915-mhz-antenna-48-for-rak-miner-2-nebra-indoor-bobcat-hotspots",
        checked="2026-09-23",
        caveat=(
            "The highest gain here and the narrowest pattern. More gain is not more range "
            "if the pattern misses what you are trying to reach."
        ),
    ),
)

BY_KEY: dict[str, Antenna] = {antenna.key: antenna for antenna in ANTENNAS}

# The band this mesh runs on, in MHz. An antenna that does not cover it
# is not a choice a picker should offer.
BAND_LOW_MHZ = 902.0
BAND_HIGH_MHZ = 928.0


def covers_the_band(antenna: Antenna) -> bool:
    """Return true when the antenna is tuned across 902-928 MHz."""
    return antenna.frequency_low_mhz <= BAND_LOW_MHZ and antenna.frequency_high_mhz >= BAND_HIGH_MHZ
