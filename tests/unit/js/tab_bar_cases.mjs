/*
 * Behaviour cases for `tab-bar.js` (#282).
 *
 * Run by `tests/unit/test_bottom_nav.py`, which shells out to node.
 *
 * The rule worth running is "the closest tab". A deep link opens a page
 * that is not one of the four, and the bar must light the tab that page
 * belongs to, or no tab at all. It must never light a tab that is wrong:
 * a packet is not a node, and a traceroute is not the map.
 *
 * `tab-bar.js` is an IIFE that assigns to `window`, so it is evaluated
 * here with a `window` object standing in for the browser's.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/tab-bar.js'), 'utf8');

const window = {};
new Function('window', source)(window);
const { tabOf } = window.SonoranTabBar;

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) return;
  failed += 1;
  console.error(`FAIL ${name}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
};

const TABS = ['map', 'nodes', 'chat', 'dashboard'];

// A tab's own page is that tab, exactly.
for (const page of TABS) eq(`${page} is its own tab`, tabOf(page, TABS), { tab: page, exact: true });

// A node page belongs to Nodes, but it is not the Nodes page.
eq('a node page lights Nodes', tabOf('node', TABS), { tab: 'nodes', exact: false });

// Pages behind More, and detail pages with no tab, light nothing.
for (const page of ['packet', 'link', 'traceroute', 'traceroutes', 'firehose', 'settings',
  'planner', 'graph', 'stats', 'rf', 'gaps', 'coverage', 'config', 'meshnet']) {
  eq(`${page} lights no tab`, tabOf(page, TABS), null);
}

// The closest tab must itself be in the bar. With Nodes gone, a node page lights nothing.
eq('no Nodes tab, no light for a node', tabOf('node', ['map', 'chat']), null);

// An unknown page lights nothing rather than throwing.
eq('an unknown page', tabOf('nonsense', TABS), null);
eq('no page at all', tabOf('', TABS), null);

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('tab bar cases: all passed');
