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

Directional antennas
--------------------

This module used to say Yagis were excluded, because the engine takes
one gain and assumes the antenna radiates equally in every direction,
so a Yagi in this table would have drawn a map claiming it was aimed at
every point at once. **That is now implemented rather than avoided**:
a directional antenna carries `directional=True` and the azimuth it is
pointed at is asked for separately, per end, in the planner. The model
and its assumptions are written down in `docs/PLANNER.md`; read that
before adding another directional entry.

Two consequences worth knowing here:

* `horizontal_beamwidth_deg` may be **None even on a Yagi**. The L-Com
  listing states no beamwidth at all. A pattern cannot be drawn from a
  gain figure alone, so that entry is carried with the gap visible
  rather than filled in with a plausible number.
* The monotonic "more gain, narrower pattern" relation holds for omnis
  only. The 12 dBi Yagi claims a 32-degree vertical beamwidth, wider
  than the 10 dBi omni's 12, because a Yagi buys its gain in azimuth as
  well as elevation. Comparing the two as though they were the same
  kind of number is a mistake.

What is deliberately not here
-----------------------------

Rokland's 915 MHz collection also sells things that are not a planner
choice, and each is left out for a stated reason rather than an
oversight:

* the 2.4 GHz Bluetooth PCB antenna -- a different band entirely;
* the 915 MHz IPEX PCB antenna -- **no gain is stated anywhere on the
  listing**, and an entry whose whole purpose is to supply a gain
  cannot be built from a page that does not give one;
* coax, pigtails and RP-SMA/SMA adapters -- modelled in `cables.py` and
  `adapters.py`, where their loss belongs;
* the 5.8 dBi indoor "antenna kit" and the Heltec pigtail package --
  bundles of an antenna *and* a cable. Recording one as a single
  antenna would hide a cable whose loss the planner already counts
  separately, so it would be counted twice or not at all;
* the colour MESHTAC 2.5 dBi -- electrically the entry already here,
  sold in other colours.

