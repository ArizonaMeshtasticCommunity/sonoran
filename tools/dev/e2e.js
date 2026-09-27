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
 * Set SONORAN_URL to walk a different instance. Set
 * SONORAN_LOCAL_STATIC=1 to walk one with this checkout's `app.js` and
 * `app.css` in place of its own, which is how a dashboard change is
 * tested against real data before it is deployed.
 */

const fs = require('fs');
const path = require('path');

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
// Console errors from somebody else's host. Reported, never fatal.
const elsewhere = [];
const errors = [];

/*
 * A tile that is not cached yet is a 404 by design, as in check_pages.js.
 *
 * "No terrain is held for this area" is the same fact one level up. The
 * planner logs its refusal before it prints it, and on an instance with
 * an empty terrain cache — CI — that refusal is the page working
 * correctly. It is matched by its own sentence, so any other planner
 * failure still counts as an error.
 */
const IGNORE = /404|favicon|tile|No terrain is held for this area/i;

/*
 * A console error is only ours if it came from our own origin.
 *
 * The suite treats any console error as a failure, which is right --
 * it is how a silently broken page gets caught. But the dashboard
 * makes one outbound request by design: the config check page asks
 * api.github.com which firmware release is current. An unauthenticated
 * runner gets rate-limited, GitHub answers 403, and the whole suite
 * failed on somebody else's quota while reporting "19/19 journeys
 * passed" -- a red run with nothing red in it, which is the worst kind.
 *
 * So a failed request to a host that is not the app under test is
 * recorded and reported, and does not fail the run. A failure from our
 * own origin still does.
 *
 * The URL is captured too. The message alone was "Failed to load
 * resource: the server responded with a status of 403 ()", with no way
 * to tell which host, which cost real time to diagnose.
 */
function ourOrigin() {
  try {
    return new URL(BASE).origin;
  } catch {
    return null;
  }
}

function isOurs(url) {
  const origin = ourOrigin();
  if (!origin || !url) return true;
  try {
    return new URL(url).origin === origin;
  } catch {
    return true;
  }
}

function must(condition, message) {
  if (!condition) throw new Error(message);
}

/*
 * Serve the working tree's static files over somebody else's instance.
 *
 * A dashboard change has no data of its own. The instance worth
 * walking is the one with a real mesh in it, and that one runs the
 * deployed code, so a journey run against it cannot say whether an
 * unmerged change works. `SONORAN_LOCAL_STATIC=1` fulfils the four
 * asset requests from this checkout instead, which tests the change
 * against real rows before it is deployed. The default is off: a run
 * with no environment set still walks exactly what is deployed.
 */
const LOCAL_STATIC = process.env.SONORAN_LOCAL_STATIC === '1';
const STATIC_DIR = path.join(__dirname, '..', '..', 'src', 'sonoran', 'web', 'static');
const TYPES = { js: 'application/javascript', css: 'text/css' };

async function serveLocalStatic(page) {
  if (!LOCAL_STATIC) return;
  // A regular expression, not a glob: every asset is requested with a
  // `?v=` cache buster on it, and a glob `*` does not cross the `?`.
  await page.route(/\/static\/[^/?]+\.(js|css)(\?|$)/, (route, request) => {
    const name = path.basename(new URL(request.url()).pathname);
    const file = path.join(STATIC_DIR, name);
    if (!fs.existsSync(file)) return route.continue();
    return route.fulfill({
      contentType: TYPES[name.split('.').pop()],
      body: fs.readFileSync(file, 'utf8'),
    });
  });
}

