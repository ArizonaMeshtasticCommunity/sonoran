"""What a hardware model tells us about the radio in it.

A node reports its hardware model. That names the chip and the power
amplifier, and nothing else that matters to a prediction.

Two figures in this table are assumptions, not facts:

- The transmit power is a setting, not a property of the board. The
  board sets a ceiling. The operator sets the value below it, and the
  mesh never reports which value. `assumed_tx_power_dbm` is the value
  to use when nothing better is known.
- The antenna is not part of the board. `assumed_antenna_gain_dbi`
  describes the antenna the device is sold with. An operator who fits a
  better antenna must say so in the overrides file.

Treat both as a first guess. The calibration job corrects them from
measurements, and the overrides file beats both.
"""

from dataclasses import dataclass

# The gain of the rubber antenna a device is usually sold with, in dBi.
#
# 2.15 dBi is the gain of a half-wave dipole. A stock rubber antenna is
# near it and often below it.
STOCK_ANTENNA_GAIN_DBI = 2.15

# The gain of an antenna built into the case, in dBi.
#
# A tracker or a wearable has no antenna connector. Its antenna is small
# and close to a body, so it does worse than a dipole.
INTERNAL_ANTENNA_GAIN_DBI = 0.0

# The power a plain SX1262 board transmits with, in dBm.
SX1262_TX_POWER_DBM = 22.0

# The power an older SX1276 board transmits with, in dBm.
SX1276_TX_POWER_DBM = 20.0


@dataclass(frozen=True)
class HardwareProfile:
    """The radio a hardware model holds.

    `max_tx_power_dbm` is the ceiling of the board. `assumed_tx_power_dbm`
    is the value to predict with. They are the same for a plain board,
    and they differ where a board has a power amplifier that an operator
    may choose not to drive fully.
    """

    chipset: str
    max_tx_power_dbm: float
    assumed_tx_power_dbm: float
    assumed_antenna_gain_dbi: float
    # True when the antenna is inside the case and cannot be changed.
    fixed_antenna: bool = False
    # True when nothing in the table matched and a family rule was used.
    inferred: bool = False


def _sx1262(gain: float = STOCK_ANTENNA_GAIN_DBI) -> HardwareProfile:
    """Return the profile of a plain SX1262 board."""
    return HardwareProfile("SX1262", SX1262_TX_POWER_DBM, SX1262_TX_POWER_DBM, gain)


def _sx1276(gain: float = STOCK_ANTENNA_GAIN_DBI) -> HardwareProfile:
    """Return the profile of an older SX1276 board."""
    return HardwareProfile("SX1276", SX1276_TX_POWER_DBM, SX1276_TX_POWER_DBM, gain)


def _tracker() -> HardwareProfile:
    """Return the profile of a tracker with an antenna in its case."""
    return HardwareProfile(
        "SX1262", SX1262_TX_POWER_DBM, SX1262_TX_POWER_DBM, INTERNAL_ANTENNA_GAIN_DBI, True
    )


