/*
 * The signal floor of the coverage map (#334, item 4).
 *
 * The cases that matter are these:
 *
 * - The floor starts at 0 dB, which is the map the page always drew.
 *   Only 0, 5, 10 and 20 are floors. Anything else in a link is 0.
 * - The floor is a map choice. It goes in the address, it counts on the
 *   badge, Reset clears it, and it is never stored for the viewer.
 * - A run with no margin tiles, or with an encoding this page does not
 *   know, cannot draw a floor. `marginSpec` answers null for it.
 * - At 0 dB the browser draws every margin exactly as Python drew the
 *   colour tile. Above it, a cell under the floor is clear.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SOURCE = readFileSync(
  new URL('../../../src/sonoran/web/static/coverage-settings.js', import.meta.url), 'utf8',
);
// Python writes this table. `test_coverage_floor.py` checks that it is
// still what `coverage/render.py` draws.
const TABLE = JSON.parse(readFileSync(new URL('./coverage_ramp_margins.json', import.meta.url), 'utf8'));

function load() {
  const sandbox = { window: {}, JSON, Number, Date, URLSearchParams, Uint8ClampedArray, Math };
  vm.createContext(sandbox);
  new vm.Script(SOURCE).runInContext(sandbox);
  return sandbox.window.SonoranCoverageSettings;
}

function storage(saved = {}) {
  const store = { ...saved };
  return {
    store,
    getItem: (key) => (key in store ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
    removeItem: (key) => { delete store[key]; },
  };
}

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  }
};

const C = load();

const SUMMARY = {
  ramp_span_db: TABLE.span,
  margin_tiles: { encoding: 'margin_db_plus_one', ramp: TABLE.ramp, alpha: TABLE.alpha },
};

/* One grey pixel for each margin, as a canvas decodes a grey PNG. */
function greyPixels(bytes) {
  const out = new Uint8ClampedArray(bytes.length * 4);
  bytes.forEach((byte, i) => {
    out.set([byte, byte, byte, 255], i * 4);
  });
  return out;
}

function pixel(data, index) {
  return [...data.slice(index * 4, index * 4 + 4)];
}

// --- the defaults and the choices -------------------------------------
{
  eq('the floor starts at 0 dB, the map as it always was', C.defaults().floor, 0);
  eq('the panel offers 0, 5, 10 and 20 dB', C.FLOORS, [0, 5, 10, 20]);
  eq('a floor the panel offers is kept', [0, 5, 10, 20].map(C.floorOf), [0, 5, 10, 20]);
  eq('anything else is no floor', ['7', '-5', 'ten', null, undefined, '1e1x', 30].map(C.floorOf),
    [0, 0, 0, 0, 0, 0, 0]);
  eq('a numeric string from a link is a floor', C.floorOf('10'), 10);
}

// --- the badge and Reset ----------------------------------------------
{
  eq('a floor of 0 counts nothing', C.changedCount({ ...C.defaults(), floor: 0 }), 0);
  eq('a floor above 0 counts one', C.changedCount({ ...C.defaults(), floor: 10 }), 1);
  eq('with the layer it counts two', C.changedCount({ ...C.defaults(), floor: 20, layer: 'empirical_heatmap_position' }), 2);
  eq('Reset clears the floor', C.reset().floor, 0);
}

// --- the address, not the storage --------------------------------------
{
  eq('a plain link has no floor', C.fromHash('#coverage').floor, 0);
  eq('a link names its floor', C.fromHash('#coverage?floor=10').floor, 10);
  eq('a floor the panel does not offer is no floor', C.fromHash('#coverage?floor=15').floor, 0);
  eq('the floor is written into the address',
    C.toHash({ ...C.defaults(), floor: 10 }), '#coverage?floor=10');
  eq('no floor writes nothing', C.toHash({ ...C.defaults(), floor: 0 }), '#coverage');
  eq('with the other map choices',
    C.toHash({ ...C.defaults(), approximate: true, layer: 'empirical_heatmap_position', floor: 5 }),
    '#coverage?approx=1&layer=empirical_heatmap_position&floor=5');
  const round = { ...C.defaults(), layer: 'empirical_heatmap_position', floor: 20 };
  eq('a written floor reads back', C.fromHash(C.toHash(round)).floor, 20);

  const kept = storage();
  C.save(kept, { ...C.defaults(), floor: 20 });
  eq('the floor is never stored for the viewer',
    JSON.parse(kept.store['sonoran.coverage.settings']).floor, undefined);
  const stale = storage({ 'sonoran.coverage.settings': JSON.stringify({ floor: 20 }) });
  eq('a floor found in storage is not read back', C.load(stale).floor, 0);
}