Stock status is not recorded. It changes daily and a source file cannot
track it; several entries here were out of stock on the day they were
read and that says nothing about whether the figures are right.

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
    # stub | whip | gooseneck | fiberglass_omni | mobile_whip | yagi
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
    # True where the antenna has to be aimed. The planner then asks for
    # a bearing for that end; see `docs/PLANNER.md`.
    directional: bool = False
    # Degrees between the half-power points across the horizon. None on
    # an omni (it radiates all the way round) and also None on a
    # directional antenna whose listing does not state one -- those are
    # different facts, told apart by `directional`.
    horizontal_beamwidth_deg: float | None = None
    # How far down the pattern is behind the antenna, in dB. No listing
    # read so far states it, so this is None everywhere; the planner
    # applies a documented assumption instead of inventing one here.
    front_to_back_db: float | None = None


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
    # --- more Rokland omnis, read 2026-09-26 -----------------------
    Antenna(
        key="rokland-omni-6",
        name="6 dBi low profile N-female omni, outdoor",
        maker="Rokland",
        gain_dbi_claimed=6.0,
        connector="N female",
        kind="fiberglass_omni",
        frequency_low_mhz=900,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=35.0,
        length_in=21.6,
        good_for=(
            "A shorter outdoor omni with a little more gain than the 5.8, and the same "
            "forgiving pattern. A good compromise where a 32-inch mast is too much."
        ),
        url=(
            "https://store.rokland.com/products/low-profile-6-dbi-n-female-omni-outdoor-"
            "915-mhz-antenna-for-helium-rak-miner-2-nebra-indoor-syncrob-it-bobcat"
        ),
        checked="2026-09-26",
        caveat=(
            "N FEMALE. It claims the same 35-degree pattern as the 5.8 dBi with more gain, "
            "which is not how the trade-off usually works; treat the extra 0.2 dB as noise."
        ),
    ),
    Antenna(
        key="rokland-omni-4",
        name="4 dBi N-male fiberglass omni, outdoor",
        maker="Rokland",
        gain_dbi_claimed=4.0,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=698,
        frequency_high_mhz=960,
        outdoor=True,
        vertical_beamwidth_deg=45.0,
        length_in=13.5,
        good_for=(
            "The cheapest way to get an antenna outdoors and out of the building. "
            "The widest pattern here, so it is hard to aim wrong."
        ),
        url=(
            "https://store.rokland.com/products/4-dbi-helium-hotspot-fiberglass-outdoor-"
            "antenna-bracket-mount-for-rak-bobcat-nebra-sensecap"
        ),
        checked="2026-09-26",
        caveat=(
            "Tuned across 698-960 MHz. A very wide antenna is rarely as good as its "
            "headline figure anywhere in particular, including here."
        ),
    ),
    # --- other makers Rokland stocks -------------------------------
    Antenna(
        key="parley-omni-8",
        name="Parley Labs 8 dBi fiberglass omni, 36 inch",
        maker="Parley Labs",
        gain_dbi_claimed=8.0,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=860,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=15.0,
        length_in=36.0,
        good_for=(
            "Flat ground seen from a rooftop. Its pattern is much flatter than the other "
            "8 dBi here, so it reaches further out and sees less below itself."
        ),
        url=(
            "https://store.rokland.com/products/8-dbi-outdoor-fiberglass-antenna-us-868-"
            "915-mhz-for-meshtastic-helium-iot"
        ),
        checked="2026-09-26",
        caveat=(
            "15 degrees tall against 25 for Rokland's own 8 dBi. Two antennas claiming the "
            "same gain with different patterns are not interchangeable: this one is the "
            "worse choice on a hill."
        ),
    ),
    Antenna(
        key="parley-omni-3",
        name="Parley Labs PL-AT-3000 3 dBi fiberglass omni",
        maker="Parley Labs",
        gain_dbi_claimed=3.0,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=900,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=12.25,
        good_for=(
            "A small outdoor antenna tuned tightly to this band rather than spread across "
            "several. Sensible on a short mast where height matters more than gain."
        ),
        url=(
            "https://store.rokland.com/products/3-dbi-n-male-fiberglass-outdoor-antenna-"
            "bracket-mount-for-usa-900-930-mhz-parley-labs"
        ),
        checked="2026-09-26",
        caveat="DC grounded, which is worth having on a mast.",
    ),
    Antenna(
        key="rak-omni-8",
        name="RAKwireless 8 dBi outdoor fiberglass (PID 916001)",
        maker="RAKwireless",
        gain_dbi_claimed=8.0,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=900,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=35.4,
        good_for=(
            "A rooftop omni from the maker of a lot of the hardware on this mesh, with the "
            "tightest VSWR figure quoted for any antenna here."
        ),
        url=(
            "https://store.rokland.com/products/rakwireless-8-dbi-outdoor-fiberglass-"
            "helium-hotspot-antenna-us-868-915-mhz"
        ),
        checked="2026-09-26",
        caveat=(
            "NO PATTERN FIGURE. The listing states a 360-degree VERTICAL beamwidth, which "
            "is impossible for an 8 dBi omni -- that is the horizontal pattern under the "
            "wrong heading, so nothing is recorded. Expect something near the 25 degrees "
            "of the other 8 dBi antennas and do not rely on it."
        ),
    ),
    Antenna(
        key="rak-omni-5.8",
        name="RAKwireless 5.8 dBi outdoor fiberglass",
        maker="RAKwireless",
        gain_dbi_claimed=5.8,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=860,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=31.5,
        good_for=(
            "The RAK equivalent of the 5.8 dBi omni: a sound first outdoor antenna, sold "
            "in white or black."
        ),
        url=(
            "https://store.rokland.com/products/rak-wireless-5-8-dbi-outdoor-black-"
            "fiberglass-helium-hotspot-antenna"
        ),
        checked="2026-09-26",
        caveat=(
            "NO PATTERN FIGURE is given. The gain is a RANGE, '5.1 to 5.8 dBi'; the top is "
            "recorded, so assume the bottom. Rated for 20 W, the lowest here."
        ),
    ),
    Antenna(
        key="rak-omni-3",
        name="RAKwireless 3 dBi fiberglass omni (PID 915008)",
        maker="RAKwireless",
        gain_dbi_claimed=3.0,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=860,
        frequency_high_mhz=930,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=14.17,
        good_for=(
            "A short outdoor antenna with a bracket for a pole or a length of PVC. "
            "Modest gain, easy to mount."
        ),
        url=(
            "https://store.rokland.com/products/3-dbi-rak-brand-fiberglass-outdoor-"
            "antenna-bracket-mount-for-rak-bobcat-sensecap"
        ),
        checked="2026-09-26",
        caveat=(
            "VSWR is quoted at 2.5, the loosest figure in this table, so slightly more of "
            "your power comes back down the cable than with the others."
        ),
    ),
    Antenna(
        key="alfa-aoa-8696-3acm",
        name="ALFA AOA-8696-3ACM 3 dBi fiberglass omni",
        maker="ALFA Network",
        gain_dbi_claimed=3.0,
        connector="N male",
        kind="fiberglass_omni",
        frequency_low_mhz=868,
        frequency_high_mhz=960,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=23.6,
        good_for=(
            "A two-foot outdoor omni that will work on either the European or the US band, "
            "which suits somebody who may move it."
        ),
        url=(
            "https://store.rokland.com/products/3-dbi-n-male-alfa-fiberglass-outdoor-"
            "antenna-bracket-mount-for-usa-eu-868-960-mhz-rak-bobcat-sensecap"
        ),
        checked="2026-09-26",
        caveat="DC grounded. Pole mount for 30-50 mm.",
    ),
    Antenna(
        key="alfa-aoa-915-5acm",
        name="ALFA AOA-915-5ACM 5 dBi mini omni",
        maker="ALFA Network",
        gain_dbi_claimed=5.0,
        connector="N male",
        kind="stub",
        frequency_low_mhz=902,
        frequency_high_mhz=928,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=7.1,
        good_for=(
            "Seven inches long and weatherproof. The obvious choice where a mast is out of "
            "the question but the node still lives outside."
        ),
        url=(
            "https://store.rokland.com/products/alfa-aoa-915-5acm-5-dbi-omni-outdoor-"
            "915mhz-802-11ah-mini-antenna-for-lora-halow-application"
        ),
        checked="2026-09-26",
        caveat=(
            "Tuned to exactly 902-928 MHz -- this band and nothing else, which is a point "
            "in its favour against the wideband antennas here."
        ),
    ),
    Antenna(
        key="alfa-aoa-915-2acm",
        name="ALFA AOA-915-2ACM 2 dBi mini omni",
        maker="ALFA Network",
        gain_dbi_claimed=2.0,
        connector="N male",
        kind="stub",
        frequency_low_mhz=902,
        frequency_high_mhz=928,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=2.5,
        good_for=(
            "A two-and-a-half-inch stub for a node that has to stay small and still sit "
            "outdoors. Barely more than the dipole it replaces."
        ),
        url=(
            "https://store.rokland.com/products/alfa-aoa-915-2acm-2-dbi-omni-915mhz-802-"
            "11ah-mini-lora-antenna-meshtastic-n-male"
        ),
        checked="2026-09-26",
        caveat="Band-tuned to 902-928 MHz.",
    ),
    Antenna(
        key="rokland-wave-3.5",
        name="Rokland Wave 3.5 dBi NMO mobile whip",
        maker="Rokland",
        gain_dbi_claimed=3.5,
        connector="NMO",
        kind="mobile_whip",
        frequency_low_mhz=896,
        frequency_high_mhz=970,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=8.6,
        good_for=(
            "A vehicle. The NMO form factor is what mobile radio has used for decades and "
            "it survives a car wash."
        ),
        url=(
            "https://store.rokland.com/products/rokland-wave-antenna-896-970mhz-3-5-dbi-"
            "gain-220mm-8-6-inch-straight-whip"
        ),
        checked="2026-09-26",
        caveat=(
            "The element ONLY: an NMO mount is needed and is not included. Its gain assumes "
            "a metal roof acting as the ground plane, so on anything else expect less."
        ),
    ),
    Antenna(
        key="rak-blade-2.3",
        name="RAKwireless Blade 2.3 dBi (PID 926019)",
        maker="RAKwireless",
        gain_dbi_claimed=2.3,
        connector="RP-SMA male",
        kind="whip",
        frequency_low_mhz=902,
        frequency_high_mhz=928,
        outdoor=False,
        vertical_beamwidth_deg=None,
        length_in=None,
        good_for=(
            "The flat indoor antenna that ships with RAK gateways. Unobtrusive, and better "
            "than the stub on many boards."
        ),
        url="https://store.rokland.com/products/blade-antenna",
        checked="2026-09-26",
        caveat=(
            "The listing gives only '915 MHz', not a range; the figures here are the US "
            "band it is sold for, NOT a span read off the page. No length is stated."
        ),
    ),
    Antenna(
        key="heltec-whip-2",
        name="Heltec 2 dBi omnidirectional whip",
        maker="Heltec",
        gain_dbi_claimed=2.0,
        connector="SMA male",
        kind="whip",
        frequency_low_mhz=863,
        frequency_high_mhz=928,
        outdoor=False,
        vertical_beamwidth_deg=None,
        length_in=6.6,
        good_for=(
            "The replacement whip for a Heltec board whose own antenna has been lost or "
            "broken. Nothing more, and nothing less."
        ),
        url="https://store.rokland.com/products/heltec-omnidirectional-whip-antenna-868-915-mhz",
        checked="2026-09-26",
        caveat=(
            "The gain is given as a range, 1.76 to 2.39 dBi; 2 is recorded. Rated to 10 W "
            "only, which is far above anything Meshtastic transmits."
        ),
    ),
    Antenna(
        key="alfa-ars-9096rp-5",
        name="ALFA ARS-9096RP 5 dBi indoor dipole, 90-degree elbow",
        maker="ALFA Network",
        gain_dbi_claimed=5.0,
        connector="RP-SMA male",
        kind="whip",
        frequency_low_mhz=900,
        frequency_high_mhz=960,
        outdoor=False,
        vertical_beamwidth_deg=None,
        length_in=17.0,
        good_for=(
            "An indoor gateway on a shelf. The elbow lets a 17-inch antenna stand upright "
            "out of a socket that points sideways."
        ),
        url=(
            "https://store.rokland.com/products/alfa-network-ars-9096rp-5-dbi-indoor-"
            "antenna-for-helium-hotspots"
        ),
        checked="2026-09-26",
        caveat=(
            "RP-SMA, the reverse-polarity connector. It will not mate with the plain SMA "
            "on most Meshtastic boards without an adapter."
        ),
    ),
    Antenna(
        key="alfa-ars-915p-2",
        name="ALFA ARS-915P 2 dBi whip, 90-degree elbow (SMA)",
        maker="ALFA Network",
        gain_dbi_claimed=2.0,
        connector="SMA male",
        kind="whip",
        frequency_low_mhz=902,
        frequency_high_mhz=928,
        outdoor=False,
        vertical_beamwidth_deg=None,
        length_in=7.7,
        good_for=(
            "A T-Beam or LoRa32 that has to lie flat. The elbow turns the antenna upright "
            "without stressing the socket."
        ),
        url=(
            "https://store.rokland.com/products/alfa-network-ars-915pr-2-dbi-sma-male-915-"
            "mhz-antenna-with-90-elbow-for-t-beam-t-echo-lora32"
        ),
        checked="2026-09-26",
        caveat=(
            "The spec table says 902-928 MHz while the description says 900-930; the table "
            "is recorded. Plain SMA, unlike its RP-SMA twin below."
        ),
    ),
    Antenna(
        key="alfa-ars-915pr-2",
        name="ALFA ARS-915PR 2 dBi whip, 90-degree elbow (RP-SMA)",
        maker="ALFA Network",
        gain_dbi_claimed=2.0,
        connector="RP-SMA male",
        kind="whip",
        frequency_low_mhz=900,
        frequency_high_mhz=960,
        outdoor=False,
        vertical_beamwidth_deg=None,
        length_in=7.7,
        good_for=(
            "The same antenna as the ARS-915P for a hotspot with an RP-SMA socket, which "
            "most Helium-era hardware has."
        ),
        url=(
            "https://store.rokland.com/products/alfa-network-ars-915pr-2-dbi-helium-miner-"
            "hotspot-replacement-antenna-with-90-elbow-for-rak-bobcat-sensecap-m1"
        ),
        checked="2026-09-26",
        caveat=(
            "RP-SMA. Identical in gain to the SMA version, so the only question is which "
            "socket your radio has -- get this wrong and nothing screws together."
        ),
    ),
    # --- directional. Read docs/PLANNER.md before adding more. -----
    Antenna(
        key="alfa-aya-9012-12",
        name="ALFA AYA-9012 12 dBi Yagi, directional",
        maker="ALFA Network",
        gain_dbi_claimed=12.0,
        connector="N female",
        kind="yagi",
        frequency_low_mhz=824,
        frequency_high_mhz=960,
        outdoor=True,
        vertical_beamwidth_deg=32.0,
        length_in=None,
        good_for=(
            "One link you already know the direction of: a distant repeater, or a valley "
            "you want to reach past everything else. It hears almost nothing behind it, "
            "which is the point and also the risk."
        ),
        url=(
            "https://store.rokland.com/products/12-dbi-aya-9012-alfa-network-n-female-"
            "directional-yagi-outdoor-iot-915-mhz-antenna"
        ),
        checked="2026-09-26",
        caveat=(
            "MUST BE AIMED, and mounted with its elements VERTICAL to match everybody "
            "else's polarisation -- it can be installed either way and the wrong way costs "
            "far more than the 12 dBi buys. No length or front-to-back figure is stated."
        ),
        directional=True,
        horizontal_beamwidth_deg=36.0,
    ),
    Antenna(
        key="lcom-hg906ye-6",
        name="L-Com HG906YE-NF 6 dBi Yagi, directional",
        maker="L-Com",
        gain_dbi_claimed=6.0,
        connector="N female",
        kind="yagi",
        frequency_low_mhz=824,
        frequency_high_mhz=960,
        outdoor=True,
        vertical_beamwidth_deg=None,
        length_in=17.5,
        good_for=(
            "A short aimed antenna for one known link, in anodised aluminium that will "
            "outlast a fibreglass tube."
        ),
        url="https://store.rokland.com/products/900-mhz-6-dbi-yagi-antenna-n-female-connector",
        checked="2026-09-26",
        caveat=(
            "THE LISTING STATES NO BEAMWIDTH, in either plane. The planner therefore "
            "cannot draw its pattern from the catalogue and asks you to enter a width "
            "yourself. Nothing here is a substitute for the missing figure."
        ),
        directional=True,
        horizontal_beamwidth_deg=None,
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
