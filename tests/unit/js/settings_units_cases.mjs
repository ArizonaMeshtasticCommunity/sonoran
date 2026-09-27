/*
 * The settings store and the units formatter.
 *
 * The cases that matter are the refusals and the thresholds. A settings
 * store that accepts a value no control can show puts the site in a state
 * the reader cannot undo, and a formatter with the wrong threshold is
 * technically correct and useless to read.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SRC = (name) => readFileSync(
  new URL(`../../../src/sonoran/web/static/${name}`, import.meta.url), 'utf8',
);

/** A fresh pair of modules with their own storage. */
function load({ saved = {}, storage = true } = {}) {
  const store = { ...saved };
  const localStorage = storage
    ? {
      getItem: (key) => (key in store ? store[key] : null),
      setItem: (key, value) => { store[key] = value; },
    }
    : {
      getItem() { throw new Error('blocked'); },
      setItem() { throw new Error('blocked'); },
    };
  /*
   * `addEventListener` is captured rather than stubbed away, because the
   * cross-tab path is only reachable through it. `fire` is what a second
   * tab's write looks like from in here: the value is already in storage
   * (the browser writes before it dispatches) and the event names the key.
   */
  const registered = [];
  const sandbox = {
    window: {
      localStorage,
      addEventListener: (type, fn) => registered.push([type, fn]),
    },
    console: { warn() {} },
    JSON,
  };
  vm.createContext(sandbox);
  for (const name of ['settings.js', 'units.js']) {
    new vm.Script(SRC(name)).runInContext(sandbox);
  }
  const fire = (key) => {
    for (const [type, fn] of registered) if (type === 'storage') fn({ key });
  };
  return {
    S: sandbox.window.SonoranSettings,
    U: sandbox.window.SonoranUnits,
    store,
    fire,
    registered,
  };
}

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
};

// --- defaults -------------------------------------------------------
{
  const { S } = load();
  eq('imperial by default (Will asked for miles and feet)', S.get('units'), 'imperial');
  eq('fahrenheit by default', S.get('temperature'), 'fahrenheit');
  eq('the theme follows the device by default', S.get('theme'), 'system');
}

// --- refusals, which are the point ----------------------------------
{
  const { S } = load();
  eq('an unknown value is refused', S.set('units', 'furlongs'), false);
  eq('and nothing changed', S.get('units'), 'imperial');
  eq('an unknown setting is refused', S.set('nonsense', 'x'), false);
  eq('setting the same value is not a change', S.set('units', 'imperial'), false);
  eq('a real change returns true', S.set('units', 'metric'), true);
}

// A stored value that was valid once, or was hand-edited, must not pin the
// site to a state no control can show.
eq('a stale stored value is ignored',
  load({ saved: { 'sonoran.settings': '{"units":"furlongs"}' } }).S.get('units'), 'imperial');
eq('unparseable storage is ignored',
  load({ saved: { 'sonoran.settings': 'not json' } }).S.get('units'), 'imperial');
eq('a stored array is ignored',
  load({ saved: { 'sonoran.settings': '[1,2]' } }).S.get('units'), 'imperial');
eq('stored null is ignored',
  load({ saved: { 'sonoran.settings': 'null' } }).S.get('units'), 'imperial');

// --- the theme keeps its own key ------------------------------------
// The pre-paint script in index.html reads `sonoran.theme` directly, so
// moving the value into the blob would either bring back the flash of the
// wrong colours or silently reset everybody who has already chosen.
eq('an existing theme choice is honoured',
  load({ saved: { 'sonoran.theme': 'dark' } }).S.get('theme'), 'dark');
{
  const { S, store } = load();
  S.set('theme', 'light');
  eq('the theme is written where the boot script looks', store['sonoran.theme'], 'light');
  S.set('units', 'metric');
  eq('and is not duplicated into the blob',
    JSON.parse(store['sonoran.settings']).theme, undefined);
}

// --- storage that throws --------------------------------------------
{
  const { S } = load({ storage: false });
  eq('blocked storage still has defaults', S.get('units'), 'imperial');
  eq('and can still be changed for this visit', S.set('units', 'metric'), true);
  eq('which takes effect', S.get('units'), 'metric');
}

// --- subscribers ----------------------------------------------------
{
  const { S } = load();
  const seen = [];
  S.onChange((name, value) => { throw new Error('boom'); });
  S.onChange((name, value) => seen.push([name, value]));
  S.set('units', 'metric');
  eq('a throwing subscriber does not stop the rest', seen, [['units', 'metric']]);
}

