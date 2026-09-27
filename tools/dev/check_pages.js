/*
 * Load every page and fail on a JavaScript error.
 *
 * There is no build step and no JavaScript test runner here, so a
 * mistake like a name that does not exist is not caught by anything
 * until somebody opens the page. It does not look like a crash either:
 * the function that threw simply stops, and the part of the page it
 * was drawing stays empty. A legend lost its upper figure that way.
 *
 * This opens each page in a real browser and reports what the console
 * and the error handler saw. A missing tile is a 404 by design, so
 * those are ignored.
 *
 *     ./tools/dev/preview.sh            # in one terminal
 *     node tools/dev/check_pages.js     # in another
 *
 * Set SONORAN_URL to check a different instance.
 */

/*
 * Playwright may be installed here, globally, or not at all. Try each
 * in turn and say which, rather than failing with a stack trace.
 */
function loadChromium() {
  /*
   * `@playwright/test` bundles its own copy and is what Homebrew
   * installs, so a machine with a working `e2e.js` could still not run
   * this one — it knew two of the three places and `npm i -g playwright`
   * fails on that machine with a file conflict. A check that answers
   * "not installed" on a machine that has it is a check nobody runs, so
   * the two loaders now know the same list.
   */
  const places = [
    'playwright',
    '/opt/node22/lib/node_modules/playwright',
    '/opt/homebrew/lib/node_modules/@playwright/test',
  ];
  for (const place of places) {
    try {
      return require(place).chromium;
    } catch (error) {
      if (error.code !== 'MODULE_NOT_FOUND') throw error;
    }
  }
  console.log('playwright is not installed. Run: npm i -g playwright');
  process.exit(2);
  return null;
}

const chromium = loadChromium();

const BASE = process.env.SONORAN_URL || 'http://127.0.0.1:8000';

// Every page the router serves, and the embed, which is its own
// document and shares none of the dashboard's code.
const PAGES = [
  '/#dashboard',
  '/#map',
  '/#planner',
  '/#coverage',
  '/#config',
  '/#graph',
  '/#nodes',
  '/#chat',
  /*
   * `#meshnet`, not `#checkin`.
   *
   * This list said `#checkin`, which is not a route: `route()` does not
   * find it in `PAGES` and falls back to the dashboard. So the weekly
   * check-in page was never opened by this check, and the dashboard was
   * checked twice -- a green that meant nothing for the page it named.
   * The nav link has always been `#meshnet`.
   */
  '/#meshnet',
  '/#firehose',
  '/#traceroutes',
  '/#stats',
  '/#gaps',
  '/embed/coverage',
];

// A tile that was never written is ground no node reaches. The map
// asks for it, gets a 404, and draws nothing. That is the design.
const EXPECTED = [
  /Failed to load resource.*404/i,
  // The config check page reads the latest firmware version from
  // api.github.com, which the CSP allows and which sends nothing about
  // the config being checked. A sandbox that inspects TLS breaks that
  // one request and it is not a fault in the page.
  /ERR_CERT_AUTHORITY_INVALID/i,
];

async function main() {
  const browser = await chromium.launch();
  let failures = 0;

  for (const path of PAGES) {
    const page = await browser.newPage();
    const errors = [];
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('pageerror', (error) => errors.push(String(error)));

    try {
      await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      // The pages draw after they fetch. Give them a moment to throw.
      await page.waitForTimeout(2500);
    } catch (error) {
      errors.push(`goto: ${error.message}`);
    }

    const real = errors.filter((text) => !EXPECTED.some((pattern) => pattern.test(text)));
    if (real.length) {
      failures += 1;
      console.log(`FAIL ${path}`);
      for (const text of real.slice(0, 6)) console.log(`       ${text}`);
    } else {
      console.log(`ok   ${path}`);
    }
    await page.close();
  }

  await browser.close();
  if (failures) {
    console.log(`\n${failures} page(s) reported a JavaScript error.`);
    process.exit(1);
  }
  console.log('\nEvery page loaded with no JavaScript error.');
}

main();
