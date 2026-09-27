/*
 * Behaviour cases for the node page's Identity and Device fields (#254).
 *
 * Run by `tests/unit/test_node_fields.py`, which shells out to node.
 *
 * Run rather than read. What matters is what the shipped functions DO
 * at each threshold and with a missing value, and a source grep cannot
 * tell `>=` from `>` at a boundary, or see that `null < 5` is true.
 *
 * `app.js` is one big script, not a module, so the functions under test
 * are cut out of the shipped file by name. `SONORAN_APP_JS` points the
 * cases at another copy, which is how the Python side runs them against
 * a deliberately broken one without touching the real file.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const file = process.env.SONORAN_APP_JS || join(here, '../../../src/sonoran/web/static/app.js');
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

/* A DOM stand-in: enough of `el` to see what the panel would draw. */
const el = (tag, attrs = {}, ...kids) => ({ tag, attrs, kids: kids.flat().filter((k) => k != null) });
const text = (node) => (typeof node === 'string' ? node
  : [node.attrs.text || '', ...node.kids.map(text)].join(''));

const stubs = {
  el,
  round: (value, digits = 1) => (value == null ? null : Math.round(value * 10 ** digits) / 10 ** digits),
  roleLabel: (role) => role,
  yesNo: (value) => (value == null ? null : value ? 'Yes' : 'No'),
  stamp: (value) => (value ? 'STAMP' : '-'),
  ago: () => '1h',
  SonoranUnits: { heightFromM: (m) => `${m} m` },
};

const names = [
  'BATTERY_LOW', 'BATTERY_WEAK', 'ON_MAINS_ABOVE',
  'CHANNEL_USE_POLITE', 'CHANNEL_USE_MAX', 'AIR_TX_CHECK', 'AIR_TX_HIGH',
  'ALTITUDE_NOT_OURS', 'HEALTH_STATES', 'DEVICE_LABELS', 'FIELD_FLAGS',
];
const functions = [
  'reading', 'batteryState', 'fieldFlag', 'altitudeFlag', 'fieldValue',
  'deviceRows', 'identityRows',
];
const api = new Function(...Object.keys(stubs), [
  ...names.map(constant),
  ...functions.map(extract),
  `return { ${[...names, ...functions].join(', ')} };`,
].join('\n'))(...Object.values(stubs));

let failed = 0;
let ran = 0;
const check = (name, cond, detail = '') => {
  ran += 1;
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};
const state = (key, value) => (api.fieldFlag(key, value) || { state: 'none' }).state;

/* --- Absent is not bad ------------------------------------------ */

for (const key of ['battery_level', 'channel_utilization', 'air_util_tx']) {
  for (const missing of [null, undefined, NaN, '', '0']) {
    check(`ABSENT: a ${key} of ${JSON.stringify(missing)} is not a reading and is never flagged`,
      api.fieldFlag(key, missing) === null,
      `got ${JSON.stringify(api.fieldFlag(key, missing))}`);
  }
}
check('ABSENT: a node with no battery level is unknown, not flat',
  api.batteryState(null) === 'unknown', `got ${api.batteryState(null)}`);
check('ABSENT: a Device panel with nothing sent draws no rows at all',
  api.deviceRows({ battery_level: null, channel_utilization: null, air_util_tx: null }).length === 0);

/* --- Each line, at the line ------------------------------------- */

const { CHANNEL_USE_POLITE: POLITE, CHANNEL_USE_MAX: MAX, AIR_TX_CHECK: TX_CHECK, AIR_TX_HIGH: TX_HIGH } = api;
check('FIRMWARE: the polite channel line is 25 % (src/airtime.h)', POLITE === 25, `got ${POLITE}`);
check('FIRMWARE: the hard channel line is 40 % (src/airtime.h)', MAX === 40, `got ${MAX}`);
check('TIED: air time red is the polite channel line, one constant', TX_HIGH === POLITE);
const bands = [
  ['channel_utilization', POLITE - 0.1, 'none'], ['channel_utilization', POLITE, 'warn'],
  ['channel_utilization', MAX - 0.1, 'warn'], ['channel_utilization', MAX, 'bad'],
  ['channel_utilization', 0, 'none'],
  ['air_util_tx', TX_CHECK - 0.1, 'none'], ['air_util_tx', TX_CHECK, 'warn'],
  ['air_util_tx', TX_HIGH - 0.1, 'warn'], ['air_util_tx', TX_HIGH, 'bad'],
  ['air_util_tx', 0, 'none'],
  // The Power card's band, so the card and the row agree.
  ['battery_level', api.BATTERY_WEAK + 1, 'none'], ['battery_level', api.BATTERY_WEAK, 'warn'],
  ['battery_level', api.BATTERY_LOW, 'warn'], ['battery_level', api.BATTERY_LOW - 1, 'bad'],
  ['battery_level', 0, 'bad'], ['battery_level', 100, 'none'], ['battery_level', 101, 'none'],
];
for (const [key, value, want] of bands) {
  // The firmware holds back AT the figure (it sends while util < figure).
  check(`BOUNDARY: ${key} ${value} is ${want}`, state(key, value) === want, `got ${state(key, value)}`);
}
check('MAINS: 101 is external power, never a battery reading',
  api.batteryState(101) === 'mains');
