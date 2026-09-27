/*
 * The planner's boxes in the reader's units, exercised (#246).
 *
 * The boxes show and accept feet and miles to an imperial reader and
 * metres and kilometres to a metric one. The form value, the share link
 * and the engine stay metric. These cases hold three things:
 *
 * 1. The same antenna typed in feet and in metres reaches the engine as
 *    the same numbers.
 * 2. A link made by an imperial reader and opened by a metric one, or
 *    the other way round, reaches the engine as the same numbers as it
 *    did for the reader who made it.
 * 3. An untouched box is not converted back. 6 m shows as 19.69 ft, and
 *    19.69 ft is 6.0015 m, so a page that re-read its own display would
 *    move the antenna and change the link.
 *
 * `node planner_units_cases.mjs --emit` prints the engine inputs of each
 * scenario as JSON instead. `test_planner_units_follow_the_setting.py`
 * runs the real engine on them, so the claim is checked against a
 * prediction and not only against the numbers that go into one.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SRC = (name) => readFileSync(
  new URL(`../../../src/sonoran/web/static/${name}`, import.meta.url), 'utf8',
);

/** A fresh page: settings, units and the planner's parameters. */
function load(units) {
  const store = { 'sonoran.settings': JSON.stringify({ units }) };
  const sandbox = {
    window: {
      localStorage: {
        getItem: (key) => (key in store ? store[key] : null),
        setItem: (key, value) => { store[key] = value; },
      },
      addEventListener() {},
    },
    console: { warn() {} },
    JSON,
    URLSearchParams,
  };
  vm.createContext(sandbox);
  for (const name of ['settings.js', 'units.js', 'planner-params.js']) {
    new vm.Script(SRC(name)).runInContext(sandbox);
  }
  return {
    S: sandbox.window.SonoranSettings,
    U: sandbox.window.SonoranUnits,
    P: sandbox.window.SonoranPlannerParams,
  };
}

const SITE = { lat: 34.0, lon: -111.5 };
const BOXES = ['tx_height', 'rx_height', 'clutter_height', 'radius'];

/*
 * What `fillForm` and `readForm` in `planner.js` do with the unit
 * boxes, without a page. `fill` writes each box and holds its value
 * beside the text. `read` reads each box through `readBox`, with any
 * text the reader typed over it.
 */
function fill(page, values) {
  const boxes = {};
  for (const name of BOXES) {
    const shown = page.P.toBox(name, values[name], page.U);
    boxes[name] = { typed: shown, held: { shown, value: Number(values[name]) } };
  }
  return boxes;
}

function read(page, values, boxes) {
  const out = { ...values };
  for (const name of BOXES) {
    out[name] = page.P.readBox(name, boxes[name].typed, boxes[name].held, page.U);
  }
  return out;
}

/** The form's values, as the engine takes them. `readForm` scales the range. */
function engine(page, values) {
  return page.P.toEngineParams({ ...values, radius: values.radius * 1000 });
}

/** Open a share link, as `applyShareLink` does, and read the form back. */
function open(page, query) {
  const values = { ...page.P.FORM_DEFAULTS, ...page.P.fromShareQuery(query).values };
  const boxes = fill(page, values);
  return { values, boxes, read: read(page, values, boxes) };
}

const scenarios = {};

// --- an imperial reader types feet and miles ------------------------
const imperial = load('imperial');
const typedFeet = { tx_height: '20', rx_height: '5', clutter_height: '0', radius: '6' };
const writer = { ...imperial.P.FORM_DEFAULTS, ...SITE };
for (const [name, text] of Object.entries(typedFeet)) {
  writer[name] = imperial.P.fromBox(name, text, imperial.U);
}
const feetLink = imperial.P.toShareQuery(writer, null);
scenarios.typed_in_feet = engine(imperial, writer);

// --- a metric reader opens that link --------------------------------
const metric = load('metric');
const opened = open(metric, feetLink);
scenarios.feet_link_opened_in_metric = engine(metric, opened.read);

// --- a metric reader types the same antenna in metres ---------------
const typedMetres = { tx_height: '6.096', rx_height: '1.524', clutter_height: '0', radius: '9.656064' };
const metricWriter = { ...metric.P.FORM_DEFAULTS, ...SITE };
for (const [name, text] of Object.entries(typedMetres)) {
  metricWriter[name] = metric.P.fromBox(name, text, metric.U);
}
scenarios.typed_in_metres = engine(metric, metricWriter);

// --- a metric link, opened by each kind of reader -------------------
const metresLink = 'v=1&lat=34&lon=-111.5&tx_height=6&rx_height=1.5&radius=10';
const inMetric = open(load('metric'), metresLink);
const inImperial = open(load('imperial'), metresLink);
scenarios.metres_link_opened_in_metric = engine(metric, inMetric.read);
scenarios.metres_link_opened_in_imperial = engine(imperial, inImperial.read);

