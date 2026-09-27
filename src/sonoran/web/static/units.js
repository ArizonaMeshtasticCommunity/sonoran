/*
 * Distances, heights and temperatures, in the reader's units.
 *
 * CONVERTED AT DISPLAY. The API keeps SI and keeps saying so --
 * `distance_km`, `"unit": "km"` -- and every conversion happens here, in
 * the browser, once. The alternative, an API that answers in whichever
 * unit the caller asked for, puts a display preference into the data layer
 * and makes every cached response unit-dependent.
 *
 * WHAT THIS MUST NOT TOUCH: the planner's own metres. `planner-params.js`
 * converts metres to feet for the engine, and `docs/PLANNER.md` records
 * that confusing the two overstates every antenna by 3.28 times. That
 * conversion is arithmetic on the way into a model, not a label for a
 * reader, and it stays in metres whatever this module says.
 *
 * Rounding is per quantity, not one global rule. "0.3 km" reading as
 * "0.2 miles" is fine; a "12 m mast" reading as "39.37 ft" is not, because
 * masts come in whole feet. Each function below decides its own, and the
 * decision is the reason each one exists rather than a single `convert`.
 */
window.SonoranUnits = (function build() {
  const FEET_PER_METRE = 3.280839895;
  const MILES_PER_KM = 0.621371192;
  const MM_PER_INCH = 25.4;
  const INHG_PER_HPA = 0.0295299830714;
  const METRES_PER_SECOND_PER_KNOT = 1852 / 3600;

  /** True when the reader wants miles and feet. Defaults to imperial. */
  function imperial() {
    const settings = window.SonoranSettings;
    return settings ? settings.isImperial() : true;
  }

  /** True when the reader wants Fahrenheit. */
  function fahrenheit() {
    const settings = window.SonoranSettings;
    return settings ? settings.get('temperature') === 'fahrenheit' : true;
  }

  /**
   * A number, or null for anything that is not one.
   *
   * `null`, `undefined` and `''` are refused BEFORE the conversion,
   * because `Number(null)` and `Number('')` are both 0 and 0 is finite --
   * so a missing distance came out as "0 ft", which claims two nodes are
   * on top of each other when we do not know where one of them is.
   *
   * This is the fifth instance in this repository of one bug shape: a
   * value meaning ABSENT sharing storage with a value that means
   * something. See #149, #157, #197 and #190. A real zero still passes,
   * which is the half that keeps the fix honest -- 0 °C is a temperature
   * and two nodes at the same spot are 0 ft apart.
   */
  function num(value) {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  /*
   * The small-unit threshold: below a thousand feet, or a thousand metres,
   * a distance reads in the small unit.
   *
   * A thousand and not "under one mile", which is where this started and
   * was wrong in a way worth recording: at that threshold 1 km came out as
   * "3281 ft", because 1 km is 0.62 of a mile. Technically right, useless
   * to read. A thousand is the point where the small unit stops being
   * easier than the big one, and it makes both unit systems switch at
   * roughly the same real distance.
   */
  const SMALL_UNIT_LIMIT = 1000;

  /**
   * A distance given in kilometres.
   *
   * Feet for short hops -- "530 ft" is a better answer than "0.1 miles"
   * for two nodes in one street -- and miles once that stops helping.
   */
  function distanceFromKm(km, { digits = 1 } = {}) {
    const value = num(km);
    if (value === null) return '';
    if (!imperial()) {
      const metres = value * 1000;
      return metres < SMALL_UNIT_LIMIT
        ? `${Math.round(metres)} m`
        : `${value.toFixed(digits)} km`;
    }
    const feet = value * 1000 * FEET_PER_METRE;
    if (feet < SMALL_UNIT_LIMIT) return `${Math.round(feet)} ft`;
    return `${(value * MILES_PER_KM).toFixed(digits)} mi`;
  }

  /** A distance given in metres. */
  function distanceFromM(metres) {
    const value = num(metres);
    if (value === null) return '';
    return distanceFromKm(value / 1000);
  }

  /**
   * A height or an altitude, given in metres.
   *
   * Whole units both ways: nobody states a mast to a tenth of a foot, and
   * a tenth of a metre is below the accuracy of the altitude these come
   * from.
   */
  function heightFromM(metres) {
    const value = num(metres);
    if (value === null) return '';
    /*
     * Grouped, because these run into the thousands: a mountain-top node
     * at 9,000 ft reads as "9000 ft" without it, and the RF page had its
     * own `toLocaleString` here for exactly that reason before this
     * module existed.
     */
    const rounded = Math.round(imperial() ? value * FEET_PER_METRE : value);
    return `${rounded.toLocaleString()} ${imperial() ? 'ft' : 'm'}`;
  }

  /** A temperature given in Celsius, which is how the sensors report. */
  function temperatureFromC(celsius, { digits = 1 } = {}) {
    const value = num(celsius);
    if (value === null) return '';
    return fahrenheit()
      ? `${(value * 9 / 5 + 32).toFixed(digits)} °F`
      : `${value.toFixed(digits)} °C`;
  }

  /**
   * An area given in square kilometres, as coverage reports it.
   *
   * Whole units once it is ten or more, because nobody reads a coverage
   * area to a tenth of a square mile. Below ten, one decimal place, so a
   * small area does not read as "0".
   */
  function areaFromKm2(km2) {
    const value = num(km2);
    if (value === null) return '';
    const shown = imperial() ? value * MILES_PER_KM * MILES_PER_KM : value;
    const text = shown >= 10
      ? Math.round(shown).toLocaleString()
      : shown.toFixed(1);
    return `${text} ${imperial() ? 'mi²' : 'km²'}`;
  }

  /**
   * A speed given in metres per second, as Meshtastic reports it.
   *
   * Miles per hour or kilometres per hour, not metres per second: the
   * reader compares a wind or a vehicle with a road sign, and road signs
   * are in one of those two.
   */
  function speedFromMs(metresPerSecond) {
    const value = num(metresPerSecond);
    if (value === null) return '';
    const kmh = value * 3.6;
    return imperial()
      ? `${(kmh * MILES_PER_KM).toFixed(1)} mph`
      : `${kmh.toFixed(1)} km/h`;
  }

  /** A speed given in kilometres per hour. */
  function speedFromKmh(kmh) {
    const value = num(kmh);
    if (value === null) return '';
    return speedFromMs(value / 3.6);
  }

  /** A speed given in knots, as APRS and weather stations send it. */
  function speedFromKn(knots) {
    const value = num(knots);
    if (value === null) return '';
    return speedFromMs(value * METRES_PER_SECOND_PER_KNOT);
  }

  /**
   * A small length given in millimetres: rainfall, snow.
   *
   * Two decimal places in inches and one in millimetres. A hundredth of
   * an inch is how a rain gauge reads in the United States, and it is
   * about a quarter of a millimetre.
   */
  function lengthFromMm(mm) {
    const value = num(mm);
    if (value === null) return '';
    return imperial()
      ? `${(value / MM_PER_INCH).toFixed(2)} in`
      : `${value.toFixed(1)} mm`;
  }

  /**
   * An air pressure given in hectopascals, as the sensors report it.
   *
   * Inches of mercury in imperial mode (Will, #291). Two decimal places,
   * which is how a barometer in inches is read.
   */
  function pressureFromHpa(hpa) {
    const value = num(hpa);
    if (value === null) return '';
    return imperial()
      ? `${(value * INHG_PER_HPA).toFixed(2)} inHg`
      : `${value.toFixed(1)} hPa`;
  }

  /*
   * The SI units the API names, and the function that turns each into the
   * reader's units. Keys are the exact spellings the API sends.
   */
  const MEASURES = {
    km: distanceFromKm,
    m: distanceFromM,
    '°C': temperatureFromC,
    'km²': areaFromKm2,
    'm/s': speedFromMs,
    'km/h': speedFromKmh,
    mm: lengthFromMm,
    hPa: pressureFromHpa,
  };

  /**
   * A value the API sent with its unit, in the reader's units.
   *
   * For payloads that carry `{value, unit}` rather than a named field,
   * such as the leaderboards and the firehose summary. A unit this module
   * does not convert (a percentage, a count of gateways, a decibel) is
   * passed through unchanged. A missing value is blank, never "0".
   */
  function measure(value, unit) {
    const n = num(value);
    if (n === null) return '';
    const convert = MEASURES[unit];
    if (convert) return convert(n);
    return unit ? `${n.toLocaleString()} ${unit}` : n.toLocaleString();
  }

  /**
   * The word for the unit a typed field is in, for a label.
   *
   * Used where a reader types a number rather than reads one, so the label
   * has to say which unit the box is in.
   */
  function heightUnit() {
    return imperial() ? 'ft' : 'm';
  }

  function distanceUnit() {
    return imperial() ? 'mi' : 'km';
  }

  /**
   * A typed height, back into metres for the API or the model.
   *
   * The other direction, and the one that matters for correctness: a form
   * that accepts feet must not hand feet to something expecting metres.
   */
  function heightToM(typed) {
    const value = num(typed);
    if (value === null) return null;
    return imperial() ? value / FEET_PER_METRE : value;
  }

  return {
    imperial,
    fahrenheit,
    distanceFromKm,
    distanceFromM,
    heightFromM,
    temperatureFromC,
    areaFromKm2,
    speedFromMs,
    speedFromKmh,
    speedFromKn,
    lengthFromMm,
    pressureFromHpa,
    measure,
    heightUnit,
    distanceUnit,
    heightToM,
    FEET_PER_METRE,
    MILES_PER_KM,
  };
}());