# The models this mesh sees, and the models worth naming because their
# power is not the usual figure.
#
# A model that is not here falls to the family rules in `_infer`.
_PROFILES: dict[str, HardwareProfile] = {
    # The common SX1262 boards.
    "RAK4631": _sx1262(),
    "RAK11200": _sx1262(),
    "RAK11310": _sx1262(),
    "RAK3172": _sx1262(),
    "HELTEC_V3": _sx1262(),
    "HELTEC_V4": _sx1262(),
    "HELTEC_WSL_V3": _sx1262(),
    "HELTEC_MESH_NODE_T114": _sx1262(),
    "HELTEC_VISION_MASTER_T190": _sx1262(),
    "HELTEC_VISION_MASTER_E213": _sx1262(),
    "HELTEC_VISION_MASTER_E290": _sx1262(),
    "HELTEC_WIRELESS_PAPER": _sx1262(),
    "HELTEC_WIRELESS_PAPER_V1_0": _sx1262(),
    "LILYGO_TBEAM_S3_CORE": _sx1262(),
    "TLORA_T3_S3": _sx1262(),
    "T_DECK": _sx1262(),
    "T_ECHO": _sx1262(),
    "T_WATCH_S3": _sx1262(),
    "NANO_G2_ULTRA": _sx1262(),
    "RP2040_LORA": _sx1262(),
    "SEEED_XIAO_S3": _sx1262(),
    "SEEED_SOLAR_NODE": _sx1262(),
    "MESHSTICK_1262": _sx1262(),
    "WIO_WM1110": _sx1262(),
    # The older SX1276 boards.
    "TBEAM": _sx1276(),
    "TBEAM_V0P7": _sx1276(),
    "HELTEC_V1": _sx1276(),
    "HELTEC_V2_0": _sx1276(),
    "HELTEC_V2_1": _sx1276(),
    "TLORA_V1": _sx1276(),
    "TLORA_V1_1P3": _sx1276(),
    "TLORA_V2": _sx1276(),
    "TLORA_V2_1_1P6": _sx1276(),
    "TLORA_V2_1_1P8": _sx1276(),
    "NANO_G1": _sx1276(),
    "NANO_G1_EXPLORER": _sx1276(),
    # Trackers and wearables. The antenna is in the case.
    "TRACKER_T1000_E": _tracker(),
    "TRACKER_T1000_E_PRO": _tracker(),
    "SEEED_WIO_TRACKER_L1": _tracker(),
    "SEEED_WIO_TRACKER_L1_EINK": _tracker(),
    "HELTEC_WIRELESS_TRACKER": _tracker(),
    "HELTEC_WIRELESS_TRACKER_V1_0": _tracker(),
    "HELTEC_WIRELESS_TRACKER_V2": _tracker(),
    # The boards with a power amplifier.
    #
    # A Station G2 can reach 35 dBm. Few are run there, because the
    # amplifier is hot and most are solar. 30 dBm is the value to
    # predict with until a measurement says otherwise.
    "STATION_G1": HardwareProfile("SX1276", 30.0, 27.0, STOCK_ANTENNA_GAIN_DBI),
    "STATION_G2": HardwareProfile("SX1262", 35.0, 30.0, STOCK_ANTENNA_GAIN_DBI),
    "STATION_G3": HardwareProfile("SX1262", 35.0, 30.0, STOCK_ANTENNA_GAIN_DBI),
    "TBEAM_1_WATT": HardwareProfile("SX1262", 30.0, 30.0, STOCK_ANTENNA_GAIN_DBI),
    "RAK2560": HardwareProfile("SX1262", 30.0, 27.0, STOCK_ANTENNA_GAIN_DBI),
}

# The profile for a model this table does not name and the family rules
# do not recognise.
#
# It is a plain SX1262 board with a stock antenna, which is what most of
# the mesh is. `inferred` says the figure is a guess.
UNKNOWN_PROFILE = HardwareProfile(
    "unknown", SX1262_TX_POWER_DBM, SX1262_TX_POWER_DBM, STOCK_ANTENNA_GAIN_DBI, inferred=True
)

# Words in a model name that name a device with the antenna in its case.
_TRACKER_WORDS = ("TRACKER", "T1000", "WATCH", "TAG", "CARD")

# Words in a model name that name an older SX1276 board.
#
# The Meshtastic hardware list has 138 models and grows with every
# firmware release. A rule that reads the name keeps a new board out of
# the unknown bucket without an edit here.
_SX1276_WORDS = ("HELTEC_V1", "HELTEC_V2", "TLORA_V1", "TLORA_V2", "TBEAM_V0")


def _infer(model: str) -> HardwareProfile:
    """Return a profile worked out from the name of a model."""
    if any(word in model for word in _SX1276_WORDS):
        profile = _sx1276()
    elif any(word in model for word in _TRACKER_WORDS):
        profile = _tracker()
    else:
        return UNKNOWN_PROFILE
    return HardwareProfile(
        profile.chipset,
        profile.max_tx_power_dbm,
        profile.assumed_tx_power_dbm,
        profile.assumed_antenna_gain_dbi,
        profile.fixed_antenna,
        inferred=True,
    )


def hardware_profile(hw_model: str | None) -> HardwareProfile:
    """Return the radio profile of a hardware model.

    An unknown model gives `UNKNOWN_PROFILE`. The result always has
    figures in it, so a caller never has to test for a missing profile.
    Read `inferred` to find out whether the figures were looked up or
    guessed.
    """
    if not hw_model:
        return UNKNOWN_PROFILE
    model = hw_model.strip().upper()
    found = _PROFILES.get(model)
    if found is not None:
        return found
    return _infer(model)
