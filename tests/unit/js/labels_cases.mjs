/*
 * Behaviour cases for `labels.js` (#157).
 *
 * Run by `tests/unit/test_traffic_labels_in_the_browser.py`, which
 * shells out to node.
 *
 * Run rather than read. The thing worth protecting here is not that a
 * string appears in the file -- it is that `portnumLabel` reaches the
 * new table and that `portnumWire`, which reads a table backwards,
 * does NOT. Source text cannot tell you which of two maps a lookup
 * found, and that distinction is the entire risk in this change: the
 * firehose filter turns what somebody types into a value the API
 * accepts, and `UNREADABLE_PKI` is not one.
 *
 * `labels.js` is an IIFE that assigns to `window`, not an ES module,
 * so it is evaluated here with a `window` object standing in for the
 * browser's. That is the file as shipped, not a copy of it.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/labels.js'), 'utf8');

const window = {};
new Function('window', source)(window);
const { portnumLabel, portnumWire } = window.SonoranLabels;

let failed = 0;
const eq = (name, got, want) => {
  if (got === want) return;
  failed += 1;
  console.error(`FAIL ${name}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
};
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

// The new bucket names reach a reader as phrases.
eq('pki', portnumLabel('UNREADABLE_PKI'), 'Direct message, encrypted');
eq('no key', portnumLabel('UNREADABLE_NO_KEY'), 'No key for this channel');
eq('unrecorded', portnumLabel('UNREADABLE_UNRECORDED'), 'Unreadable, reason not recorded');

// Non-regression: every existing band keeps the name it had. If this
// breaks, the change renamed the dashboard instead of fixing a bucket.
eq('telemetry', portnumLabel('TELEMETRY_APP'), 'Telemetry');
eq('text', portnumLabel('TEXT_MESSAGE_APP'), 'Text message');
eq('position', portnumLabel('POSITION_APP'), 'Position');
eq('unknown app', portnumLabel('UNKNOWN_APP'), 'Unknown');
eq('nothing at all', portnumLabel(null), 'Packet');
eq('an unlisted enum still reads', portnumLabel('SOMETHING_NEW_APP'), 'Something new');

// THE ONE THAT MATTERS. `portnumWire` builds a reverse index from the
// port-name table so the firehose filter can take "Position". The new
// names are not port numbers and the API answers 422 for them, so they
// must not be reachable backwards.
for (const phrase of [
  'Direct message, encrypted',
  'No key for this channel',
  'Unreadable, reason not recorded',
]) {
  const wire = portnumWire(phrase);
  ok(
    `portnumWire does not offer ${JSON.stringify(phrase)}`,
    !String(wire).startsWith('UNREADABLE_'),
    `it returned ${JSON.stringify(wire)}, which the API refuses`,
  );
}

// Positive control for the check above: the reverse lookup does work
// for a real port, so a passing run means "these three are absent",
// not "the reverse lookup is broken".
eq('the reverse lookup still works', portnumWire('Position'), 'POSITION_APP');
eq('a number still passes through', portnumWire('3'), '3');

if (failed) {
  console.error(`${failed} failed`);
  process.exit(1);
}
console.log('labels: all cases passed');
