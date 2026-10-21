/*
 * The radio climate from the site (#239), exercised.
 *
 * Three things are held here:
 *
 * 1. The page reads the same cell the server reads. The real shipped
 *    data is unpacked and cut into a page exactly as
 *    `sonoran/climate/store.py::page` cuts it, so Phoenix and Flagstaff
 *    are asserted against the data that ships, not a mock.
 * 2. `auto` is answered before the engine, and a place with no class
 *    falls back to desert and says so.
 * 3. A link made before this change predicts what it predicted then: a
 *    version 1 link that names no climate keeps desert.
 *
 * `test_planner_climate.py` runs this under node.
 */
import { readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import vm from 'node:vm';

const SRC = readFileSync(
  new URL('../../../src/sonoran/web/static/planner-params.js', import.meta.url),
  'utf8',
);

function load() {
  const sandbox = { window: {}, URLSearchParams };
  vm.createContext(sandbox);
  new vm.Script(SRC).runInContext(sandbox);
  return sandbox.window.SonoranPlannerParams;
}

const P = load();

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
};
const throws = (name, fn) => {
  try { fn(); failed += 1; console.log(`  FAIL ${name}: nothing was thrown`); }
  catch { console.log(`  PASS ${name}`); }
};

// --- the shipped data, cut as the server cuts it ---------------------
const CELLS = 120;
const CROP = { south: 30, north: 38, west: -116, east: -108 };
const grid = gunzipSync(readFileSync(
  new URL('../../../src/sonoran/climate/koppen_1991_2020.u8.gz', import.meta.url),
));
const columns = (CROP.east - CROP.west) * CELLS;

/** What `/api/climate/page/{tile}` returns for the square at (lat, lon). */
function servedPage(latitude, longitude) {
  const top = (CROP.north - latitude - 1) * CELLS;
  const left = (longitude - CROP.west) * CELLS;
  const out = new Uint8Array(CELLS * CELLS);
  for (let row = 0; row < CELLS; row += 1) {
    out.set(grid.subarray((top + row) * columns + left, (top + row) * columns + left + CELLS), row * CELLS);
  }
  return out;
}

/** The whole lookup the page does: name the square, fetch it, read the cell. */
function koppenAt(latitude, longitude) {
  const tile = P.tileNameOf(latitude, longitude);
  const lat = (tile[0] === 'N' ? 1 : -1) * Number(tile.slice(1, 3));
  const lon = (tile[3] === 'E' ? 1 : -1) * Number(tile.slice(4, 7));
  return P.climateCell(servedPage(lat, lon), latitude, longitude, CELLS);
}

eq('the shipped grid is the 960 by 960 crop', grid.length, 960 * 960);
eq('Phoenix is BWh (4)', koppenAt(33.4342, -112.0116), 4);
eq('Flagstaff is Dsb (18)', koppenAt(35.1983, -111.6513), 18);
eq('Tucson downtown is BWh', koppenAt(32.2217, -110.9265), 4);
eq('Tucson airport is BSh', koppenAt(32.1161, -110.9410), 6);
eq('Prescott downtown is Csa', koppenAt(34.5400, -112.4685), 8);
eq('Prescott airport is BSk', koppenAt(34.6545, -112.4196), 7);
eq('Yuma is BWh', koppenAt(32.6927, -114.6277), 4);
eq('Wickenburg is BWh', koppenAt(33.9686, -112.7296), 4);
eq('Show Low is Csa', koppenAt(34.2542, -110.0298), 8);
eq('the Gulf of California has no class', koppenAt(31.0, -114.0), null);

// --- naming the square ------------------------------------------------
eq('112.07 W is in the square whose west edge is 113 W (AGENTS 9.13.1)',
  P.tileNameOf(33.4342, -112.0116), 'N33W113');
eq('Flagstaff is N35W112', P.tileNameOf(35.1983, -111.6513), 'N35W112');
eq('the south and the east are named too', P.tileNameOf(-33.9, 18.4), 'S34E018');

