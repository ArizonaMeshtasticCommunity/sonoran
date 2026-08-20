// Screenshot the running dev dashboard. Development helper, not shipped.
//   node tools/dev/shot.js [path-or-url] [out.png] [width] [height]
//
// A path such as "/#nodes" goes to the development server. A full URL,
// including file:///tmp/preview.html#nodes, is used as it is.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const path = process.argv[2] || '/';
const out = process.argv[3] || '/tmp/sonoran-shot.png';
const width = Number(process.argv[4] || 1440);
const height = Number(process.argv[5] || 900);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width, height } });
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  // A path goes to the development server. A full URL, including a
  // file:// URL, is used as it is, so a built preview file can be
  // checked the same way.
  const url = /^(https?|file):/.test(path) ? path : `http://127.0.0.1:8000${path}`;
  // The dashboard refreshes itself on a timer, so the network never
  // goes idle. Wait for the document instead.
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 })
    .catch((e) => errors.push(`goto: ${e.message}`));
  await page.waitForTimeout(2500);
  await page.screenshot({ path: out, fullPage: false });
  await browser.close();
  if (errors.length) console.log('page errors:\n  ' + errors.slice(0, 15).join('\n  '));
  console.log(`saved ${out}`);
})();
