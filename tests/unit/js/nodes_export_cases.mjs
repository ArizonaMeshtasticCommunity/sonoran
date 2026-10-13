/*
 * Behaviour cases for the node list export (#350).
 *
 * The file must hold what the list shows. In the browser that rests on
 * two pure functions, run here rather than read:
 *
 *  - `nodeExportQuery` takes the list's own query and removes only the
 *    paging. Every filter, the search and the sort must survive it.
 *  - `nodeExportColumns` reads the columns from `nodeColumns`, the one
 *    list the table is drawn from, in the order it is drawn.
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

const nodeExportQuery = new Function(`${extract('nodeExportQuery')}; return nodeExportQuery;`)();
const nodeExportName = new Function(`${extract('nodeExportName')}; return nodeExportName;`)();
const nodeExportColumns = new Function(`${extract('nodeExportColumns')}; return nodeExportColumns;`)();
// `nodeColumns` builds cells with page helpers. None of them runs here:
// only the column objects are read, never a cell.
const nodeColumns = new Function(
  'const el = () => null, nodeChip = el, roleCell = el, tapTip = el, ago = el;'
  + " const HEARD_HINT = '', nodeSort = { key: 'last_heard', order: 'desc' };"
  + ` ${extract('nodeColumns')}; return nodeColumns;`,
)();

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

const params = (path) => new URLSearchParams(path.split('?')[1]);

// --- the query ------------------------------------------------------
const list = 'api/nodes?limit=100&sort=name&order=asc&cursor=abc&offset=200&q=base'
  + '&active_hours=24&role=ROUTER&gateway=true&channel=LongFast&position=none'
  + '&gaps=bad&gaps_preset=LongFast';
const path = nodeExportQuery(list, 'csv', ['name', 'node_id']);
const got = params(path);
ok('the export asks the export route', path.startsWith('api/nodes/export?'), path);
for (const key of ['limit', 'cursor', 'offset']) {
  ok(`the paging (${key}) comes off`, !got.has(key), path);
}
for (const key of ['q', 'active_hours', 'role', 'gateway', 'channel', 'position', 'gaps',
  'gaps_preset', 'sort', 'order']) {
  ok(`the filter ${key} goes with the file`, got.get(key) === params(list).get(key),
    `${key}: ${got.get(key)} in ${path}`);
}
ok('the format is named', got.get('format') === 'csv', path);
ok('the columns keep their order', got.get('columns') === 'name,node_id', path);
ok('a list with no filters still works',
  nodeExportQuery('api/nodes?limit=100', 'json', ['role']) === 'api/nodes/export?format=json&columns=role');

// --- the columns ----------------------------------------------------
const columns = nodeColumns(() => {});
const keys = nodeExportColumns(columns);
ok('every drawn column is in the file', keys.length === columns.length,
  `${keys.length} export keys for ${columns.length} columns`);
ok('the columns come in the drawn order',
  keys.join() === 'name,node_id,hw,role,flags,last_heard', keys.join());
const moved = [columns[5], columns[0]];
ok('a moved column moves in the file', nodeExportColumns(moved).join() === 'last_heard,name');

// --- the file name --------------------------------------------------
ok('the server name is used',
  nodeExportName('attachment; filename="sonoran-nodes-20261008-120000Z.csv"', 'csv')
    === 'sonoran-nodes-20261008-120000Z.csv');
ok('no header still gives a name', nodeExportName(null, 'json') === 'sonoran-nodes.json');

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('nodes export cases: all passed');
