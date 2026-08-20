// Record every API response the dashboard asks for.
//
// The recording lets a self-contained copy of the dashboard run with
// no server. See tools/dev/artifact.js.
//
//   node tools/dev/record.js [out.json]
const fs = require('fs');
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const BASE = process.env.SONORAN_DEV_URL || 'http://127.0.0.1:8000';
const OUT = process.argv[2] || '/tmp/sonoran-recording.json';

// The pages in the sidebar. The planner and the config check need a
// device and a WebAssembly engine, so they are left out.
const PAGES = ['dashboard', 'map', 'nodes', 'chat', 'meshnet', 'firehose',
               'traceroutes', 'graph', 'stats'];

const recorded = {};
let hits = 0;

function keyOf(url) {
  const u = new URL(url);
  u.searchParams.sort();
  return u.pathname + (u.search || '');
}

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

  page.on('response', async (response) => {
    const url = response.url();
    if (!url.startsWith(BASE)) return;
    const type = (response.headers()['content-type'] || '');
    if (!type.includes('application/json')) return;
    if (!response.ok()) return;
    const key = keyOf(url);
    if (key in recorded) return;
    try {
      recorded[key] = await response.json();
      hits += 1;
    } catch {
      /* not JSON after all */
    }
  });

  // The dashboard refreshes itself on a timer, so the network never
  // goes idle. Wait for the document, then give the requests of the
  // page a moment to come back.
  async function visit(hash) {
    await page.goto(`${BASE}/#${hash}`, { waitUntil: 'domcontentloaded', timeout: 20000 })
      .catch(() => {});
    await page.waitForTimeout(1200);
  }

  // Each page, once.
  for (const name of PAGES) {
    await visit(name);
    console.log(`  ${name.padEnd(12)} ${hits} responses so far`);
  }

  // Every option of every select, so the filters have data behind
  // them.
  //
  // A select is found again by its position each time. A change to a
  // filter can draw the panel again, which makes an element handle
  // from before the change point to nothing. An operation on such a
  // handle waits for the full timeout and finds nothing.
  //
  // Each page also has a deadline. One slow page must not stop the
  // run.
  page.setDefaultTimeout(2000);
  const PAGE_BUDGET_MS = 45000;

  for (const name of PAGES) {
    await visit(name);
    const deadline = Date.now() + PAGE_BUDGET_MS;
    const count = await page.$$eval('select', (els) => els.length).catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const values = await page
        .$$eval('select', (els, idx) => (els[idx] ? [...els[idx].options].map((o) => o.value) : []), i)
        .catch(() => []);
      for (const value of values.slice(0, 8)) {
        if (Date.now() > deadline) break;
        await page.selectOption(`select >> nth=${i}`, value, { timeout: 1500 }).catch(() => {});
        await page.waitForTimeout(220);
      }
      if (Date.now() > deadline) break;
    }
    console.log(`  ${name.padEnd(12)} ${hits} responses after the selects`);
  }

  // The detail page of every node.
  const nodes = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/nodes?limit=100`);
    const body = await r.json();
    const list = Array.isArray(body) ? body : body.nodes || body.items || [];
    return list.map((n) => n.node_id).filter(Boolean);
  }, BASE).catch(() => []);

  for (const id of nodes) {
    await visit(`node/${id}`);
  }
  console.log(`  nodes        ${hits} responses after ${nodes.length} node pages`);

  // The detail page of every traceroute on the list.
  const traces = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/traceroutes?limit=50`);
    const body = await r.json();
    const list = Array.isArray(body) ? body : body.traceroutes || body.items || [];
    return list.map((t) => t.id ?? t.trace_id).filter((v) => v != null);
  }, BASE).catch(() => []);

  for (const id of traces) {
    await visit(`traceroute/${id}`);
  }
  console.log(`  traceroutes  ${hits} responses after ${traces.length} trace pages`);

  await browser.close();
  fs.writeFileSync(OUT, JSON.stringify(recorded));
  const size = (fs.statSync(OUT).size / 1024 / 1024).toFixed(2);
  console.log(`\nsaved ${Object.keys(recorded).length} responses to ${OUT} (${size} MB)`);
}

main();
