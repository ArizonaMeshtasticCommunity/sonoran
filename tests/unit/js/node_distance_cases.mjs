/*
 * Behaviour cases for the node page's estimated distances (#257).
 *
 * `roughKm` is the one place a distance from a rounded position becomes
 * text. Three claims, each about a value, so they are run and not read:
 *
 *  - the estimate is rounded to its own error, never printed finer;
 *  - an error as large as the distance gives an upper bound, not an
 *    estimate that the error swallows;
 *  - a missing estimate gives nothing, never "about 0 ft".
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const static_ = join(here, '../../../src/sonoran/web/static');
const source = readFileSync(join(static_, 'app.js'), 'utf8');

function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  const end = source.indexOf('\n}', start);
  return source.slice(start, end + 2);
}

function block(prefix) {
  const start = source.indexOf(prefix);
  if (start < 0) throw new Error(`${prefix} not found`);
  const end = source.indexOf(');\n', start);
  return source.slice(start, end + 3);
}

// The real units module, in metric, so the numbers read back in km.
globalThis.window = { SonoranSettings: { isImperial: () => false, get: () => 'celsius' } };
new Function(readFileSync(join(static_, 'units.js'), 'utf8'))();
const { SonoranUnits } = globalThis.window;
const roughKm = new Function('SonoranUnits',
  `${block('const km = (value) => (')}\n${extract('roughKm')}; return roughKm;`)(SonoranUnits);

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

// A 2.9 km error (13-bit rounding) rounds the estimate to whole km.
const coarse = roughKm(288.52, 2.9);
ok('an estimate is rounded to its own error, not printed to a tenth',
  coarse && coarse.value === 'about 289 km', JSON.stringify(coarse));
ok('the error bar travels with it', coarse && coarse.bar === '± 2.9 km', JSON.stringify(coarse));

// A 23.3 km error (10-bit rounding) rounds to tens.
const wide = roughKm(147.2, 23.3);
ok('an estimate is rounded to its own error: a wider error rounds to tens', wide && wide.value === 'about 150 km', JSON.stringify(wide));

// Under a kilometre of error, a tenth is earned.
const fine = roughKm(12.34, 0.73);
ok('an estimate is rounded to its own error: a small error keeps a tenth', fine && fine.value === 'about 12.3 km', JSON.stringify(fine));

// An error as large as the distance: only an upper bound is true.
const swallowed = roughKm(5, 5.8);
ok('an error as large as the distance gives an upper bound',
  swallowed && /^under /.test(swallowed.value) && swallowed.value === 'under 11 km',
  JSON.stringify(swallowed));

// Absent is not zero.
ok('a missing estimate gives nothing, never "about 0"', roughKm(null, 2.9) === null);
ok('a missing error gives nothing, never an estimate with no bar', roughKm(100, null) === null);
ok('no error at all is not an estimate', roughKm(100, 0) === null);

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('node distance cases: all passed');
