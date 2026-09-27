/*
 * Behaviour cases for the reported-neighbour table on a packet page (#240).
 *
 * Run by `tests/unit/test_neighbours_are_named.py`, which shells out to
 * node.
 *
 * Run rather than read. What went wrong in #240 was not a missing
 * string, it was a cell that built a node ID and then handed that same
 * ID to `nodeChip` as the display name, so the name the API sends could
 * never appear. A grep for `neighbor_name` in the file would pass on a
 * version that read the field and threw it away. These cases call the
 * cell and look at what came out.
 *
 * `app.js` is one big script, not a module, so the functions under test
 * are extracted from the shipped file by name, the way
 * `design_pass_cases.mjs` does it. The guard at the bottom fails loudly
 * if an extraction stops finding its target, because a harness that
 * silently tests nothing is worse than no harness.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/app.js'), 'utf8');

/** Pull one top-level `function name(...) { ... }` out of the file. */
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found in app.js`);
  const end = source.indexOf('\n}', start);
  if (end < 0) throw new Error(`${name} has no closing brace`);
  return source.slice(start, end + 2);
}

/** Pull one top-level `const NAME = { ... };` out of the file. */
function objectConstant(name) {
  const start = source.indexOf(`const ${name} = {`);
  if (start < 0) throw new Error(`${name} not found in app.js`);
  const end = source.indexOf('\n};', start);
  if (end < 0) throw new Error(`${name} has no closing brace`);
  return source.slice(start, end + 3);
}

/*
 * Stand-ins for the browser's half.
 *
 * `el` records what was built instead of making DOM. `table` hands the
 * column definitions straight back, so a case can call one cell with
 * one row -- which is the unit the bug lived in. `openNode` exists
 * because `nodeChip` closes over it for a click handler that no case
 * fires.
 */
const el = (tag, attrs = {}, ...kids) => ({ tag, attrs, kids: kids.flat() });
const table = (columns, rows, emptyMessage) => ({ columns, rows, emptyMessage });
const snrCell = (snr) => ({ tag: 'span', attrs: { text: `${snr} dB` }, kids: [] });
const openNode = () => {};

const api = new Function('el', 'table', 'snrCell', 'openNode', [
  extract('nodeChip'),
  extract('neighbourValues'),
  objectConstant('DECODED_KIND'),
  'return { nodeChip, neighbourValues, DECODED_KIND };',
].join('\n'))(el, table, snrCell, openNode);

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

/** The visible text of the chip a column cell produced. */
function shown(cell) {
  // nodeChip wraps the chip in a button when it has an ID to open.
  const chip = cell.tag === 'button' ? cell.kids[0] : cell;
  const long = chip.kids.find((kid) => kid && kid.attrs && kid.attrs.class === 'long');
  return long ? long.attrs.text : null;
}

const built = api.neighbourValues([]);
const columns = built.kids[0].columns;
const nameColumn = columns[0];
const idOf = (cell) => (cell.tag === 'button' ? cell.attrs.title : null);

// --- The bug: a named neighbour must read as its name ---------------

const named = nameColumn.cell({
  neighbor_node_num: 173121538,
  neighbor_id: '!0a51a002',
  neighbor_name: 'Usery Pass Relay',
  snr: -6.25,
});
eq('a named neighbour shows its name', shown(named), 'Usery Pass Relay');
// The ID is still there to click and to hover, exactly as the gateway
// column above it does. Losing it would trade one bug for another.
eq('the name still opens the node page', idOf(named), '!0a51a002');

// --- The fallback the issue asked for ------------------------------

/*
 * The API resolves the name through `name_of`, which falls back to the
 * ID form itself, so this is what an unnamed neighbour actually looks
 * like on the wire: `neighbor_name` IS the ID.
 */
const unnamed = nameColumn.cell({
  neighbor_node_num: 3735928559,
  neighbor_id: '!deadbeef',
  neighbor_name: '!deadbeef',
  snr: -18.5,
});
eq('an unnamed neighbour shows its ID', shown(unnamed), '!deadbeef');

/*
 * And the belt-and-braces case: a row with no named fields at all. The
 * API always sends them now, so this is the shape of a cached or
 * hand-made row, and it must still print a node rather than nothing.
 * A node number above 2^31 is negative as a signed 32-bit integer, so
 * this also proves the `>>> 0` is still there.
 */
const bare = nameColumn.cell({ neighbor_node_num: 3735928559, snr: -18.5 });
eq('a row with no name falls back to the number', shown(bare), '!deadbeef');
eq('the fallback ID is clickable too', idOf(bare), '!deadbeef');

// --- #240, the second half: the spelling --------------------------

eq('the panel heading', api.DECODED_KIND.neighbors, 'Neighbors it reported');
eq('the column heading', nameColumn.label, 'Neighbor');
eq('the empty state', built.kids[0].emptyMessage, 'It reported no neighbors.');
ok(
  'no British spelling reaches the reader here',
  ![nameColumn.label, built.kids[0].emptyMessage, api.DECODED_KIND.neighbors, columns[1].hint]
    .some((text) => /neighbour/i.test(text)),
  'one of the packet page neighbour strings still says "neighbour"',
);

// --- The harness guard --------------------------------------------

ok('the name column was found', Boolean(nameColumn && nameColumn.cell),
  'neighbourValues did not yield a first column with a cell function');
ok('the SNR column is still beside it', columns[1] && columns[1].label === 'SNR',
  `second column is ${JSON.stringify(columns[1] && columns[1].label)}`);

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('neighbour name cases: all passed');