// --- distances ------------------------------------------------------
{
  const { U } = load();
  eq('164 ft for 50 m', U.distanceFromKm(0.05), '164 ft');
  eq('984 ft for 300 m', U.distanceFromKm(0.3), '984 ft');
  // The threshold. At "under one mile" this returned "3281 ft" for 1 km --
  // right, and useless. A thousand feet is where the small unit stops
  // helping.
  eq('0.6 mi for 1 km, not 3281 ft', U.distanceFromKm(1), '0.6 mi');
  eq('7.8 mi for 12.5 km', U.distanceFromKm(12.5), '7.8 mi');
  eq('93.2 mi for 150 km', U.distanceFromKm(150), '93.2 mi');
  eq('metres in, same answer', U.distanceFromM(300), '984 ft');
  // The fifth instance of one bug shape in this repository: `Number(null)`
  // is 0 and 0 is finite, so a MISSING distance rendered as "0 ft" --
  // which claims two nodes are on top of each other. See #149, #157, #197
  // and #190 for the others.
  eq('a missing distance is nothing, not 0 ft', U.distanceFromKm(null), '');
  eq('undefined is nothing', U.distanceFromKm(undefined), '');
  eq('an empty string is nothing', U.distanceFromKm(''), '');
  eq('text is nothing', U.distanceFromKm('far'), '');
  // And the half that keeps it honest: a real zero is a measurement.
  eq('two nodes at one spot are 0 ft apart', U.distanceFromKm(0), '0 ft');
  eq('a real zero height is 0 ft', U.heightFromM(0), '0 ft');
  eq('a missing height is nothing', U.heightFromM(null), '');
  eq('a missing temperature is nothing', U.temperatureFromC(null), '');
}
{
  const { S, U } = load();
  S.set('units', 'metric');
  eq('50 m stays 50 m', U.distanceFromKm(0.05), '50 m');
  eq('999 m is metres', U.distanceFromKm(0.999), '999 m');
  eq('1 km is kilometres', U.distanceFromKm(1), '1.0 km');
  eq('both systems switch at about the same real distance',
    [U.distanceFromKm(0.3).endsWith('m'), true], [true, true]);
}

// --- heights, whole units both ways ---------------------------------
{
  const { S, U } = load();
  eq('a 9 m mast is 30 ft', U.heightFromM(9), '30 ft');
  eq('not 29.53 ft', U.heightFromM(9).includes('.'), false);
  eq('the unit word for a typed box', U.heightUnit(), 'ft');
  // The direction that matters for correctness: a form in feet must not
  // hand feet to something expecting metres.
  eq('30 ft typed comes back as metres', U.heightToM(30).toFixed(3), '9.144');
  S.set('units', 'metric');
  eq('9 m stays 9 m', U.heightFromM(9), '9 m');
  eq('30 m typed is 30 m', U.heightToM(30), 30);
}

// --- temperature ----------------------------------------------------
{
  const { S, U } = load();
  eq('37.1 C is 98.8 F', U.temperatureFromC(37.1), '98.8 °F');
  eq('0 C is 32 F', U.temperatureFromC(0), '32.0 °F');
  eq('a real zero is not treated as missing', U.temperatureFromC(0) !== '', true);
  S.set('temperature', 'celsius');
  eq('37.1 C stays 37.1 C', U.temperatureFromC(37.1), '37.1 °C');
}

// --- the conversion constants ---------------------------------------
{
  const { U } = load();
  eq('feet per metre', U.FEET_PER_METRE.toFixed(6), '3.280840');
  eq('miles per km', U.MILES_PER_KM.toFixed(6), '0.621371');
}

/*
 * Thousands are grouped.
 *
 * Arizona has nodes on mountain tops: Mount Ord is about 2,200 m, which is
 * over 7,000 ft. "7218 ft" is a number you have to count the digits of.
 * The RF page had its own `toLocaleString` for this before units.js
 * existed, and dropping it while moving the call there would have been a
 * silent downgrade rather than a visible one.
 */
{
  const { S, U } = load();
  eq('a mountain-top altitude is grouped', U.heightFromM(2200), '7,218 ft');
  S.set('units', 'metric');
  eq('and grouped in metric too', U.heightFromM(2200), '2,200 m');
  eq('a small height needs no separator', U.heightFromM(9), '9 m');
}