// --- a run with no margin data ----------------------------------------
{
  eq('a new run can draw a floor', C.marginSpec(SUMMARY) !== null, true);
  eq('the spec carries the span from the run', C.marginSpec(SUMMARY).span, TABLE.span);
  eq('a run made before the margin tiles cannot', C.marginSpec({ ramp_span_db: 60 }), null);
  eq('no summary cannot', C.marginSpec(null), null);
  eq('an encoding this page does not know cannot',
    C.marginSpec({ ...SUMMARY, margin_tiles: { ...SUMMARY.margin_tiles, encoding: 'level_byte' } }), null);
  eq('a ramp that is not colours cannot',
    C.marginSpec({ ...SUMMARY, margin_tiles: { ...SUMMARY.margin_tiles, ramp: [[0, 0, 0], ['x', 0, 0]] } }), null);
  eq('a ramp of one colour cannot',
    C.marginSpec({ ...SUMMARY, margin_tiles: { ...SUMMARY.margin_tiles, ramp: [[0, 0, 0]] } }), null);
  eq('an alpha outside a byte cannot',
    C.marginSpec({ ...SUMMARY, margin_tiles: { ...SUMMARY.margin_tiles, alpha: 300 } }), null);
  eq('no span cannot', C.marginSpec({ ...SUMMARY, ramp_span_db: 0 }), null);
}

// --- colouring a margin tile -------------------------------------------
{
  const spec = C.marginSpec(SUMMARY);
  const margins = TABLE.pixels.map((_, margin) => margin + 1);
  const drawn = C.colourMargins(greyPixels(margins), 0, spec);
  const wrong = [];
  TABLE.pixels.forEach((want, margin) => {
    const got = pixel(drawn, margin);
    if (JSON.stringify(got) !== JSON.stringify(want)) wrong.push({ margin, got, want });
  });
  eq(`at 0 dB every margin (0 to ${TABLE.pixels.length - 1}) is the colour Python drew`, wrong, []);

  const empty = C.colourMargins(greyPixels([0]), 0, spec);
  eq('byte 0 is clear at any floor', pixel(empty, 0), [0, 0, 0, 0]);

  // Margins 0, 5, 10, 20, 60 and 100 dB at each floor the panel offers.
  const sample = [0, 5, 10, 20, 60, 100];
  for (const floor of C.FLOORS) {
    const out = C.colourMargins(greyPixels(sample.map((margin) => margin + 1)), floor, spec);
    const shown = sample.filter((_, i) => pixel(out, i)[3] > 0);
    eq(`a floor of ${floor} dB shows only margins of at least ${floor} dB`,
      shown, sample.filter((margin) => margin >= floor));
    const colours = sample.map((margin, i) => (margin >= floor ? pixel(out, i) : null)).filter(Boolean);
    const want = sample.filter((margin) => margin >= floor).map((margin) => TABLE.pixels[margin]);
    eq(`a floor of ${floor} dB keeps the colours of the cells it shows`, colours, want);
  }

  eq('the colour at 60 dB and past it is the top of the ramp',
    [pixel(C.colourMargins(greyPixels([61]), 0, spec), 0), pixel(C.colourMargins(greyPixels([201]), 0, spec), 0)],
    [[...TABLE.ramp[TABLE.ramp.length - 1], TABLE.alpha], [...TABLE.ramp[TABLE.ramp.length - 1], TABLE.alpha]]);
  eq('a floor not offered draws as 0 dB',
    pixel(C.colourMargins(greyPixels([3]), 7, spec), 0)[3], TABLE.alpha);
}

// --- the words ---------------------------------------------------------
{
  eq('no floor has no words', C.floorWords(0), '');
  eq('a floor says what it means', C.floorWords(10), 'at least 10 dB above what the radio needs');
  eq('the map words are as before without a floor',
    C.mapWords('Routers and repeaters', false), 'Routers and repeaters · precise positions only');
  eq('the map words name a floor',
    C.mapWords('Routers and repeaters', false, 10),
    'Routers and repeaters · precise positions only · 10 dB floor');
}

if (failed) {
  console.log(`\n${failed} case(s) failed`);
  process.exit(1);
}
console.log('\nall cases passed');
