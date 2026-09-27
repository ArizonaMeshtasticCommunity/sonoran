/*
 * Behaviour cases for the packet timeline's paging (#259).
 *
 * `mergePacketPage` is the pure half of the infinite scroll: which rows
 * arriving are new, and whether the list has ended. Run, not read -- the
 * claims are about values.
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

const mergePacketPage = new Function(
  `${extract('packetRowKey')}\n${extract('mergePacketPage')}; return mergePacketPage;`,
)();

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

const rows = (from, howMany, sender = '!00000001') =>
  Array.from({ length: howMany }, (_, index) => ({ from_node: sender, packet_id: from + index }));

const first = mergePacketPage([], rows(0, 50), 50);
ok('a full first page is kept whole', first.rows.length === 50);
ok('a full page is not the end', first.exhausted === false);

const short = mergePacketPage(first.rows, rows(50, 7), 50);
ok('a short page is the end', short.exhausted === true);
ok('the rows are appended in order', short.rows.length === 57 && short.rows[56].packet_id === 56);

// The same row arriving twice is drawn once.
const again = mergePacketPage(first.rows, [...rows(49, 1), ...rows(50, 3)], 50);
ok('a repeated row is not drawn twice', again.rows.length === 53, `rows ${again.rows.length}`);
ok('only the new rows are reported added', again.added.length === 3);

// Identity is sender AND packet id: two senders may share a packet id.
const other = mergePacketPage(rows(0, 3), rows(0, 3, '!00000002'), 50);
ok('two senders with the same packet id are two packets', other.rows.length === 6,
  `rows ${other.rows.length}`);

// An empty or failed answer is the end, and changes nothing held.
const empty = mergePacketPage(first.rows, null, 50);
ok('an empty answer is the end', empty.exhausted === true && empty.rows.length === 50);

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('packet paging cases: all passed');