async function journey(context, name, body) {
  const page = await context.newPage();
  await serveLocalStatic(page);
  page.on('pageerror', (error) => errors.push(`${name}: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() !== 'error' || IGNORE.test(message.text())) return;
    // A console error carries the offending URL in its location, which
    // the text does not.
    const where = (message.location() || {}).url || '';
    if (!isOurs(where)) {
      elsewhere.push(`${name}: ${message.text()} [${where || 'unknown host'}]`);
      return;
    }
    errors.push(`${name}: ${message.text()}${where ? ` [${where}]` : ''}`);
  });
  page.on('requestfailed', (request) => {
    const url = request.url();
    if (!isOurs(url) || IGNORE.test(url)) return;
    errors.push(`${name}: request failed ${url} (${(request.failure() || {}).errorText})`);
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

/**
 * Poll a condition in the page until it holds, or give up.
 *
 * NOT `page.waitForFunction`. That installs its poller with CDP
 * `Runtime.evaluate`, which is a string of JavaScript, and this
 * dashboard's Content-Security-Policy refuses it: `script-src` carries
 * 'self', a nonce and 'wasm-unsafe-eval', and deliberately not
 * 'unsafe-eval'. On a CI instance it fails with
 *
 *   EvalError: Refused to evaluate a string as JavaScript
 *
 * and it fails only when the condition is not already true, because
 * Playwright evaluates the predicate once before it starts polling. So
 * it works on the developer's machine and breaks on the server, which
 * is the worst shape a helper can have. `page.evaluate` goes through
 * `Runtime.callFunctionOn` and is not subject to the policy, which is
 * why every journey in this file uses it.
 */
async function waitFor(page, condition, timeout = 240000, step = 500) {
  const until = Date.now() + timeout;
  for (;;) {
    if (await page.evaluate(condition)) return true;
    if (Date.now() >= until) return false;
    await page.waitForTimeout(step);
  }
}

/** True once the planner has either drawn a summary or refused to. */
const PLANNER_SETTLED = () => {
  const summary = document.querySelector('[data-planner-summary]');
  const notice = document.querySelector('[data-planner-notice]');
  const refused = notice && notice.className.includes('bad') && notice.textContent.trim();
  return (summary && summary.children.length > 0) || Boolean(refused);
};

/**
 * Wait for the planner, and report whether it could predict at all.
 *
 * An instance with an empty terrain cache cannot predict anything: every
 * page comes back 404 and the planner refuses, which is the deployment
 * being new rather than the page being broken. CI is exactly that
 * deployment. This waits for whichever comes first, a filled summary or
 * a refusal, so a journey can carry on either way and say which it got.
 *
 * The first draft of this waited only for the summary and turned a
 * missing terrain cache into a five-minute timeout and a red suite.
 *
 * `start` runs the prediction. A shared link starts one by itself, and
 * then there is nothing to click.
 */
async function predict(page, start, timeout = 240000) {
  if (start) await start();
  if (!(await waitFor(page, PLANNER_SETTLED, timeout))) {
    return { ran: false, why: 'the run neither finished nor refused inside the time allowed' };
  }
  const filled = await page.evaluate(
    () => document.querySelector('[data-planner-summary]').children.length > 0,
  );
  if (filled) {
    await page.waitForTimeout(1200);
    return { ran: true, why: '' };
  }
  // `textContent`, not `innerText`: the notice may be hidden again by
  // the time this reads it, and a hidden element has no innerText.
  const said = (await page.locator('[data-planner-notice]').textContent().catch(() => '')) || '';
  return { ran: false, why: said.trim().slice(0, 90) || 'the planner refused and said nothing' };
}

/*
 * Put the planner form into Advanced.
 *
 * §6.5 moved Range, and all the rest of Ground and air, out of Simple.
 * The mode is CSS, so `.value` still reads on a hidden field and only
 * Playwright's `fill` and `selectOption` care -- they refuse an element
 * that is not visible, which is the right refusal and not a bug to work
 * around with `force`.
 *
 * The journeys that need this are the two that ask for a short run: a
 * 10 km radius rather than the default 30, because the run is the slow
 * part of each of them.
 *
 * `waitFor` and not `page.waitForFunction`: see the note on `waitFor`.
 * `waitForFunction` installs its poller as a string of JavaScript, which
 * this dashboard's Content-Security-Policy refuses, and it refuses it
 * only when the condition is not already true -- so it would work here
 * and fail on the server.
 */
async function advanced(page) {
  await page.click('[data-planner-mode="advanced"]');
  const shown = await waitFor(page, () => {
    const box = document.querySelector('[data-planner="radius"]');
    return Boolean(box && box.offsetParent !== null);
  }, 5000);
  must(shown, 'the Advanced control did not reveal the fields it hides');
}

/*
 * The widths a node page table is held to (#255, #260): a phone at the
 * WCAG reflow floor, a tablet, a small laptop and a desktop. Each one
 * puts the node page grid on a different number of tracks, so a table
 * that fits at one says nothing about the next.
 */
const TABLE_WIDTHS = [320, 768, 1024, 1440];

/**
 * Whether one table fits the `.table-wrap` that holds it, at each width.
 *
 * The reflow journey below measures the DOCUMENT, and a table scrolling
 * sideways inside its own wrapper never widens the document -- that is
 * what the wrapper is for. So the 320 px sweep stayed green over both
 * tables Will reported. This measures the wrapper.
 *
 * (Not the sweep's own title here: `test_settings_and_units.py` finds the
 * sweep by that title, and a comment quoting it is found first.)
 *
 * `find` runs in the page and returns the `.table-wrap`, or null. A
 * missing wrapper is a failure, never a pass: a panel that drew its empty
 * state instead of the table has fitted nothing.
 */
async function tableFitsAt(page, find, label) {
  const out = [];
  for (const width of TABLE_WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(400);
    const size = await page.evaluate(find);
    must(size, `${label}: no table at ${width} px, so nothing was measured`);
    must(
      size.scroll <= size.client + 1,
      `${label} scrolls sideways at ${width} px: the table is ${size.scroll} px in a ${size.client} px panel`,
    );
    out.push(`${width}:${size.scroll}/${size.client}`);
  }
  return out.join(' ');
}

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

  await journey(context, 'the Activity table fits its panel at every width', async (page) => {
    /*
     * #255. The seeded mesh sends mostly telemetry, and "Telemetry" fits
     * anywhere, so a real node alone would pass this before the fix as
     * well as after it. The node's own answer is therefore extended with
     * the three longest labels the dashboard really prints and a count in
     * the millions -- what a busy node on the live mesh shows -- and the
     * table is asserted to have drawn them before anything is measured.
     */
    const nodes = await (await page.request.get(`${BASE}/api/nodes?limit=5`)).json();
    must(Array.isArray(nodes) && nodes.length, 'the instance has no nodes to open');
    const LONG = ['UNREADABLE_UNRECORDED', 'TEXT_MESSAGE_COMPRESSED_APP', 'UNREADABLE_PKI'];
    await page.route(/\/api\/nodes\/[^/]+\/detail\?/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.activity.by_portnum.push(...LONG.map((portnum) => ({ portnum, count: 1234567 })));
      await route.fulfill({ response, json: body });
    });
    // Found by its heading, the thing a reader finds it by, so the
    // journey does not depend on a hook the fix itself added.
    const find = () => {
      const panel = [...document.querySelectorAll('[data-page="node"] .panel')]
        .find((node) => /^Activity/.test((node.querySelector('h3') || {}).textContent || ''));
      const wrap = panel && panel.querySelector('.table-wrap');
      const table = wrap && wrap.querySelector('table');
      return table ? {
        scroll: Math.max(table.scrollWidth, wrap.scrollWidth),
        client: wrap.clientWidth,
        text: wrap.innerText,
      } : null;
    };
    await page.goto(`${BASE}/#node/${encodeURIComponent(nodes[0].node_id)}`, { waitUntil: 'load' });
    must(await waitFor(page, find, 15000), 'the Activity table never drew');
    const { text } = await page.evaluate(find);
    must(/Unreadable, reason not recorded/.test(text) && /1,234,567/.test(text),
      'the long labels were not drawn, so this would measure a table that was never stressed');
    return tableFitsAt(page, find, 'the Activity table');
  });

  await journey(context, 'the Who hears it table fits its panel at every width', async (page) => {
    /*
     * #260. On the node heard by the most nodes, as the issue asks: the
     * rows come from `/routes`, so that is what is compared. One row's
     * name is then replaced with a long name that has no space in it --
     * names like that are ordinary on this mesh -- because a table that
     * fits only short names has not been shown to fit.
     */
    const nodes = await (await page.request.get(`${BASE}/api/nodes?limit=40`)).json();
    must(Array.isArray(nodes) && nodes.length, 'the instance has no nodes to open');
    let busiest = null;
    for (const node of nodes) {
      const id = encodeURIComponent(node.node_id);
      const routes = await (await page.request.get(`${BASE}/api/nodes/${id}/routes?hours=720`)).json();
      const heard = (routes.heard_by || []).length;
      if (!busiest || heard > busiest.heard) busiest = { id: node.node_id, heard };
    }
    must(busiest && busiest.heard > 0, 'no node on this instance is heard by any other node');
    const LONG_NAME = 'UTOPIA-PLANITIA-G3-RIDGELINE-REPEATER';
    await page.route(/\/api\/nodes\/[^/]+\/routes\?/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      if (body.heard_by && body.heard_by.length) body.heard_by[0].display_name = LONG_NAME;
      await route.fulfill({ response, json: body });
    });
    const find = () => {
      const heading = [...document.querySelectorAll('[data-page="node"] h4')]
        .find((node) => /^Who hears it/.test(node.textContent));
      const wrap = heading && heading.parentElement.querySelector('.table-wrap');
      const table = wrap && wrap.querySelector('table');
      return table ? {
        scroll: Math.max(table.scrollWidth, wrap.scrollWidth),
        client: wrap.clientWidth,
        text: wrap.innerText,
      } : null;
    };
    await page.goto(`${BASE}/#node/${encodeURIComponent(busiest.id)}`, { waitUntil: 'load' });
    must(await waitFor(page, find, 15000), 'the Who hears it table never drew');
    must((await page.evaluate(find)).text.includes(LONG_NAME),
      'the long name was not drawn, so this would measure a table that was never stressed');
    const fits = await tableFitsAt(page, find, 'the Who hears it table');
    /*
     * Fitting on the fonts of the machine that runs this is not enough.
     * It passed here at exactly 254 px in a 254 px panel on macOS, and
     * failed on the CI runner, whose Linux fonts are wider, at 269. So at
     * the narrowest width it must also fit with every letter 0.05em wider,
     * about the difference between the two.
     */
    await page.setViewportSize({ width: TABLE_WIDTHS[0], height: 900 });
    await page.addStyleTag({ content: '.route-list * { letter-spacing: .05em !important; }' });
    await page.waitForTimeout(400);
    const wide = await page.evaluate(find);
    must(
      wide.scroll <= wide.client + 1,
      `the Who hears it table scrolls sideways at ${TABLE_WIDTHS[0]} px with wider letters: the table is ${wide.scroll} px in a ${wide.client} px panel`,
    );
    return `${busiest.id}, heard by ${busiest.heard}: ${fits}; wider letters ${wide.scroll}/${wide.client}`;
  });

  await journey(context, 'a furthest-node tile shows a distance or says why not', async (page) => {
    /*
     * #257. Every node shows a distance -- with a range when a position
     * is rounded -- or a sentence saying why there is none. Never a bare
     * "-", and never a precise-looking figure from a rounded position.
     *
     * One node of each kind the API reports is opened: an exact distance,
     * an estimate, and each reason for none. The kinds come from /routes,
     * so the tiles are checked against what they were given rather than
     * against a count written here.
     */
    const nodes = await (await page.request.get(`${BASE}/api/nodes?limit=40`)).json();
    must(Array.isArray(nodes) && nodes.length, 'the instance has no nodes to open');
    const kinds = new Map();
    for (const node of nodes) {
      const routes = await (await page.request.get(
        `${BASE}/api/nodes/${encodeURIComponent(node.node_id)}/routes?hours=720`)).json();
      const row = routes.furthest_heard_by;
      const kind = !row ? `reason:${routes.furthest_heard_by_reason}`
        : row.distance_km != null ? 'exact' : 'estimate';
      if (!kinds.has(kind)) kinds.set(kind, node.node_id);
    }
    must(kinds.has('estimate'), `no node here has an estimated distance; kinds found: ${[...kinds.keys()].join(', ')}`);
    must([...kinds.keys()].some((kind) => kind.startsWith('reason:')),
      'no node here lacks a distance, so the reason sentences were never exercised');
    const seen = [];
    for (const [kind, id] of kinds) {
      await page.goto(`${BASE}/#node/${encodeURIComponent(id)}`, { waitUntil: 'load' });
      // Written out in full: `page.evaluate` sends the function's text,
      // so it cannot close over a helper defined out here.
      const read = () => {
        const found = [...document.querySelectorAll('[data-page="node"] .route-tile')]
          .find((node) => /^Furthest node that heard it/i.test(node.querySelector('.label').textContent));
        return found ? {
          value: found.querySelector('.value').textContent.trim(),
          detail: [...found.querySelectorAll('.muted')].map((node) => node.textContent).join(' '),
        } : null;
      };
      must(await waitFor(page, read, 15000), `${id}: the furthest tile never drew`);
      const { value, detail } = await page.evaluate(read);
      must(value !== '-' && value !== '', `${id} (${kind}): the tile is a bare "${value}"`);
      if (kind === 'exact') {
        must(/^\d[\d.,]*\s?(ft|mi|m|km)$/.test(value), `${id}: an exact distance reads "${value}"`);
      } else if (kind === 'estimate') {
        must(/^(about|under) /.test(value), `${id}: an estimate is printed as a plain figure: "${value}"`);
        must(/±|rounded by up to/.test(detail), `${id}: an estimate has no range beside it: "${detail}"`);
      } else {
        must(value === 'Not known', `${id} (${kind}): no distance, yet the tile reads "${value}"`);
        must(detail.length > 40, `${id} (${kind}): no sentence says why: "${detail}"`);
      }
      seen.push(`${kind}=${value}`);
    }
    return seen.join('; ');
  });

  await journey(context, 'the packet timeline scrolls on by cursor', async (page) => {
    /*
     * #259. Four claims, each checked on the running page:
     *   1. the explanation is behind an info control on the title, and
     *      "LAST 720 H" is gone;
     *   2. the window control is on the title's row, at its right;
     *   3. scrolling to the foot loads the next page with `before=`, never
     *      `offset=`, and carries the sort -- watched on the requests, the
     *      only place a client-side shortcut cannot hide;
     *   4. the 7-day rule is still enforced and says so.
     * The node with the most packets is used, so that there IS a second
     * page to scroll to; the journey says so when no node has one.
     */
    const nodes = await (await page.request.get(`${BASE}/api/nodes?limit=40`)).json();
    must(Array.isArray(nodes) && nodes.length, 'the instance has no nodes to open');
    let busiest = null;
    for (const node of nodes) {
      const answer = await page.request.get(
        `${BASE}/api/nodes/${encodeURIComponent(node.node_id)}/packets?hours=720&limit=1`);
      const total = Number(answer.headers()['x-total-count'] || 0);
      if (!busiest || total > busiest.total) busiest = { id: node.node_id, total };
    }
    must(busiest.total > 50, `no node has more than one page of packets (most: ${busiest.total}), so paging cannot be seen`);
    const asked = [];
    page.on('request', (request) => {
      if (/\/api\/nodes\/[^/]+\/packets\?/.test(request.url())) asked.push(request.url());
    });
    await page.goto(`${BASE}/#node/${encodeURIComponent(busiest.id)}`, { waitUntil: 'load' });
    const panel = page.locator('[data-page="node"] .timeline');
    must(await waitFor(page, () => document.querySelectorAll('[data-page="node"] .timeline tbody tr').length > 0, 20000),
      'the packet timeline drew no rows');

    // 1. The sentence moved, not deleted, and the window label is gone.
    const hint = await panel.locator('h3').getAttribute('data-hint');
    must(/^A packet is one transmission/.test(hint || ''), `the title carries no explanation: ${hint}`);
    must(/7 days or less/.test(hint), 'the 7-day rule is no longer explained on the title');
    must(await panel.locator('h3 .hint-open').count() === 1, 'the title has no info control to open it');
    const text = await panel.innerText();
    must(!/A packet is one transmission/.test(text), 'the explanation is still printed in the panel');
    must(!/last \d+ h/i.test(text), 'the "LAST 720 H" label is still there');

    // 2. The window control on the title's row, right-aligned.
    const title = await panel.locator('h3').boundingBox();
    const control = await panel.locator('[data-timeline-hours]').boundingBox();
    const box = await panel.boundingBox();
    must(control, 'there is no window control in the panel');
    must(Math.abs((control.y + control.height / 2) - (title.y + title.height / 2)) < 20,
      `the window control is not on the title's row (title y=${Math.round(title.y)}, control y=${Math.round(control.y)})`);
    const gap = (box.x + box.width) - (control.x + control.width);
    must(gap < 40, `the window control is not at the right of the panel: ${Math.round(gap)} px from its edge`);

    // 4, first half: at 30 days the observation sorts are refused and say why.
    const hops = panel.locator('th[data-label="Hops"]');
    must(await hops.locator('.sort-button').count() === 0, 'Hops is sortable over 30 days');
    must(/7 days or less/.test(await hops.getAttribute('data-hint') || ''), 'Hops says nothing about why it cannot sort');

    // 3. Sort, then scroll, and read the requests.
    await panel.locator('th[data-label="Type"] .sort-button').click();
    // The redraw is asynchronous, so wait for the NEW heading: the old
    // rows are still there for a moment and would satisfy "rows > 0".
    must(await waitFor(page, () => {
      const th = document.querySelector('[data-page="node"] .timeline th[data-label="Type"]');
      return th && th.getAttribute('aria-sort') !== 'none'
        && document.querySelectorAll('[data-page="node"] .timeline tbody tr').length > 0;
    }, 15000), 'sorting by type drew nothing');
    const before = await panel.locator('tbody tr').count();
    asked.length = 0;
    await panel.locator('[data-timeline-more]').scrollIntoViewIfNeeded();
    must(await waitFor(page, () => document.querySelectorAll('[data-page="node"] .timeline tbody tr').length > 50, 15000),
      `scrolling to the foot loaded nothing more (${before} rows)`);
    const after = await panel.locator('tbody tr').count();
    const paged = asked.filter((url) => /[?&]before=/.test(url));
    must(paged.length > 0, `no request carried before=: ${asked.join(' ') || 'no request at all'}`);
    must(paged.every((url) => /[?&]sort=type\b/.test(url)), `a page lost the sort: ${paged.join(' ')}`);
    must(!asked.some((url) => /[?&]offset=/.test(url)), `a page was asked for by offset: ${asked.join(' ')}`);
    const hrefs = await panel.locator('tbody tr a.linky').evaluateAll((links) => links.map((a) => a.getAttribute('href')));
    must(new Set(hrefs).size === hrefs.length, 'a packet appears twice after paging');
    const status = await panel.locator('[data-timeline-more] [role="status"]').innerText();

    // 4, second half: choosing 7 days in the panel brings the sort back.
    await panel.locator('[data-timeline-hours]').selectOption('168');
    must(await waitFor(page, () => !!document.querySelector('[data-page="node"] .timeline th[data-label="Hops"] .sort-button'), 15000),
      'Hops is still not sortable at 7 days');
    return `${busiest.id}: ${before} -> ${after} rows by scrolling, ${paged.length} page(s) by cursor with the sort; "${status}"`;
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

    /*
     * The claim is that the sort goes to the SERVER -- a browser
     * reordering the rows it already holds would sort one page of a
     * capped list and leave the rest wrong.
     *
     * This used to read that off the summary sentence, which said
     * "sorted by role". Will had that sentence removed on 2026-09-26
     * (the heading already carries the sort), so the proxy went with it.
     * Watching the request is what the sentence stood for anyway, and it
     * is the stronger claim: a client-side sort issues no request at all,
     * and no wording change can make this pass for the wrong reason.
     */
    const asked = [];
    const watch = (request) => {
      const url = request.url();
      if (url.includes('api/nodes?')) asked.push(url);
    };
    page.on('request', watch);
    await page.click('[data-page="nodes"] th:nth-child(4) .sort-button');
    await page.waitForTimeout(2500);
    page.off('request', watch);
    const after = await roles();
    const nowSaying = await summary();

    const sortedRequest = asked.find((url) => /[?&]sort=role\b/.test(url));
    must(
      sortedRequest !== undefined,
      `no request carried sort=role; the browser sorted what it held: ${asked.join(' ') || 'no /api/nodes request at all'}`,
    );
    // The heading has to say it too, or a screen reader cannot tell which
    // column the order came from.
    const announced = await page.getAttribute('[data-page="nodes"] th:nth-child(4)', 'aria-sort');
    must(
      announced === 'ascending' || announced === 'descending',
      `the heading does not announce the sort: aria-sort=${announced}`,
    );
    const total = (line) => (line.match(/^[\d,]+/) || [''])[0];
    must(total(wasSaying) === total(nowSaying), `the total moved: ${wasSaying} -> ${nowSaying}`);
    must(before.join() !== after.join() || before.length < 2, 'the rows did not reorder');
    const sorted = [...after].sort((a, b) => a.localeCompare(b));
    must(after.join() === sorted.join(), `not in order: ${after.join(', ')}`);
    return `${total(nowSaying)} nodes, reordered by role (aria-sort=${announced})`;
  });

  await journey(context, 'the units setting reaches the pages', async (page) => {
    /*
     * The setting has to change what is ON SCREEN, which is a different
     * claim from the formatter being right.
     *
     * `units.js` had complete unit tests and nineteen call sites, and for
     * a while NONE of them were wired: every test passed and every page
     * still read in metres. The only instrument that catches that is a
     * page compared against itself under the two settings.
     *
     * The node page is used because it is the one page in the seeded data
     * that shows both an altitude and a set of distances. Measurements are
     * matched with `(?!\sago)` on the end: "52m ago" is a relative time
     * and would otherwise read as 52 metres.
     */
    const MEASURED = /(\d[\d,]*(?:\.\d+)?)\s?(ft|mi|km|m)\b(?!\sago)/g;
    const measurements = async () => {
      const text = await page.evaluate(() => document.body.innerText);
      return [...text.matchAll(MEASURED)].map((hit) => hit[0]);
    };
    /*
     * A node that HAS something to convert, found by asking rather than by
     * taking the first row.
     *
     * This used to click the nodes list's first link. That is whichever
     * node was heard most recently, which is a fact about the traffic, not
     * about the node: during one run it was a test node inserted with no
     * altitude on purpose, and in another a node whose position is too
     * coarse to measure from. The journey then reported "no measurement at
     * all" -- a data accident read as a units regression. So it asks the
     * API for a node with a usable position and an altitude, and says so
     * when there is none rather than failing on the wrong question.
     */
    // The site is loaded first so these are same-origin requests. From
    // about:blank a fetch has no base to resolve against, and an absolute
    // one comes from origin `null` and is refused by CORS.
    await open(page, 'dashboard', 1500);
    const nodeId = await page.evaluate(async (base) => {
      const list = await (await fetch(`${base}/api/nodes?limit=200`)).json();
      for (const row of list.filter((n) => n.has_position)) {
        const detail = await (await fetch(`${base}/api/nodes/${encodeURIComponent(row.node_id)}/detail?hours=720`)).json();
        const position = detail && (detail.position || (detail.node && detail.node.position));
        if (position && position.altitude != null) return row.node_id;
      }
      return null;
    }, BASE);
    if (!nodeId) return 'no node on this instance has a position with an altitude to convert';
    const openANode = async () => {
      await open(page, `node/${encodeURIComponent(nodeId)}`, 4500);
      must(/#node/.test(page.url()), 'did not reach a node page');
    };

    await openANode();
    const imperial = await measurements();
    const feetOrMiles = imperial.filter((hit) => /\s?(ft|mi)$/.test(hit));
    must(
      feetOrMiles.length > 0,
      `nothing on the node page read in feet or miles: ${imperial.join(', ') || 'no measurement at all'}`,
    );
    /*
     * And NOTHING is left in metric. This assertion is here because the
     * weaker one above passed a mutation it should have caught: reverting
     * one of the nineteen call sites to hardcoded kilometres still left
     * the altitude converting, so "something reads in feet" held while
     * half the page read in kilometres. Requiring every measurement to
     * agree is what makes one missed call site fail.
     */
    const strayMetric = imperial.filter((hit) => /\s?(m|km)$/.test(hit));
    must(
      strayMetric.length === 0,
      `these read in metric on an imperial page, so a call site is unconverted: ${strayMetric.join(', ')}`,
    );

    /*
     * Flipped through the real control rather than by writing storage, so
     * a control that draws but does nothing fails here too.
     */
    await open(page, 'settings');
    const metricOption = page.locator('[data-setting="units"] .settings-option', { hasText: /metric|kilometre|km/i });
    must(await metricOption.count() > 0, 'the settings page offers no metric option');
    await metricOption.first().click();
    await page.waitForTimeout(600);

    await openANode();
    const metric = await measurements();
    const metresOrKm = metric.filter((hit) => /\s?(m|km)$/.test(hit));
    must(
      metresOrKm.length > 0,
      `nothing read in metres or kilometres after switching: ${metric.join(', ') || 'no measurement at all'}`,
    );
    must(
      metric.filter((hit) => /\s?(ft|mi)$/.test(hit)).length === 0,
      `still showing imperial after switching to metric: ${metric.join(', ')}`,
    );

    /*
     * And the numbers are a CONVERSION, not a relabelling. Comparing the
     * largest measurement each way catches a switch that changes the unit
     * word and leaves the number alone -- which is what a naive fix looks
     * like and reads as working.
     */
    const biggest = (list) => Math.max(...list.map((hit) => Number(hit.replace(/[^\d.]/g, ''))));
    const ratio = biggest(imperial) / biggest(metric);
    must(
      ratio > 1.2 && ratio < 4,
      `the numbers did not convert: ${biggest(imperial)} imperial against ${biggest(metric)} metric`,
    );

    // Put it back, so a later journey on this context is not surprised.
    await open(page, 'settings');
    const imperialOption = page.locator('[data-setting="units"] .settings-option', { hasText: /imperial|mile|mi\b/i });
    if (await imperialOption.count()) await imperialOption.first().click();

    return `${feetOrMiles.slice(0, 3).join(', ')} became ${metresOrKm.slice(0, 3).join(', ')}`;
  });

  await journey(context, 'chat reflows at 320px with a busy reaction', async (page) => {
    /*
     * WCAG 2.1 SC 1.4.10 Reflow: 320 CSS px with no two-dimensional
     * scrolling. A tapback several people sent draws as one chip
     * listing every sender, and with long node names that row does not
     * break on its own. A real one measured 344px and took the whole
     * page sideways.
     *
     * It needs a reaction with several long-named senders to show at
     * all, which is why the seed makes one.
     */
    await page.setViewportSize({ width: 320, height: 800 });
    await open(page, 'chat', 4000);
    const measured = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      reactions: document.querySelectorAll('.reaction').length,
    }));
    must(
      measured.scrollWidth <= measured.clientWidth + 1,
      `the page scrolls sideways at 320px: ${measured.scrollWidth}/${measured.clientWidth}`,
    );
    return measured.reactions
      ? `${measured.scrollWidth}/${measured.clientWidth} with ${measured.reactions} reaction(s)`
      : `${measured.scrollWidth}/${measured.clientWidth}, but no reaction was drawn to test`;
  });

  await journey(context, 'chat reloads on a new range', async (page) => {
    /*
     * The three fixed windows became a range (§6.1), so this drives the
     * quick button that fills it rather than a `<select>` that is gone.
     *
     * The range has to reach the ADDRESS: the fragment is where every page
     * keeps its state, and a range that lived only in the control could not
     * be linked to -- somebody sharing "what was said last night" would
     * send a link that opened on the default week.
     */
    await open(page, 'chat');
    const before = await page.locator('[data-chat-body] .panel').count();
    await page.click('[data-chat-quick="24"]');
    await page.waitForTimeout(3500);
    const after = await page.locator('[data-chat-body] .panel').count();
    must(after > 0, 'no channel sections after changing the range');
    const hash = await page.evaluate(() => window.location.hash);
    must(/[?&]from=/.test(hash), `the range did not reach the address: ${hash}`);
    /*
     * And no `to=`, because a quick range stays open at the newest end.
     * "Last 24 h" that froze at the moment it was pressed would go stale
     * while somebody watched it, and live would stop appending.
     */
    must(!/[?&]to=/.test(hash), `a quick range should stay open-ended: ${hash}`);
    return `${before} sections over the default week, ${after} over 24 h`;
  });

  await journey(context, 'the chat reads bottom-up and pages upward', async (page) => {
    /*
     * The hardest item in the brief, so this asserts the two things that
     * are invisible until they are wrong.
     *
     * ORDER: a chat reads oldest at the top and newest at the bottom, and
     * opens at the newest message.
     *
     * ANCHORING: rows added ABOVE the viewport push everything down by
     * their own height, so a list that simply prepends jumps away from
     * whatever was being read -- every time, and further the more it
     * loads. The row under the reader's eye must not move. Measured
     * during development: 0 px of drift across a 100-row prepend.
     *
     * The seed may hold fewer than one page for every channel, in which
     * case there is nothing to page and the journey says so rather than
     * passing quietly on an assertion that never ran.
     */
    await open(page, 'chat');
    const channel = await page.evaluate(() => {
      const link = document.querySelector('[data-page="chat"] a.title[href^="#chat/"]');
      return link ? decodeURIComponent(link.getAttribute('href').replace('#chat/', '')) : null;
    });
    if (!channel) return 'no channel has stored messages on this instance';
    await open(page, `chat/${encodeURIComponent(channel)}`, 4500);

    const scroller = page.locator('[data-chat-scroll]');
    must(await scroller.count() > 0, 'the chat view has no scroller, so it cannot page');
    const opened = await page.evaluate(() => {
      const sc = document.querySelector('[data-chat-scroll]');
      return {
        atBottom: sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 48,
        rows: sc.querySelectorAll('.messages li').length,
        more: !!document.querySelector('[data-chat-older]'),
      };
    });
    must(opened.rows > 0, 'the chat drew no messages');
    must(opened.atBottom, 'the chat did not open at the newest message');

    // Oldest at the top: compare the first and last rows' own timestamps.
    const ordered = await page.evaluate(() => {
      const stamps = [...document.querySelectorAll('[data-chat-scroll] .messages li .when')]
        .map((el) => el.getAttribute('title') || el.textContent || '');
      return { first: stamps[0], last: stamps[stamps.length - 1], n: stamps.length };
    });
    must(ordered.n > 0, 'no message carried a time to check the order with');

    if (!opened.more) return `${opened.rows} rows, opened at the newest; one page holds this channel`;

    const anchor = await page.evaluate(() => {
      const sc = document.querySelector('[data-chat-scroll]');
      sc.scrollTop = 0;
      const li = sc.querySelector('.messages li');
      return { text: li.textContent.trim().slice(0, 40), viewportY: Math.round(li.getBoundingClientRect().top) };
    });
    await page.waitForTimeout(3000);
    const after = await page.evaluate((text) => {
      const sc = document.querySelector('[data-chat-scroll]');
      const li = [...sc.querySelectorAll('.messages li')]
        .find((n) => n.textContent.trim().slice(0, 40) === text);
      return {
        rows: sc.querySelectorAll('.messages li').length,
        viewportY: li ? Math.round(li.getBoundingClientRect().top) : null,
      };
    }, anchor.text);
    must(after.rows > opened.rows, `scrolling to the top loaded nothing (${opened.rows} rows)`);
    must(after.viewportY !== null, 'the row that was being read is gone after paging');
    const drift = Math.abs(after.viewportY - anchor.viewportY);
    must(drift <= 4, `the list jumped ${drift}px under the reader when older messages loaded`);
    return `${opened.rows} -> ${after.rows} rows, the anchored row drifted ${drift}px`;
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
    // The embed is a deployment setting and it is OFF in production, so
    // this journey used to fail for a correct instance. A skipped test
    // that says why beats a red one nobody can act on -- but it still
    // asserts everything once the feature is on.
    if ((await page.locator('[data-embed-box] > summary').count()) === 0) {
      return 'skipped: EMBED_ENABLED is off on this instance';
    }
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
    /* Siting is its own job -- `sonoran-gaps-siting-once`, which runs
       the engine -- so an instance can have a gaps assessment and no
       siting one. That is a real state the page handles, and it has
       neither the limits nor the radio to print. Assert that it SAYS
       so, rather than demanding numbers that were never computed. */
    if (/no siting answer has been worked out|no assessment to site against|nothing to site against/i.test(text)) {
      return 'skipped: no siting assessment has been written on this instance';
    }
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

  await journey(context, 'a node bubble on the map survives live refreshes', async (page) => {
    /*
     * #264, reported by StarSkream: open a node's bubble on the map, and
     * the next live refresh closed it. `drawMapNodes` cleared the layer
     * and built every marker again, and a Leaflet popup dies with its
     * marker.
     *
     * The map draws on a canvas (`preferCanvas`), so a dot has no DOM
     * element to click. The bubble is opened the way a click opens it,
     * `openPopup()` on the node's own marker, found through
     * `window.SonoranMap`, which is the map's published console handle.
     * The bubble itself IS in the DOM, and that is what is asserted.
     *
     * The node list is served through a route here so that one node can
     * move and another can vanish without writing to a shared database.
     * Everything else about the refresh is the page's own: `render('map')`
     * is exactly what the Live timer calls, and `nodeCache.at = 0` only
     * expires the two-minute node cache so the next render refetches.
     */
    const edits = { move: null, drop: null };
    await page.route(/\/api\/map\/nodes(\?|$)/, async (route) => {
      const response = await route.fetch();
      let rows = await response.json();
      if (edits.drop) rows = rows.filter((row) => row.node_id !== edits.drop);
      if (edits.move) {
        rows = rows.map((row) => (row.node_id === edits.move
          ? { ...row, lat: row.lat + 0.05, lon: row.lon + 0.05 } : row));
      }
      return route.fulfill({ response, json: rows });
    });
    await open(page, 'map', 4000);
    must(await waitFor(page, () => window.SonoranMap.marks instanceof Map
      && window.SonoranMap.marks.size >= 2, 20000), 'the map drew fewer than two nodes');

    const picked = await page.evaluate(() => {
      const [a, b] = [...window.SonoranMap.marks.entries()];
      window.__e2eBubble = a[1].marker;
      a[1].marker.openPopup();
      const at = b[1].marker.getLatLng();
      return { open: a[0], moved: b[0], lat: at.lat, lon: at.lng };
    });
    const BUBBLE = () => {
      const bubble = document.querySelector('[data-page="map"] .leaflet-popup');
      return Boolean(bubble && /Open node detail/.test(bubble.textContent));
    };
    // Leaflet fades a closed popup out and takes it from the DOM 200 ms
    // later, so a bubble read at once after it closed is still there.
    // Every DOM reading below waits past that fade first.
    const FADE_MS = 600;
    must(await page.evaluate(BUBBLE), 'opening a node did not show its bubble');

    // One refresh from the Live timer itself, unprompted: wait for the
    // map's traffic request that only the timer's `render('map')` sends.
    let ticks = 0;
    page.on('request', (request) => {
      if (/\/api\/map\/traffic/.test(request.url())) ticks += 1;
    });
    const deadline = Date.now() + 40000;
    while (ticks < 1 && Date.now() < deadline) await page.waitForTimeout(500);
    must(ticks >= 1, 'the Live timer did not refresh the map within 40 s');
    await page.waitForTimeout(1500);
    must(await page.evaluate(BUBBLE), 'the bubble closed when the Live timer refreshed the map');
    const timed = ticks;

    // Then three more through the same call, with fresh rows each time
    // and one OTHER node moved.
    edits.move = picked.moved;
    for (let refresh = 0; refresh < 3; refresh += 1) {
      await page.evaluate(async () => {
        nodeCache.at = 0;
        await render('map');
      });
    }
    await page.waitForTimeout(FADE_MS);
    const after = await page.evaluate(({ open, moved }) => {
      const marks = window.SonoranMap.marks;
      const bubble = marks.get(open);
      const at = marks.get(moved) && marks.get(moved).marker.getLatLng();
      return {
        same: Boolean(bubble) && bubble.marker === window.__e2eBubble,
        popupOpen: Boolean(bubble) && bubble.marker.isPopupOpen(),
        lat: at && at.lat,
        lon: at && at.lng,
      };
    }, picked);
    must(await page.evaluate(BUBBLE), 'the bubble closed after three live refreshes');
    must(after.same && after.popupOpen, 'the open node was rebuilt rather than updated in place');
    must(
      Math.abs(after.lat - (picked.lat + 0.05)) < 1e-9 && Math.abs(after.lon - (picked.lon + 0.05)) < 1e-9,
      `a node that moved stayed where it was (${picked.lat},${picked.lon} -> ${after.lat},${after.lon})`,
    );

    // The zoom still restyles the dots that are kept (#196).
    const radii = await page.evaluate(async ({ moved }) => {
      const { map, marks } = window.SonoranMap;
      const marker = marks.get(moved).marker;
      const before = marker.options.radius;
      await new Promise((done) => {
        map.once('zoomend', done);
        map.setZoom(map.getZoom() >= 12 ? 6 : 14, { animate: false });
      });
      return { before, after: marker.options.radius };
    }, picked);
    must(radii.before !== radii.after, `zooming did not restyle the dots (radius ${radii.before} both times)`);

    // A node that really went away takes its open bubble with it.
    edits.drop = picked.open;
    await page.evaluate(async () => {
      nodeCache.at = 0;
      await render('map');
    });
    const gone = await page.evaluate(({ open }) => ({
      held: window.SonoranMap.marks.has(open),
      onMap: window.SonoranMap.map.hasLayer(window.__e2eBubble),
    }), picked);
    must(!gone.held && !gone.onMap, 'a node missing from the refresh is still drawn');
    await page.waitForTimeout(FADE_MS);
    must(!(await page.evaluate(BUBBLE)), 'the bubble of a node that went away is still open');
    return `bubble held through ${timed} timer + 3 forced refreshes; moved node moved; `
      + `zoom radius ${radii.before} -> ${radii.after}; gone node closed its bubble`;
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
    /*
     * Waits for the charts, not for a number of seconds (#154).
     *
     * This journey used `open(page, 'stats', 6000)` -- a fixed pause
     * after `load` -- and failed on a cold load while passing on later
     * runs in the same session. Measured against the dev instance, four
     * fresh browser contexts:
     *
     *     run 1   load 10661 ms   first sized canvas 12718 ms  (+2057)
     *     run 2   load  9012 ms   first sized canvas  9042 ms  (+30)
     *     run 3   load  9008 ms   first sized canvas  9011 ms  (+3)
     *     run 4   load  9284 ms   first sized canvas  9291 ms  (+7)
     *
     * The gap the fixed pause has to cover varies by seventy times
     * between a cold run and a warm one, because the leaderboards on
     * this page are behind a 900-second cache and the first request
     * after a cold start does the whole read.
     *
     * Raising the 6000 would trade a fast flake for a slow one and
     * would still be a guess. Waiting for the condition -- canvases
     * present AND sized -- cannot flake on a slow cache, and still
     * fails if the charts never draw, which is the property this
     * journey is for.
     *
     * `width > 0` matters: ECharts inserts its canvas before it has
     * measured the container, so a canvas can exist at zero size for a
     * frame or two and a count alone would pass on a chart nobody can
     * see.
     */
    await page.goto(`${BASE}/#stats`, { waitUntil: 'load' });
    /*
     * Through `waitFor`, and NOT `page.waitForFunction`. The first
     * version of this fix used the latter and went red on CI with
     *
     *   EvalError: Refused to evaluate a string as JavaScript
     *
     * which is the trap the comment on `waitFor` above was written to
     * stop -- and this journey was added after that comment. It passes
     * locally either way, because Playwright evaluates the predicate
     * once before it installs the poller, and on a warm cache the
     * charts are already drawn by then. The condition is only ever
     * POLLED on the run where it is not already true, which is the
     * cold-cache run this journey exists for.
     *
     * The selector is written inside the predicate rather than passed
     * in, because `page.evaluate` serialises the function and a closure
     * over `sized` would arrive undefined.
     */
    const canvases = () => [...document.querySelectorAll('[data-page="stats"] canvas')]
      .filter((canvas) => canvas.width > 0 && canvas.height > 0).length;
    const drawn = await waitFor(page, () => [...document.querySelectorAll('[data-page="stats"] canvas')]
      .filter((canvas) => canvas.width > 0 && canvas.height > 0).length > 0, 30000);
    const count = await page.evaluate(canvases);
    must(drawn && count > 0, 'no chart was drawn');
    return `${count} charts`;
  });

  await journey(context, 'statistics and the firehose follow the units setting (#291)', async (page) => {
    /*
     * Will: "The statistics page isn't showing the distances and metrics
     * in what is set in the settings. Seems stuck in km."
     *
     * The link board is the one that was stuck, and the seeded mesh has
     * no two-way link long enough to rank, so its rows are supplied here
     * with the API's own shape: a value and `"unit": "km"`. The firehose
     * line is supplied the same way, with a temperature and a pressure,
     * because its server-built prose said "21.5 C" in every mode.
     */
    /*
     * Each handler tolerates the page closing under it. The firehose
     * refreshes on its own, so a request can still be in flight when the
     * journey ends, and an unhandled rejection there stops the whole run.
     */
    const patch = (edit) => async (route) => {
      try {
        const response = await route.fetch();
        const body = await response.json();
        edit(body);
        await route.fulfill({ response, json: body });
      } catch {
        await route.abort().catch(() => {});
      }
    };
    await page.route(/\/api\/stats\/leaderboards(\?|$)/, patch((body) => {
      for (const board of body.boards || []) {
        if (board.key !== 'longest_link') continue;
        board.rows = [{
          node_id: '!0a51d002', display_name: 'Link End A',
          other_id: '!0a51b007', other_name: 'Link End B',
          value: 25, unit: 'km', detail: '9.0 dB, 3 and 4 reports each way',
        }];
      }
    }));
    await page.route(/\/api\/packets\?.*summary=true/, patch((body) => {
      if (!body.length) return;
      body[0].summary = '21.5 °C, humidity 40 %, 1013.2 hPa';
      body[0].summary_parts = [
        { value: 21.5, unit: '°C' }, ', ', 'humidity 40 %', ', ', { value: 1013.2, unit: 'hPa' },
      ];
    }));
    const linkValue = async () => {
      await waitFor(page, () => [...document.querySelectorAll('[data-page="stats"] .leaderboard h3')]
        .some((h) => /Longest reliable link/.test(h.textContent)), 20000);
      return page.evaluate(() => {
        const board = [...document.querySelectorAll('[data-page="stats"] .leaderboard')]
          .find((panel) => /Longest reliable link/.test(panel.querySelector('h3').textContent));
        const value = board && board.querySelector('.board .value');
        return value ? value.textContent : null;
      });
    };
    const firstSummary = async () => {
      await waitFor(page, () => !!document.querySelector('[data-page="firehose"] .summary'), 20000);
      return page.evaluate(() => document.querySelector('[data-page="firehose"] .summary').textContent);
    };

    await page.goto(`${BASE}/#stats`, { waitUntil: 'load' });
    const imperialLink = await linkValue();
    must(imperialLink === '15.5 mi', `the link board read ${imperialLink} in imperial, not 15.5 mi`);

    /*
     * The same page, switched in place. The page must redraw on its own.
     *
     * Only once the first draw has finished: `render` ignores a call that
     * arrives while a page is still loading, so a switch made mid-load is
     * not redrawn. That is a separate fault from the one this journey is
     * for, and it is noted in the #291 report.
     */
    await waitFor(page, () => !loading, 60000);
    await page.evaluate(() => {
      window.SonoranSettings.set('units', 'metric');
      window.SonoranSettings.set('temperature', 'celsius');
    });
    await waitFor(page, () => {
      const value = document.querySelector('[data-page="stats"] .leaderboard .board .value');
      return [...document.querySelectorAll('[data-page="stats"] .leaderboard .board .value')]
        .some((node) => /km$/.test(node.textContent)) || !value;
    }, 10000);
    const metricLink = await linkValue();
    must(metricLink === '25.0 km', `the link board read ${metricLink} in metric, not 25.0 km`);

    await page.goto(`${BASE}/#firehose`, { waitUntil: 'load' });
    const metricLine = await firstSummary();
    must(metricLine === '21.5 °C, humidity 40 %, 1013.2 hPa', `the firehose line read "${metricLine}" in metric`);
    await waitFor(page, () => !loading, 60000);
    await page.evaluate(() => {
      window.SonoranSettings.set('units', 'imperial');
      window.SonoranSettings.set('temperature', 'fahrenheit');
    });
    await waitFor(page, () => {
      const line = document.querySelector('[data-page="firehose"] .summary');
      return !!line && /inHg/.test(line.textContent);
    }, 20000);
    const imperialLine = await firstSummary();
    must(imperialLine === '70.7 °F, humidity 40 %, 29.92 inHg', `the firehose line read "${imperialLine}" in imperial`);
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    return `${imperialLink} / ${metricLink}; "${imperialLine}"`;
  });

  await journey(context, 'the statistics range reaches every widget (#294)', async (page) => {
    /*
     * Will: "all the stats, widgets, etc should adjust to them. Default is
     * last 30 days rolling." So this checks the requests every widget
     * makes, not only the chips: a chip that changes while its widget still
     * asks for 24 hours is the failure this journey is for.
     */
    const asked = [];
    page.on('request', (request) => {
      const url = request.url();
      if (/\/api\/stats(\/(top|leaderboards|daily|hardware|activity|broadcast))?\?/.test(url)) asked.push(url);
    });
    const WIDGETS = ['stats?', 'top?', 'leaderboards?', 'daily?', 'hardware?', 'activity?', 'broadcast?'];
    const everyWidgetAsked = (needle) => WIDGETS.filter((path) =>
      !asked.some((url) => url.includes(`/api/${path === 'stats?' ? '' : 'stats/'}${path}`) && url.includes(needle)));
    const settled = () => waitFor(page, () => !loading, 60000);
    const chips = () => page.evaluate(() => [...document.querySelectorAll('[data-page="stats"] [data-range-chip]')]
      .map((chip) => chip.textContent));
    const pressed = () => page.evaluate(() => [...document.querySelectorAll('[data-stats-quick][aria-pressed="true"]')]
      .map((button) => button.dataset.statsQuick));

    await page.goto(`${BASE}/#stats`, { waitUntil: 'load' });
    await settled();
    must(JSON.stringify(await pressed()) === '["30d"]', `the default is not 30 d: ${await pressed()}`);
    let missing = everyWidgetAsked('hours=720');
    must(!missing.length, `these widgets did not ask for 30 days: ${missing.join(', ')}`);
    const defaultChips = await chips();
    must(defaultChips.length >= 5 && defaultChips.every((text) => text.startsWith('last 30 d')),
      `a widget does not name the range: ${defaultChips.join(' | ')}`);

    // A quick range: every widget again, the address, and no history entry.
    const depth = await page.evaluate(() => history.length);
    asked.length = 0;
    await page.click('[data-stats-quick="7d"]');
    await settled();
    must(page.url().endsWith('#stats?range=7d'), `the address is ${page.url()}`);
    must(await page.evaluate(() => history.length) === depth, 'the range added a history entry');
    missing = everyWidgetAsked('hours=168');
    must(!missing.length, `these widgets did not follow 7 d: ${missing.join(', ')}`);
    must((await chips()).every((text) => text.startsWith('last 7 d')), 'a chip still names another range');

    /*
     * The gaps-backed boards cannot follow the range, and say so. The link
     * board does follow it.
     */
    const boards = await page.evaluate(() => [...document.querySelectorAll('[data-page="stats"] .leaderboard h3')]
      .map((h) => [h.dataset.label, (h.querySelector('span.muted') || {}).textContent || '']));
    if (boards.length) {
      const link = boards.find(([title]) => /Longest reliable link/.test(title));
      must(link && link[1] === 'last 7 d', `the link board chip reads ${link && link[1]}`);
      const fixed = boards.filter(([title]) => !/Longest reliable link/.test(title));
      must(fixed.every(([, chip]) => /not the page range/.test(chip)),
        `a gaps board does not say it keeps its own window: ${JSON.stringify(fixed)}`);
    }

    // A reload keeps it.
    await page.reload({ waitUntil: 'load' });
    await settled();
    must(JSON.stringify(await pressed()) === '["7d"]', 'a reload lost the range');

    // 24 h draws its charts, by hour.
    await page.goto(`${BASE}/#stats?range=24h`, { waitUntil: 'load' });
    await settled();
    const drawn = await waitFor(page, () => [...document.querySelectorAll('[data-page="stats"] canvas')]
      .filter((canvas) => canvas.width > 0 && canvas.height > 0).length > 0, 30000);
    must(drawn, 'no chart was drawn at 24 h');
    const title = await page.evaluate(() => document.querySelector('[data-activity-title]').textContent);
    must(/by hour$/.test(title), `at 24 h the activity chart says "${title}"`);

    /*
     * A custom range that starts before what is kept: every packet widget
     * says where it really counts from. 26 days, so the API accepts it.
     */
    const day = (offset) => new Date(Date.now() - offset * 86400000).toISOString().slice(0, 10);
    asked.length = 0;
    await page.goto(`${BASE}/#stats?from=${day(40)}&to=${day(15)}`, { waitUntil: 'load' });
    await settled();
    missing = everyWidgetAsked(`since=${day(40)}`);
    must(!missing.length, `these widgets did not follow the dates: ${missing.join(', ')}`);
    const capped = await chips();
    must(capped.every((text) => /counted from/.test(text)),
      `a widget does not say retention cuts the range short: ${capped.join(' | ')}`);
    const packetTile = await page.evaluate(() => [...document.querySelectorAll('[data-page="stats"] .stat')]
      .map((tile) => tile.innerText).find((text) => /PACKETS|Packets/.test(text)) || '');
    must(/counted from/.test(packetTile), `the packets tile compares a part with a whole: ${packetTile}`);

    // Longer than retention is refused beside the boxes, and nothing moves.
    const before = page.url();
    await page.evaluate(() => {
      const range = document.querySelector('[data-stats-range]');
      range.classList.add('show-custom');
    });
    await page.fill('[data-stats-from]', day(45));
    await page.fill('[data-stats-to]', day(1));
    await page.dispatchEvent('[data-stats-to]', 'change');
    const refusal = await page.evaluate(() => {
      const note = document.querySelector('[data-stats-range-note]');
      return note.hidden ? '' : note.textContent;
    });
    must(/at most 30 days/.test(refusal), `a 45 day range was not refused in words: "${refusal}"`);
    must(page.url() === before, 'a refused range still changed the address');
    return `${WIDGETS.length} widgets follow 30 d, 7 d, 24 h and a custom range; capped ranges say so`;
  });

  await journey(context, 'the planner offers its control', async (page) => {
    await open(page, 'planner', 5000);
    must((await page.locator('[data-planner-run]').count()) > 0, 'no run control');
    return 'run control present';
  });

  await journey(context, 'the planner sidebar stays flush after a run', async (page) => {
    /*
     * #108: the sidebar was reported to open a gap once the planner page
     * grows, which it does by about 1800 px after a run. The sidebar is
     * `position: sticky; top: 0; height: 100svh`, so a gap is the
     * difference between that height and the visible viewport.
     *
     * This asserts the thing the eye would see: the sidebar's box covers
     * the viewport top to bottom, at three scroll positions. It asks for
     * a prediction first, because the height is what the report turns
     * on: 1083 px before a run against a 1050 px viewport, 2838 px
     * after one.
     *
     * An instance with no terrain cannot predict, and there the same
     * measurement is still made on the shorter page. That keeps its
     * teeth: a sidebar shortened to 92svh was 84 px short at scrollY 0,
     * before any scrolling at all.
     *
     * The tolerance is 1 px. A sticky box lands on a fractional offset
     * when `scrollTo` does, and 0.5 px was measured in Chromium and in
     * Firefox at the foot of the page. A real gap is tens of pixels.
     */
    await open(page, 'planner', 5000);
    const shape = () => page.evaluate(() => {
      const box = document.querySelector('.sidebar').getBoundingClientRect();
      const doc = document.documentElement;
      return {
        top: box.top,
        bottom: box.bottom,
        scrollY: Math.round(window.scrollY),
        innerHeight: window.innerHeight,
        docHeight: Math.round(doc.scrollHeight),
        sideways: doc.scrollWidth - doc.clientWidth,
        position: getComputedStyle(document.querySelector('.sidebar')).position,
      };
    });
    const before = await shape();
    // A gap can only show where the sidebar is the sticky column. At
    // 60rem and under it is a static top bar that scrolls away, which is
    // a different layout and not what #108 describes.
    must(before.position === 'sticky', `the sidebar is ${before.position} at this width`);

    // Phoenix, in the middle of the served region, and 10 km rather than
    // the default 30: the run is the slow part of this journey and a
    // short one still fills the summary and the table.
    await advanced(page);
    await page.fill('[data-planner="lat"]', '33.45');
    await page.fill('[data-planner="lon"]', '-112.07');
    await page.fill('[data-planner="radius"]', '10');
    const started = Date.now();
    const run = await predict(page);
    const took = Math.round((Date.now() - started) / 1000);

    const bad = [];
    let after = null;
    for (const part of [0, 0.5, 1]) {
      await page.evaluate((fraction) => {
        window.scrollTo(0, Math.round(document.documentElement.scrollHeight * fraction));
      }, part);
      await page.waitForTimeout(600);
      const now = await shape();
      after = now;
      if (now.top > 1) bad.push(`top ${now.top.toFixed(1)} px at scrollY ${now.scrollY}`);
      if (now.bottom < now.innerHeight - 1) {
        bad.push(`${(now.innerHeight - now.bottom).toFixed(1)} px short at scrollY ${now.scrollY}`);
      }
      if (now.sideways > 1) bad.push(`${now.sideways} px of sideways scroll at scrollY ${now.scrollY}`);
    }
    if (run.ran) {
      must(after.docHeight > before.docHeight + 200,
        `the page did not grow after the run (${before.docHeight} -> ${after.docHeight} px)`);
    }
    must(bad.length === 0, `the sidebar left a gap: ${bad.join(', ')}`);
    return run.ran
      ? `${before.docHeight} -> ${after.docHeight} px, flush at three positions, run took ${took} s`
      : `no prediction on this instance (${run.why}); flush at three positions on ${after.docHeight} px`;
  });

  await journey(context, 'a planner link carries the plan to a clean browser', async (page) => {
    /*
     * #107. The prediction is raster data made in the browser, so a link
     * carries the settings and the page that opens it runs them again.
     * The thing worth asserting is the round trip: the form that comes
     * back, and a coverage image on the map rather than an empty one.
     *
     * The second half runs in a context of its own so that nothing is
     * carried over in memory. A link that only works in the tab that
     * made it is not a link.
     *
     * An instance with no terrain cannot predict, and there the map and
     * the node count cannot be compared. The settings still travel, and
     * the round trip of the form is still asserted, so this walks that
     * far and says it went no further.
     */
    await open(page, 'planner', 5000);
    await advanced(page);
    await page.fill('[data-planner="site_name"]', 'Shaw Butte');
    await page.fill('[data-planner="lat"]', '33.5905');
    await page.fill('[data-planner="lon"]', '-112.0865');
    await page.fill('[data-planner="tx_height"]', '6');
    await page.selectOption('[data-planner="preset"]', 'LONG_FAST');
    await page.fill('[data-planner="radius"]', '10');
    await page.locator('[data-planner="radius"]').blur();
    await page.waitForTimeout(500);

    const query = new URLSearchParams(page.url().split('?')[1] || '');
    must(query.get('tx_height') === '6', `the address did not follow the form: ${page.url()}`);
    // Only what moved. A link that writes all 21 fields is four times
    // as long and nobody reads it. Measured: 478 characters against 142.
    must(!query.has('tx_power'), `an untouched field was written: ${[...query.keys()].join(',')}`);

    const run = await predict(page, () => page.click('[data-planner-run]'));
    const link = page.url();
    let reached = null;
    if (run.ran) {
      // The date is stamped by a finished run, so it is only owed when
      // there was one.
      must(/ran=\d{4}-\d{2}-\d{2}/.test(link), `the link carries no date for the run: ${link}`);
      reached = (await page.locator('[data-planner-summary]').innerText()).match(/(\d+) of (\d+)/);
      must(reached, 'the summary printed no node count');
    }

    const clean = await browser.newContext({ viewport: { width: 1500, height: 1050 } });
    const opened = await clean.newPage();
    await opened.goto(link, { waitUntil: 'load' });
    const again = await predict(opened, null);
    const back = await opened.evaluate(() => {
      const read = (name) => document.querySelector(`[data-planner="${name}"]`).value;
      return {
        site_name: read('site_name'),
        lat: read('lat'),
        tx_height: read('tx_height'),
        preset: read('preset'),
        // Left out of the link, because it follows the preset. It has to
        // come back as Long fast's own figure and not as the form
        // default, or the link predicts a reach that preset has not got.
        sensitivity: read('sensitivity'),
        tx_power: read('tx_power'),
        overlays: document.querySelectorAll('.leaflet-image-layer').length,
        said: document.querySelector('[data-planner-shared]').textContent.trim(),
      };
    });
    const sameCount = again.ran
      ? (await opened.locator('[data-planner-summary]').innerText()).match(/(\d+) of (\d+)/)
      : null;
    await opened.close();
    await clean.close();

    // The settings travel whether or not there is terrain to predict over.
    must(back.site_name === 'Shaw Butte' && back.lat === '33.5905', `the site came back as ${back.lat}`);
    must(back.tx_height === '6' && back.preset === 'LONG_FAST', 'the settings did not come back');
    must(back.sensitivity === '-139', `the sensitivity came back as ${back.sensitivity}`);
    must(back.tx_power === '30', `an unshared field did not take its default: ${back.tx_power}`);
    if (!run.ran) return `${link.length} characters, settings restored; no prediction here (${run.why})`;

    must(back.overlays > 0, 'the link drew no coverage on the map');
    must(/shared on \d{4}-\d{2}-\d{2}/.test(back.said), `the page did not date the plan: ${back.said}`);
    must(sameCount && sameCount[0] === reached[0],
      `the same link reached ${sameCount && sameCount[0]} where the original reached ${reached[0]}`);
    return `${link.length} characters, reached ${reached[0]} in both`;
  });

  await journey(context, 'a hand-typed planner link cannot break the page', async (page) => {
    /*
     * A link is a string somebody can edit, and the numbers in it go
     * into a WebAssembly engine. Every one is clamped, an unknown choice
     * falls back to the default, and the page says what it did rather
     * than quietly predicting something else.
     *
     * This waits for the line that reports what the link needed, not for
     * a prediction. The holding happens as the form is filled, before
     * any run, so this works on an instance with no terrain as well.
     */
    await page.goto(
      `${BASE}/#planner?v=9&lat=33.45&lon=-112.07&radius=99999&tx_height=abc`
        + '&preset=NOT_A_PRESET&nonsense=1&situation_fraction=0',
      { waitUntil: 'load' },
    );
    const reported = await waitFor(page, () => {
      const line = document.querySelector('[data-planner-shared]');
      return Boolean(line && !line.hidden && line.textContent.trim().length > 0);
    }, 30000);
    must(reported, 'the page said nothing at all about the link it was opened with');
    const held = await page.evaluate(() => ({
      radius: document.querySelector('[data-planner="radius"]').value,
      tx_height: document.querySelector('[data-planner="tx_height"]').value,
      preset: document.querySelector('[data-planner="preset"]').value,
      situation: document.querySelector('[data-planner="situation_fraction"]').value,
      said: document.querySelector('[data-planner-shared]').textContent.trim(),
    }));
    must(held.radius === '150', `the range is ${held.radius} km, past the engine's 150`);
    must(held.tx_height === '3', `"abc" became ${held.tx_height} rather than the default`);
    must(held.preset === 'MEDIUM_FAST', `an unknown preset became ${held.preset}`);
    must(held.situation === '1', `the situation fraction is ${held.situation}`);
    must(/version 9/.test(held.said), `nothing said the version was unknown: ${held.said}`);
    must(/nonsense/.test(held.said), `the unknown key was not reported: ${held.said}`);
    return 'range, height, preset, fraction and version all reported';
  });

  await journey(context, 'the copy link control says what the clipboard did', async (page) => {
    /*
     * `navigator.clipboard` exists only in a secure context. Measured
     * `undefined` on a plain-http instance, which is how this dashboard
     * is usually reached, so the refused path is the common one and it
     * has to be visible rather than silent.
     */
    await open(page, 'planner', 5000);
    await page.fill('[data-planner="lat"]', '33.45');
    await page.fill('[data-planner="lon"]', '-112.07');
    await page.locator('[data-planner="lon"]').blur();
    await page.click('[data-planner-share]');
    await page.waitForTimeout(400);
    const box = await page.evaluate(() => ({
      secure: window.isSecureContext,
      hidden: document.querySelector('[data-planner-share-box]').hidden,
      value: document.querySelector('[data-planner-share-url]').value,
      focused: document.activeElement.dataset.plannerShareUrl !== undefined,
      status: document.querySelector('[data-planner-share-status]').textContent.trim(),
    }));
    // Whatever the clipboard did, the link is on the page and selected,
    // and something says which of the two happened.
    must(!box.hidden, 'the link box stayed hidden');
    must(box.value.includes('#planner?v='), `the box holds ${box.value}`);
    must(box.focused, 'the link box does not have focus, so Ctrl-C would copy nothing');
    must(box.status.length > 10, `the status said ${JSON.stringify(box.status)}`);
    return `secure context ${box.secure}: ${JSON.stringify(box.status.slice(0, 48))}`;
  });

  /*
   * A phone, walked as a phone.
   *
   * Everything above runs at 1500 px, where the nav is a list of pages
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
    // Counted against the document, not against a number written here.
    // This said 13 and the RF page made it 14, so the suite failed for
    // a page being added -- which is not a regression, and a test that
    // cries about one stops being read.
    const links = await page.locator('#site-nav a').count();
    const pages = await page.locator('main .page').count();
    must(links > 0, 'the menu holds no links');
    must(links >= 10, `the menu holds only ${links} links, so something did not render`);
    must(links <= pages, `the menu holds ${links} links but there are only ${pages} pages`);
    await page.locator('#site-nav a[data-nav="firehose"]').click();
    await page.waitForTimeout(3000);
    // Choosing a page closes the menu, and the button then says where
    // you are without having to be opened again.
    must((await toggle.getAttribute('aria-expanded')) === 'false',
      'the menu stayed open after a page was chosen');
    must((await page.locator('[data-nav-here]').textContent()).trim() === 'Firehose',
      'the button does not name the page');
    must(/#firehose/.test(page.url()), `did not navigate (${page.url()})`);

    /*
     * Settings, which is the one page NOT in that list.
     *
     * It is a link in the menu footer, under the preset switch, and the
     * nav entry that used to duplicate it is gone (Will, 2026-09-26:
     * "there is a duplicate settings button on the bottom"). So the count
     * above walks past it entirely -- `#site-nav a` does not match it --
     * and a phone losing its only route to the page would not move a
     * single number in this journey.
     *
     * The close is asserted separately for the same reason. The handler
     * that closes the menu used to be bound to the nav, so this link
     * routed underneath a menu that stayed open on top of it.
     */
    await toggle.click();
    await page.waitForTimeout(250);
    const settings = page.locator('#site-menu a[href="#settings"]');
    must((await settings.count()) === 1,
      `${await settings.count()} routes to settings in the menu; there must be exactly one`);
    must(await settings.isVisible(), 'the settings link is not on the screen with the menu open');
    await settings.click();
    await page.waitForTimeout(1500);
    must(/#settings/.test(page.url()), `settings did not open (${page.url()})`);
    must((await toggle.getAttribute('aria-expanded')) === 'false',
      'the menu stayed open after settings was chosen, so the page opened underneath it');
    must((await page.locator('[data-nav-here]').textContent()).trim() === 'Settings',
      'the button does not name the settings page, so nothing says where you are');
    must((await settings.getAttribute('aria-current')) === 'page',
      'the settings link is not marked as the current page');
    must(await page.locator('[data-page="settings"].active [data-setting]').count() > 0,
      'the settings page opened with no controls on it');

    return `${links} links + settings in the footer, menu closes on choosing`;
  });

  await journey(phone, 'a phone can read what a column means', async (page) => {
    /*
     * The same journey as before #99, walked over the control that
     * replaced the "What these columns mean" block: the sentence is now
     * on the heading it explains. The assertions that matter are
     * unchanged -- a finger can reach the Uploads sentence and the
     * exact wire value, and neither is on the screen until it is asked
     * for. A `title` tooltip could pass neither check on a touch
     * screen.
     */
    await open(page, 'firehose', 4500);
    const table = page.locator('[data-page="firehose"] .table-wrap').first();
    const buttons = table.locator('.hint-open');
    must((await buttons.count()) > 0, 'no column carries a hint control');
    const uploads = table.locator('th[data-label="Uploads"] .hint-open');
    must((await uploads.count()) > 0, 'the Uploads column has no hint control');
    must((await uploads.getAttribute('aria-expanded')) === 'false', 'the hint starts open');
    const panel = page.locator(`#${await uploads.getAttribute('aria-controls')}`);
    must(!(await panel.isVisible()), 'the sentence is on the screen before it is asked for');

    await uploads.tap();
    await page.waitForTimeout(250);
    must((await uploads.getAttribute('aria-expanded')) === 'true', 'tapping did not open it');
    must(await panel.isVisible(), 'the panel did not appear');
    must(/uploaded this packet to MQTT/.test(await panel.innerText()),
      'the Uploads sentence is not in the panel');
    // It must fit the screen, which is what `.table-wrap` would have
    // taken away from a panel drawn inside the table.
    const box = await panel.boundingBox();
    const width = page.viewportSize().width;
    must(box.x >= -1 && box.x + box.width <= width + 1,
      `the panel runs off the screen: ${Math.round(box.x)}..${Math.round(box.x + box.width)} of ${width}`);

    // And the exact wire value, which used to live only in `title`.
    const type = table.locator('th[data-label="Type"] .hint-open');
    await type.tap();
    await page.waitForTimeout(250);
    const exact = page.locator(`#${await type.getAttribute('aria-controls')}`);
    must(/TELEMETRY_APP|POSITION_APP|NODEINFO_APP/.test(await exact.innerText()),
      'no exact protocol value is reachable');
    // Opening one closes the other, and Escape closes what is open.
    must((await uploads.getAttribute('aria-expanded')) === 'false',
      'two hint panels are open at once');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    must((await type.getAttribute('aria-expanded')) === 'false', 'Escape did not close it');
    return `${await buttons.count()} columns explained, hints and exact values both reachable`;
  });

  await journey(phone, 'a phone can read what a node field means (#256)', async (page) => {
    /*
     * Every Identity and Device field carries the same hint button as a
     * column heading. The unit cases prove each field HAS a sentence;
     * only a browser proves `revealHints` turned it into something a
     * finger and a keyboard can open. So: every `dt` has a button, a tap
     * opens one and it fits the screen, Escape shuts it, and Enter opens
     * it again from the keyboard.
     */
    const nodes = await page.request.get(`${BASE}/api/nodes?limit=1`).then((r) => r.json());
    must(nodes.length, 'no node to open');
    await page.goto(`${BASE}/#node/${encodeURIComponent(nodes[0].node_id)}`, { waitUntil: 'load' });
    await page.waitForTimeout(3500);
    const fields = page.locator('[data-page="node"] .summary-row dl.fields dt');
    const count = await fields.count();
    must(count >= 10, `only ${count} Identity and Device fields drawn`);
    const bare = await page.evaluate(() => [...document.querySelectorAll(
      '[data-page="node"] .summary-row dl.fields dt')]
      .filter((dt) => !dt.querySelector('.hint-open')).map((dt) => dt.dataset.label || dt.textContent));
    must(bare.length === 0, `fields with no hint button: ${bare.join(', ')}`);

    const gateway = page.locator('[data-page="node"] dt[data-label="MQTT gateway"] .hint-open');
    const panel = page.locator(`#${await gateway.getAttribute('aria-controls')}`);
    must(!(await panel.isVisible()), 'the sentence is on the screen before it is asked for');
    await gateway.tap();
    await page.waitForTimeout(250);
    must(await panel.isVisible(), 'tapping the MQTT gateway hint did not open it');
    must(/internet/.test(await panel.innerText()), 'the MQTT gateway sentence is not in the panel');
    const box = await panel.boundingBox();
    const width = page.viewportSize().width;
    must(box.x >= -1 && box.x + box.width <= width + 1,
      `the panel runs off the screen: ${Math.round(box.x)}..${Math.round(box.x + box.width)} of ${width}`);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    must(!(await panel.isVisible()), 'Escape did not close it');
    await gateway.focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(250);
    must((await gateway.getAttribute('aria-expanded')) === 'true', 'Enter did not open it');
    await page.keyboard.press('Escape');
    return `${count} fields, every one explained; tap, Escape and Enter all work`;
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
   * #253: on an iPad, overscrolling past the top showed a band about
   * 25 px tall. Chromium cannot rubber-band, so this does not reproduce
   * the band. It measures what the band is made of: the background of
   * `html` (which was transparent), of `body`, the `--bg` token, and the
   * `theme-color` Safari tints its bars with (which was dark in both
   * themes). All four must be one colour, in each theme and after a
   * switch made through the page's own `applyTheme`.
   */
  for (const scheme of ['dark', 'light']) {
    const themed = await browser.newContext({
      viewport: { width: 834, height: 1194 }, isMobile: true, hasTouch: true, colorScheme: scheme,
    });
    await journey(themed, `the colour behind the page is the page colour (${scheme})`, async (page) => {
      await open(page, 'dashboard', 1500);
      const read = () => page.evaluate(() => {
        const root = document.documentElement;
        const probe = document.createElement('div');
        probe.style.color = getComputedStyle(root).getPropertyValue('--bg').trim();
        document.body.append(probe);
        const token = getComputedStyle(probe).color;
        probe.remove();
        const meta = document.querySelector('meta[name="theme-color"]');
        probe.style.color = meta ? meta.getAttribute('content') : '';
        document.body.append(probe);
        const tint = getComputedStyle(probe).color;
        probe.remove();
        return {
          theme: root.getAttribute('data-theme'),
          token,
          html: getComputedStyle(root).backgroundColor,
          body: getComputedStyle(document.body).backgroundColor,
          tint,
        };
      });
      const check = (got, when) => {
        must(got.html === got.token, `${when}: html is ${got.html}, the page colour is ${got.token}`);
        must(got.body === got.token, `${when}: body is ${got.body}, the page colour is ${got.token}`);
        must(got.tint === got.token, `${when}: theme-color is ${got.tint}, the page colour is ${got.token}`);
      };
      const first = await read();
      must(first.theme === scheme, `the page opened in ${first.theme}, the system asked for ${scheme}`);
      check(first, `${scheme} on load`);
      const other = scheme === 'dark' ? 'light' : 'dark';
      await page.evaluate((mode) => applyTheme(mode), other);
      const switched = await read();
      must(switched.theme === other, `applyTheme('${other}') left the page ${switched.theme}`);
      must(switched.token !== first.token, 'the two themes have the same page colour, so this proves nothing');
      check(switched, `after switching to ${other}`);
      return `${first.token} on load, ${switched.token} after switching; html, body and theme-color agree`;
    });
    await themed.close();
  }

  /*
   * 320 CSS px, which is WCAG 2.2 SC 1.4.10 Reflow: content must not
   * need scrolling in two dimensions there. It is also 1280 px at the
   * 400 percent zoom the criterion is derived from.
   * https://www.w3.org/TR/WCAG22/#reflow
   */
  const narrow = await browser.newContext({
    viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true,
  });
  await journey(narrow, 'a folded control cannot hide an overflow at 320px', async (page) => {
    /*
     * The sweep below walks every page AS IT FIRST DRAWS, so anything
     * behind a disclosure is measured shut. That is how a real overflow
     * shipped: the chat's date boxes fold behind a "Dates…" button on a
     * phone, and opened they took the document sideways by 139 px. A
     * `datetime-local` has an intrinsic minimum width wider than the flex
     * basis asked for, and `min-width: 0` cannot fix that -- the control's
     * own minimum is what exceeds the row.
     *
     * So this opens what folds, and measures again.
     */
    await open(page, 'chat', 3500);
    const link = await page.evaluate(() => {
      const a = document.querySelector('[data-page="chat"] a.title[href^="#chat/"]');
      return a ? a.getAttribute('href').slice(1) : null;
    });
    if (!link) return 'no channel has stored messages on this instance';
    await open(page, link, 4500);
    const toggle = page.locator('[data-chat-custom-toggle]');
    if (!(await toggle.count())) return 'this build has no folded control on the chat';
    if (!(await toggle.isVisible())) return 'the fold is not used at this width';
    await toggle.click();
    await page.waitForTimeout(400);
    const measured = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      expanded: document.querySelector('[data-chat-custom-toggle]').getAttribute('aria-expanded'),
      shown: !!document.querySelector('[data-chat-custom]').offsetParent,
    }));
    must(measured.expanded === 'true', 'the control did not report itself open');
    must(measured.shown, 'it says it is open but the fields are not shown');
    must(
      measured.scrollWidth <= measured.clientWidth + 1,
      `opening the date range scrolls the page sideways: ${measured.scrollWidth}/${measured.clientWidth}`,
    );
    return `opened at 320px, ${measured.scrollWidth}/${measured.clientWidth}`;
  });

  await journey(narrow, 'the mesh-graph link is a link drawn as a button (#258)', async (page) => {
    /*
     * The node page is not in the sweep below, because it needs a node
     * id, so its one new control is walked here. Three claims, each of
     * which a plausible edit breaks: it is still an `<a>` that opens a
     * new tab (turning it into a `<button>` loses middle-click), its
     * icon is sized (an unsized `<svg>` is 300x150), and the page does
     * not scroll sideways at 320 px with it on screen.
     */
    const nodes = await page.request.get(`${BASE}/api/nodes?limit=1`).then((r) => r.json());
    must(nodes.length, 'no node to open');
    await page.goto(`${BASE}/#node/${encodeURIComponent(nodes[0].node_id)}`, { waitUntil: 'load' });
    await page.waitForTimeout(3500);
    const link = await page.evaluate(() => {
      const a = document.querySelector('[data-node-graph-link]');
      const icon = a && a.querySelector('svg.icon');
      const box = icon ? icon.getBoundingClientRect() : null;
      return a && {
        tag: a.tagName, target: a.target, rel: a.rel, href: a.getAttribute('href'),
        visible: !a.hidden && a.getBoundingClientRect().width > 0,
        icon: box ? [Math.round(box.width), Math.round(box.height)] : null,
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      };
    });
    must(link, 'the node page has no mesh-graph link');
    must(link.tag === 'A', `it is a <${link.tag.toLowerCase()}>, and only a link opens in a new tab on middle-click`);
    must(link.target === '_blank' && /noopener/.test(link.rel), `target=${link.target} rel=${link.rel}`);
    must(link.visible && link.href, 'the link is hidden or has nowhere to go');
    must(link.icon && link.icon[0] <= 24 && link.icon[1] <= 24, `the icon is unsized: ${link.icon}`);
    must(link.scroll <= link.client + 1, `the node page scrolls sideways: ${link.scroll}/${link.client}`);
    return `an <a> with a ${link.icon.join('x')} icon, ${link.scroll}/${link.client} px`;
  });

  await journey(narrow, 'every page reflows at 320 CSS px', async (page) => {
    const bad = [];
    // Every page, and the list is hardcoded on purpose so that adding a
    // page without adding it here is a visible omission rather than a
    // silent gap in the sweep.
    for (const name of ['dashboard', 'map', 'planner', 'coverage', 'gaps', 'config',
      'graph', 'nodes', 'chat', 'meshnet', 'firehose', 'traceroutes', 'stats',
      'settings']) {
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
    return 'all 14 pages, no sideways document scroll';
  });
  await narrow.close();

  await browser.close();

  console.log(results.join('\n'));
  console.log('\nconsole and page errors: ' + (errors.length ? '\n  ' + errors.slice(0, 8).join('\n  ') : 'none'));
  if (elsewhere.length) {
    console.log('\nerrors from other hosts (not counted): \n  ' + elsewhere.slice(0, 8).join('\n  '));
  }
  const failed = results.filter((line) => line.startsWith('FAIL')).length;
  console.log(`\n${results.length - failed}/${results.length} journeys passed`);
  process.exit(failed || errors.length ? 1 : 0);
}

main();
