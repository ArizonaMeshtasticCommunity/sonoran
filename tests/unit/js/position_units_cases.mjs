/*
 * Behaviour cases for a position's ground speed and ground track: the
 * units the firmware sends them in, and what a packet page and a node
 * page print.
 *
 * Run by `tests/unit/test_position_units.py`, which shells out to node.
 *
 * The report (Discord, 2026-10-25): packet !a6960bfc/2507943990 carries a
 * raw ground speed of 127 and the site printed 284 mph. 127 is km/h
 * already, which is 79 mph. 127 m/s is 284 mph, so the site read it as
 * metres per second. The same packet's ground track is 30975000 and the
 * site printed "30975000 deg".
 *
 * Sources for the expected numbers:
 * - meshtastic/protobufs meshtastic/mesh.proto, Position.ground_speed:
 *   "Ground speed in km/h".
 * - meshtastic/firmware src/gps/GPS.cpp: `p.ground_speed =
 *   reader.speed.kmph();` and `p.ground_track = reader.course.value() *
 *   1e3; // ... match the expected degrees * 10^-5`.
 * - meshtastic/firmware src/modules/PositionModule.cpp: "ground_track is
 *   stored as degrees * 1e5".
 *
 * `app.js` is one big script, not a module, so the pieces under test are
 * cut out of the shipped file by name. `SONORAN_APP_JS` points the cases
 * at another copy, which is how the Python side runs them against a
 * deliberately broken one. The units formatter is the real `units.js`.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const STATIC = join(here, '../../../src/sonoran/web/static');
const file = process.env.SONORAN_APP_JS || join(STATIC, 'app.js');
const source = readFileSync(file, 'utf8');

/** Pull one top-level `function name(...) { ... }` out of the file. */
function extract(name) {
  const start = source.indexOf(`\nfunction ${name}(`);
  if (start < 0) throw new Error(`${name} not found in app.js`);
  const end = source.indexOf('\n}', start + 1);
  if (end < 0) throw new Error(`${name} has no closing brace`);
  return source.slice(start, end + 2);
}

/** A one-line `const NAME = ...;`, or a multi-line object ending `\n};`. */
function constant(name) {
  const start = source.indexOf(`\nconst ${name} =`);
  if (start < 0) throw new Error(`${name} not found in app.js`);
  const line = source.slice(start, source.indexOf('\n', start + 1));
  if (!line.trimEnd().endsWith('{')) return `${line}\n`;
  return source.slice(start, source.indexOf('\n};', start) + 3);
}

/** The real units formatter, set to imperial or metric. */
function units(choice) {
  const saved = { 'sonoran.settings': JSON.stringify({ units: choice }) };
  const sandbox = {
    window: {
      localStorage: {
        getItem: (key) => (key in saved ? saved[key] : null),
        setItem: () => {},
      },
      addEventListener: () => {},
    },
    console: { warn() {} },
    JSON,
  };
  vm.createContext(sandbox);
  for (const name of ['settings.js', 'units.js']) {
    new vm.Script(readFileSync(join(STATIC, name), 'utf8')).runInContext(sandbox);
  }
  return sandbox.window.SonoranUnits;
}

/* A DOM stand-in: enough of `el` to read what a panel would draw. */
const el = (tag, attrs = {}, ...kids) => ({ tag, attrs, kids: kids.flat().filter((k) => k != null) });

/** The `dt` -> `dd` pairs of a drawn `dl`. */
function pairs(dl) {
  const out = {};
  for (let i = 0; i < dl.kids.length; i += 2) out[dl.kids[i].attrs.text] = dl.kids[i + 1].attrs.text;
  return out;
}

function load(choice) {
  const stubs = {
    el,
    SonoranUnits: units(choice),
    WEATHER_LABELS: {},
    DEVICE_LABELS: {},
    // Two lines in app.js, so `constant` cannot cut it out. Same body.
    round: (value, digits = 1) =>
      (value == null ? null : Math.round(value * 10 ** digits) / 10 ** digits),
  };
  return new Function(...Object.keys(stubs), [
    extract('precisionMetres'),
    constant('DECODED_LABELS'),
    extract('decodedValues'),
    extract('positionValues'),
    'return { DECODED_LABELS, decodedValues, positionValues };',
  ].join('\n'))(...Object.values(stubs));
}

let failed = 0;
let ran = 0;
const eq = (name, got, want) => {
  ran += 1;
  if (got === want) return;
  failed += 1;
  console.error(`FAIL ${name}\n  got  ${JSON.stringify(got)}\n  want ${JSON.stringify(want)}`);
};

// The reported packet, as position_metrics stores it on the box.
const reported = {
  latitude: 33.5, longitude: -112.1, altitude: 400,
  ground_speed: 127, ground_track: 30975000, precision_bits: 32, sats_in_view: 9,
};

for (const [choice, speed] of [['imperial', '78.9 mph'], ['metric', '127.0 km/h']]) {
  const api = load(choice);
  const packet = pairs(api.decodedValues(reported));
  eq(`KMH: the packet page reads ground speed 127 as km/h (${choice})`, packet['Ground speed'], speed);
  const node = pairs(api.positionValues(reported));
  eq(`KMH: the node page reads ground speed 127 as km/h (${choice})`, node['Ground speed'], speed);
}

const api = load('imperial');
// A plausible wrong fix: the old m/s reading is 3.6 times too fast.
eq('WOULD BE CAUGHT: a truck at 127 km/h is not shown at 284 mph',
  pairs(api.decodedValues({ ground_speed: 127 }))['Ground speed'] === '284.1 mph', false);

if (failed) {
  console.error(`${failed} of ${ran} checks failed`);
  process.exit(1);
}
console.log(`${ran} checks passed`);
