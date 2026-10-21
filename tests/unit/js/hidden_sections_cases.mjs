/*
 * Behaviour cases for `sections.js` (HIDDEN_SECTIONS).
 *
 * Run by `tests/unit/test_hidden_sections_page.py`, which shells out to
 * node. `sections.js` is an IIFE that reads `window.SONORAN` and assigns
 * to `window`, so it is evaluated here with a stand-in `window`.
 *
 * The rules worth running:
 *
 * - The page name of a link is the part of its `#` address before a `/`
 *   or a `?`. `#rf`, `#rf/x` and `#rf?x` are RF. `#rfx` is not.
 * - A hidden page is routed to the "not available" page. Any other page
 *   is routed to itself.
 * - With nothing hidden, nothing changes: every page routes to itself.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/sections.js'), 'utf8');

function load(hiddenSections) {
  const window = { SONORAN: hiddenSections === undefined ? {} : { hiddenSections } };
  new Function('window', source)(window);
  return window.SonoranSections;
}

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) return;
  failed += 1;
  console.error(`FAIL ${name}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
};

const PAGES = ['dashboard', 'map', 'nodes', 'chat', 'rf', 'planner', 'stats', 'node', 'settings'];

// The default: nothing hidden, every page is itself.
for (const config of [undefined, [], null, 'rf']) {
  const sections = load(config);
  for (const page of PAGES) eq(`default ${JSON.stringify(config)}: ${page}`, sections.pageFor(page), page);
  eq(`default ${JSON.stringify(config)}: nothing is hidden`, sections.isHidden('rf'), false);
}

// A hidden page goes to the "not available" page. The others do not move.
{
  const sections = load(['rf', 'planner']);
  eq('rf is hidden', sections.isHidden('rf'), true);
  eq('rf routes away', sections.pageFor('rf'), 'unavailable');
  eq('planner routes away', sections.pageFor('planner'), 'unavailable');
  eq('the map stays', sections.pageFor('map'), 'map');
  eq('the dashboard stays', sections.pageFor('dashboard'), 'dashboard');
  eq('the name of the page', sections.UNAVAILABLE, 'unavailable');
}

// The page name of a link.
{
  const { pageOf } = load(['rf']);
  eq('#rf', pageOf('#rf'), 'rf');
  eq('#rf/x', pageOf('#rf/station-1'), 'rf');
  eq('#rf?x', pageOf('#rf?view=sweeps'), 'rf');
  eq('#map/node/x?preset=y', pageOf('#map/node/!abcd?preset=LongFast'), 'map');
  eq('#rfx is another page', pageOf('#rfx'), 'rfx');
  eq('# alone', pageOf('#'), null);
  eq('a full address', pageOf('https://example.net/#rf'), null);
  eq('nothing', pageOf(null), null);
}

// A link is to be hidden when its page is hidden, and only then.
{
  const { linkIsHidden } = load(['rf', 'gaps']);
  eq('a link to rf', linkIsHidden('#rf'), true);
  eq('a link to a gaps area', linkIsHidden('#gaps?area=1'), true);
  eq('a link to the map', linkIsHidden('#map'), false);
  eq('a link to rfx', linkIsHidden('#rfx'), false);
  eq('an outside link', linkIsHidden('https://example.net/#rf'), false);
}

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('hidden sections cases: all passed');
