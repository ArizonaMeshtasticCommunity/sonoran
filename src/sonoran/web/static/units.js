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
    heightUnit,
    distanceUnit,
    heightToM,
    FEET_PER_METRE,
    MILES_PER_KM,
  };
}());
