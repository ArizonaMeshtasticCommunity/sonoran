/*
 * Planner parameters and the conversion to engine values.
 *
 * A port of `src/engine/params.ts` from the Meshtastic Site Planner,
 * with the Meshtastic tables from its `parameters.md`.
 *
 * The one trap here: the engine takes antenna heights in FEET. That is
 * inherited from SPLAT!. The form holds metres, whatever units the boxes
 * show the reader (see `UNIT_BOXES`), so the conversion below must not be
 * skipped. Feeding metres straight
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

/* ---------------------------------------------------------------- */
/* The radio climate of the site (#239)                              */

/*
 * The climate choice that means "read it from the site".
 *
 * It is the default. The page turns it into one of the seven codes above
 * before a run, from the Köppen-Geiger class of the site's own ground
 * (`sonoran/climate/`). It never reaches the engine as itself:
 * `toEngineParams` refuses it.
 *
 * Where the data has no class, the answer is `desert` and the page says
 * "not known here, using desert". A lookup that is confidently wrong is
 * worse than a default that is openly a default.
 */
const CLIMATE_AUTO = 'auto';
const CLIMATE_FALLBACK = 'desert';

/** The words for a climate code, or the code itself. */
function climateLabel(key) {
  const found = CLIMATE_LABELS.find(([value]) => value === key);
  return found ? found[1] : String(key);
}

/**
 * The square a place is in, named for its south-west corner.
 *
 * `Math.floor`, not truncation: 112.07 W is in the square whose west edge
 * is 113 W, so Phoenix is N33W113 and not N33W112. AGENTS.md 9.13.1.
 */
function tileNameOf(latitude, longitude) {
  const lat = Math.floor(latitude);
  const lon = Math.floor(longitude);
  const ns = lat >= 0 ? 'N' : 'S';
  const ew = lon >= 0 ? 'E' : 'W';
  return `${ns}${String(Math.abs(lat)).padStart(2, '0')}${ew}${String(Math.abs(lon)).padStart(3, '0')}`;
}

/**
 * The Köppen-Geiger class at a place, read out of its climate page.
 *
 * A page is one degree square, `cellsPerDegree` cells on a side, with
 * row 0 at the NORTH edge and column 0 at the WEST edge. That is the
 * order of `/api/climate/page/{tile}`, and it is not the order of a
 * terrain page (AGENTS.md 9.13.1). Null when there is no page or the
 * cell holds no class (0).
 */
function climateCell(page, latitude, longitude, cellsPerDegree) {
  if (!page || !(cellsPerDegree > 0)) return null;
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (page.length !== cellsPerDegree * cellsPerDegree) return null;
  const north = Math.floor(latitude) + 1;
  const west = Math.floor(longitude);
  const row = Math.min(Math.floor((north - latitude) * cellsPerDegree), cellsPerDegree - 1);
  const column = Math.min(Math.floor((longitude - west) * cellsPerDegree), cellsPerDegree - 1);
  const value = page[row * cellsPerDegree + column];
  return value ? value : null;
}

/**
 * The climate a run uses, and where it came from.
 *
 * `chosen` is the form's choice. `found` is the Köppen class the page
 * looked up for the site, as `/api/climate/classes` describes it
 * (`{ code, symbol, climate }`), or null when it found none.
 *
 *   source 'chosen'    somebody picked a climate, in Advanced or in a link
 *   source 'site'      read from the site's Köppen class
 *   source 'fallback'  no class here, so `desert`, and the page says so
 */
function resolveClimate(chosen, found) {
  if (chosen && chosen !== CLIMATE_AUTO) return { climate: chosen, source: 'chosen', koppen: null };
  if (found && CLIMATE_CODES[found.climate] !== undefined) {
    return { climate: found.climate, source: 'site', koppen: found.symbol };
  }
  return { climate: CLIMATE_FALLBACK, source: 'fallback', koppen: null };
}

/** One line that says which climate a run used, and why. */
function describeClimate(answer) {
  const label = climateLabel(answer.climate);
  if (answer.source === 'site') return `${label}, from the site's Köppen class ${answer.koppen}`;
  if (answer.source === 'fallback') return `${label}: the climate is not known here, using desert`;
  return `${label}, as chosen`;
}

