/*
 * Behaviour cases for the badge on the nodes list's Filters button (#301).
 *
 * A first visit showed "2" with nothing chosen: the badge counted every
 * key of the list query, which held the toolbar's default "Last 24 h"
 * and the sidebar's preset channel. Will (2026-09-27): count only what
 * the reader changed, toolbar or panel, and never the preset.
 *
 * Run rather than read, because the claim is about a number.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/app.js'), 'utf8');

function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  const end = source.indexOf('\n}', start);
  return source.slice(start, end + 2);
}

const nodeFilterCount = new Function(`${extract('nodeFilterCount')}; return nodeFilterCount;`)();

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

const DEFAULTS = { q: '', active_hours: '24', role: '', gateway: false };
const toolbar = (changes = {}) => ({ ...DEFAULTS, ...changes });
const panel = (entries = []) => new Map(entries);

// --- the report ----------------------------------------------------
const first = nodeFilterCount(toolbar(), DEFAULTS, panel());
ok('a first visit counts nothing', first === 0, `counted ${first}`);

// --- the panel -----------------------------------------------------
ok('one panel choice counts one',
  nodeFilterCount(toolbar(), DEFAULTS, panel([['position', 'none']])) === 1);
ok('gaps and its preset are one filter',
  nodeFilterCount(toolbar(), DEFAULTS, panel([['gaps', 'bad'], ['gaps_preset', 'LongFast']])) === 1);
ok('two panel choices count two',
  nodeFilterCount(toolbar(), DEFAULTS, panel([['hw', 'TBEAM'], ['licensed', 'true']])) === 2);

// --- the toolbar, when it differs from its default -----------------
ok('a search counts', nodeFilterCount(toolbar({ q: 'base' }), DEFAULTS, panel()) === 1);
ok('"Any time" is a change from "Last 24 h", so it counts',
  nodeFilterCount(toolbar({ active_hours: '' }), DEFAULTS, panel()) === 1);
ok('a role counts', nodeFilterCount(toolbar({ role: 'ROUTER' }), DEFAULTS, panel()) === 1);
ok('Gateways counts', nodeFilterCount(toolbar({ gateway: true }), DEFAULTS, panel()) === 1);
ok('all four count four',
  nodeFilterCount(toolbar({ q: 'x', active_hours: '1', role: 'ROUTER', gateway: true }),
    DEFAULTS, panel()) === 4);

// --- one filter set in both places counts once ----------------------
ok('"Heard within" in the toolbar and the panel counts once',
  nodeFilterCount(toolbar({ active_hours: '168' }), DEFAULTS, panel([['active_hours', '1']])) === 1);
ok('a role in both places counts once',
  nodeFilterCount(toolbar({ role: 'ROUTER' }), DEFAULTS, panel([['role', 'CLIENT']])) === 1);

// --- the preset is never a filter here ------------------------------
// It is not a toolbar key and not a panel key, so there is no way for
// it to reach the count. A channel chosen IN the panel is the reader's
// choice, and counts.
ok('the preset is not counted, because it is not passed',
  nodeFilterCount(toolbar(), DEFAULTS, panel()) === 0);
ok('a channel chosen in the panel counts',
  nodeFilterCount(toolbar(), DEFAULTS, panel([['channel', 'LongFast']])) === 1);

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('nodes filter count: all cases pass');
