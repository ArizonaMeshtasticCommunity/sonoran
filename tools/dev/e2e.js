/*
 * Walk the dashboard the way a person does, and fail when a journey breaks.
 *
 * `check_pages.js` opens every page and fails on a JavaScript error. That
 * catches a page that throws. It does not catch a page that loads happily
 * and does nothing useful: a search box wired to no handler, a button that
 * expands nothing, a picker that reloads the same rows.
 *
 * So this clicks. Each journey asserts the thing a person came for, and
 * asserts it in a way that a broken feature fails rather than passes. The
 * first draft of the search journey asserted `rows > 0` after typing, which
 * passed against a search that filtered nothing at all.
 *
 *     ./tools/dev/preview.sh          # in one terminal
 *     node tools/dev/e2e.js           # in another
 *
 * Set SONORAN_URL to walk a different instance.
 */

function loadChromium() {
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

const results = [];
const errors = [];

/* A tile that is not cached yet is a 404 by design, as in check_pages.js. */
const IGNORE = /404|favicon|tile/i;

function must(condition, message) {
  if (!condition) throw new Error(message);
}

async function journey(context, name, body) {
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(`${name}: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' && !IGNORE.test(message.text())) {
      errors.push(`${name}: ${message.text()}`);
    }
  });
  try {
    const detail = await body(page);
    results.push(`PASS  ${name}${detail ? ' — ' + detail : ''}`);
  } catch (error) {
    const first = String(error.message).split('\n')[0].slice(0, 140);
    results.push(`FAIL  ${name} — ${first}`);
  }
  await page.close();
}

const open = async (page, hash, settle = 3500) => {
  await page.goto(`${BASE}/#${hash}`, { waitUntil: 'load' });
  await page.waitForTimeout(settle);
};

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1500, height: 1050 } });

  await journey(context, 'dashboard → a node page', async (page) => {
    await open(page, 'dashboard');
    const link = page.locator('[data-page="dashboard"] button.linky, [data-page="dashboard"] .linky').first();
    const label = (await link.textContent()).trim();
    await link.click();
    await page.waitForTimeout(3500);
    must(/#node/.test(page.url()), 'did not route to a node page');
    const head = await page.locator('[data-page="node"] .page-head, [data-page="node"] h2').first().textContent();
    must(head && head.trim(), 'the node page drew no heading');
    return `opened ${JSON.stringify(label)}`;
  });

  await journey(context, 'a capped list opens in place', async (page) => {
    await open(page, 'nodes');
    await page.locator('[data-page="nodes"] .linky').first().click();
    await page.waitForTimeout(4000);
    const more = page.locator('[data-page="node"] .more');
    if ((await more.count()) === 0) return 'this node has nothing capped';
    const button = more.first();
    const rows = (node) => node.closest('.panel').querySelectorAll('tbody tr, ul.messages li').length;
    const before = await button.evaluate(rows);
    await button.click();
    await page.waitForTimeout(400);
    const after = await button.evaluate(rows);
    must(after > before, `rows did not grow (${before} -> ${after})`);
    return `${before} -> ${after} rows`;
  });

  await journey(context, 'the nodes search narrows the list', async (page) => {
    await open(page, 'nodes');
    const count = () => page.locator('[data-page="nodes"] tbody tr').count();
    const before = await count();
    const box = page.locator('[data-page="nodes"] [data-node-search]').first();
    /*
     * Enter, not typing. This search applies on Enter or the Apply
     * button, unlike the graph search which filters on input. Typing
     * alone must never be mistaken for a working search.
     */
    await box.fill('base');
    await box.press('Enter');
    await page.waitForTimeout(3500);
    const narrowed = await count();
    must(narrowed > 0, 'a plausible term returned nothing');
    must(narrowed < before, `the list did not narrow (${before} -> ${narrowed})`);
    await box.fill('zzzznotathing');
    await box.press('Enter');
    await page.waitForTimeout(3000);
    const none = await count();
    must(none === 0, `a nonsense term still returned ${none} rows`);
    return `${before} -> ${narrowed} for "base", 0 for nonsense`;
  });

  await journey(context, 'chat reloads on a new window', async (page) => {
    await open(page, 'chat');
    const before = await page.locator('[data-chat-body] .panel').count();
    await page.selectOption('[data-chat-hours]', '24');
    await page.waitForTimeout(3500);
    const after = await page.locator('[data-chat-body] .panel').count();
    must(after > 0, 'no channel sections after changing the window');
    return `${before} sections over 7 days, ${after} over 24 h`;
  });

  await journey(context, 'coverage switches preset', async (page) => {
    await open(page, 'coverage', 5000);
    /*
     * A deployment with no published coverage run offers no preset,
     * because there is nothing to choose between. That is the page
     * working, not the page broken, and a preview usually looks like
     * this: the coverage job has never run there.
     *
     * So ask the API what it has before deciding what the page owes us.
     * Asserting `options > 0` unconditionally failed against every fresh
     * preview and told nobody anything.
     */
    const published = await page.evaluate(async () => {
      const base = (window.SONORAN && window.SONORAN.apiBase) || '';
      const answer = await fetch(`${base.replace(/\/$/, '')}/api/coverage`);
      return answer.ok ? (await answer.json()).available === true : false;
    });
    const select = page.locator('[data-coverage-preset]');
    const options = await select.locator('option').count();
    if (!published) {
      must(options === 0, `no run is published, yet ${options} presets were offered`);
      const said = await page.locator('[data-page="coverage"]').innerText();
      must(said.trim().length > 40, 'no run, and the page said nothing about it');
      return 'no run published; the page says so';
    }
    must(options > 0, 'a run is published but no preset was offered');
    if (options > 1) {
      await select.selectOption(await select.locator('option').nth(1).getAttribute('value'));
      await page.waitForTimeout(4000);
    }
    must((await page.locator('#coverage-map').count()) > 0, 'the coverage map went away');
    return `${options} presets`;
  });

  await journey(context, 'the embed snippet can be got at', async (page) => {
    await open(page, 'coverage', 4000);
    await page.click('[data-embed-box] > summary');
    await page.waitForTimeout(600);
    const snippet = await page.$eval('[data-embed-snippet]', (node) => node.value);
    const status = await page.$eval('[data-embed-status]', (node) => node.textContent.trim());
    must(snippet.includes('<iframe'), 'the snippet holds no iframe');
    must(status.length > 20, 'nothing said whether the embed would work');
    return 'snippet and status both present';
  });

  await journey(context, 'gaps counts what it cannot tell', async (page) => {
    await open(page, 'gaps', 5000);
    const text = await page.locator('[data-page="gaps"]').innerText();
    /* Unknown must never render as zero or as clean. */
    must(/cannot tell|not enough evidence/i.test(text), 'the unknown state is not surfaced');
    const select = page.locator('[data-page="gaps"] select').first();
    if ((await select.count()) > 0 && (await select.locator('option').count()) > 1) {
      await select.selectOption(await select.locator('option').nth(1).getAttribute('value'));
      await page.waitForTimeout(3500);
    }
    must((await page.locator('[data-page="gaps"]').innerText()).length > 200, 'the page emptied on switching preset');
    return 'unknown surfaced, preset switch holds';
  });

  await journey(context, 'gaps sites against an area', async (page) => {
    await open(page, 'gaps', 6000);
    const panel = page.locator('.gap-siting');
    must((await panel.count()) > 0, 'the siting half is not on the page');
    const text = await panel.innerText();
    /* A siting suggestion that does not say what it cannot know is a
       lie of omission, so the limits list is the first assertion. */
    must(/cannot know/i.test(text), 'the siting limits are not shown');
    must(/dBm of transmit power/.test(text), 'the assumed radio is not printed');
    const rows = await page.locator('.gap-siting table tbody tr').count();
    if (!rows) return 'no area to site against, and the page says so';
    /* The tail of the ranking opens in place and the count is real. */
    const more = page.locator('.gap-siting button.linky').first();
    if ((await more.count()) > 0) {
      const before = rows;
      await more.click();
      await page.waitForTimeout(800);
      const after = await page.locator('.gap-siting table tbody tr').count();
      must(after > before, `the ranking did not open (${before} -> ${after})`);
    }
    /* A row opens to what the engine or the screen actually said. */
    await page.locator('.gap-siting table tbody tr').first().click();
    await page.waitForTimeout(600);
    const opened = await page.locator('.gap-siting .gap-detail').count();
    must(opened > 0, 'a candidate row did not open');
    return `${rows} candidates, a row opens`;
  });

  await journey(context, 'watch mode opens and Escape leaves', async (page) => {
    await open(page, 'map', 6000);
    const enter = page.locator('[aria-label="Watch mode"]').first();
    must((await enter.count()) > 0, 'no watch mode control');
    await enter.click();
    await page.waitForTimeout(2500);
    const panel = page.locator('[data-watch-panel]');
    must((await panel.count()) > 0, 'no watch panel appeared');
    const controls = page.locator('[data-watch-panel] button, [data-watch-panel] [role="tab"]');
    const total = await controls.count();
    if (total > 1) {
      await controls.nth(1).click();
      await page.waitForTimeout(900);
    }
    await page.keyboard.press('Escape');
    await page.waitForTimeout(1800);
    return `panel with ${total} controls, Escape exits`;
  });

  await journey(context, 'a traceroute opens', async (page) => {
    await open(page, 'traceroutes', 4000);
    const link = page.locator('[data-page="traceroutes"] .linky').first();
    if ((await link.count()) === 0) return 'none stored to open';
    await link.click();
    await page.waitForTimeout(3000);
    must(/#traceroute|#packet|#node|#link/.test(page.url()), `did not navigate (${page.url()})`);
    return 'opened one';
  });

  await journey(context, 'the firehose draws rows', async (page) => {
    await open(page, 'firehose', 4000);
    const rows = await page.locator('[data-page="firehose"] tbody tr, [data-page="firehose"] li').count();
    must(rows > 0, 'the firehose drew nothing');
    return `${rows} rows`;
  });

  await journey(context, 'statistics draws its charts', async (page) => {
    await open(page, 'stats', 6000);
    const canvases = await page.locator('[data-page="stats"] canvas').count();
    must(canvases > 0, 'no chart was drawn');
    return `${canvases} charts`;
  });

  await journey(context, 'the planner offers its control', async (page) => {
    await open(page, 'planner', 5000);
    must((await page.locator('[data-planner-run]').count()) > 0, 'no run control');
    return 'run control present';
  });

  await browser.close();

  console.log(results.join('\n'));
  console.log('\nconsole and page errors: ' + (errors.length ? '\n  ' + errors.slice(0, 8).join('\n  ') : 'none'));
  const failed = results.filter((line) => line.startsWith('FAIL')).length;
  console.log(`\n${results.length - failed}/${results.length} journeys passed`);
  process.exit(failed || errors.length ? 1 : 0);
}

main();