/*
 * Receiver sensitivity by modem preset, in dBm.
 *
 * Each is 22 dBm minus the link budget the Meshtastic docs publish for
 * the preset (https://meshtastic.org/docs/overview/radio-settings/),
 * which they say assumes a 22 dBm transmitter and a 0 dB antenna (#362).
 * Real air is worse. In a town it is realistic to allow several dB of
 * noise on top, which is why the form lets the number be edited after a
 * preset is chosen. Presets the docs give no budget for (Long slow,
 * Very long slow) are not offered here.
 *
 * A preset is also a different radio configuration: a node on LongFast
 * cannot hear a node on MediumFast at all. See AGENTS.md 9.7.
 *
 * `bandwidthHz` is here for the frequency slot, not for the link
 * budget. A slot is one bandwidth wide, so the same slot number is a
 * different frequency on each preset, and the two cannot be worked out
 * apart. The figures are `sonoran/radio/presets.py`, and
 * `tests/unit/test_planner_slot_and_frequency.py` pins the two tables
 * together so a preset cannot be edited in one and not the other.
 */
const PRESETS = [
  { key: 'SHORT_TURBO', label: 'Short turbo', sensitivity: -118, bandwidthHz: 500000 },
  { key: 'SHORT_FAST', label: 'Short fast', sensitivity: -121, bandwidthHz: 250000 },
  { key: 'MEDIUM_TURBO', label: 'Medium turbo', sensitivity: -123, bandwidthHz: 500000 },
  { key: 'SHORT_SLOW', label: 'Short slow', sensitivity: -123.5, bandwidthHz: 250000 },
  { key: 'MEDIUM_FAST', label: 'Medium fast', sensitivity: -126, bandwidthHz: 250000 },
  { key: 'NARROW_FAST', label: 'Narrow fast', sensitivity: -127, bandwidthHz: 62500 },
  { key: 'LONG_TURBO', label: 'Long turbo', sensitivity: -128, bandwidthHz: 500000 },
  { key: 'MEDIUM_SLOW', label: 'Medium slow', sensitivity: -128.5, bandwidthHz: 250000 },
  { key: 'LITE_FAST', label: 'Lite fast', sensitivity: -129, bandwidthHz: 125000 },
  { key: 'NARROW_SLOW', label: 'Narrow slow', sensitivity: -129.5, bandwidthHz: 62500 },
  { key: 'LONG_FAST', label: 'Long fast', sensitivity: -131, bandwidthHz: 250000 },
  { key: 'LITE_SLOW', label: 'Lite slow', sensitivity: -131.5, bandwidthHz: 125000 },
  { key: 'TINY_FAST', label: 'Tiny fast', sensitivity: -133, bandwidthHz: 15600 },
  { key: 'LONG_MODERATE', label: 'Long moderate', sensitivity: -134, bandwidthHz: 125000 },
  { key: 'TINY_SLOW', label: 'Tiny slow', sensitivity: -135.5, bandwidthHz: 15600 },
];

/* ---------------------------------------------------------------- */
/* The frequency slot                                                */

/*
 * The US 902 to 928 MHz band, which is the only region this mesh runs.
 *
 * The firmware divides it into slots one bandwidth wide and a node sits
 * in the middle of one of them:
 *
 *     slots     = floor((end - start) / bandwidth)
 *     centre    = start + bandwidth / 2 + (slot - 1) * bandwidth
 *
 * **`slot` here is the number the operator sets, `lora.channel_num`,
 * and it counts from 1.** `sonoran/radio/channels.py` computes the same
 * frequencies from a zero-based index, because there it comes out of a
 * hash of the channel name. The two differ by one, and getting that
 * wrong moves every prediction one slot — 250 kHz — with nothing on
 * screen to show it. The check that keeps them honest is LongFast: the
 * firmware default is `channel_num` 20 and 906.875 MHz, which
 * `channels.py` reaches as its index 19.
 */
const BAND_START_HZ = 902000000;
const BAND_END_HZ = 928000000;

/** How many slots a preset's bandwidth divides the band into. */
function slotsForPreset(key) {
  const found = PRESETS.find((item) => item.key === key);
  if (!found) return 0;
  return Math.floor((BAND_END_HZ - BAND_START_HZ) / found.bandwidthHz);
}

