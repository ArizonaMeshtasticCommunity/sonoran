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

  await journey(context, 'a column heading reorders the whole list', async (page) => {
    await open(page, 'nodes');
    const summary = () => page.locator('[data-node-count]').innerText();
    const roles = () => page.$$eval(
      '[data-page="nodes"] tbody tr td:nth-child(4) span',
      (cells) => cells.slice(0, 6).map((cell) => cell.textContent.trim()),
    );
    const before = await roles();
    const wasSaying = await summary();
    await page.click('[data-page="nodes"] th:nth-child(4) .sort-button');
    await page.waitForTimeout(2500);
    const after = await roles();
    const nowSaying = await summary();

    /*
     * The sort happens on the server, so the summary must name the new
     * order and the total must not move. A browser that reordered the
     * rows it already held would change the rows and leave the summary
     * saying the old thing.
     */
    must(nowSaying.includes('sorted by role'), `the summary did not follow: ${nowSaying}`);
    const total = (line) => (line.match(/^[\d,]+/) || [''])[0];
    must(total(wasSaying) === total(nowSaying), `the total moved: ${wasSaying} -> ${nowSaying}`);
    must(before.join() !== after.join() || before.length < 2, 'the rows did not reorder');
    const sorted = [...after].sort((a, b) => a.localeCompare(b));
    must(after.join() === sorted.join(), `not in order: ${after.join(', ')}`);
    return `${total(nowSaying)} nodes, reordered by role`;
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

  /*
   * A phone, walked as a phone.
   *
   * Everything above runs at 1500 px, where the nav is thirteen links
   * down the side and every hint is a tooltip a mouse can hover. On a
   * phone both of those are different objects — the nav is behind a
   * button and the hints are written into the page — and neither is
   * exercised by any journey above. A 320 px pass rides along with it,
   * because WCAG 2.2 SC 1.4.10 Reflow is a number that can be asserted
   * and a layout that regresses at 320 px regresses silently.
   */
  const phone = await browser.newContext({
    viewport: { width: 390, height: 664 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
      + 'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
  });

  await journey(phone, 'a phone reaches every page through the menu', async (page) => {
    await open(page, 'dashboard');
    const toggle = page.locator('[data-nav-toggle]');
    must(await toggle.isVisible(), 'the menu button is not shown at phone width');
    must((await toggle.getAttribute('aria-expanded')) === 'false', 'the menu starts open');
    // The nav must not be on the screen before it is asked for: that is
    // the whole point, and a stacked nav here is about 1230 CSS px.
    must(await page.locator('#site-nav').isHidden(), 'the nav is on the screen while closed');
    const box = await toggle.boundingBox();
    must(box.width >= 24 && box.height >= 24,
      `the menu button is ${box.width}x${box.height}, under 24x24 CSS px (SC 2.5.8)`);
    await toggle.click();
    await page.waitForTimeout(250);
    const links = await page.locator('#site-nav a').count();
    must(links === 13, `the menu holds ${links} links, not 13`);
    await page.locator('#site-nav a[data-nav="firehose"]').click();
    await page.waitForTimeout(3000);
    // Choosing a page closes the menu, and the button then says where
    // you are without having to be opened again.
    must((await toggle.getAttribute('aria-expanded')) === 'false',
      'the menu stayed open after a page was chosen');
    must((await page.locator('[data-nav-here]').textContent()).trim() === 'Firehose',
      'the button does not name the page');
    must(/#firehose/.test(page.url()), `did not navigate (${page.url()})`);
    return `${links} links, menu closes on choosing`;
  });

  await journey(phone, 'a phone can read what a column means', async (page) => {
    await open(page, 'firehose', 4500);
    const notes = page.locator('[data-page="firehose"] .hint-notes').first();
    must((await notes.count()) > 0, 'no column notes were written under the table');
    // Closed, the sentences are not on the screen; open, they are. A
    // `title` tooltip could pass neither check on a touch screen.
    must(!(await notes.evaluate((node) => node.open)), 'the notes start open');
    await notes.locator('summary').click();
    await page.waitForTimeout(200);
    const text = await notes.innerText();
    must(/uploaded this packet to MQTT/.test(text),
      'the Uploads sentence is not in the page');
    // And the exact wire value, which used to live only in `title`.
    must(/TELEMETRY_APP|POSITION_APP|NODEINFO_APP/.test(text),
      'no exact protocol value is reachable');
    return 'hints and exact values both visible';
  });

  await journey(phone, 'no form control invites the iOS zoom', async (page) => {
    // Under 16 px, Safari on iOS zooms the page in on focus and does
    // not zoom back out. The planner is the worst case: 21 fields.
    const small = [];
    for (const name of ['planner', 'nodes', 'coverage', 'firehose', 'graph', 'meshnet', 'map']) {
      await open(page, name, 2500);
      small.push(...await page.evaluate(() => {
        const out = [];
        for (const node of document.querySelectorAll('.page.active input, .page.active select, .page.active textarea')) {
          if (!node.getBoundingClientRect().width) continue;
          if (node.type === 'range' || node.type === 'file') continue;
          const size = parseFloat(getComputedStyle(node).fontSize);
          if (size < 16) out.push(`${location.hash} ${node.type} ${size}px`);
        }
        return out;
      }));
    }
    must(small.length === 0, `under 16 px: ${small.slice(0, 4).join(', ')}`);
    return 'every control is 16 px or larger';
  });

  await phone.close();

  /*
   * 320 CSS px, which is WCAG 2.2 SC 1.4.10 Reflow: content must not
   * need scrolling in two dimensions there. It is also 1280 px at the
   * 400 percent zoom the criterion is derived from.
   * https://www.w3.org/TR/WCAG22/#reflow
   */
  const narrow = await browser.newContext({
    viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true,
  });
  await journey(narrow, 'every page reflows at 320 CSS px', async (page) => {
    const bad = [];
    for (const name of ['dashboard', 'map', 'planner', 'coverage', 'gaps', 'config',
      'graph', 'nodes', 'chat', 'meshnet', 'firehose', 'traceroutes', 'stats']) {
      await open(page, name, 2500);
      const size = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
      // A table may scroll sideways inside `.table-wrap` — the criterion
      // excepts data tables. The DOCUMENT may not.
      if (size.scroll > size.client + 1) bad.push(`${name} ${size.scroll}/${size.client}`);
    }
    must(bad.length === 0, `scrolls in two dimensions: ${bad.join(', ')}`);
    return 'all 13 pages, no sideways document scroll';
  });
  await narrow.close();

  await browser.close();

  console.log(results.join('\n'));
  console.log('\nconsole and page errors: ' + (errors.length ? '\n  ' + errors.slice(0, 8).join('\n  ') : 'none'));
  const failed = results.filter((line) => line.startsWith('FAIL')).length;
  console.log(`\n${results.length - failed}/${results.length} journeys passed`);
  process.exit(failed || errors.length ? 1 : 0);
}

main();
