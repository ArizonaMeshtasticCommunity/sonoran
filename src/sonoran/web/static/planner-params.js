/*
 * Planner parameters and the conversion to engine values.
 *
 * A port of `src/engine/params.ts` from the Meshtastic Site Planner,
 * with the Meshtastic tables from its `parameters.md`.
 *
 * The one trap here: the engine takes antenna heights in FEET. That is
 * inherited from SPLAT!. The form asks for metres, as everybody expects,
 * so the conversion below must not be skipped. Feeding metres straight
 * through overstates every antenna by a factor of 3.28 and draws
 * coverage that does not exist.
 */

const METRES_PER_FOOT = 0.3048;

// SPLAT! climate codes. The number is what the engine wants.
const CLIMATE_CODES = {
  equatorial: 1,
  continental_subtropical: 2,
  maritime_subtropical: 3,
  desert: 4,
  continental_temperate: 5,
  maritime_temperate_land: 6,
  maritime_temperate_sea: 7,
};

const CLIMATE_LABELS = [
  ['continental_temperate', 'Continental temperate'],
  ['desert', 'Desert'],
  ['equatorial', 'Equatorial'],
  ['continental_subtropical', 'Continental subtropical'],
  ['maritime_subtropical', 'Maritime subtropical'],
  ['maritime_temperate_land', 'Maritime temperate, land'],
  ['maritime_temperate_sea', 'Maritime temperate, sea'],
];

const POLARIZATION_CODES = { horizontal: 0, vertical: 1 };

/*
 * Receiver sensitivity by modem preset, in dBm.
 *
 * These are the theoretical figures for the SX1262. Real air is worse.
 * In a town it is realistic to allow several dB of noise on top, which
 * is why the form lets the number be edited after a preset is chosen.
 *
 * A preset is also a different radio configuration: a node on LongFast
 * cannot hear a node on MediumFast at all. See AGENTS.md 9.7.
 */
const PRESETS = [
  { key: 'SHORT_TURBO', label: 'Short turbo', sensitivity: -126 },
  { key: 'SHORT_FAST', label: 'Short fast', sensitivity: -129 },
  { key: 'SHORT_SLOW', label: 'Short slow', sensitivity: -131.5 },
  { key: 'MEDIUM_FAST', label: 'Medium fast', sensitivity: -134 },
  { key: 'MEDIUM_SLOW', label: 'Medium slow', sensitivity: -136.5 },
  { key: 'LONG_FAST', label: 'Long fast', sensitivity: -139 },
  { key: 'LONG_MODERATE', label: 'Long moderate', sensitivity: -142 },
  { key: 'LONG_SLOW', label: 'Long slow', sensitivity: -144.5 },
  { key: 'VERY_LONG_SLOW', label: 'Very long slow', sensitivity: -147.5 },
];

/*
 * The largest radius the engine can plot.
 *
 * The compiled page region reaches at most 3.5 degrees from the
 * transmitter. Past that the run would be clipped without saying so.
 */
const MAX_RADIUS_METRES = 150000;

/*
 * Defaults for this mesh.
 *
 * 906.875 MHz is the middle of the US 915 band that Meshtastic uses.
 * 0.1 W and 2.15 dBi describe a stock device with its rubber antenna.
 * Desert is the right climate for Arizona, not the temperate default
 * the site planner ships.
 */
const DEFAULTS = {
  lat: null,
  lon: null,
  site_name: '',
  tx_height: 3,
  tx_power: 30,
  tx_gain: 2.15,
  system_loss: 2,
  frequency_mhz: 906.875,
  rx_height: 1,
  rx_gain: 2.15,
  // Medium fast, because that is what this mesh actually runs (#105).
  // The sensitivity has to move with it -- the two are one choice, and
  // a form that opens on Medium fast with Long fast's -139 dBm would
  // predict a reach nobody has. The change handler already keeps them
  // together after the first load; this keeps them together before it.
  sensitivity: -134,
  preset: 'MEDIUM_FAST',
  clutter_height: 0,
  ground_dielectric: 15,
  ground_conductivity: 0.005,
  atmosphere_bending: 301,
  radio_climate: 'desert',
  polarization: 'vertical',
  radius: 30000,
  situation_fraction: 50,
  time_fraction: 90,
};

/** Round to two decimal places, as the original backend wrote its files. */
function round2(value) {
  return Number(value.toFixed(2));
}

/**
 * Effective radiated power in watts.
 *
 * The transmit power is in dBm, so the gain and the system loss are
 * applied in the logarithmic domain before the conversion.
 */
function erpWatts(request) {
  return 10 ** ((request.tx_power + request.tx_gain - request.system_loss - 30) / 10);
}

/** Turn a filled-in form into the values the engine takes. */
function toEngineParams(request) {
  const climate = CLIMATE_CODES[request.radio_climate];
  const polarization = POLARIZATION_CODES[request.polarization];
  if (climate === undefined) throw new Error(`unknown radio climate: ${request.radio_climate}`);
  if (polarization === undefined) throw new Error(`unknown polarization: ${request.polarization}`);

  return {
    lat: request.lat,
    lon: request.lon,
    // Metres to feet. See the note at the top of this file.
    txAltFeet: request.tx_height / METRES_PER_FOOT,
    rxAltFeet: request.rx_height / METRES_PER_FOOT,
    frequencyMhz: request.frequency_mhz,
    erpWatts: round2(erpWatts(request)),
    groundDielectric: request.ground_dielectric,
    groundConductivity: request.ground_conductivity,
    atmosphereBending: request.atmosphere_bending,
    radioClimate: climate,
    polarization,
    conf: round2(request.situation_fraction / 100),
    rel: round2(request.time_fraction / 100),
    clutterHeightM: request.clutter_height,
    radiusKm: Math.min(request.radius, MAX_RADIUS_METRES) / 1000,
    // 1200 points per degree is about 90 m. The terrain service serves
    // pages at this resolution only.
    resolutionIppd: 1200,
  };
}

/**
 * The signal level a receiver would see, in dBm.
 *
 * The engine reports the transmitted field. The receiving antenna adds
 * its gain and its cable takes some away, so the usable level at the
 * radio is the sum of the three.
 */
function receivedDbm(fieldDbm, request) {
  return fieldDbm + request.rx_gain - request.system_loss;
}

window.SonoranPlannerParams = {
  METRES_PER_FOOT,
  CLIMATE_CODES,
  CLIMATE_LABELS,
  POLARIZATION_CODES,
  PRESETS,
  MAX_RADIUS_METRES,
  DEFAULTS,
  erpWatts,
  toEngineParams,
  receivedDbm,
};