/**
 * The centre frequency of one slot, in MHz, or null.
 *
 * Null for a slot this preset has not got, and for anything that is not a
 * whole number in range.
 *
 * **The range check is what handles ABSENT, and it is not a coincidence.**
 * `Number(null)`, `Number('')` and `Number(' ')` are all 0, and slot 0
 * does not exist: an empty slot menu -- which is exactly what "not on a
 * slot" leaves behind -- would otherwise compute 901.875 MHz, below the
 * band, and read as an ordinary typo. This is the fifth instance in this
 * repository of a value meaning ABSENT sharing storage with a real one
 * (#149, #157, #190, #197).
 *
 * There was an explicit `slot === null || slot === undefined || slot ===
 * ''` guard above this. It was removed because a mutation test could not
 * kill it: `number < 1` already answers every one of those cases, and a
 * line no test can fail is a line that documents nothing and could be
 * wrong without anybody knowing. The cases for the empty values are still
 * in `planner_slot_cases.mjs`; they now exercise the guard that does the
 * work.
 */
function frequencyForSlot(key, slot) {
  const found = PRESETS.find((item) => item.key === key);
  if (!found) return null;
  const number = Number(slot);
  if (!Number.isInteger(number)) return null;
  if (number < 1 || number > slotsForPreset(key)) return null;
  const hz = BAND_START_HZ + found.bandwidthHz / 2 + (number - 1) * found.bandwidthHz;
  /*
   * Five decimals, not three.
   *
   * Three is a kilohertz, which is finer than any slot is wide and looked
   * like plenty. It is not: half of 62.5 kHz is 31.25 kHz, so Very long
   * slow's slots sit on quarter-kilohertz boundaries and 902.03125 MHz
   * came back as 902.031. The error was a quarter of a kilohertz -- far
   * too small to change a prediction, and just inside the tolerance in
   * `slotForFrequency`, so every round trip still passed. What found it
   * was comparing against `sonoran/radio/channels.py`, which does the
   * same arithmetic in integer hertz: Long moderate's own channel is
   * 912.8125 MHz there and was 912.812 here.
   *
   * `Number` then drops the trailing zeros, so slot 18 is still 906.375
   * and not 906.37500.
   */
  return Number((hz / 1000000).toFixed(5));
}

/**
 * The slot a frequency sits in the middle of, or null.
 *
 * Null when the frequency is not a slot centre for this preset. That is
 * a real answer and not a failure: a licensed operator may set any
 * frequency, and `lora.override_frequency` exists for exactly that. The
 * form says "not on a slot" rather than snapping the number somebody
 * typed, because snapping would change a prediction without being asked.
 */
function slotForFrequency(key, megahertz) {
  const found = PRESETS.find((item) => item.key === key);
  if (!found) return null;
  if (megahertz === null || megahertz === undefined || megahertz === '') return null;
  const mhz = Number(megahertz);
  if (!Number.isFinite(mhz)) return null;
  const offset = mhz * 1000000 - BAND_START_HZ - found.bandwidthHz / 2;
  const guess = Math.round(offset / found.bandwidthHz) + 1;
  const centre = frequencyForSlot(key, guess);
  if (centre === null) return null;
  // Compared as frequencies rather than as an integer test on the
  // division: a float division of 906.375 MHz by 250 kHz does not land
  // exactly on 17, and a tolerance in slots is a tolerance that changes
  // size with the bandwidth. Half a kilohertz is inside every slot.
  return Math.abs(centre - mhz) < 0.0005 ? guess : null;
}

/*
 * The largest radius the engine can plot.
 *
 * The compiled page region reaches at most 3.5 degrees from the
 * transmitter. Past that the run would be clipped without saying so.
 */
const MAX_RADIUS_METRES = 150000;

/*
 * The slot this mesh runs, and the frequency it comes to.
 *
 * Slot 18 is what the azmsh.net recommendation asks a metro node for --
 * `METRO_RECOMMENDATIONS.channelNum` in the config checker, which is the
 * same number the reader sets on the radio. On Medium fast's 250 kHz
 * that is 906.375 MHz.
 *
 * It was 906.875 MHz here, which is LongFast's own slot 20 and not
 * anything this mesh is configured for: the comment called it "the
 * middle of the US 915 band", which it is not either. Derived rather
 * than typed, so the number cannot drift from the slot it claims to be.
 */
const DEFAULT_SLOT = 18;
const DEFAULT_PRESET_KEY = 'MEDIUM_FAST';