// --- reading a cell: row 0 is north, column 0 is west ------------------
{
  const page = new Uint8Array(CELLS * CELLS);
  page[0] = 11; // north-west corner
  page[CELLS - 1] = 12; // north-east
  page[(CELLS - 1) * CELLS] = 13; // south-west
  page[CELLS * CELLS - 1] = 14; // south-east
  eq('north-west', P.climateCell(page, 35.9999, -111.9999, CELLS), 11);
  eq('north-east', P.climateCell(page, 35.9999, -111.0001, CELLS), 12);
  eq('south-west', P.climateCell(page, 35.0001, -111.9999, CELLS), 13);
  eq('south-east', P.climateCell(page, 35.0001, -111.0001, CELLS), 14);
  eq('a cell of 0 is no class', P.climateCell(page, 35.5, -111.5, CELLS), null);
  eq('no page is no class', P.climateCell(null, 35.5, -111.5, CELLS), null);
  eq('a page of the wrong size is refused', P.climateCell(new Uint8Array(10), 35.5, -111.5, CELLS), null);
  eq('not a number is no class', P.climateCell(page, NaN, -111.5, CELLS), null);
}

// --- auto is answered before the engine ------------------------------
const DSB = { code: 18, symbol: 'Dsb', climate: 'continental_temperate' };
eq('the form opens on auto', P.DEFAULTS.radio_climate, 'auto');
eq('auto at Flagstaff is continental temperate, from the site',
  P.resolveClimate('auto', DSB), { climate: 'continental_temperate', source: 'site', koppen: 'Dsb' });
eq('auto with no class is desert, and marked as the fallback',
  P.resolveClimate('auto', null), { climate: 'desert', source: 'fallback', koppen: null });
eq('a class with a climate the engine has not got is the fallback too',
  P.resolveClimate('auto', { code: 99, symbol: 'X', climate: 'lunar' }).source, 'fallback');
eq('a climate chosen by hand wins over the site',
  P.resolveClimate('desert', DSB), { climate: 'desert', source: 'chosen', koppen: null });
eq('the line says where it came from',
  P.describeClimate(P.resolveClimate('auto', DSB)),
  "Continental temperate, from the site's Köppen class Dsb");
eq('and says it does not know, when it does not',
  P.describeClimate(P.resolveClimate('auto', null)),
  'Desert: the climate is not known here, using desert');
throws('the engine is never handed auto', () => P.toEngineParams({ ...P.DEFAULTS, lat: 35, lon: -111, radius: 1000 }));
eq('a resolved Flagstaff run gives the engine code 5',
  P.toEngineParams({ ...P.DEFAULTS, lat: 35.2, lon: -111.65, radio_climate: 'continental_temperate' }).radioClimate, 5);

// --- the share link ---------------------------------------------------
eq('a link is version 2', P.SHARE_VERSION, 2);
{
  const auto = P.toShareQuery({ ...P.FORM_DEFAULTS, lat: 35.1983, lon: -111.6513 }, null);
  eq('auto is the default, so a link leaves it out', auto, 'v=2&lat=35.1983&lon=-111.6513');
  const chosen = P.toShareQuery({ ...P.FORM_DEFAULTS, lat: 35.1983, lon: -111.6513, radio_climate: 'desert' }, null);
  eq('a climate chosen by hand is written, even desert', chosen, 'v=2&lat=35.1983&lon=-111.6513&radio_climate=desert');
  const back = P.fromShareQuery(chosen);
  eq('and comes back as chosen', back.values.radio_climate, 'desert');
  eq('a version 2 link with no climate opens on auto',
    { ...P.FORM_DEFAULTS, ...P.fromShareQuery(auto).values }.radio_climate, 'auto');
}
{
  // Made before #239 at Flagstaff, on the default desert. It must not
  // turn into continental temperate when it is opened now.
  const old = P.fromShareQuery('v=1&lat=35.1983&lon=-111.6513&ran=2026-09-22');
  eq('a version 1 link with no climate keeps desert', old.values.radio_climate, 'desert');
  eq('and says why, without calling the link broken', [old.notes, old.kept.length], [[], 1]);
  eq('a link with no version is read as version 1',
    P.fromShareQuery('lat=35.1983&lon=-111.6513').values.radio_climate, 'desert');
  const named = P.fromShareQuery('v=1&lat=35.1983&radio_climate=continental_temperate');
  eq('a version 1 link that named a climate keeps that one', named.values.radio_climate, 'continental_temperate');
  eq('and is not remarked on', named.kept, []);
  eq('passed on again, the old link keeps its desert, now written out',
    P.toShareQuery({ ...P.FORM_DEFAULTS, ...old.values }, null),
    'v=2&lat=35.1983&lon=-111.6513&radio_climate=desert');
  const future = P.fromShareQuery('v=9&lat=35.1983');
  eq('an unknown version is still noted', future.notes.length, 1);
  eq('and is not pinned to desert', future.values.radio_climate, undefined);
  eq('auto is a choice a link may name', P.fromShareQuery('v=2&radio_climate=auto').values.radio_climate, 'auto');
}

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