const mains = api.deviceRows({ battery_level: 101 })[0];
check('MAINS: the row says "External power", not "101 %"', mains && mains.text === 'External power',
  `got ${mains && mains.text}`);

/* --- Every flag has words, not only a colour --------------------- */

for (const [key, value] of [['channel_utilization', MAX], ['air_util_tx', TX_CHECK], ['battery_level', 1]]) {
  const flag = api.fieldFlag(key, value);
  const dd = api.fieldValue('x', flag);
  check(`WORDS: a flagged ${key} carries a word beside the colour (WCAG 1.4.1)`,
    flag && flag.word && text(dd).includes(flag.word), `drew ${JSON.stringify(text(dd))}`);
  const glyph = JSON.stringify(dd).includes('"aria-hidden":"true"');
  check(`WORDS: the glyph on ${key} is hidden from a screen reader, the word is not`, glyph);
}
check('WORDS: an unflagged value is a plain dd', api.fieldValue('3 %', null).attrs.class == null);

/* --- Altitude: three states, and the one exemption --------------- */

const node = (position, role = 'CLIENT') => ({ node_id: '!1', role, position });
const altitude = (n) => api.identityRows(n).find((row) => row.key === 'altitude');
check('ALTITUDE: no position at all is not red for altitude',
  api.altitudeFlag(node(null)) === null);
check('ALTITUDE: no position draws no altitude row', altitude(node(null)) === undefined);
const noAlt = altitude(node({ lat: 33.4, lon: -112, altitude: null }));
check('ALTITUDE: position without altitude reads "Unknown", capitalised',
  noAlt && noAlt.text === 'Unknown', `got ${noAlt && noAlt.text}`);
check('ALTITUDE: position without altitude is red',
  noAlt && noAlt.flag && noAlt.flag.state === 'bad', `got ${JSON.stringify(noAlt && noAlt.flag)}`);
const withAlt = altitude(node({ lat: 33.4, lon: -112, altitude: 400 }));
check('ALTITUDE: position with altitude is not red', withAlt && !withAlt.flag,
  `got ${JSON.stringify(withAlt && withAlt.flag)}`);
check('ALTITUDE: TAK sends altitude_hae, which ingest drops, so it is not red',
  api.altitudeFlag(node({ lat: 33.4, lon: -112, altitude: null }, 'TAK')) === null
    && api.altitudeFlag(node({ lat: 33.4, lon: -112, altitude: null }, 'TAK_TRACKER')) === null);

/* --- Placeholders are capitalised -------------------------------- */

const bare = api.identityRows({ node_id: '!1', position: null });
for (const row of bare) {
  check(`CAPITAL: ${row.label} placeholder "${row.text}" starts with a capital or a symbol`,
    !/^[a-z]/.test(String(row.text)));
}
check('CAPITAL: the three placeholders are the ones this page uses',
  ['Not reported', 'Unknown', 'Never'].every((word) => bare.some((row) => row.text === word)),
  `got ${JSON.stringify(bare.map((row) => row.text))}`);

/* --- The Power card reads the same band -------------------------- */

const health = source.slice(source.indexOf('\nfunction healthChecks('), source.indexOf('\n}', source.indexOf('\nfunction healthChecks(')));
check('ONE BAND: the Power card asks batteryState, as the Device row does',
  health.includes('batteryState(battery)'));
check('ONE BAND: the Power card holds no comparison of its own against the battery constants',
  !/BATTERY_WEAK \?|BATTERY_LOW \?|>= BATTERY_LOW/.test(health));

/* The harness guard: a harness that found nothing to check passes. */
if (ran < 40) {
  console.error(`FAIL the harness ran only ${ran} checks; the extraction is broken`);
  failed += 1;
}
if (failed) {
  console.error(`\n${failed} of ${ran} checks failed`);
  process.exit(1);
}
console.log(`all ${ran} checks passed`);