/*
 * Defaults for this mesh.
 *
 * 0.1 W and 2.15 dBi describe a stock device with its rubber antenna.
 * The climate is read from the site rather than fixed (#239). Phoenix
 * is desert and Flagstaff is continental temperate.
 */
const DEFAULTS = {
  lat: null,
  lon: null,
  site_name: '',
  tx_height: 3,
  tx_power: 30,
  tx_gain: 2.15,
  system_loss: 2,
  // Slot 18 on the default preset. `frequencyForSlot` is declared above
  // this object, so it can be called here; the alternative -- a literal
  // with the slot in a comment beside it -- is how the old 906.875 came
  // to describe a slot nothing on this mesh uses.
  frequency_mhz: frequencyForSlot(DEFAULT_PRESET_KEY, DEFAULT_SLOT),
  rx_height: 1,
  rx_gain: 2.15,
  /*
   * Aiming, for a directional antenna only.
   *
   * Both default to null and NOT to 0. Zero is a real bearing -- due
   * north -- so a 0 default would silently aim every Yagi at the north
   * pole and look like a deliberate choice. Null means "not aimed", and
   * the raster is left omnidirectional until both are present.
   */
  tx_azimuth: null,
  tx_beamwidth: null,
  // Medium fast, because that is what this mesh actually runs (#105).
  // The sensitivity has to move with it -- the two are one choice, and
  // a form that opens on Medium fast with Long fast's -131 dBm would
  // predict a reach nobody has. The change handler already keeps them
  // together after the first load; this keeps them together before it.
  sensitivity: -126,
  // Spelled out rather than `DEFAULT_PRESET_KEY`, because
  // `test_page_defaults.py` reads this literal to check that the
  // sensitivity beside it is the one this preset implies. A node case
  // asserts the two names agree, so the pair cannot drift.
  preset: 'MEDIUM_FAST',
  clutter_height: 0,
  ground_dielectric: 15,
  ground_conductivity: 0.005,
  atmosphere_bending: 301,
  // Read from the site (#239). See `CLIMATE_AUTO`.
  radio_climate: CLIMATE_AUTO,
  polarization: 'vertical',
  radius: 30000,
  situation_fraction: 50,
  time_fraction: 90,
};

/*
 * The same defaults in the units the FORM asks for.
 *
 * One field differs: the form asks for a range in kilometres and the
 * engine takes metres. Everything that fills or reads the form works in
 * these units, and so does the share link, so the two cannot drift.
 */
const FORM_DEFAULTS = { ...DEFAULTS, radius: DEFAULTS.radius / 1000 };

/* ---------------------------------------------------------------- */
/* The boxes in the reader's units (#246)                            */

/*
 * The four boxes whose unit follows the reader's units setting.
 *
 * THE FORM VALUE STAYS METRIC. Heights are metres and the range is
 * kilometres, in the form values, in the share link and on the way to
 * the engine, whatever the setting says. Only the text in the box is in
 * the reader's units, and it is converted here, at the box and nowhere
 * else. A link must predict the same thing for two readers, so it
 * cannot carry a display preference.
 *
 * The cable length is not one of these. Cable is sold in feet and the
 * catalogue's figures are per 100 ft, so that box is feet for everyone.
 */
const UNIT_BOXES = {
  tx_height: 'height',
  rx_height: 'height',
  clutter_height: 'height',
  radius: 'distance',
};

/*
 * How many decimals a box shows, and how many a typed value keeps.
 *
 * Shown to a hundredth, because a box full of digits reads as a
 * measurement nobody made. Kept to a millionth -- a micrometre, or a
 * millimetre of range -- which is far below anything the model can
 * resolve and is enough for a whole or two-decimal number of feet to
 * land on one exact metre figure. That is what makes 20 ft typed and
 * 6.096 m typed the same antenna, and the same prediction.
 */
const SHOWN_DECIMALS = 2;
const KEPT_DECIMALS = 6;

/**
 * The text a box shows for a form value (metres, or km for the range).
 *
 * `units` is `SonoranUnits`, passed in rather than read from `window`, so
 * nothing else in this file can come to depend on a display setting.
 */
