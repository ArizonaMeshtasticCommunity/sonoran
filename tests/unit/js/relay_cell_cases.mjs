/*
 * Behaviour cases for the "Relayed by" cell on a packet page (#378).
 *
 * Run by `tests/unit/test_relay_cell.py`, which shells out to node.
 *
 * The bug: `el()` flattens its children one level only. The cell passed
 * an array of [separator, chip] pairs, so each pair became the text
 * ",[object HTMLButtonElement]" (s.azmsh.dev, packet !96cc67b6/2313674657).
 * A grep would not see it. These cases build the cell with the shipped
 * `el()` and read the text a browser would show.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/app.js'), 'utf8');

function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found in app.js`);
  const end = source.indexOf('\n}', start);
  if (end < 0) throw new Error(`${name} has no closing brace`);
  return source.slice(start, end + 2);
}

// A DOM just big enough for el(): elements keep their children, and an
// element that is turned into a string says so, as a browser does.
class FakeElement {
  constructor(tag) { this.tag = tag; this.nodeType = 1; this.children = []; this.own = ''; }
  set className(v) { this.cls = v; }
  set textContent(v) { this.own = v; }
  setAttribute() {}
  addEventListener() {}
  get dataset() { return {}; }
  append(child) { this.children.push(child); }
  get text() { return this.own + this.children.map((c) => c.text).join(''); }
  toString() { return '[object HTMLButtonElement]'; }
}
const document = {
  createElement: (tag) => new FakeElement(tag),
  createTextNode: (text) => ({ nodeType: 3, text }),
};
const nodeChip = (node) => { const b = new FakeElement('button'); b.own = node.display_name; return b; };

const relayCell = new Function('document', 'nodeChip',
  `${extract('el')}\n${extract('relayCell')}\nreturn relayCell;`)(document, nodeChip);

const failures = [];
function check(label, got, want) {
  if (got !== want) failures.push(`${label}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
}
const cand = (...names) => names.map((display_name, i) => ({ node_id: `!0000000${i}`, display_name }));

check('three candidates read as names, comma separated',
  relayCell({ byte: '55', candidates: cand('Glass Cannon', '!7ba90655', 'WanderNode') }).text,
  '…55: Glass Cannon, !7ba90655, WanderNode (one of these candidates)');
check('one candidate is just its name',
  relayCell({ byte: '81', candidates: cand('South Mountain Spicy') }).text,
  '…81: South Mountain Spicy');
check('more than three: three names, then the rest as a count',
  relayCell({ byte: 'c8', candidates: cand('a', 'b', 'c', 'd', 'e') }).text,
  '…c8: a, b, c +2 (one of these candidates)');
check('no candidate heard lately',
  relayCell({ byte: '0f', candidates: [] }).text, '…0f, no node heard lately');
check('no hop: the sender itself, named as the sender, not as a candidate',
  relayCell({ byte: 'b6', exact: true, candidates: cand('Cactus Gaming Lounge') }).text,
  '…b6: Cactus Gaming Lounge (the sender, no hop)');
check('no relay byte', relayCell(null).text, '-');

if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}
console.log('relay cell: 6 cases pass');
