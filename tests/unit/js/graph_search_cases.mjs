/*
 * Behaviour cases for the mesh graph's "Find a node" box (#223).
 *
 * Reported as "does nothing". It was not doing nothing -- it was doing
 * something invisible, in two ways at once:
 *
 *  - the highlight tested `display_name` only, while `focusNode` tested
 *    `display_name` and `node_id`. A **short name** matched neither,
 *    and a short name is what the reporter typed.
 *  - past 120 nodes a dot is 3 px and the match was a 2 px border on
 *    it, which in a four-hundred-node mesh is not findable.
 *
 * Run rather than read, because the claim is about which strings match
 * and how big the mark is -- neither visible in a source grep.
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

const matchesGraphQuery = new Function(
  `${extract('matchesGraphQuery')}; return matchesGraphQuery;`,
)();

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

const node = {
  display_name: 'Shaw Butte 3.1 [azmsh.net]',
  short_name: 'SB31',
  long_name: 'Shaw Butte 3.1 [azmsh.net]',
  node_id: '!a038f6bc',
};

// THE REPORTED CASE. A short name must match.
ok('a short name matches', matchesGraphQuery(node, 'sb31'), 'this is what was typed');
ok('a short name matches case-insensitively', matchesGraphQuery(node, 'SB31'.toLowerCase()));

ok('a long name matches', matchesGraphQuery(node, 'shaw butte'));
ok('a partial long name matches', matchesGraphQuery(node, 'butte'));
ok('a node id matches', matchesGraphQuery(node, 'a038f6bc'));
ok('a node id with its bang matches', matchesGraphQuery(node, '!a038f6bc'));

ok('an unrelated string does not match', !matchesGraphQuery(node, 'zzzz'));
ok('an empty query matches nothing', !matchesGraphQuery(node, ''));
ok('a null query matches nothing', !matchesGraphQuery(node, null));

// A node missing some names must not throw: the graph carries nodes
// that never sent a NodeInfo.
const bare = { display_name: '!deadbeef', node_id: '!deadbeef' };
ok('a node with no short name is safe', matchesGraphQuery(bare, 'deadbeef'));
ok('a node with no short name does not match junk', !matchesGraphQuery(bare, 'sb31'));
const empty = {};
ok('a node with no names at all is safe', !matchesGraphQuery(empty, 'anything'));

// --- the mark has to be findable ----------------------------------
//
// Read from the source, because it is a literal in the option object
// rather than a function. The floor is what makes a match visible in a
// dense graph, which is the half of #223 that is not about matching.
ok('a match has a size floor', /Math\.max\(14,/.test(source),
  'no floor: a match stays a 3 px dot in a large graph');
ok('a match uses the accent, not the text colour',
  /borderColor: PALETTE\.accent, borderWidth: 3/.test(source));
ok('a match is drawn at full opacity',
  /borderWidth: 3, opacity: 1/.test(source),
  'a stale match is still the node that was asked for');

if (failed) { console.error(`${failed} failed`); process.exit(1); }
console.log('graph search: all cases passed');