function toBox(name, value, units) {
  const kind = UNIT_BOXES[name];
  if (value === null || value === undefined || value === '') return '';
  const number = Number(value);
  if (!kind || !Number.isFinite(number)) return String(value);
  // A metric reader sees the form value exactly as it is held, so a
  // metric box never rounds anything.
  if (!units.imperial()) return String(number);
  const factor = kind === 'height' ? units.FEET_PER_METRE : units.MILES_PER_KM;
  return String(Number((number * factor).toFixed(SHOWN_DECIMALS)));
}

/** A typed box back into a form value, or null when it is not a number. */
function fromBox(name, typed, units) {
  const text = typed === null || typed === undefined ? '' : String(typed).trim();
  const value = UNIT_BOXES[name] === 'height' ? units.heightToM(text) : units.distanceToKm(text);
  return value === null ? null : Number(value.toFixed(KEPT_DECIMALS));
}

/**
 * What a box holds, as a form value.
 *
 * `held` is what the page last wrote into the box: `{ shown, value }`.
 * While the box still says `shown`, the answer is `value`, untouched.
 * Only text the reader typed is converted.
 *
 * This is the part that keeps a link lossless. A metric link's 6 m reads
 * as 19.69 ft in an imperial box, and 19.69 ft is 6.0015 m. Converting
 * the box back would move the antenna by a millimetre and a half and a
 * link re-shared from it would no longer be the link it was. Keeping the
 * value next to its text, and using it until the text changes, means an
 * untouched box is never converted at all.
 */
function readBox(name, typed, held, units) {
  if (held && typed === held.shown) return held.value;
  return fromBox(name, typed, units);
}

/* ---------------------------------------------------------------- */
/* The share link                                                    */

/*
 * The version key in a share link.
 *
 * It is written into every link. A link made now says which spelling of
 * the fields it used, so a later change can read old links rather than
 * guess at them.
 *
 * Version 2 (#239) is the first time that mattered. A link writes only
 * what differs from the default, and the default climate was `desert`.
 * It is now "read it from the site". So a version 1 link with no
 * `radio_climate` in it meant desert, and must go on meaning desert: a
 * link made before the change predicts what it predicted then.
 * `fromShareQuery` puts the desert back. A link with no `v` at all is
 * read as version 1, because every link this page ever wrote has one.
 */
const SHARE_VERSION = 2;
const SHARE_VERSIONS_READ = ['1', '2'];

/*
 * The order a link writes its settings in.
 *
 * It is the order of the form: site, transmitter, receiver, ground and
 * air. A link is read by people in chat clients before it is opened,
 * so the order it reads in is worth keeping.
 *
 * **The frequency slot is deliberately not one of them.** A slot is the
 * frequency and the preset's bandwidth said another way, and a link
 * carrying both a slot and a frequency could carry two that disagree --
 * which the reader of the link has no way to notice. The page that opens
 * a link works the slot out from the frequency it was given, so there is
 * one number in the link and one answer on the form.
 */
const SHARE_FIELDS = [
  'site_name',
  'lat',
  'lon',
  'tx_height',
  'tx_power',
  'tx_gain',
  'tx_azimuth',
  'tx_beamwidth',
  'frequency_mhz',
  'preset',
  'sensitivity',
  'rx_height',
  'rx_gain',
  'system_loss',
  'radio_climate',
  'polarization',
  'clutter_height',
  'radius',
  'ground_dielectric',
  'ground_conductivity',
  'atmosphere_bending',
  'situation_fraction',
  'time_fraction',
];

/** The three fields that are a choice from a list, not a number. */
const SHARE_CHOICES = {
  preset: () => PRESETS.map((item) => item.key),
  radio_climate: () => [CLIMATE_AUTO, ...Object.keys(CLIMATE_CODES)],
  polarization: () => Object.keys(POLARIZATION_CODES),
};

/*
 * Bounds for a number that arrives from a URL.
 *
 * These are wide sanity bounds, not the model's validity limits. A
 * share link can be hand-typed, truncated by a chat client, or edited
 * for fun, and the engine is a WebAssembly module that is given these
 * numbers directly. The job here is to keep an absurd value out of it,
 * not to argue with anybody's radio.
 *
 * Two are not arbitrary. The range ceiling is `MAX_RADIUS_METRES`,
 * which is what the compiled page region can reach. The two fractions
 * stop short of 0 and 100 because `toEngineParams` turns them into
 * probabilities and the model's inverse-normal has no value at either
 * end.
 */
