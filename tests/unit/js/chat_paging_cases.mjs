/*
 * Behaviour cases for the chat page's held rows (#297).
 *
 * `chatKey` decides whether the rows already loaded still belong to the
 * page being drawn, and `chatMergeNewer` puts newly arrived rows on top
 * of them. Both are pure. Run, not read -- the claims are about values.
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

const { chatKey, chatMergeNewer } = new Function(
  `${extract('chatRowKey')}\n${extract('chatKey')}\n${extract('chatMergeNewer')}
   return { chatKey, chatMergeNewer };`,
)();

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

// The default range has no address. Its start moves every millisecond, so
// the key must not be made from it: two draws a moment apart are the
// same page.
const first = chatKey('MediumFast', null);
await new Promise((resolve) => setTimeout(resolve, 5));
ok('the default range keeps one key across redraws', chatKey('MediumFast', null) === first,
  `${first} then ${chatKey('MediumFast', null)}`);
ok('another channel is another key', chatKey('Weather', null) !== first);
// #313: azmsh on LongFast and azmsh on MediumFast are different rows.
ok('another preset is another key',
  chatKey('azmsh', null, 'LongFast') !== chatKey('azmsh', null, 'MediumFast'));
ok('the same preset keeps its key',
  chatKey('azmsh', null, 'LongFast') === chatKey('azmsh', null, 'LongFast'));

const tuesday = { from: new Date('2026-09-22T18:00:00Z'), to: new Date('2026-09-22T20:00:00Z') };
const keyed = chatKey('MediumFast', tuesday);
ok('a named range is not the default range', keyed !== first);
ok('the same named range is the same key',
  keyed === chatKey('MediumFast', { from: new Date(tuesday.from), to: new Date(tuesday.to) }));
ok('a different end is a different key',
  keyed !== chatKey('MediumFast', { from: tuesday.from, to: null }));

const rows = (from, howMany) => Array.from({ length: howMany }, (_, index) => ({
  packet_id: from + index, from_node_id: '!00000001', seen_at: `2026-09-27T00:${String(from + index).padStart(2, '0')}:00Z`,
})).reverse();

const held = rows(0, 30);
const topped = chatMergeNewer(held, rows(29, 4), 100);
ok('new rows go on top, a repeated row once', topped.rows.length === 33,
  `rows ${topped.rows.length}`);
ok('the newest row is first', topped.rows[0].packet_id === 32);
ok('a short page keeps what was held', topped.restarted === false && topped.rows[32] === held[29]);

const nothing = chatMergeNewer(held, null, 100);
ok('a failed answer changes nothing held', nothing.rows.length === 30 && !nothing.restarted);

// A full page may have more behind it than it holds. Keeping the old rows
// under it would leave a hole in the conversation that nobody could see.
const flood = rows(40, 10);
const full = chatMergeNewer(held, flood, 10);
ok('a full page starts again rather than leave a hole', full.restarted === true && full.rows.length === 10,
  `restarted ${full.restarted}, rows ${full.rows.length}`);

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('chat paging cases: all passed');