/*
 * Another tab changed a setting.
 *
 * Without this, two open tabs disagree: the reader switches to miles in
 * one, comes back to the other, and sees kilometres with the switch on
 * screen saying "miles". The listener is the only thing that closes that,
 * and it has to announce so the page redraws -- dropping the cache alone
 * would leave the OLD render on screen until something else re-rendered.
 */
{
  const { S, fire, store } = load();
  const seen = [];
  S.onChange((name, value) => seen.push([name, value]));
  eq('imperial to start', S.get('units'), 'imperial');

  // What the other tab did: wrote storage, then the browser dispatched.
  store['sonoran.settings'] = JSON.stringify({ units: 'metric' });
  fire('sonoran.settings');
  eq('the new value is read back', S.get('units'), 'metric');
  eq('and it was announced, so the page redraws', seen, [['units', 'metric']]);
}

{
  // An unrelated key must not cost a re-read or announce a change. Any
  // site on the origin can write its own keys.
  const { S, fire } = load();
  const seen = [];
  S.onChange((name) => seen.push(name));
  fire('some.other.app');
  eq('another key is ignored', seen, []);
  eq('and the value is untouched', S.get('units'), 'imperial');
}

{
  // localStorage.clear() in another tab arrives as key === null, and every
  // setting goes back to its default. Announcing that is right: the page
  // is now showing values that no longer match storage.
  const { S, fire, store } = load();
  S.set('units', 'metric');
  const seen = [];
  S.onChange((name, value) => seen.push([name, value]));
  delete store['sonoran.settings'];
  fire(null);
  eq('a cleared storage falls back to the default', S.get('units'), 'imperial');
  eq('and says so', seen, [['units', 'imperial']]);
}

/*
 * A storage event that changes nothing must stay silent, or every tab
 * redraws whenever any tab writes the value it already had.
 */
{
  const { S, fire, store } = load();
  const seen = [];
  S.onChange((name) => seen.push(name));
  store['sonoran.settings'] = JSON.stringify({ units: 'imperial' });
  fire('sonoran.settings');
  eq('no change means no announcement', seen, []);
}

// --- measure: a value the API sent with its SI unit (#291) ------------
/*
 * The link leaderboard sent `"unit": "km"` and the page printed it as it
 * came, so Statistics read km in every mode. `measure` is the one place a
 * `{value, unit}` pair becomes text.
 */
{
  const { S, U } = load();
  eq('km in imperial', U.measure(25, 'km'), '15.5 mi');
  eq('m in imperial', U.measure(120, 'm'), '394 ft');
  eq('°C in fahrenheit', U.measure(21.5, '°C'), '70.7 °F');
  eq('hPa is inches of mercury in imperial (Will, #291)', U.measure(1013.25, 'hPa'), '29.92 inHg');
  eq('mm is inches in imperial (Will, #291)', U.measure(25.4, 'mm'), '1.00 in');
  eq('m/s is mph in imperial', U.measure(10, 'm/s'), '22.4 mph');
  eq('km² is mi² in imperial', U.measure(100, 'km²'), '39 mi²');
  eq('an unknown unit passes through', U.measure(95.5, '%'), '95.5 %');
  eq('a word for a unit passes through', U.measure(3, 'gateways'), '3 gateways');
  eq('null is blank, never 0', U.measure(null, 'km'), '');
  eq('undefined is blank', U.measure(undefined, 'm'), '');
  eq('an empty string is blank', U.measure('', '°C'), '');
  eq('null in an unknown unit is blank too', U.measure(null, '%'), '');
  eq('a real zero is still a reading', U.measure(0, '°C'), '32.0 °F');
  S.set('units', 'metric');
  S.set('temperature', 'celsius');
  eq('km in metric', U.measure(25, 'km'), '25.0 km');
  eq('m in metric', U.measure(120, 'm'), '120 m');
  eq('°C in celsius', U.measure(21.5, '°C'), '21.5 °C');
  eq('hPa in metric', U.measure(1013.25, 'hPa'), '1013.3 hPa');
  eq('mm in metric', U.measure(2.5, 'mm'), '2.5 mm');
  eq('m/s is km/h in metric', U.measure(10, 'm/s'), '36.0 km/h');
  eq('km² in metric', U.measure(4.25, 'km²'), '4.3 km²');
}

// --- speeds from the other sources ------------------------------------
{
  const { S, U } = load();
  eq('knots in imperial', U.speedFromKn(10), '11.5 mph');
  eq('km/h in imperial', U.speedFromKmh(100), '62.1 mph');
  eq('a missing speed is blank', U.speedFromKn(null), '');
  S.set('units', 'metric');
  eq('knots in metric', U.speedFromKn(10), '18.5 km/h');
}

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