const SHARE_BOUNDS = {
  lat: [-90, 90],
  lon: [-180, 180],
  tx_height: [0, 3000],
  tx_power: [-30, 60],
  tx_gain: [-20, 40],
  tx_azimuth: [0, 360],
  tx_beamwidth: [1, 360],
  frequency_mhz: [20, 20000],
  sensitivity: [-174, 0],
  rx_height: [0, 3000],
  rx_gain: [-20, 40],
  system_loss: [0, 40],
  clutter_height: [0, 100],
  radius: [0.1, MAX_RADIUS_METRES / 1000],
  ground_dielectric: [1, 100],
  ground_conductivity: [0.00001, 100],
  atmosphere_bending: [200, 450],
  situation_fraction: [1, 99],
  time_fraction: [1, 99],
};

/*
 * The longest site name a link will carry.
 *
 * A name is the reader's own words and it goes in the link as they
 * typed it. It is capped so that one pasted paragraph cannot turn a
 * link into something no chat client will keep on one line.
 */
const SHARE_NAME_LIMIT = 60;

/** The sensitivity a preset implies, or null when the key is unknown. */
function sensitivityForPreset(key) {
  const found = PRESETS.find((item) => item.key === key);
  return found ? found.sensitivity : null;
}

/** Numbers compare by value, so "2.150" and 2.15 are the same setting. */
function sameAsDefault(name, value) {
  const fallback = FORM_DEFAULTS[name];
  if (SHARE_CHOICES[name] || name === 'site_name') return String(value) === String(fallback);
  if (fallback == null) return false;
  return Number(value) === Number(fallback);
}

/**
 * Write the form out as the query part of a share link.
 *
 * Only what differs from the default is written. A link for the
 * defaults with a site on it is then three keys long rather than
 * twenty-one, which is the difference between a link somebody reads
 * and a link they scroll past.
 *
 * `ran` is the day the link was made, written only when there is a
 * prediction behind it. Terrain and the node list move, so the page
 * that opens the link says what the numbers are as of.
 */
function toShareQuery(values, ran) {
  const parts = [`v=${SHARE_VERSION}`];
  for (const name of SHARE_FIELDS) {
    const value = values[name];
    if (value == null || value === '') continue;
    /*
     * The sensitivity follows the preset unless it has been edited, and
     * the reader below puts it back the same way. Writing it out when
     * it is still the preset's own figure would put a number in every
     * link that changes a preset.
     */
    if (name === 'sensitivity' && Number(value) === sensitivityForPreset(values.preset)) continue;
    if (sameAsDefault(name, value)) continue;
    const written = name === 'site_name' ? String(value).trim().slice(0, SHARE_NAME_LIMIT) : String(value);
    if (!written) continue;
    parts.push(`${name}=${encodeURIComponent(written)}`);
  }
  if (ran) parts.push(`ran=${encodeURIComponent(ran)}`);
  return parts.join('&');
}

/**
 * Read the query part of a share link.
 *
 * Returns the settings it could use, the day the link says it was
 * made, and a note for everything it had to change or drop. Nothing is
 * thrown: a bad link opens the planner on the settings it could read
 * and says what it did with the rest.
 */
