/*
 * Behaviour cases for the nodes list's paging (§6.2).
 *
 * The list scrolls on instead of stopping at a cap with a "Show more"
 * button. Two pieces of that are pure and are the pieces that go wrong
 * quietly, so they are run here rather than read in a grep:
 *
 *  - `mergeNodePage`, which decides what the next offset is and which
 *    arriving rows are new. The plan (§6.2) asks for keyset pagination
 *    to stop rows repeating and the API serves `limit`/`offset` only, so
 *    this is where that risk is actually handled.
 *  - `nodeProgressWords`, which says how much of the list is loaded. An
 *    absent total must never read as zero, and `Number(null)` is 0.
 *
 * Run rather than read, because both claims are about values -- and a
 * source grep cannot tell a `+ served.length` from a `+ added.length`.
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

function line(prefix) {
  const found = source.split('\n').find((row) => row.startsWith(prefix));
  if (!found) throw new Error(`${prefix} not found`);
  return found;
}

const mergeNodePage = new Function(`${extract('mergeNodePage')}; return mergeNodePage;`)();
// `nodeProgressWords` formats through `count`, which is the guard that
// prints an absent number as "-" rather than 0. Both come from the file
// so this cannot pass against a copy that drifted.
const nodeProgressWords = new Function(
  `${line('const NUMBER =')}\n${line('const count =')}\n${extract('nodeProgressWords')};`
  + ' return nodeProgressWords;',
)();

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

const rowsFrom = (from, howMany) =>
  Array.from({ length: howMany }, (_, index) => ({ node_id: `!${from + index}` }));

// --- the ordinary page ---------------------------------------------
const first = mergeNodePage([], rowsFrom(0, 100), { offset: 0, pageSize: 100 });
ok('a full first page is kept whole', first.rows.length === 100);
ok('the offset lands past the first page', first.offset === 100, `offset ${first.offset}`);
ok('a full page is not the end of the list', first.exhausted === false);

const second = mergeNodePage(first.rows, rowsFrom(100, 100), { offset: first.offset, pageSize: 100 });
ok('the second page is appended', second.rows.length === 200);
ok('the rows stay in the order the server sent them',
  second.rows[100].node_id === '!100' && second.rows[199].node_id === '!199',
  second.rows[100].node_id);
ok('only the new rows are reported as added', second.added.length === 100);
ok('the offset keeps rising', second.offset === 200, `offset ${second.offset}`);

// --- the end of the list -------------------------------------------
const short = mergeNodePage(second.rows, rowsFrom(200, 37), { offset: 200, pageSize: 100 });
ok('a short page ends the list', short.exhausted === true);
ok('a short page is still kept', short.rows.length === 237);
const nothing = mergeNodePage(short.rows, [], { offset: 237, pageSize: 100 });
ok('an empty page ends the list', nothing.exhausted === true);
ok('an empty page changes nothing else', nothing.rows.length === 237 && nothing.offset === 237);

// --- THE REASON THIS FUNCTION EXISTS -------------------------------
//
// The mesh reorders under us: `last_heard` moves and a node that was on
// page one arrives again on page two. It must be drawn once...
const overlap = mergeNodePage(rowsFrom(0, 100), rowsFrom(98, 100), { offset: 100, pageSize: 100 });
ok('a row that arrives twice is drawn once',
  overlap.rows.length === 198, `${overlap.rows.length} rows`);
ok('the repeat is not counted as added', overlap.added.length === 98);
const ids = overlap.rows.map((row) => row.node_id);
ok('and no id appears twice', new Set(ids).size === ids.length);
// ... and the offset must still advance by what the SERVER served, or the
// next request asks for the rows just dropped and the list pages forever.
ok('the offset advances by what the server served, not by what was kept',
  overlap.offset === 200, `offset ${overlap.offset}, which would re-ask for dropped rows`);

// A whole page of repeats is still progress through the server's list.
const allRepeats = mergeNodePage(rowsFrom(0, 100), rowsFrom(0, 100), { offset: 100, pageSize: 100 });
ok('a page of nothing but repeats adds nothing', allRepeats.added.length === 0);
ok('a page of nothing but repeats still moves the offset', allRepeats.offset === 200);
ok('a page of nothing but repeats is not the end', allRepeats.exhausted === false);

// --- rubbish in ----------------------------------------------------
const junk = mergeNodePage([], null, { offset: 0, pageSize: 100 });
ok('no rows at all does not throw', junk.rows.length === 0 && junk.exhausted === true);
const noId = mergeNodePage([], [{ node_id: null }, { node_id: '!1' }], { offset: 0, pageSize: 100 });
ok('a row with no id is dropped rather than drawn as a duplicate of the next',
  noId.rows.length === 1 && noId.rows[0].node_id === '!1');
ok('but it still counted towards the offset', noId.offset === 2, `offset ${noId.offset}`);

// --- what the foot of the list says --------------------------------
ok('partway through, the foot says both numbers',
  nodeProgressWords(100, 570, false) === 'Showing 100 of 570',
  nodeProgressWords(100, 570, false));
ok('the numbers are grouped for reading',
  nodeProgressWords(1000, 2372, false) === 'Showing 1,000 of 2,372',
  nodeProgressWords(1000, 2372, false));
ok('at the end it says all of it is there',
  nodeProgressWords(570, 570, true) === 'All 570 shown',
  nodeProgressWords(570, 570, true));
// The total is counted by a second query, so it can disagree by a row or
// two. At the end, what is on screen is the number that cannot be wrong.
ok('at the end it counts the rows, not the total',
  nodeProgressWords(569, 570, true) === 'All 569 shown',
  nodeProgressWords(569, 570, true));

// AN ABSENT TOTAL IS NOT ZERO. `X-Total-Count` is missing on an older
// build or behind a proxy that drops it.
ok('an absent total says so instead of showing a number',
  nodeProgressWords(100, null, false) === '100 loaded · the total is unknown',
  nodeProgressWords(100, null, false));
ok('an absent total never reads as 0',
  !/\b0\b/.test(nodeProgressWords(100, null, false)),
  nodeProgressWords(100, null, false));
ok('an absent total at the end still counts the rows',
  nodeProgressWords(37, null, true) === 'All 37 shown',
  nodeProgressWords(37, null, true));
ok('an absent total does not turn into "of -"',
  !nodeProgressWords(100, null, false).includes('of -'),
  nodeProgressWords(100, null, false));

// A list that fits on one page has nothing more to offer and must not
// invite a reader to ask for more.
ok('a single short page reads as complete',
  nodeProgressWords(19, 19, true) === 'All 19 shown',
  nodeProgressWords(19, 19, true));

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('nodes paging: all cases pass');