/*
 * The negative control: the same imperial page, reading its own boxes
 * back through the conversion instead of through what they hold. This
 * is what `readBox` exists to prevent, and it must come out different,
 * or the scenario above proves nothing.
 */
const reparsed = { ...inImperial.values };
for (const name of BOXES) {
  reparsed[name] = imperial.P.fromBox(name, inImperial.boxes[name].typed, imperial.U);
}
scenarios.metres_link_reparsed_in_imperial = engine(imperial, reparsed);

/*
 * The positive control for the engine: 20 typed into a feet box and
 * handed on as metres. That is the 3.28 times error `docs/PLANNER.md`
 * warns about, and the prediction must see it.
 */
scenarios.feet_read_as_metres = engine(imperial, { ...writer, tx_height: 20 });

if (process.argv.includes('--emit')) {
  console.log(JSON.stringify(scenarios));
  process.exit(0);
}

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
};
const differ = (name, a, b) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       both ${JSON.stringify(a)}`); }
};

// --- the link is metric, whatever the writer read -------------------
{
  const query = new URLSearchParams(feetLink);
  eq('20 ft goes into the link as 6.096 m', query.get('tx_height'), '6.096');
  eq('5 ft goes in as 1.524 m', query.get('rx_height'), '1.524');
  eq('6 mi goes in as 9.656064 km', query.get('radius'), '9.656064');
  eq('0 ft of clutter is the default, so it is left out', query.has('clutter_height'), false);
}

// --- one antenna, two unit systems, one engine input ----------------
eq('20 ft typed and 6.096 m typed are the same antenna to the engine',
  scenarios.typed_in_feet, scenarios.typed_in_metres);
eq('a feet link opened in metric predicts what its writer predicted',
  scenarios.feet_link_opened_in_metric, scenarios.typed_in_feet);
eq('a metric link opened in imperial predicts what it does in metric',
  scenarios.metres_link_opened_in_imperial, scenarios.metres_link_opened_in_metric);
differ('re-reading the rounded display instead would change the engine input',
  scenarios.metres_link_reparsed_in_imperial, scenarios.metres_link_opened_in_metric);
differ('feet read as metres changes it', scenarios.feet_read_as_metres, scenarios.typed_in_feet);

// --- what each reader sees ------------------------------------------
eq('a metric reader sees the feet link in metres, exactly',
  BOXES.map((name) => opened.boxes[name].typed), ['6.096', '1.524', '0', '9.656064']);
eq('an imperial reader sees the metric link in feet and miles, to a hundredth',
  BOXES.map((name) => inImperial.boxes[name].typed), ['19.69', '4.92', '0', '6.21']);
eq('and 19.69 ft read back as typed would be 6.001512 m, not 6',
  imperial.P.fromBox('tx_height', '19.69', imperial.U), 6.001512);

// --- a link survives being passed on --------------------------------
{
  const again = imperial.P.toShareQuery({ ...inImperial.read }, null);
  eq('an imperial reader who changes nothing passes the same link on', again, metresLink);
  const back = metric.P.toShareQuery({ ...opened.read }, null);
  eq('so does a metric reader', back, feetLink);
}

// --- a box the reader typed into ------------------------------------
{
  const boxes = fill(imperial, { ...writer });
  boxes.tx_height.typed = '33';
  const values = read(imperial, writer, boxes);
  eq('typed text is converted from the reader\'s units', values.tx_height, 10.0584);
  eq('an untouched box beside it is not', values.rx_height, 1.524);
}

// --- absent is not zero ---------------------------------------------
eq('an empty box shows nothing', imperial.P.toBox('tx_height', '', imperial.U), '');
eq('an empty box reads as absent', imperial.P.fromBox('tx_height', '', imperial.U), null);
eq('spaces are absent too, not 0 ft', imperial.P.fromBox('tx_height', '   ', imperial.U), null);
eq('text is not a height', imperial.P.fromBox('tx_height', 'tall', imperial.U), null);
eq('a real zero is still zero', imperial.P.fromBox('clutter_height', '0', imperial.U), 0);

// --- the setting changes under a box --------------------------------
{
  const page = load('imperial');
  const held = { shown: '20', value: page.P.fromBox('tx_height', '20', page.U) };
  page.S.set('units', 'metric');
  eq('a 20 ft box switched to metric shows 6.096 m',
    page.P.toBox('tx_height', held.value, page.U), '6.096');
  page.S.set('units', 'imperial');
  eq('and switched back shows 20 ft again, not 19.99',
    page.P.toBox('tx_height', held.value, page.U), '20');
}

// --- the share link does not read the setting -----------------------
eq('planner-params.js never reads the units setting itself',
  /\b(SonoranUnits|SonoranSettings)\s*[.[]/.test(SRC('planner-params.js')), false);

if (failed) {
  console.log(`\n${failed} failed`);
  process.exit(1);
}
console.log('\nall passed');