function fromShareQuery(search) {
  const query = new URLSearchParams(search || '');
  const values = {};
  const notes = [];
  const kept = [];
  const unknown = [];
  let ran = null;
  let used = 0;
  // No `v` is version 1. See `SHARE_VERSION`.
  const version = query.get('v') ?? '1';

  for (const [key, raw] of query.entries()) {
    if (key === 'v') {
      if (!SHARE_VERSIONS_READ.includes(raw)) {
        notes.push(`this link says it is version ${raw}, and this planner reads version ${SHARE_VERSION}`);
      }
      continue;
    }
    if (key === 'ran') {
      // A date, not a setting. Anything that is not a date is dropped
      // rather than printed back at the reader.
      if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) ran = raw;
      continue;
    }
    if (!SHARE_FIELDS.includes(key)) {
      unknown.push(key);
      continue;
    }
    if (SHARE_CHOICES[key]) {
      if (!SHARE_CHOICES[key]().includes(raw)) {
        notes.push(`${key} is not a choice this planner has, so it kept the default`);
        continue;
      }
      values[key] = raw;
      used += 1;
      continue;
    }
    if (key === 'site_name') {
      const name = raw.trim().slice(0, SHARE_NAME_LIMIT);
      if (raw.trim().length > SHARE_NAME_LIMIT) notes.push('the site name was shortened');
      if (name) {
        values[key] = name;
        used += 1;
      }
      continue;
    }
    const number = Number.parseFloat(raw);
    if (!Number.isFinite(number)) {
      notes.push(`${key.replace(/_/g, ' ')} is not a number, so it kept the default`);
      continue;
    }
    const [low, high] = SHARE_BOUNDS[key];
    const held = Math.min(high, Math.max(low, number));
    if (held !== number) notes.push(`${key.replace(/_/g, ' ')} was held to ${held}`);
    values[key] = held;
    used += 1;
  }

  if (unknown.length) notes.push(`ignored: ${unknown.join(', ')}`);
  /*
   * A version 1 link that names no climate was made on `desert`, which
   * was the default then and so was left out. It keeps it. Without this,
   * a Flagstaff link made before #239 would open on continental
   * temperate and predict something its writer never saw.
   */
  if (version === '1' && values.radio_climate == null) {
    values.radio_climate = CLIMATE_FALLBACK;
    kept.push(
      'This link was made before the planner read the climate from the site, ' +
        'so it keeps desert, as it predicted then.',
    );
  }
  /*
   * A link that names a preset and no sensitivity means the preset's
   * own figure, which is what the writer left out. Without this, a link
   * to Long fast would open on Long fast with Medium fast's -126 dBm
   * and predict a reach that preset does not have. See AGENTS.md 9.7.
   */
  if (values.preset && values.sensitivity == null) {
    values.sensitivity = sensitivityForPreset(values.preset);
  }
  return { values, ran, notes, kept, used };
}

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

/*
 * `system_loss` IS APPLIED TWICE, ONCE AT EACH END.
 *
 * The form calls it "Cable loss (dB)" and takes one number. It is
 * subtracted here, from the transmitted power, and again in
 * `receivedDbm` below, from the level at the receiver. So a reader who
 * types 2 loses 4 dB across the link.
 *
 * That is defensible as "assume both ends have a similar run", and it
 * is what the model does today. It is NOT what the label says, and
 * nobody typing into a box marked "Cable loss (dB)" expects it to count
 * twice.
 *
 * #112 asks for this to be fixed or documented, and fixing it properly
 * means a separate cable run per end -- a form change, not a sign
 * change. Halving it here instead would quietly alter every prediction
 * the planner has made so far. So it is documented, loudly, and
 * `radio/cables.py` now holds the sourced per-cable figures that the
 * two-ended version will need.
 *
 * For scale, from those datasheets at 915 MHz: 30 ft of LMR-400 is
 * 1.18 dB and the same run of LMR-195 is 3.33 dB. Doubling either is
 * the difference between a link closing and not.
 */

/** Turn a filled-in form into the values the engine takes. */
function toEngineParams(request) {
  // `auto` is a question, not a climate. The page answers it first, with
  // `resolveClimate`, so the engine is never handed a guess.
  if (request.radio_climate === CLIMATE_AUTO) {
    throw new Error('the radio climate must be read from the site before a run');
  }
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
  // The second of the two places `system_loss` is subtracted. See the
  // note above `erpWatts`: one box, applied at both ends.
  return fieldDbm + request.rx_gain - request.system_loss;
}

window.SonoranPlannerParams = {
  METRES_PER_FOOT,
  CLIMATE_CODES,
  CLIMATE_LABELS,
  CLIMATE_AUTO,
  CLIMATE_FALLBACK,
  climateLabel,
  tileNameOf,
  climateCell,
  resolveClimate,
  describeClimate,
  POLARIZATION_CODES,
  PRESETS,
  BAND_START_HZ,
  BAND_END_HZ,
  DEFAULT_SLOT,
  DEFAULT_PRESET_KEY,
  slotsForPreset,
  frequencyForSlot,
  slotForFrequency,
  MAX_RADIUS_METRES,
  DEFAULTS,
  FORM_DEFAULTS,
  UNIT_BOXES,
  toBox,
  fromBox,
  readBox,
  SHARE_VERSION,
  SHARE_FIELDS,
  SHARE_BOUNDS,
  SHARE_NAME_LIMIT,
  sensitivityForPreset,
  toShareQuery,
  fromShareQuery,
  erpWatts,
  toEngineParams,
  receivedDbm,
};
