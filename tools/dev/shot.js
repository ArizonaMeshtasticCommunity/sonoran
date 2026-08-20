// Screenshot the running dev dashboard. Development helper, not shipped.
//   node tools/dev/shot.js [url-path] [out.png] [width] [height]
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
  await page.goto(`http://127.0.0.1:8000${path}`, { waitUntil: 'networkidle', timeout: 30000 })
    .catch((e) => errors.push(`goto: ${e.message}`));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: out, fullPage: false });
  await browser.close();
  if (errors.length) console.log('page errors:\n  ' + errors.slice(0, 15).join('\n  '));
  console.log(`saved ${out}`);
})();
