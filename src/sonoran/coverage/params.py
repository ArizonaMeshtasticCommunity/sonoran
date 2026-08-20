"""The values the engine takes for one prediction.

A port of `web/static/planner-params.js`, which is itself a port of
`src/engine/params.ts` from the Meshtastic Site Planner. The planner
page runs in the browser and reads no Python, so the two exist side by
side. A test keeps their preset tables the same.

Two conversions happen here and nowhere else:

- Heights arrive in metres and reach the engine in feet. See `units`.
- Power arrives in dBm and reaches the engine in watts. Antenna gain
  and cable loss are applied first, in the logarithmic domain.
"""

from dataclasses import dataclass

from sonoran.coverage.units import metres_to_feet

# SPLAT! climate codes. The number is what the engine takes.
CLIMATE_CODES: dict[str, int] = {
    "equatorial": 1,
    "continental_subtropical": 2,
    "maritime_subtropical": 3,
    "desert": 4,
    "continental_temperate": 5,
    "maritime_temperate_land": 6,
    "maritime_temperate_sea": 7,
}

POLARIZATION_CODES: dict[str, int] = {"horizontal": 0, "vertical": 1}

# The largest radius the engine can plot, in metres.
#
# The compiled page region reaches at most 3.5 degrees from the
# transmitter. Past that a run is clipped and says nothing about it.
MAX_RADIUS_METRES = 150_000.0

# Points of terrain for each degree of latitude.
#
# 1200 points is about 90 m. The terrain service serves pages at this
# resolution only. See `sonoran/terrain/srtm.py`.
RESOLUTION_IPPD = 1200

# The middle of the US 915 MHz band that Meshtastic uses, in MHz.
DEFAULT_FREQUENCY_MHZ = 906.875

# Ground constants for dry desert soil.
DEFAULT_GROUND_DIELECTRIC = 15.0
DEFAULT_GROUND_CONDUCTIVITY = 0.005

# Surface refractivity, in N units.
DEFAULT_ATMOSPHERE_BENDING = 301.0


def erp_watts(tx_power_dbm: float, antenna_gain_dbi: float, cable_loss_db: float) -> float:
    """Return the effective radiated power in watts.

    The power is in dBm, so the gain and the loss are applied in the
    logarithmic domain before the conversion.
    """
    return 10.0 ** ((tx_power_dbm + antenna_gain_dbi - cable_loss_db - 30.0) / 10.0)


def received_dbm(field_dbm: float, rx_gain_dbi: float, rx_cable_loss_db: float) -> float:
    """Return the level a receiver would see, in dBm.

    The engine reports the transmitted field. The receiving antenna adds
    its gain, and its cable takes some away.
    """
    return field_dbm + rx_gain_dbi - rx_cable_loss_db


def _round2(value: float) -> float:
    """Round to two places, as the original backend wrote its files."""
    return round(value, 2)


@dataclass(frozen=True)
class EngineParams:
    """One prediction, in the units the engine takes.

    Heights are named in metres and converted on the way out. Nothing
    here takes a height in feet, so a bare number cannot reach the
    engine in the wrong unit.
    """

    latitude: float
    longitude: float
    tx_height_m: float
    rx_height_m: float
    erp_watts: float
    radius_m: float
    frequency_mhz: float = DEFAULT_FREQUENCY_MHZ
    ground_dielectric: float = DEFAULT_GROUND_DIELECTRIC
    ground_conductivity: float = DEFAULT_GROUND_CONDUCTIVITY
    atmosphere_bending: float = DEFAULT_ATMOSPHERE_BENDING
    radio_climate: str = "desert"
    polarization: str = "vertical"
    # The fraction of situations and of time the prediction must hold
    # for, from 0 to 1. The planner form asks for percentages.
    situation_fraction: float = 0.5
    time_fraction: float = 0.9
    clutter_height_m: float = 0.0
    resolution_ippd: int = RESOLUTION_IPPD

    @property
    def tx_alt_feet(self) -> float:
        """Return the transmit antenna height in feet."""
        return metres_to_feet(self.tx_height_m)

    @property
    def rx_alt_feet(self) -> float:
        """Return the receive antenna height in feet."""
        return metres_to_feet(self.rx_height_m)

    @property
    def radius_km(self) -> float:
        """Return the radius in kilometres, held to what the engine can do."""
        return min(self.radius_m, MAX_RADIUS_METRES) / 1000.0

    @property
    def climate_code(self) -> int:
        """Return the SPLAT! code for the radio climate."""
        code = CLIMATE_CODES.get(self.radio_climate)
        if code is None:
            raise ValueError(f"unknown radio climate: {self.radio_climate}")
        return code

    @property
    def polarization_code(self) -> int:
        """Return the SPLAT! code for the polarization."""
        code = POLARIZATION_CODES.get(self.polarization)
        if code is None:
            raise ValueError(f"unknown polarization: {self.polarization}")
        return code

    def to_arguments(self) -> tuple[float | int, ...]:
        """Return the sixteen values `splat_create` takes, in order.

        The order is fixed by the compiled engine. Do not change it
        without reading `web/static/planner.worker.js`, which passes the
        same list.

        Three of the sixteen are whole numbers to the engine, not
        floating point: the climate code, the polarization code, and the
        resolution. JavaScript hides that, because it has one number
        type and the loader converts. Python does not, and `wasmtime`
        refuses a float where the engine declared an integer. The
        signature is:

            (f64 f64 f64 f64 f64 f64 f64 f64 f64 i32 i32 f64 f64 f64 f64 i32) -> i32
        """
        return (
            self.latitude,
            self.longitude,
            self.tx_alt_feet,
            self.rx_alt_feet,
            self.frequency_mhz,
            _round2(self.erp_watts),
            self.ground_dielectric,
            self.ground_conductivity,
            self.atmosphere_bending,
            self.climate_code,
            self.polarization_code,
            _round2(self.situation_fraction),
            _round2(self.time_fraction),
            self.clutter_height_m,
            self.radius_km,
            self.resolution_ippd,
        )
