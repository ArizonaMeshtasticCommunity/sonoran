/*
 * How a gap signal's number becomes text (#265, suggested by StarSkream).
 *
 * "New user seeing 'Yes 0.226' doesn't add value at the surface level."
 * The page printed `String(value)`. It now formats by the unit the
 * server sends, in `formatValue`, and these cases run that function
 * rather than read it.
 *
 * Three rules are exercised, each a way this has gone wrong:
 *
 * - absent is not zero (`Number(null)` is 0: five bugs in this repo);
 * - no "100%" for a value that is not exactly 1;
 * - a number whose unit is not known is not printed at all.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sandbox = {
  window: {},
  document: { querySelector: () => null, querySelectorAll: () => [] },
  location: { hash: '' },
  URLSearchParams,
  console: { warn() {}, log() {} },
};
vm.createContext(sandbox);
new vm.Script(readFileSync(
  new URL('../../../src/sonoran/web/static/gaps.js', import.meta.url), 'utf8',
)).runInContext(sandbox);
const { formatValue, heading } = sandbox.window.SonoranGaps;

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  }
};

console.log("StarSkream's example");
eq('0.226 reads as 22.6%', formatValue(0.226, 'fraction'), '22.6%');
eq('the full-precision third reads to one place', formatValue(1 / 3, 'fraction'), '33.3%');

console.log('\nno perfect score that was not measured');
eq('exactly 1 is 100%', formatValue(1, 'fraction'), '100%');
eq('0.9996 is not 100%', formatValue(0.9996, 'fraction'), '>99.9%');
eq('0.99949 rounds down honestly', formatValue(0.99949, 'fraction'), '99.9%');
eq('exactly 0 is 0%', formatValue(0, 'fraction'), '0%');
eq('a sliver above 0 is not 0%', formatValue(0.0004, 'fraction'), '<0.1%');
eq('a share above 1 is not drawn', formatValue(1.3, 'fraction'), null);
eq('a share below 0 is not drawn', formatValue(-0.1, 'fraction'), null);

console.log('\nabsent is not zero');
for (const missing of [null, undefined, '', '0.5', Number.NaN, Infinity, {}, []]) {
  for (const unit of ['fraction', 'db', 'gateways', 'dbm', 'm']) {
    eq(`${JSON.stringify(missing) ?? String(missing)} in ${unit} is not a number`, formatValue(missing, unit), null);
  }
}

console.log('\na number with no known unit is not printed');
eq('no unit', formatValue(0.226, null), null);
eq('undefined unit (an assessment written before #265)', formatValue(0.226, undefined), null);
eq('an unknown unit', formatValue(0.226, 'furlongs'), null);

console.log('\nthe other units');
eq('a margin is signed', formatValue(13.48, 'db'), '+13.5 dB');
eq('a margin below zero reads as one', formatValue(-2.04, 'db'), '-2.0 dB');
eq('a margin of zero has no sign', formatValue(0.02, 'db'), '0.0 dB');
eq('a negative zero has no sign', formatValue(-0.02, 'db'), '0.0 dB');
eq('one gateway', formatValue(1, 'gateways'), '1 gateway');
eq('eight gateways', formatValue(8, 'gateways'), '8 gateways');
eq('a fractional gateway count is not drawn', formatValue(1.5, 'gateways'), null);
eq('a predicted level', formatValue(-128, 'dbm'), '-128 dBm');
eq('a distance', formatValue(2900, 'm'), '2900 m');

console.log('\nthe heading carries the unit');
const labels = { rf_intermittent: 'Gets out over the air only sometimes', radio_isolated: 'Reaches us only through MQTT' };
const units = { rf_intermittent: '% of hours heard' };
eq('with a unit', heading('rf_intermittent', labels, units),
  'Gets out over the air only sometimes (% of hours heard)');
eq('a signal with no number has no unit', heading('radio_isolated', labels, units),
  'Reaches us only through MQTT');
eq('a server that sent no units still gets its label', heading('rf_intermittent', labels, {}),
  'Gets out over the air only sometimes');

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
