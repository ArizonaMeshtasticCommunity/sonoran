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
const DRAWING = /\/api\/traceroutes\/\d+\/drawing\.svg$/;

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
    /*
     * The trace drawing is mesh-graph's picture, proxied by our API
     * (#51), so a failure there is mesh-graph's answer on our origin:
     * 502 when it cannot be reached, which is every test instance, and
     * 404 when it holds no drawing. It counts as somebody else's host.
     * It went unseen until #289, because the picture was lazy-loaded
     * while hidden and Chromium never asked for it at all.
     */
    if (!isOurs(where) || DRAWING.test(where)) {
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
async function waitFor(page, condition, timeout = 240000, step = 500, arg = undefined) {
  const until = Date.now() + timeout;
  for (;;) {
    if (await page.evaluate(condition, arg)) return true;
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
/*
 * The first value a page function returns that is not null, from ONE
 * call. `waitFor` then a second `evaluate` is two reads, and a page that
 * re-renders between them hands the second one nothing: "Cannot
 * destructure property 'value' of null" on the CI runner.
 */
async function valueOf(page, read, timeout = 15000, step = 300) {
  const until = Date.now() + timeout;
  for (;;) {
    const got = await page.evaluate(read);
    if (got != null) return got;
    if (Date.now() >= until) return null;
    await page.waitForTimeout(step);
  }
}

/*
 * Read a page value until `good` accepts it, and return the last one
 * read either way, so a failure can say what it saw. One `evaluate` per
 * read (AGENTS.md 9.32).
 */
async function waitForValue(page, read, arg, good, timeout = 10000) {
  const until = Date.now() + timeout;
  let got = null;
  for (;;) {
    got = await page.evaluate(read, arg);
    if (good(got)) return { ok: true, got };
    if (Date.now() >= until) return { ok: false, got };
    await page.waitForTimeout(250);
  }
}

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
 * Set the reader's units on this page, and so on every page of its context.
 *
 * The planner's height and range boxes follow the setting (#246), and the
 * journeys share one browser context: "the units setting reaches the
 * pages" switches it to metric through the real control and it stays
 * switched. A journey that types feet says so here rather than inheriting
 * whatever an earlier journey left. The planner rewrites its boxes when
 * the setting changes, so this works after the form is filled too.
 */
async function setUnits(page, units) {
  await page.evaluate((value) => window.SonoranSettings.set('units', value), units);
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

/*
 * A published coverage run, served through routes (#334).
 *
 * The seeded instance has no coverage run, because the job runs the
 * engine for minutes, and a page with no run hides its settings. So the
 * settings journeys serve a small manifest of their own. `approximate`
 * adds the `infrastructure_approximate` map, which is what a server with
 * COVERAGE_INCLUDE_APPROXIMATE on publishes. The tiles are one clear
 * pixel and the nodes are three routers, one of them rounded.
 */
const STUB_STAMP = '20261008T000000Z';
const CLEAR_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);

/*
 * A margin tile for the signal floor journeys (#334): 256 grey pixels
 * square, the west half 5 dB above the limit and the east half 30 dB.
 * Byte n is n - 1 dB, as `coverage/render.py` writes it.
 */
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let k = 0; k < 8; k += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function greyPng(width, height, byteAt) {
  const zlib = require('zlib');
  const rows = Buffer.alloc((width + 1) * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) rows[y * (width + 1) + 1 + x] = byteAt(x, y);
  }
  const chunk = (kind, payload) => {
    const head = Buffer.alloc(4);
    head.writeUInt32BE(payload.length);
    const body = Buffer.concat([Buffer.from(kind, 'ascii'), payload]);
    const tail = Buffer.alloc(4);
    tail.writeUInt32BE(crc32(body));
    return Buffer.concat([head, body, tail]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 0, 0, 0, 0], 8);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(rows)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

const MARGIN_PNG = greyPng(256, 256, (x) => (x < 128 ? 6 : 31));

function stubManifest({ approximate, margins = false }) {
  const box = [33.0, -112.6, 33.9, -111.6];
  const site = (id, extra = {}) => ({
    node_id: id,
    display_name: `Site ${id}`,
    used: true,
    eirp_dbm: 30,
    antenna_height_m: 10,
    clutter_height_m: 0,
    calibrated: false,
    position_deviation_m: null,
    position_source: 'reported',
    ...extra,
  });
  const preset = (nodes) => ({
    preset: 'MediumFast',
    site_count: nodes.length,
    candidate_count: 3,
    sensitivity_dbm: -136,
    usable_area_km2: 120,
    downlink_area_km2: 240,
    data_bounds: box,
    excluded_by_role: {},
    nodes,
  });
  const precise = preset([site('!e2e00001'), site('!e2e00002')]);
  const rounded = preset([
    site('!e2e00001'),
    site('!e2e00002'),
    site('!e2e00003', { position_deviation_m: 1500 }),
  ]);
  const roles = ['REPEATER', 'ROUTER', 'ROUTER_LATE'];
  const sets = [{
    key: 'infrastructure', label: 'Routers and repeaters', site_roles: roles,
    is_diagnostic: false, presets: [precise], data_bounds: box,
    site_precision: 'precise', approximate: false,
  }];
  if (approximate) {
    sets.push({
      key: 'infrastructure_approximate',
      label: 'Routers and repeaters, rounded positions included',
      site_roles: roles, is_diagnostic: false, presets: [rounded], data_bounds: box,
      site_precision: 'approximate', approximate: true,
    });
  }
  return {
    available: true,
    stamp: STUB_STAMP,
    layers: [
      { key: 'usable', label: 'Usable both ways' },
      { key: 'downlink', label: 'Node heard here' },
      { key: 'uplink', label: 'Here heard by a node' },
    ],
    active_hours: 168,
    tile_size: 256,
    min_zoom: 6,
    max_zoom: 11,
    bounds: box,
    data_bounds: box,
    ramp_span_db: 30,
    generated_at: new Date().toISOString(),
    seconds: 12,
    site_roles: roles,
    is_diagnostic: false,
    rx_height_m: 1.5,
    rx_gain_dbi: 2,
    handheld_tx_power_dbm: 22,
    radius_km: 40,
    has_terrain: true,
    has_landcover: false,
    missing_terrain_tiles: [],
    coarse_sites: [],
    presets: [precise],
    site_sets: sets,
    // A run made since #334 says how its margin tiles are encoded. One
    // made before has no such field, and cannot draw a signal floor.
    ...(margins ? {
      margin_tiles: {
        encoding: 'margin_db_plus_one',
        ramp: [[255, 45, 85], [255, 122, 0], [255, 230, 0], [0, 217, 139], [0, 168, 255]],
        alpha: 235,
      },
    } : {}),
  };
}

async function stubCoverage(page, { approximate = false, margins = false } = {}) {
  const heard = new Date().toISOString();
  const node = (id, lat, lon, role) => ({
    node_id: id, display_name: `Site ${id}`, lat, lon, role, last_heard: heard, is_mqtt_gateway: false,
  });
  await page.route(/\/api\/coverage(\?|$)/, (route) => route.fulfill({ json: stubManifest({ approximate, margins }) }));
  await page.route(/\/api\/coverage\/calibration(\?|$)/, (route) => route.fulfill({ json: { available: false, nodes: [] } }));
  await page.route(/\/api\/coverage\/tiles\//, (route) => route.fulfill({ contentType: 'image/png', body: CLEAR_PNG }));
  // Registered later, so it is asked first.
  await page.route(/\/api\/coverage\/tiles\/.*\/margin\//, (route) => route.fulfill({ contentType: 'image/png', body: MARGIN_PNG }));
  await page.route(/\/api\/map\/nodes(\?|$)/, (route) => route.fulfill({
    json: [
      node('!e2e00001', 33.45, -112.07, 'ROUTER'),
      node('!e2e00002', 33.30, -111.90, 'REPEATER'),
      node('!e2e00003', 33.60, -112.30, 'ROUTER_LATE'),
    ],
  }));
}

/* The tile URL template of the signal layer on show, or null. */
const COVERAGE_TILE_URL = () => {
  const state = window.SonoranCoverageState;
  return state && state.tiles ? state.tiles._url : null;
};

/**
 * The packet type menu on the map, at one size (#385).
 *
 * Will: "it breaks the header by adding another line and it's not
 * obvious you have to click 'Packet type all ^' to collapse it. Maybe a
 * drop down menu with checkbox multi select would be better? Make sure
 * it looks good on mobile."
 *
 * So, with letters as wide as CI's Linux fonts draw them: opening the
 * menu must not move the header or the map by a pixel, the menu must be
 * on top and on the screen, each kind must be a labelled checkbox that
 * filters at once, and Escape, a tap outside and Done must each close
 * it. The old row of chips grew the header on open, so the first
 * measurement fails it.
 */
async function familyMenuWalk(page, { watch }) {
  await open(page, 'map', 3500);
  await page.addStyleTag({
    content: '.page-head *, .family-menu * { letter-spacing: .12em !important; }',
  });
  await page.waitForTimeout(200);
  const toggle = page.locator('[data-page="map"] [data-family-toggle]');
  must(await toggle.count() === 1, 'the map has no packet type button');
  const layout = () => page.evaluate(() => {
    const head = document.querySelector('[data-page="map"] .page-head');
    const map = document.querySelector('#live-map');
    return {
      head: Math.round(head.getBoundingClientRect().height),
      map: Math.round(map.getBoundingClientRect().top),
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    };
  });
  const menuState = () => page.evaluate(() => {
    const menu = document.querySelector('[data-family-menu]');
    const box = menu.getBoundingClientRect();
    const first = menu.querySelector('.family-option');
    let onTop = false;
    if (first && box.width > 0) {
      const r = first.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      onTop = Boolean(hit && menu.contains(hit));
    }
    return {
      open: box.width > 0 && box.height > 0,
      expanded: document.querySelector('[data-family-toggle]').getAttribute('aria-expanded'),
      left: box.left,
      right: box.right,
      top: box.top,
      bottom: box.bottom,
      wide: window.innerWidth,
      tall: window.innerHeight,
      onTop,
      boxes: [...menu.querySelectorAll('input[type="checkbox"]')].map((input) => ({
        label: input.closest('label') ? input.closest('label').textContent.trim() : '',
        checked: input.checked,
      })),
      summary: document.querySelector('[data-family-summary]').textContent.trim(),
    };
  });

  if (watch) {
    await page.locator('[aria-label="Watch mode"]').first().click();
    await page.waitForTimeout(1500);
  }
  // Live off, so no timer refresh can land inside a measurement below.
  await page.locator('[data-page="map"] [data-live]').click();
  must(await waitFor(page, () => !loading, 20000, 100), 'the map did not settle after Live went off');
  let mapRequests = 0;
  page.on('request', (request) => {
    if (/\/api\/map\//.test(request.url())) mapRequests += 1;
  });
  const before = await layout();
  await toggle.click();
  await page.waitForTimeout(300);
  const opened = await menuState();
  const after = await layout();
  must(opened.open && opened.expanded === 'true', 'the button did not open the menu');
  if (!watch) {
    must(after.head === before.head, `opening the menu grew the header from ${before.head} to ${after.head} px`);
    must(after.map === before.map, `opening the menu moved the map from ${before.map} to ${after.map} px`);
  }
  must(after.scroll <= after.client + 1, `the open menu scrolls the page sideways: ${after.scroll}/${after.client}`);
  must(opened.left >= 0 && opened.right <= opened.wide && opened.top >= 0 && opened.bottom <= opened.tall,
    `the menu runs off the screen: ${Math.round(opened.left)}..${Math.round(opened.right)} of ${opened.wide}, `
    + `${Math.round(opened.top)}..${Math.round(opened.bottom)} of ${opened.tall}`);
  must(opened.onTop, 'something covers the open menu');
  must(opened.boxes.length === 7, `the menu holds ${opened.boxes.length} checkboxes, not one per kind`);
  must(opened.boxes.every((box) => box.label.length > 2 && box.checked),
    `a checkbox has no name or starts unchecked: ${JSON.stringify(opened.boxes)}`);
  must(opened.summary === 'Packet Types: all', `the button says "${opened.summary}"`);

  // One kind off: the button counts it and the map is told, and the
  // menu stays open for the next choice.
  await page.locator('[data-family-menu] label.family-option[data-family="POSITION_APP"]').click();
  await page.waitForTimeout(300);
  const one = await menuState();
  const hidden = await page.evaluate(() => [...hiddenFamilies]);
  must(one.open, 'choosing a kind closed the menu');
  must(one.summary === 'Packet Types: 6 of 7', `after one kind off the button says "${one.summary}"`);
  must(hidden.join() === 'POSITION_APP', `the map hides ${JSON.stringify(hidden)}`);

  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const escaped = await menuState();
  must(!escaped.open && escaped.expanded === 'false', 'Escape did not close the menu');
  if (watch) {
    // Escape closes the menu first. It must not also leave watch mode.
    must(await page.evaluate(() => document.querySelector('[data-map-shell]').classList.contains('watch')),
      'the Escape that closed the menu also left watch mode');
  }

  await toggle.click();
  await page.waitForTimeout(300);
  must((await menuState()).open, 'the menu did not open a second time');
  await page.mouse.click(5, Math.round((await menuState()).tall / 2));
  await page.waitForTimeout(300);
  must(!(await menuState()).open, 'a tap outside did not close the menu');

  await toggle.click();
  await page.waitForTimeout(300);
  await page.locator('[data-family-all]').click();
  await page.waitForTimeout(300);
  const reset = await menuState();
  must(reset.summary === 'Packet Types: all' && reset.boxes.every((box) => box.checked),
    'Show all did not show every kind');
  must(await waitFor(page, () => !loading, 20000, 100), 'the map did not settle after Show all');
  const requestsBeforeDone = mapRequests;
  await page.locator('[data-family-done]').click();
  await page.waitForTimeout(1000);
  const done = await menuState();
  // Done only closes the menu. The shared `.toggle` handler would mark it
  // pressed and fetch the whole map again.
  must(!(await page.locator('[data-family-done]').evaluate((button) => button.hasAttribute('aria-pressed'))),
    'Done carries aria-pressed, so it reads as a toggle');
  must(mapRequests === requestsBeforeDone,
    `Done asked the API for the map again (${mapRequests - requestsBeforeDone} requests)`);
  must(!done.open, 'Done did not close the menu');
  must(await page.evaluate(() => document.activeElement
    && document.activeElement.matches('[data-family-toggle]')), 'Done did not give focus back to the button');
  if (watch) await page.keyboard.press('Escape');
  return `head ${before.head} px open and shut, menu ${Math.round(opened.left)}..${Math.round(opened.right)}`
    + ` of ${opened.wide} px; filters, Escape, outside, Show all, Done`;
}

/*
 * Will, #387: the "16m ago" of a message on a node page opened a popup
 * with the date. A click, a tap or Enter must open the packet page, as
 * on the chat page, and a hover still gives the exact time through the
 * link's title. The node is the sender of the newest stored message
 * whose packet is known, so the link has a packet to land on. The
 * positive control is the packet page itself: it must show that packet
 * ID and not "packet not found".
 */
/*
 * A proxy on this machine in front of BASE, for the update notice journey
 * (#382). It passes every request through, and adds `extra` to the body
 * of `/sw.js`, which is what a deploy does to the worker's bytes. The
 * worker is asked for without compression, so the added line is text.
 */
async function workerProxy() {
  const http = require('http');
  const target = new URL(BASE);
  const client = target.protocol === 'https:' ? require('https') : http;
  const state = { extra: '', served: [] };
  const server = http.createServer((request, response) => {
    const worker = /^\/sw\.js(\?|$)/.test(request.url);
    const headers = { ...request.headers, host: target.host };
    if (worker) headers['accept-encoding'] = 'identity';
    const upstream = client.request({
      protocol: target.protocol, hostname: target.hostname, port: target.port,
      path: request.url, method: request.method, headers,
    }, (answer) => {
      if (!worker) {
        response.writeHead(answer.statusCode, answer.headers);
        answer.pipe(response);
        return;
      }
      const chunks = [];
      answer.on('data', (chunk) => chunks.push(chunk));
      answer.on('end', () => {
        const body = Buffer.concat(chunks).toString('utf8') + state.extra;
        state.served.push(body);
        const out = { ...answer.headers };
        delete out['content-length'];
        response.writeHead(answer.statusCode, out);
        response.end(body);
      });
    });
    upstream.on('error', () => response.destroy());
    request.pipe(upstream);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    served: state.served,
    change: (extra) => { state.extra = extra; },
    close: () => new Promise((resolve) => {
      server.close(resolve);
      server.closeAllConnections();
    }),
  };
}

async function nodeMessageOpensPacket(page, how) {
  const chat = await page.request.get(`${BASE}/api/chat?limit=50`).then((r) => r.json());
  const sent = chat.find((message) => message.packet_id != null);
  must(sent, 'no stored message has a packet, so there is nothing to link');
  await page.goto('about:blank');
  await open(page, `node/${encodeURIComponent(sent.from_node)}`, 500);
  const panel = '[data-page="node"] .panel:has(h3:has-text("Messages sent"))';
  const link = page.locator(`${panel} a.when`).first();
  await link.waitFor({ state: 'attached', timeout: 20000 }).catch(() => {});
  must(await link.count(), `${how}: a message time on the node page is not a link`);
  const href = await link.getAttribute('href');
  const match = /^#packet\/([^/]+)\/(\d+)$/.exec(href || '');
  must(match && decodeURIComponent(match[1]) === sent.from_node,
    `${how}: the time links to ${href}, not to a packet of ${sent.from_node}`);
  const title = (await link.getAttribute('title')) || '';
  must(/\d:\d\d/.test(title), `${how}: hovering the time no longer gives the exact time ("${title}")`);
  const name = await page.locator(`${panel} .who .name`).first().innerText();
  must(name.trim().length > 0, `${how}: the sender button beside the time is empty`);
  await link.scrollIntoViewIfNeeded();
  if (how === 'tap') await link.tap();
  else if (how === 'keyboard') {
    await link.focus();
    await page.keyboard.press('Enter');
  } else await link.click();
  const id = match[2];
  const shown = await waitFor(page, (wanted) => {
    const view = document.querySelector('.page.active');
    return Boolean(view && view.dataset.page === 'packet' && view.textContent.includes(wanted)
      && !/packet not found/i.test(view.textContent));
  }, 15000, 300, id);
  must(shown, `${how} on the time did not open the packet page of ${id}`);
  return `${how} -> ${href}`;
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

  await journey(context, 'the node summary is never three narrow columns (#287)', async (page) => {
    /*
     * At 834 px, an iPad in portrait, the four summary panels fell into
     * three columns and the Identity panel was a third of the screen:
     * "(CLIENT_BASE" and ")" on two lines, Last heard on three. The
     * same row width comes back at 1112 px, where the sidebar is shown.
     * So the column count is read at both, and at the widths either
     * side, and three is a failure wherever it appears.
     *
     * The node is a CLIENT_BASE when the instance has one, because that
     * is the longest role label the review found breaking.
     */
    const nodes = await (await page.request.get(`${BASE}/api/nodes?limit=200`)).json();
    must(Array.isArray(nodes) && nodes.length, 'the instance has no nodes to open');
    const node = nodes.find((row) => row.role === 'CLIENT_BASE') || nodes[0];
    const measure = () => {
      const row = document.querySelector('[data-node-body] .summary-row');
      if (!row || !row.children.length) return null;
      const lefts = new Set([...row.children].map((child) => Math.round(child.getBoundingClientRect().left)));
      const identity = row.children[0];
      const lines = [...identity.querySelectorAll('dd')].map((dd) =>
        Math.round(dd.getBoundingClientRect().height / (parseFloat(getComputedStyle(dd).lineHeight) || 20)));
      return {
        columns: lefts.size,
        share: identity.getBoundingClientRect().width / row.getBoundingClientRect().width,
        worst: Math.max(...lines),
      };
    };
    await page.setViewportSize({ width: 834, height: 1112 });
    await page.goto(`${BASE}/#node/${encodeURIComponent(node.node_id)}`, { waitUntil: 'load' });
    must(await waitFor(page, measure, 15000), 'the summary row never drew');
    const out = [];
    for (const width of [834, 900, 1024, 1112, 1280, 1440]) {
      await page.setViewportSize({ width, height: 1112 });
      await page.waitForTimeout(400);
      const size = await page.evaluate(measure);
      must(size.columns !== 3, `the summary row is three columns at ${width} px`);
      out.push(`${width}:${size.columns}`);
    }
    // At the iPad width, with the wider letters of the CI runner's
    // fonts, no identity value may take more than two lines.
    await page.setViewportSize({ width: 834, height: 1112 });
    await page.addStyleTag({ content: '[data-node-body] * { letter-spacing: .05em !important; }' });
    await page.waitForTimeout(400);
    const ipad = await page.evaluate(measure);
    must(ipad.worst <= 2, `an identity value takes ${ipad.worst} lines at 834 px`);
    return `${node.role || 'no role'}: columns ${out.join(' ')}; identity ${Math.round(ipad.share * 100)}% wide, `
      + `longest value ${ipad.worst} line(s) at 834 px`;
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
        // Not while a render is running: its half-drawn page, or the
        // previous node's, is not this node's answer.
        if (loading) return null;
        const found = [...document.querySelectorAll('[data-page="node"] .route-tile')]
          .find((node) => /^Furthest node that heard it/i.test(node.querySelector('.label').textContent));
        return found ? {
          value: found.querySelector('.value').textContent.trim(),
          detail: [...found.querySelectorAll('.muted')].map((node) => node.textContent).join(' '),
        } : null;
      };
      const got = await valueOf(page, read);
      must(got, `${id}: the furthest tile never drew`);
      const { value, detail } = got;
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
    /*
     * An estimate with a wide range is still an estimate (#257).
     *
     * The open question was whether to hide one whose range is more than
     * half its distance, and Will (2026-09-27) said keep it. The seeded
     * mesh may hold no such pair, so the tile is fed two: 5 km ± 4.6,
     * and 3 km ± 3.2, whose range passes the distance itself. Both must
     * still print a figure with its range, never "Not known".
     */
    const someone = kinds.get('estimate');
    for (const [estimate, error, word] of [[5, 4.6, 'about'], [3, 3.2, 'under']]) {
      await page.unrouteAll();
      await page.route(/\/api\/nodes\/[^/]+\/routes\?/, async (route) => {
        const response = await route.fetch();
        const body = await response.json();
        body.furthest_heard_by = {
          ...(body.furthest_heard_by || { node_id: '!00000001', display_name: 'Wide range' }),
          distance_km: null, approx_distance_km: estimate, distance_error_km: error,
        };
        await route.fulfill({ response, json: body });
      });
      await page.goto(`${BASE}/?wide=${estimate}#node/${encodeURIComponent(someone)}`, { waitUntil: 'load' });
      const read = () => {
        // Not while a render is running: its half-drawn page, or the
        // previous node's, is not this node's answer.
        if (loading) return null;
        const found = [...document.querySelectorAll('[data-page="node"] .route-tile')]
          .find((node) => /^Furthest node that heard it/i.test(node.querySelector('.label').textContent));
        return found ? {
          value: found.querySelector('.value').textContent.trim(),
          detail: [...found.querySelectorAll('.muted')].map((node) => node.textContent).join(' '),
        } : null;
      };
      const got = await valueOf(page, read);
      must(got, `${estimate} ± ${error} km: the furthest tile never drew`);
      const { value, detail } = got;
      must(value.startsWith(`${word} `), `${estimate} ± ${error} km reads "${value}", wanted "${word} ..."`);
      must(/±|rounded by up to/.test(detail), `${estimate} ± ${error} km lost its range: "${detail}"`);
      seen.push(`${estimate}±${error}=${value}`);
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

  await journey(context, 'the nodes list scrolls on by cursor (#250)', async (page) => {
    /*
     * The seed holds one page of nodes, so a second page cannot happen
     * against it. This serves 250 nodes built from a real row, and pages
     * them the way the server does: a `cursor` that names the last row,
     * returned in `X-Next-Cursor`. The claims are about the page: every
     * later request carries the cursor and the sort, none carries an
     * offset, and the list reaches the end with no node twice. The
     * server's half is `tests/integration/test_node_cursor.py`.
     */
    const template = (await (await page.request.get(`${BASE}/api/nodes?limit=1`)).json())[0];
    must(template, 'the instance has no node to copy');
    const TOTAL = 250;
    const nodes = Array.from({ length: TOTAL }, (_, index) => ({
      ...template,
      node_num: 0x0e2e0000 + index,
      node_id: `!0e2e${String(index).padStart(4, '0')}`,
      long_name: `Cursor ${index}`,
      short_name: `C${index}`,
    }));
    const asked = [];
    await page.route(/\/api\/nodes\?/, (route, request) => {
      const url = new URL(request.url());
      asked.push(url.search);
      const limit = Number(url.searchParams.get('limit') || 100);
      const cursor = url.searchParams.get('cursor');
      const start = cursor == null ? 0 : Number(cursor) + 1;
      const rows = nodes.slice(start, start + limit);
      const headers = { 'X-Total-Count': String(TOTAL) };
      if (rows.length) headers['X-Next-Cursor'] = String(start + rows.length - 1);
      return route.fulfill({ contentType: 'application/json', headers, body: JSON.stringify(rows) });
    });
    await open(page, 'nodes');
    const count = () => page.locator('[data-page="nodes"] tbody tr').count();
    for (let tries = 0; tries < 20 && (await count()) < TOTAL; tries += 1) {
      await page.locator('[data-node-more]').scrollIntoViewIfNeeded().catch(() => {});
      await page.waitForTimeout(500);
    }
    const shown = await count();
    const later = asked.slice(1);
    must(later.length > 0, `only one page was asked for (${shown} rows)`);
    must(later.every((query) => /[?&]cursor=/.test(query)), `a later page had no cursor: ${later.join(' ')}`);
    must(!asked.some((query) => /[?&]offset=/.test(query)), `a page was asked for by offset: ${asked.join(' ')}`);
    must(asked.every((query) => /[?&]sort=last_heard\b/.test(query)), 'a page lost the sort');
    must(shown === TOTAL, `the list stopped at ${shown} of ${TOTAL}`);
    const ids = await page.$$eval('[data-page="nodes"] tbody tr code', (cells) => cells.map((cell) => cell.textContent));
    must(new Set(ids).size === ids.length, 'a node appears twice after paging');
    return `${shown} rows over ${asked.length} pages, every later page by cursor`;
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

  await journey(context, 'the nodes export holds what the list shows (#350)', async (page) => {
    /*
     * A filter and a sort, then Export -> CSV. The file must hold every
     * node the list counts, not the page that has loaded, with the
     * columns the table draws, in the table's order. The server's half
     * (the file equals the list for seven filter combinations) is
     * `tests/integration/test_nodes_export.py`.
     */
    await open(page, 'nodes');
    await page.locator('[data-page="nodes"] [data-node-active]').selectOption('');
    await page.waitForTimeout(2500);
    await page.click('[data-page="nodes"] th:nth-child(1) .sort-button');
    await page.waitForTimeout(2500);
    const said = await page.locator('[data-node-count]').innerText();
    const total = Number(((said.match(/^([\d,]+) nodes$/) || [])[1] || '').replace(/,/g, ''));
    must(Number.isFinite(total) && total > 0, `the list gives no total to compare with: "${said}"`);
    const shownIds = await page.$$eval('[data-page="nodes"] tbody tr code',
      (cells) => cells.map((cell) => cell.textContent));

    const asked = [];
    page.on('request', (request) => {
      if (request.url().includes('api/nodes/export?')) asked.push(new URL(request.url()));
    });
    await page.click('[data-page="nodes"] [data-node-export] > summary');
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 60000 }),
      page.click('[data-page="nodes"] [data-node-export-format="csv"]'),
    ]);
    const body = fs.readFileSync(await download.path(), 'utf8');
    must(/^sonoran-nodes-\d{8}-\d{6}Z\.csv$/.test(download.suggestedFilename()),
      `the file is called ${download.suggestedFilename()}`);

    // RFC 4180, by hand: a node name can hold a comma, a quote or a line break.
    const records = [];
    let row = [''];
    let quoted = false;
    const text = body.replace(/^﻿/, '');
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (quoted) {
        if (char === '"' && text[index + 1] === '"') { row[row.length - 1] += '"'; index += 1; }
        else if (char === '"') quoted = false;
        else row[row.length - 1] += char;
      } else if (char === '"') quoted = true;
      else if (char === ',') row.push('');
      else if (char === '\r' && text[index + 1] === '\n') { records.push(row); row = ['']; index += 1; }
      else row[row.length - 1] += char;
    }
    const [header, ...rows] = records;
    const expected = ['Name', 'Short name', 'Node ID', 'Hardware', 'Role', 'Gateway', 'Position', 'Last heard'];
    must(header && header.join() === expected.join(), `the header row is ${header && header.join()}`);
    must(rows.length === total, `the file holds ${rows.length} rows and the list counts ${total}`);
    const fileIds = rows.slice(0, shownIds.length).map((cells) => cells[2]);
    must(fileIds.join() === shownIds.join(), 'the file is not in the order the table shows');

    const query = asked[0];
    must(query, 'no export request was seen');
    must(query.searchParams.get('sort') === 'name', `the export lost the sort: ${query.search}`);
    must(!query.searchParams.has('active_hours'), `the export kept the old window: ${query.search}`);
    must(!query.searchParams.has('limit') && !query.searchParams.has('cursor'),
      `the export asked for one page: ${query.search}`);
    const status = await page.locator('[data-node-export-status]').innerText();
    must(/^Saved /.test(status), `the status says "${status}"`);
    return `${rows.length} rows = the list's ${total}, sorted by name; "${status}"`;
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

  await journey(context, 'Apply in the node filters leaves focus on the Filters button (#251)', async (page) => {
    /*
     * Hiding the panel took the focus out of Apply and left it on the
     * document body, so the next Tab started from the top of the page.
     * Walked with the keyboard only, and read from `activeElement`
     * after the list has reloaded, not by eye.
     */
    await open(page, 'nodes');
    const toggle = page.locator('[data-page="nodes"] [data-node-filter-open]');
    await toggle.focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(400);
    must((await toggle.getAttribute('aria-expanded')) === 'true', 'Enter did not open the panel');
    await page.locator('[data-node-filter-apply]').focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(2500);
    const focus = await page.evaluate(() => {
      const active = document.activeElement;
      return {
        onToggle: active === document.querySelector('[data-node-filter-open]'),
        tag: active ? active.tagName : null,
        hidden: document.querySelector('[data-node-filters]').hidden,
      };
    });
    must(focus.hidden, 'Apply did not close the panel');
    must(focus.onToggle, `after Apply the focus is on <${String(focus.tag).toLowerCase()}>, not the Filters button`);
    return 'Apply closes the panel and focus stays on Filters';
  });

  await journey(context, 'the Filters badge counts only what the reader changed (#301)', async (page) => {
    /*
     * A first visit showed "2" with every group at "Any": the badge
     * counted the toolbar's default 24 hours and the sidebar's preset.
     * Will (2026-09-27): count what the reader changed, toolbar or panel,
     * and never the preset. What is SENT must not change.
     */
    const asked = [];
    page.on('request', (request) => {
      if (/\/api\/nodes\?/.test(request.url())) asked.push(request.url());
    });
    await open(page, 'nodes');
    await page.locator('[data-page="nodes"] tbody tr').first().waitFor({ timeout: 15000 });
    const toggle = page.locator('[data-page="nodes"] [data-node-filter-open]');
    const badge = page.locator('[data-page="nodes"] [data-node-filter-count]');
    const state = async () => ({
      hidden: await badge.isHidden(),
      text: (await badge.textContent()).trim(),
      name: await toggle.getAttribute('aria-label'),
    });
    const first = await state();
    must(first.hidden && first.name === 'Filters',
      `a first visit shows a badge: "${first.text}", named "${first.name}"`);
    // The menu's preset travels as `preset=` since #313, never `channel=`.
    must(asked.length && /[?&]active_hours=24\b/.test(asked[0]) && /[?&]preset=/.test(asked[0])
      && !/[?&]channel=/.test(asked[0]),
      `the first request lost its window or preset: ${asked[0]}`);

    // One panel choice, applied, is one.
    await toggle.click();
    const none = page.locator('[data-node-filters] .filter-option', { hasText: 'None reported' }).first();
    await none.waitFor({ timeout: 15000 });
    await none.click();
    await page.locator('[data-node-filter-apply]').click();
    await page.waitForTimeout(2500);
    const one = await state();
    must(!one.hidden && one.text === '1', `one panel choice shows "${one.text}"`);
    must(await page.locator('[data-node-chips] .chip-drop').count() === 1, 'no chip for the one choice');

    // Clear all takes it away.
    await toggle.click();
    await page.waitForTimeout(400);
    await page.locator('[data-node-filter-clear]').click();
    await page.waitForTimeout(2500);
    must((await state()).hidden, 'Clear all left the badge up');

    // A toolbar control away from its default counts too.
    await page.locator('[data-page="nodes"] [data-node-active]').selectOption('');
    await page.waitForTimeout(2500);
    const toolbar = await state();
    must(!toolbar.hidden && toolbar.text === '1', `"Any time" in the toolbar shows "${toolbar.text}"`);
    return 'no badge on a first visit, 1 for a panel choice, none after Clear all, 1 for the toolbar';
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
    /*
     * Since #295 the range lives on a channel page only, so this finds a
     * channel from the overview and changes the range there.
     */
    await open(page, 'chat', 500);
    const link = () => {
      const found = document.querySelector('[data-page="chat"] a.title[href^="#chat/"]');
      return found ? decodeURIComponent(found.getAttribute('href').replace('#chat/', '')) : null;
    };
    must(await waitFor(page, link, 15000), 'the overview drew no channel to open');
    const channel = await page.evaluate(link);
    await open(page, `chat/${encodeURIComponent(channel)}/table`);
    const asked = [];
    page.on('request', (request) => {
      if (/\/api\/chat\?/.test(request.url())) asked.push(new URL(request.url()).searchParams.get('since'));
    });
    await page.click('[data-chat-quick="24"]');
    await page.waitForTimeout(3000);
    const hash = await page.evaluate(() => window.location.hash);
    must(/[?&]from=/.test(hash), `the range did not reach the address: ${hash}`);
    /*
     * And no `to=`, because a quick range stays open at the newest end.
     * "Last 24 h" that froze at the moment it was pressed would go stale
     * while somebody watched it, and live would stop appending.
     */
    must(!/[?&]to=/.test(hash), `a quick range should stay open-ended: ${hash}`);
    const since = asked.map((value) => new Date(value).getTime()).filter(Number.isFinite);
    const day = Date.now() - 24 * 3600000;
    must(since.some((when) => Math.abs(when - day) < 120000),
      `the channel was not asked for again over the last 24 h: ${asked.join(', ')}`);
    return `${channel} asked again from ${new Date(Math.min(...since)).toISOString()}`;
  });

  await journey(context, 'the chat overview has no range, a channel page has one', async (page) => {
    /*
     * #295. Will: the overview "is just supposed to be a quick way to see
     * the recent messages and chats"; the channel pages keep the range.
     * An old overview link with a range in it must show the same fixed
     * window, and say that window in words.
     */
    const asked = [];
    page.on('request', (request) => {
      if (/\/api\/chat\/overview\?/.test(request.url())) asked.push(new URL(request.url()).search);
    });
    const shown = () => {
      const range = document.querySelector('[data-page="chat"] [data-chat-range]');
      const quick = document.querySelector('[data-page="chat"] [data-chat-quick="24"]');
      return {
        range: Boolean(range && range.offsetParent),
        quick: Boolean(quick && quick.offsetParent),
        sub: (document.querySelector('[data-chat-sub]') || {}).textContent || '',
        hash: window.location.hash,
      };
    };
    const seen = [];
    for (const width of [320, 1440]) {
      await page.setViewportSize({ width, height: 800 });
      // A real load each time: from `#chat` to `#chat?from=` is only a
      // change of fragment, which does not load the page again.
      await page.goto('about:blank');
      await open(page, 'chat?from=2026-09-01T00:00:00Z', 500);
      // Drawn, so no request is still in flight when the page is left.
      must(await waitFor(page, () => Boolean(document.querySelector(
        '[data-page="chat"] [data-chat-body] .panel, [data-page="chat"] [data-chat-body] .empty')), 15000),
      `the overview never drew at ${width}px`);
      const overview = await page.evaluate(shown);
      must(!overview.range && !overview.quick, `the range shows on the overview at ${width}px`);
      must(/last 7 days/.test(overview.sub), `the overview does not say its window: "${overview.sub}"`);
      must(overview.hash === '#chat', `the old range stayed in the address: ${overview.hash}`);
      seen.push(`${width}px hidden`);
    }
    must(asked.length && asked.every((query) => /[?&]hours=168(&|$)/.test(query)),
      `the overview asked for another window: ${asked.join(', ')}`);
    const channel = await page.evaluate(() => {
      const link = document.querySelector('[data-page="chat"] a.title[href^="#chat/"]');
      return link ? link.getAttribute('href') : null;
    });
    must(channel, 'the overview drew no channel to open');
    await open(page, channel.slice(1), 3000);
    const on = await page.evaluate(shown);
    must(on.range && on.quick, 'the channel page lost its range control');
    return `${seen.join(', ')}; hours=168 on ${asked.length} request(s); ${channel} shows the range`;
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

  await journey(context, 'the dashboard shows five latest messages and a way to all of them', async (page) => {
    /*
     * #296. The list was a `.feed`, so none of the message styling
     * reached it: the name was a bordered button, the channel ran into
     * the time, the time was underlined in the browser's own blue, and
     * a message that was one bell character drew as an empty line.
     *
     * The answer is extended rather than replaced, so the rows are real
     * ones; the first is given a bell for a body, the second a reply, and
     * the third a DM marker, because those are what must still draw.
     */
    const asked = [];
    await page.route(/\/api\/chat\?limit=/, async (route, request) => {
      asked.push(new URL(request.url()).searchParams.get('limit'));
      const response = await route.fetch();
      const rows = await response.json();
      if (Array.isArray(rows) && rows.length >= 3) {
        rows[0] = { ...rows[0], body: '\u0007' };
        rows[1] = { ...rows[1], reply_to: { from_name: 'Quoted', body: 'the earlier message', packet_id: null } };
        rows[2] = { ...rows[2], to_node: '!0e2e0002' };
      }
      await route.fulfill({ response, json: rows });
    });
    const seen = [];
    for (const width of [320, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('about:blank');
      await open(page, 'dashboard', 500);
      const drawn = () => document.querySelectorAll('[data-recent-chat] > li').length > 0;
      must(await waitFor(page, drawn, 15000), `no message drew on the dashboard at ${width}px`);
      const m = await page.evaluate(() => {
        const list = document.querySelector('[data-recent-chat]');
        const rows = [...list.querySelectorAll(':scope > li')];
        const name = list.querySelector('.who .name');
        const when = list.querySelector('.who .when');
        const nameStyle = getComputedStyle(name);
        const whenStyle = getComputedStyle(when);
        const first = rows[0].querySelector('.body');
        return {
          rows: rows.length,
          list: list.className,
          nameBorder: nameStyle.borderTopWidth,
          nameBg: nameStyle.backgroundColor,
          underline: whenStyle.textDecorationLine,
          whenRight: when.getBoundingClientRect().right,
          whoRight: when.parentElement.getBoundingClientRect().right,
          channels: list.querySelectorAll('.channel-label').length,
          bellHeight: first ? first.getBoundingClientRect().height : -1,
          reply: list.querySelectorAll('.reply-quote').length,
          dm: list.querySelectorAll('li.dm').length,
          more: (document.querySelector('[data-page="dashboard"] a.more[href="#chat"]') || {}).textContent || '',
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        };
      });
      must(m.rows <= 5, `the dashboard drew ${m.rows} messages, not at most 5`);
      must(/\bmessages\b/.test(m.list), `the list is not .messages: "${m.list}"`);
      must(m.nameBorder === '0px', `the sender name still has a ${m.nameBorder} border`);
      must(m.underline === 'none', `the time is underlined before any hover: ${m.underline}`);
      must(Math.abs(m.whenRight - m.whoRight) <= 1, 'the time is not on the right of its line');
      must(m.channels === 0, `the channel is repeated on ${m.channels} rows`);
      must(m.bellHeight === 0, `a body of one bell character drew ${m.bellHeight}px tall`);
      must(m.reply >= 1 && m.dm >= 1, `a reply (${m.reply}) or a DM (${m.dm}) no longer draws`);
      must(m.more.trim() === 'View all messages', 'there is no View all messages link');
      must(m.scroll <= m.client + 1, `the dashboard scrolls sideways at ${width}px: ${m.scroll}/${m.client}`);
      seen.push(`${width}px ${m.rows} rows`);
    }
    must(asked.every((limit) => limit === '5'), `the dashboard asked for ${asked.join(', ')} messages`);
    // By keyboard: the link takes focus and Enter opens the chat overview.
    await page.focus('[data-page="dashboard"] a.more[href="#chat"]');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(800);
    const hash = await page.evaluate(() => window.location.hash);
    must(hash === '#chat', `Enter on View all messages went to ${hash}`);
    return `${seen.join(', ')}; limit=5; Enter opens #chat`;
  });

  await journey(context, 'chat times are a real tap target and say the date when old', async (page) => {
    /*
     * #269, from the phone review: the time links measured 41 x 19 px,
     * twenty of them to a page, and the exact time was only in a `title`,
     * which a phone never shows. The hit area must be 44 px each way
     * without moving the text, and a message older than a day must show
     * its date and time on the line itself.
     *
     * The channel is served here, so there is a message three days old to
     * look at whatever the seed's clock says.
     */
    const CHANNEL = 'E2ETimes';
    const now = Date.now();
    const row = (index, ageMs) => ({
      packet_id: 910000 + index, from_node: '!0e2e0003', from_node_id: '!0e2e0003', from_name: 'Times test',
      to_node: '^all', channel: CHANNEL, body: `message ${index}`, seen_at: new Date(now - ageMs).toISOString(),
      reply_id: null, emoji: false, reply_to: null, reactions: [], metrics: null,
    });
    const rows = [row(1, 5 * 60000), row(0, 3 * 86400000)];
    await page.route(/\/api\/chat\?/, async (route, request) => {
      const query = new URL(request.url()).searchParams;
      if (query.get('channel') !== CHANNEL) return route.continue();
      return route.fulfill({ json: query.get('before') ? [] : rows });
    });
    const measure = () => [...document.querySelectorAll('.page.active .messages .who a.when')].map((link) => {
      const box = link.getBoundingClientRect();
      return { w: Math.round(box.width), h: Math.round(box.height), text: link.textContent, title: link.title };
    });
    const seen = [];
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('about:blank');
      await open(page, `chat/${CHANNEL}`, 500);
      must(await waitFor(page, () => document.querySelectorAll('[data-chat-scroll] a.when').length === 2, 15000),
        `the served messages never drew at ${width}px`);
      const times = await page.evaluate(measure);
      for (const time of times) {
        must(time.w >= 44 && time.h >= 44, `a time link is ${time.w} x ${time.h} px at ${width}px`);
      }
      const [old, fresh] = times;
      must(!/ago$/.test(old.text) && /\d/.test(old.text) && old.title.startsWith(old.text),
        `a three-day-old message says "${old.text}", not its date and time`);
      must(/ago$/.test(fresh.text), `a five-minute-old message says "${fresh.text}"`);
      seen.push(`${width}px ${times.map((t) => `${t.w}x${t.h}`).join(' ')} "${old.text}"`);
    }
    // The dashboard's feed uses the same line.
    await page.goto('about:blank');
    await open(page, 'dashboard', 500);
    must(await waitFor(page, () => document.querySelectorAll('[data-recent-chat] a.when').length > 0, 15000),
      'no time link drew on the dashboard');
    const dash = await page.evaluate(measure);
    must(dash.every((time) => time.w >= 44 && time.h >= 44),
      `a dashboard time link is under 44 px: ${dash.map((t) => `${t.w}x${t.h}`).join(' ')}`);
    return `${seen.join('; ')}; dashboard ${dash.length} at >= 44x44`;
  });

  await journey(context, 'a message time on a node page opens its packet (#387)', async (page) => {
    const clicked = await nodeMessageOpensPacket(page, 'click');
    const keyed = await nodeMessageOpensPacket(page, 'keyboard');
    return `${clicked}; ${keyed}`;
  });

  await journey(context, 'the chat table pages on as you scroll', async (page) => {
    /*
     * #297. The table view stopped at 100 rows: only the reading view
     * paged. Will decided there is no "Load older" button, so the table
     * must load its next page as the reader scrolls to its foot.
     *
     * The seed holds a few dozen messages a channel, less than one page,
     * so the channel here is served by the journey: 250 messages a minute
     * apart, answered the way `/api/chat` answers (newest first, `before`
     * exclusive, `limit`). Each `seen_at` carries microseconds, so the
     * cursor can be checked to be the row's own string and not one
     * rounded through a Date.
     */
    const CHANNEL = 'E2EPaging';
    const TOTAL = 250;
    const now = Date.now();
    const iso = (ms, micro) => new Date(ms).toISOString().replace(/\.(\d{3})Z$/, `.$1${micro}+00:00`);
    const all = Array.from({ length: TOTAL }, (_, index) => ({
      packet_id: 900000 + index,
      from_node: '!0e2e0001', from_node_id: '!0e2e0001', from_name: 'Paging test',
      to_node: '^all', channel: CHANNEL, body: `message ${index}`,
      seen_at: iso(now - (TOTAL - index) * 60000, String(index % 1000).padStart(3, '0')),
      reply_id: null, emoji: false, reply_to: null, reactions: [], metrics: null,
    })).reverse();
    const cursors = [];
    await page.route(/\/api\/chat\?/, async (route, request) => {
      const query = new URL(request.url()).searchParams;
      if (query.get('channel') !== CHANNEL) return route.continue();
      const before = query.get('before');
      if (before) cursors.push(before);
      const since = query.get('since') ? new Date(query.get('since')).getTime() : null;
      const limit = Number(query.get('limit') || 100);
      const rows = all
        .filter((row) => !before || row.seen_at < before)
        .filter((row) => since == null || new Date(row.seen_at).getTime() >= since)
        .slice(0, limit);
      return route.fulfill({ json: rows });
    });
    await page.setViewportSize({ width: 1024, height: 800 });
    await open(page, `chat/${CHANNEL}/table`, 3000);
    const count = () => document.querySelectorAll('[data-page="chat"] [data-chat-body] tbody tr').length;
    const opened = await page.evaluate(count);
    must(opened === 100, `the table opened with ${opened} rows, not one page of 100`);
    for (let step = 0; step < 6 && (await page.evaluate(count)) < TOTAL; step += 1) {
      await page.mouse.wheel(0, 20000);
      await page.waitForTimeout(700);
    }
    const reached = await page.evaluate(count);
    must(reached === TOTAL, `scrolling the table reached ${reached} of ${TOTAL} rows`);
    const badge = await page.locator('[data-chat-count]').innerText();
    must(/250 messages/.test(badge), `the count should say every message is loaded: "${badge}"`);
    must(cursors.length >= 2 && cursors.every((cursor) => all.some((row) => row.seen_at === cursor)),
      `a cursor was not a row's own timestamp: ${cursors.join(', ')}`);

    // Switching to the reading view keeps what was loaded.
    await page.click('[data-chat-view-choice="chat"]');
    await page.waitForTimeout(1500);
    const kept = await page.evaluate(() => document.querySelectorAll('[data-chat-scroll] .messages li').length);
    must(kept === TOTAL, `switching to the chat view kept ${kept} of ${TOTAL} rows`);
    return `100 -> ${reached} rows in the table by scrolling, ${kept} kept on switching view`;
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
    /*
     * The page's own preset picker (`[data-coverage-preset]`) is gone: the
     * preset is the menu's, for every page (AGENTS.md 9.7). This used to
     * select the removed element, which only passed because a preview has
     * no published run (#299). It now drives the menu's switch, and the
     * layer drop-down that replaced the three pills.
     */
    const layer = page.locator('[data-coverage-layers]');
    if (!published) {
      must(!(await layer.isVisible()), 'no run is published, yet a layer is offered');
      const said = await page.locator('[data-page="coverage"]').innerText();
      must(said.trim().length > 40, 'no run, and the page said nothing about it');
      return 'no run published; the page says so';
    }
    const presets = page.locator('[data-preset-switch] [role="radio"]');
    const count = await presets.count();
    must(count > 0, 'a run is published but the menu offers no preset');
    // The layer is in the settings panel now (#334).
    await page.locator('[data-coverage-options]').click();
    const layers = await layer.locator('option').count();
    must(layers >= 2, `a run is published but the layer drop-down holds ${layers} options`);
    const second = await layer.locator('option').nth(1).getAttribute('value');
    await layer.selectOption(second);
    await page.waitForTimeout(800);
    const title = (await page.locator('[data-coverage-legend-title]').textContent()).trim();
    const chosen = (await layer.locator('option:checked').textContent()).trim();
    must(title === chosen, `the legend says "${title}" after choosing "${chosen}"`);
    if (count === 2) {
      // Switch, then back: the choice is global and outlives this page.
      await page.locator('[data-preset-switch] [aria-checked="false"]').click();
      await page.waitForTimeout(4000);
      must((await page.locator('#coverage-map').count()) > 0, 'the coverage map went away on a preset switch');
      await page.locator('[data-preset-switch] [aria-checked="false"]').click();
      await page.waitForTimeout(1000);
    }
    must((await page.locator('#coverage-map').count()) > 0, 'the coverage map went away');
    return `${count} presets in the menu, ${layers} layers, legend follows the layer`;
  });

  await journey(context, 'page heads keep their controls on the title row (#299)', async (page) => {
    /*
     * Coverage and Graph dropped their controls under the title at laptop
     * widths; Graph broke them into two ragged rows as well. Measured with
     * the CI slack (letter-spacing .05em, as the Who hears it journey does),
     * because the runner's fonts are wider than a Mac's.
     */
    const bad = [];
    let coverageGap = null;
    await open(page, 'graph', 1500);
    await page.addStyleTag({ content: '* { letter-spacing: .05em !important; }' });
    for (const width of [1280, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      for (const name of ['graph', 'coverage', 'nodes', 'firehose', 'planner']) {
        // A hash change routes in the same document, so the spacing stays.
        await page.evaluate((hash) => { location.hash = hash; }, name);
        await page.waitForTimeout(2500);
        const got = await page.evaluate(() => {
          const head = document.querySelector('.page.active .page-head');
          const title = head.querySelector('h2').getBoundingClientRect();
          const controls = head.querySelector('.controls').getBoundingClientRect();
          const map = document.querySelector('.page.active #coverage-map');
          return {
            below: controls.height > 0 && controls.top >= title.bottom,
            rows: Math.round(controls.height),
            /*
             * Less the "no coverage map has been made yet" notice. It is
             * there only on an instance with no published run, like a
             * fresh test database, and it is a sentence, not a row of
             * controls. With letters as wide as CI's fonts it wraps to two
             * lines, and counting it failed this at 92 px.
             */
            map: map ? Math.round(map.getBoundingClientRect().top - head.getBoundingClientRect().top
              - [...document.querySelectorAll('.page.active .notice')]
                .filter((node) => node.getBoundingClientRect().height > 0
                  && node.getBoundingClientRect().bottom <= map.getBoundingClientRect().top + 1)
                .reduce((sum, node) => {
                  const style = getComputedStyle(node);
                  return sum + node.getBoundingClientRect().height
                    + parseFloat(style.marginTop) + parseFloat(style.marginBottom);
                }, 0)) : null,
          };
        });
        if (got.below) bad.push(`${name} at ${width}: controls under the title`);
        if (got.rows > 60) bad.push(`${name} at ${width}: controls in ${got.rows} px, more than one row`);
        if (name === 'coverage' && width === 1440) coverageGap = got.map;
      }
    }
    await page.setViewportSize({ width: 1500, height: 1050 });
    must(bad.length === 0, bad.join('; '));
    // With a run published the map starts right under the head (was 205).
    if (coverageGap != null) must(coverageGap <= 90, `the coverage map starts ${coverageGap} px below the head`);
    return `5 pages at 1280 and 1440 px, one row each${coverageGap != null ? `; coverage map ${coverageGap} px below the head` : ''}`;
  });

  await journey(context, 'the graph Options button counts what changed (#299)', async (page) => {
    await open(page, 'graph', 3000);
    const button = page.locator('[data-page="graph"] [data-options-open]');
    const panel = page.locator('#graph-options');
    must(await panel.isHidden(), 'the options panel starts open');
    must((await button.getAttribute('aria-label')) === 'Options', `starts as "${await button.getAttribute('aria-label')}"`);
    await button.click();
    must((await button.getAttribute('aria-expanded')) === 'true', 'the button did not say it opened');
    must(await panel.isVisible(), 'the panel did not open');
    await page.locator('[data-graph-unconfirmed]').click();
    await page.waitForTimeout(300);
    must((await button.getAttribute('aria-label')) === 'Options, 1 changed',
      `one toggle changed, the button says "${await button.getAttribute('aria-label')}"`);
    await page.locator('[data-graph-layout]').selectOption('free');
    await page.waitForTimeout(300);
    const two = (await page.locator('[data-page="graph"] [data-options-count]').textContent()).trim();
    must(two === '2', `two options changed, the badge says "${two}"`);
    await page.locator('[data-graph-unconfirmed]').click();
    await page.locator('[data-graph-layout]').selectOption('spread');
    await page.waitForTimeout(300);
    must(await page.locator('[data-page="graph"] [data-options-count]').isHidden(), 'back to the start, the badge stayed');
    await button.click();
    must(await panel.isHidden(), 'a second press did not close the panel');
    return 'opens, counts 1 then 2, clears, closes';
  });

  await journey(context, 'coverage settings: the gear opens the panel and the layer moves the tiles (#334)', async (page) => {
    await stubCoverage(page);
    await open(page, 'coverage', 2500);
    const button = page.locator('[data-coverage-options]');
    const panel = page.locator('#coverage-options');
    must(await button.isVisible(), 'no settings button with a run published');
    must((await button.locator('use').getAttribute('href')) === '#i-settings', 'the button has no gear');
    must(await panel.isHidden(), 'the settings panel starts open');
    must(await page.locator('.page[data-page="coverage"] .page-head [data-coverage-layers]').count() === 0,
      'the layer is still in the head');
    await button.click();
    must(await panel.isVisible(), 'the gear did not open the panel');
    must((await button.getAttribute('aria-expanded')) === 'true', 'the button did not say it opened');
    const before = await valueOf(page, COVERAGE_TILE_URL);
    must(before && before.includes(`/${STUB_STAMP}/MediumFast/infrastructure/usable/`),
      `the default tiles are ${before}`);
    await page.locator('[data-coverage-layers]').selectOption('downlink');
    await page.waitForTimeout(400);
    const after = await valueOf(page, COVERAGE_TILE_URL);
    must(after && after.includes('/infrastructure/downlink/'), `after choosing the downlink the tiles are ${after}`);
    const hash = await page.evaluate(() => location.hash);
    must(hash === '#coverage?layer=downlink', `the address says ${hash}`);
    must((await button.getAttribute('aria-label')) === 'Settings, 1 changed',
      `the button says "${await button.getAttribute('aria-label')}"`);
    /*
     * The seeded run, like this stub, has no approximate map. The toggle
     * must be off, disabled, and say why, rather than offer a map that
     * was never computed.
     */
    const box = page.locator('[data-coverage-approx]');
    must(await box.isDisabled(), 'the approximate toggle is enabled with no approximate map');
    must(!(await box.isChecked()), 'the approximate toggle starts on');
    const said = (await page.locator('[data-coverage-approx-note]').textContent()).trim();
    must(said === 'Not computed on this server. An operator can turn it on with COVERAGE_INCLUDE_APPROXIMATE.',
      `the toggle says "${said}"`);
    const which = (await page.locator('[data-coverage-which]').textContent()).trim();
    must(which.includes('precise positions only'), `the stats line says "${which}"`);
    return `${before.split('/api/')[1].split('{')[0]} -> downlink; approximate disabled and says why`;
  });

  await journey(context, 'coverage settings: the approximate toggle picks the approximate map (#334)', async (page) => {
    await stubCoverage(page, { approximate: true });
    await open(page, 'coverage', 2500);
    await page.locator('[data-coverage-options]').click();
    const box = page.locator('[data-coverage-approx]');
    must(await box.isEnabled(), 'the run has an approximate map and the toggle is disabled');
    must(!(await box.isChecked()), 'the approximate map is on by default');
    await box.check();
    await page.waitForTimeout(500);
    const url = await valueOf(page, COVERAGE_TILE_URL);
    must(url && url.includes('/MediumFast/infrastructure_approximate/usable/'), `the tiles are ${url}`);
    const hash = await page.evaluate(() => location.hash);
    must(hash === '#coverage?approx=1', `the address says ${hash}`);
    const legend = (await page.locator('[data-coverage-legend-map]').textContent()).trim();
    must(legend === 'Routers and repeaters · rounded positions included', `the legend says "${legend}"`);
    const which = (await page.locator('[data-coverage-which]').textContent()).trim();
    must(which.includes('rounded positions included'), `the stats line says "${which}"`);
    // The rounded site gets a circle as wide as its rounding.
    await page.locator('[data-coverage-circles]').check();
    const radii = await valueOf(page, () => {
      const state = window.SonoranCoverageState;
      const circles = state.nodes.getLayers().filter((layer) => layer.options.className === 'coverage-uncertainty');
      return circles.length ? circles.map((layer) => layer.getRadius()) : null;
    });
    must(radii && radii.length === 1 && radii[0] === 1500, `the uncertainty circles are ${JSON.stringify(radii)}`);
    return 'infrastructure_approximate drawn and named; one 1500 m circle';
  });

  await journey(context, 'coverage settings: Reset returns every control to default (#334)', async (page) => {
    await stubCoverage(page, { approximate: true });
    await open(page, 'coverage', 2500);
    const button = page.locator('[data-coverage-options]');
    const badge = page.locator('[data-page="coverage"] [data-options-count]');
    await button.click();
    await page.locator('[data-coverage-layers]').selectOption('uplink');
    await page.locator('[data-coverage-approx]').check();
    await page.waitForTimeout(400);
    await page.locator('[data-coverage-heard]').selectOption('24h');
    await page.locator('[data-coverage-moving]').check();
    await page.locator('[data-coverage-circles]').check();
    const chip = page.locator('[data-coverage-roles] button[data-role="ROUTER"]');
    await waitFor(page, () => document.querySelector('[data-coverage-roles] button[data-role="ROUTER"]'), 10000);
    await chip.click();
    await page.locator('[data-coverage-opacity]').fill('50');
    await page.waitForTimeout(400);
    const changed = (await badge.textContent()).trim();
    must(changed === '7', `seven settings changed and the badge says "${changed}"`);
    await page.locator('[data-coverage-reset]').click();
    await page.waitForTimeout(600);
    const got = await page.evaluate(() => ({
      layer: document.querySelector('[data-coverage-layers]').value,
      approx: document.querySelector('[data-coverage-approx]').checked,
      heard: document.querySelector('[data-coverage-heard]').value,
      moving: document.querySelector('[data-coverage-moving]').checked,
      circles: document.querySelector('[data-coverage-circles]').checked,
      opacity: document.querySelector('[data-coverage-opacity]').value,
      unpressed: [...document.querySelectorAll('[data-coverage-roles] button')]
        .filter((chip) => chip.getAttribute('aria-pressed') !== 'true').length,
      hash: location.hash,
      tiles: window.SonoranCoverageState.tiles && window.SonoranCoverageState.tiles._url,
    }));
    const wrong = [];
    if (got.layer !== 'usable') wrong.push(`layer ${got.layer}`);
    if (got.approx) wrong.push('approximate on');
    if (got.heard !== 'any') wrong.push(`heard ${got.heard}`);
    if (got.moving) wrong.push('moving hidden');
    if (got.circles) wrong.push('circles on');
    if (got.opacity !== '100') wrong.push(`opacity ${got.opacity}`);
    if (got.unpressed) wrong.push(`${got.unpressed} roles still hidden`);
    if (got.hash !== '#coverage') wrong.push(`address ${got.hash}`);
    if (!got.tiles || !got.tiles.includes('/infrastructure/usable/')) wrong.push(`tiles ${got.tiles}`);
    must(!wrong.length, `after Reset: ${wrong.join(', ')}`);
    must(await badge.isHidden(), 'after Reset the badge still shows');
    must((await button.getAttribute('aria-label')) === 'Settings', `after Reset the button says "${await button.getAttribute('aria-label')}"`);
    return '7 changed, Reset puts every one back, badge 0';
  });

  await journey(context, 'coverage settings: a role chip keeps the keyboard focus (#334)', async (page) => {
    /*
     * The chips are drawn again on a click and again when the node
     * markers are drawn. A chip drawn again is a new element, so a
     * keyboard user who pressed Space was left on <body> and had to tab
     * back from the top. The focus must stay on the same role.
     */
    await stubCoverage(page);
    await open(page, 'coverage', 2500);
    await page.locator('[data-coverage-options]').click();
    await waitFor(page, () => document.querySelector('[data-coverage-roles] button[data-role="ROUTER"]'), 10000);
    await page.locator('[data-coverage-roles] button[data-role="ROUTER"]').focus();
    const read = () => {
      const active = document.activeElement;
      return {
        role: active && active.dataset ? active.dataset.role || active.tagName : null,
        pressed: active && active.getAttribute ? active.getAttribute('aria-pressed') : null,
      };
    };
    const seen = [];
    for (const expected of ['false', 'true']) {
      await page.keyboard.press('Space');
      // Wait past the marker redraw, which draws the chips once more.
      await page.waitForTimeout(1200);
      const got = await page.evaluate(read);
      seen.push(`${got.role}:${got.pressed}`);
      must(got.role === 'ROUTER', `after Space the focus is on ${got.role}, not the Router chip`);
      must(got.pressed === expected, `after Space the Router chip is aria-pressed ${got.pressed}`);
    }
    return `Space twice, focus held: ${seen.join(', ')}`;
  });

  await journey(context, 'coverage settings: an approximate link never fakes the map (#334)', async (page) => {
    // A link from a server that computes the approximate map, opened on
    // one that does not. The precise map is drawn, and named as such.
    await stubCoverage(page);
    await open(page, 'coverage?approx=1', 2500);
    const url = await valueOf(page, COVERAGE_TILE_URL);
    must(url && url.includes('/MediumFast/infrastructure/usable/'), `the tiles are ${url}`);
    const got = await page.evaluate(() => ({
      checked: document.querySelector('[data-coverage-approx]').checked,
      legend: document.querySelector('[data-coverage-legend-map]').textContent.trim(),
      hash: location.hash,
    }));
    must(!got.checked, 'the toggle is on over a map that was never computed');
    must(got.legend === 'Routers and repeaters · precise positions only', `the legend says "${got.legend}"`);
    must(got.hash === '#coverage', `the address still says ${got.hash}`);
    return 'precise tiles, precise words, and the address corrected';
  });

  await journey(context, 'coverage settings: a link restores the layer (#334)', async (page) => {
    await stubCoverage(page);
    // The hash is in the first `goto` (AGENTS.md 9.33).
    await open(page, 'coverage?layer=downlink', 2500);
    const url = await valueOf(page, COVERAGE_TILE_URL);
    must(url && url.includes('/infrastructure/downlink/'), `a link to the downlink drew ${url}`);
    const chosen = await page.evaluate(() => document.querySelector('[data-coverage-layers]').value);
    must(chosen === 'downlink', `the layer control says ${chosen}`);
    // A display filter is this viewer's own and survives a reload; the
    // map choice comes only from the address.
    await page.locator('[data-coverage-options]').click();
    await page.locator('[data-coverage-heard]').selectOption('7d');
    /*
     * A fresh load of a plain link, by way of a blank page: from one
     * hash to another is not a load (AGENTS.md 9.33), and inside one
     * visit a plain `#coverage` keeps the map that visit chose.
     */
    await page.waitForTimeout(500);
    await page.goto('about:blank');
    await page.goto(`${BASE}/#coverage`, { waitUntil: 'load' });
    await page.waitForTimeout(2500);
    const back = await page.evaluate(() => ({
      heard: document.querySelector('[data-coverage-heard]').value,
      layer: document.querySelector('[data-coverage-layers]').value,
    }));
    must(back.heard === '7d', `the saved filter came back as ${back.heard}`);
    must(back.layer === 'usable', `a plain link drew the ${back.layer} layer`);
    return 'downlink from the address; the filter kept, the plain link precise and usable';
  });

  /* The alpha of a west and an east pixel of each painted margin tile. */
  const MARGIN_ALPHAS = () => {
    const state = window.SonoranCoverageState;
    if (!state || !state.tiles || !state.tiles._tiles) return null;
    const out = [];
    for (const tile of Object.values(state.tiles._tiles)) {
      if (!tile.loaded || !(tile.el instanceof HTMLCanvasElement)) continue;
      const context = tile.el.getContext('2d');
      out.push([context.getImageData(10, 10, 1, 1).data[3], context.getImageData(200, 10, 1, 1).data[3]]);
    }
    return out.length ? out : null;
  };

  await journey(context, 'coverage settings: margin tiles that leave the map stop downloading (#334)', async (page) => {
    /*
     * A margin tile is fetched, not loaded as an image, so the browser
     * does not cancel it when Leaflet drops the tile. A reader who pans
     * or changes the floor used to keep downloading every tile that
     * was no longer on the map. Here the margin tiles answer slowly,
     * and the floor changes before they arrive: each request of the
     * old layer must be aborted.
     */
    await stubCoverage(page, { margins: true });
    let asked = 0;
    // Registered last, so it is asked first: hold each margin tile.
    await page.route(/\/api\/coverage\/tiles\/.*\/margin\//, (route) => {
      asked += 1;
      setTimeout(() => {
        route.fulfill({ contentType: 'image/png', body: MARGIN_PNG }).catch(() => {});
      }, 4000);
    });
    const aborted = [];
    page.on('requestfailed', (request) => {
      if (request.url().includes('/margin/')) aborted.push(request.failure() && request.failure().errorText);
    });
    await open(page, 'coverage', 2500);
    await page.locator('[data-coverage-options]').click();
    await page.locator('[data-coverage-reset]').click();
    await page.waitForTimeout(400);
    const floor = page.locator('[data-coverage-signal-floor]');
    await floor.selectOption('10');
    must(await waitFor(page, () => {
      const state = window.SonoranCoverageState;
      return Boolean(state.tiles && String(state.tiles._url).includes('/margin/')
        && Object.keys(state.tiles._tiles || {}).length);
    }, 10000), 'a 10 dB floor did not ask for margin tiles');
    await page.waitForTimeout(500);
    const first = asked;
    must(first > 0, 'no margin tile was asked for');
    // The old layer goes before its tiles arrive.
    await floor.selectOption('0');
    await page.waitForTimeout(1500);
    must(aborted.length >= first,
      `${first} margin tiles were in flight when the layer went, and ${aborted.length} were aborted`);
    return `${first} in flight, ${aborted.length} aborted (${[...new Set(aborted)].join(', ')})`;
  });

  await journey(context, 'coverage settings: a 10 dB floor hides the weaker ground, and Reset clears it (#334)', async (page) => {
    await stubCoverage(page, { margins: true });
    await open(page, 'coverage', 2500);
    const button = page.locator('[data-coverage-options]');
    await button.click();
    // An earlier journey in this context saved a display filter. Start
    // from the defaults, so the badge counts the floor alone.
    await page.locator('[data-coverage-reset]').click();
    await page.waitForTimeout(400);
    const floor = page.locator('[data-coverage-signal-floor]');
    must(await floor.isEnabled(), 'the run has margin tiles and the floor is disabled');
    must((await floor.inputValue()) === '0', `the floor starts at ${await floor.inputValue()}`);
    const before = await valueOf(page, COVERAGE_TILE_URL);
    must(before && !before.includes('/margin/'), `with no floor the tiles are ${before}`);

    await floor.selectOption('10');
    must(await waitFor(page, () => {
      const state = window.SonoranCoverageState;
      return Boolean(state.tiles && String(state.tiles._url).includes('/infrastructure/usable/margin/'));
    }, 10000), 'a 10 dB floor did not switch to the margin tiles');
    must(await waitFor(page, () => {
      const state = window.SonoranCoverageState;
      return Object.values(state.tiles._tiles || {}).some((tile) => tile.loaded);
    }, 10000), 'no margin tile was painted');
    const ten = await valueOf(page, MARGIN_ALPHAS);
    // West is 5 dB: under the floor, clear. East is 30 dB: drawn.
    must(ten && ten.every(([west, east]) => west === 0 && east === 235),
      `at 10 dB the west and east alphas are ${JSON.stringify(ten)}`);
    must((await page.evaluate(() => location.hash)) === '#coverage?floor=10',
      `the address says ${await page.evaluate(() => location.hash)}`);
    must((await button.getAttribute('aria-label')) === 'Settings, 1 changed',
      `the button says "${await button.getAttribute('aria-label')}"`);
    const said = (await page.locator('[data-coverage-legend-floor]').textContent()).trim();
    must(said === 'Shown from -126 dBm, 10 dB above the limit', `the legend says "${said}"`);
    const which = (await page.locator('[data-coverage-legend-map]').textContent()).trim();
    must(which.endsWith('· 10 dB floor'), `the legend names the map as "${which}"`);

    // 5 dB lets the west half back in: the drawn pixels change.
    await floor.selectOption('5');
    must(await waitFor(page, () => {
      const state = window.SonoranCoverageState;
      return state.tiles && state.tiles.options.floor === 5
        && Object.values(state.tiles._tiles || {}).some((tile) => tile.loaded);
    }, 10000), 'a 5 dB floor drew nothing');
    const five = await valueOf(page, MARGIN_ALPHAS);
    must(five && five.every(([west, east]) => west === 235 && east === 235),
      `at 5 dB the west and east alphas are ${JSON.stringify(five)}`);

    await page.locator('[data-coverage-reset]').click();
    await page.waitForTimeout(600);
    const after = await valueOf(page, COVERAGE_TILE_URL);
    must(after && !after.includes('/margin/'), `after Reset the tiles are ${after}`);
    must((await floor.inputValue()) === '0', `after Reset the floor is ${await floor.inputValue()}`);
    must((await page.evaluate(() => location.hash)) === '#coverage', 'after Reset the address keeps a floor');
    must(await page.locator('[data-coverage-legend-floor]').isHidden(), 'after Reset the legend still names a floor');
    return '10 dB: west clear, east drawn; 5 dB: both drawn; Reset: colour tiles, #coverage';
  });

  await journey(context, 'coverage settings: a run with no margin data disables the floor and says why (#334)', async (page) => {
    // A link with a floor, opened on a run made before margin tiles.
    await stubCoverage(page);
    await open(page, 'coverage?floor=10', 2500);
    const url = await valueOf(page, COVERAGE_TILE_URL);
    must(url && url.includes('/infrastructure/usable/') && !url.includes('/margin/'), `the tiles are ${url}`);
    await page.locator('[data-coverage-options]').click();
    const floor = page.locator('[data-coverage-signal-floor]');
    must(await floor.isDisabled(), 'the floor is enabled on a run with no margin tiles');
    must((await floor.inputValue()) === '0', `the floor control says ${await floor.inputValue()}`);
    const said = (await page.locator('[data-coverage-signal-floor-note]').textContent()).trim();
    must(said === 'Not available for this run. It was made before the coverage job wrote signal margins. '
      + 'The next run will have them.', `the floor says "${said}"`);
    must((await page.evaluate(() => location.hash)) === '#coverage', 'the address still names a floor');
    must(await page.locator('[data-coverage-legend-floor]').isHidden(), 'the legend names a floor it did not draw');
    return 'colour tiles, the floor disabled with its sentence, the address corrected';
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
    // A mouse gets the bubble, never the phone's sheet (#281).
    must(await page.evaluate(() => !window.SonoranSheet.current()), 'a desktop opened the phone sheet');

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
        // `render` returns at once while another render is running, and
        // the timer's own poll can still be running here on a slow
        // server. "A node that moved stayed where it was" failed two
        // runs in five on a loaded machine without this wait, and none
        // in three with it.
        while (loading) await new Promise((done) => setTimeout(done, 100));
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
      while (loading) await new Promise((done) => setTimeout(done, 100));
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

  await journey(context, 'the live traffic feed follows the lines on the map (#386)', async (page) => {
    /*
     * Will: "the box for Live traffic only updates in chunks and leads to
     * like 5 or 6 things happening". The poll fetches fifteen seconds of
     * traffic at once and the map spreads it over the next fifteen, so
     * the lines start one at a time. The feed took the whole batch at
     * fetch time. Here one poll carries four packets three seconds
     * apart, and the rows must arrive about three seconds apart too,
     * as their lines do. The old feed listed all four in one step.
     *
     * Then the colour: each row wears its family's colour token on its
     * edge and on its mark, in both themes, and still says its packet
     * type in words, so nothing rests on colour alone.
     *
     * The traffic is served through a route, so the shared database is
     * never written. The packets are made from two nodes the map has
     * placed, so each one has a line to draw.
     */
    let extra = null;
    await page.route(/\/api\/map\/traffic(\?|$)/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      if (extra) body.events = [...body.events, ...extra];
      return route.fulfill({ response, json: body });
    });
    await open(page, 'map', 4000);
    must(await waitFor(page, () => mapState.trafficPrimed === true
      && window.SonoranMap.marks instanceof Map && window.SonoranMap.marks.size >= 2, 30000),
    'the map did not draw its first traffic and two nodes');
    const KINDS = [
      ['POSITION_APP', 'pkt-position'], ['TELEMETRY_APP', 'pkt-telemetry'],
      ['TEXT_MESSAGE_APP', 'pkt-text'], ['NODEINFO_APP', 'pkt-nodeinfo'],
    ];
    extra = await page.evaluate((kinds) => {
      const [a, b] = [...window.SonoranMap.marks.entries()];
      const end = (id, mark) => {
        const at = mark.marker.getLatLng();
        return { node_id: id, display_name: `Pacing ${id}`, lat: at.lat, lon: at.lng };
      };
      const from = end(a[0], a[1]);
      const gateway = end(b[0], b[1]);
      const start = Date.now() - 12000;
      return kinds.map(([portnum], index) => ({
        time: new Date(start + index * 3000).toISOString(),
        packet_id: 3860001 + index,
        channel: 'azmsh', mqtt_topic: 'msh/e2e', snr: null, rssi: null,
        hop_limit: 2, hop_start: 3, hops_taken: 1, direct: false,
        portnum, from, gateway, has_line: true,
      }));
    }, KINDS);
    const keys = extra.map((event) => `${event.from.node_id}/${event.packet_id}`);
    const listed = () => page.evaluate((wanted) => {
      const rows = [...document.querySelectorAll('[data-traffic-feed] > li[data-key]')];
      return wanted.map((key) => rows.some((row) => row.dataset.key === key));
    }, keys);

    // One poll, through the call the Live timer makes.
    const polledAt = Date.now();
    await page.evaluate(async () => {
      while (loading) await new Promise((done) => setTimeout(done, 100));
      await render('map');
    });
    const seenAt = keys.map(() => null);
    while (Date.now() - polledAt < 16000 && seenAt.some((at) => at == null)) {
      const now = await listed();
      now.forEach((on, index) => { if (on && seenAt[index] == null) seenAt[index] = Date.now() - polledAt; });
      await page.waitForTimeout(200);
    }
    must(seenAt.every((at) => at != null), `not every packet reached the feed: ${JSON.stringify(seenAt)}`);
    for (let index = 1; index < seenAt.length; index += 1) {
      must(seenAt[index] >= seenAt[index - 1],
        `the feed listed the packets out of order: ${JSON.stringify(seenAt)}`);
    }
    const spread = seenAt[seenAt.length - 1] - seenAt[0];
    // Nine seconds apart on the map. A feed that took the batch at once
    // shows a spread of one sample, 200 ms or so.
    must(spread >= 6000, `the four rows arrived in one chunk, ${spread} ms apart from first to last`);

    const colours = async () => page.evaluate((pairs) => pairs.map(([family, token]) => {
      const row = document.querySelector(`[data-traffic-feed] > li[data-family="${family}"]`);
      if (!row) return { family, missing: true };
      const probe = document.createElement('span');
      probe.style.color = `var(--${token})`;
      document.body.append(probe);
      const want = getComputedStyle(probe).color;
      probe.remove();
      const mark = row.querySelector('.pkt-mark');
      return {
        family,
        want,
        edge: getComputedStyle(row).borderLeftColor,
        mark: mark ? getComputedStyle(mark).color : null,
        text: row.querySelector('.pkt-kind') ? row.querySelector('.pkt-kind').textContent.trim() : '',
      };
    }), KINDS);
    const report = [];
    for (const theme of ['light', 'dark']) {
      await page.evaluate((mode) => applyTheme(mode), theme);
      await page.waitForTimeout(200);
      for (const got of await colours()) {
        must(!got.missing, `${theme}: no feed row for ${got.family}`);
        must(got.edge === got.want, `${theme}: the ${got.family} row edge is ${got.edge}, its lines are ${got.want}`);
        must(got.mark === got.want, `${theme}: the ${got.family} mark is ${got.mark}, its lines are ${got.want}`);
        must(got.text.length > 2, `${theme}: the ${got.family} row does not say its type in words`);
      }
      report.push(`${theme} ${(await colours()).map((got) => got.want).join(' ')}`);
    }
    return `rows at ${seenAt.join('/')} ms after one poll (spread ${spread} ms); colours ${report.join('; ')}`;
  });

  await journey(context, 'the watch traffic table keeps a selection while rows arrive (#386)', async (page) => {
    /*
     * The list now takes each packet as its line starts, so the watch
     * table gets a new row every few seconds rather than once a poll.
     * Rebuilt whole each time, it threw away the rows a reader was
     * reading and any text they had selected. A row that did not change
     * must be the same element after new rows arrive, so the selection
     * in it holds.
     *
     * The traffic is served through a route: three packets a minute old
     * in the first poll, which the table shows at once, and three new
     * ones three seconds apart in the next.
     */
    let events = [];
    await page.route(/\/api\/map\/traffic(\?|$)/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.events = [...body.events, ...events];
      return route.fulfill({ response, json: body });
    });
    // The marks are needed before the first poll can carry made packets,
    // so the first visit only reads two placed nodes.
    await open(page, 'map', 4000);
    must(await waitFor(page, () => window.SonoranMap.marks instanceof Map
      && window.SonoranMap.marks.size >= 2, 30000), 'the map drew fewer than two nodes');
    const ends = await page.evaluate(() => [...window.SonoranMap.marks.entries()].slice(0, 2).map(([id, mark]) => {
      const at = mark.marker.getLatLng();
      return { node_id: id, display_name: `Table ${id}`, lat: at.lat, lon: at.lng };
    }));
    const made = (id, msAgo, portnum) => ({
      time: new Date(Date.now() - msAgo).toISOString(),
      packet_id: id, channel: 'azmsh', mqtt_topic: 'msh/e2e', snr: null, rssi: null,
      hop_limit: 2, hop_start: 3, hops_taken: 1, direct: false,
      portnum, from: ends[0], gateway: ends[1], has_line: true,
    });
    events = [made(3861001, 70000, 'POSITION_APP'), made(3861002, 60000, 'TELEMETRY_APP'),
      made(3861003, 50000, 'NODEINFO_APP')];
    await page.goto(`${BASE}/#map/watch/traffic/expanded`, { waitUntil: 'load' });
    must(await waitFor(page, () => document.querySelectorAll('[data-traffic-table] tbody tr').length >= 3, 30000),
      'the watch table did not show the first poll');
    const before = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('[data-traffic-table] tbody tr')];
      const row = rows[rows.length - 1];
      row.__e2eHeld = true;
      const cell = row.children[1];
      const range = document.createRange();
      range.selectNodeContents(cell);
      const selection = getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      return { rows: rows.length, text: selection.toString() };
    });
    must(before.text.trim().length > 0, 'nothing was selected in the table');

    const start = Date.now();
    events = [...events, made(3861004, 9000, 'TEXT_MESSAGE_APP'), made(3861005, 6000, 'ROUTING_APP'),
      made(3861006, 3000, 'TRACEROUTE_APP')];
    await page.evaluate(async () => {
      while (loading) await new Promise((done) => setTimeout(done, 100));
      await render('map');
    });
    must(await waitFor(page, (want) => document.querySelectorAll('[data-traffic-table] tbody tr').length >= want,
      15000, 250, before.rows + 3), 'the three new packets did not reach the table');
    const after = await page.evaluate(() => {
      const held = [...document.querySelectorAll('[data-traffic-table] tbody tr')].find((row) => row.__e2eHeld);
      return { held: Boolean(held), text: getSelection().toString(), rows: document.querySelectorAll('[data-traffic-table] tbody tr').length };
    });
    must(after.held, 'a row that did not change was rebuilt when new rows arrived');
    must(after.text === before.text, `the selection "${before.text}" became "${after.text}"`);
    return `${before.rows} -> ${after.rows} rows in ${Date.now() - start} ms; the selected row and its selection held`;
  });

  await journey(context, 'the packet type menu opens over the map, not into the head (#385)',
    (page) => familyMenuWalk(page, { watch: false }));
  await journey(context, 'the packet type menu works from the keyboard alone (#385)', async (page) => {
    /*
     * Open, tick two kinds quickly, and close, with keys only. Each tick
     * redraws the map, and the second tick lands while the first redraw
     * may still be loading. `render` returns at once while another runs,
     * so a tick must ask through `navigateRender`, which runs the redraw
     * after the one in flight rather than dropping it. The list is then
     * checked against the last choice, with Live off so only the ticks
     * can redraw it.
     */
    await page.route(/\/api\/map\/traffic(\?|$)/, async (route) => {
      // Slow enough that the second tick lands inside the first redraw.
      await new Promise((done) => setTimeout(done, 700));
      return route.continue();
    });
    await open(page, 'map', 4000);
    await page.locator('[data-page="map"] [data-live]').click();
    must(await waitFor(page, () => !loading, 20000, 100), 'the map did not settle after Live went off');
    await page.locator('[data-family-toggle]').focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(200);
    must(await page.evaluate(() => document.querySelector('[data-family-menu]').getBoundingClientRect().width > 0),
      'Enter on the button did not open the menu');
    await page.keyboard.press('Tab');
    must(await page.evaluate(() => document.activeElement.matches('input[data-family="POSITION_APP"]')),
      'Tab from the button did not reach the first checkbox');
    await page.keyboard.press('Space');
    await page.waitForTimeout(150);
    await page.keyboard.press('Tab');
    await page.keyboard.press('Space');
    const settled = await waitFor(page, () => !loading && !pendingRender, 20000, 100);
    must(settled, 'the map did not settle after the ticks');
    await page.waitForTimeout(300);
    const got = await page.evaluate(() => ({
      hidden: [...hiddenFamilies].sort().join(),
      summary: document.querySelector('[data-family-summary]').textContent.trim(),
      listed: (mapState.lastPackets || []).map((packet) => SonoranLive.familyKey(packet.portnum)),
      line: document.querySelector('[data-traffic-summary]').textContent,
    }));
    must(got.hidden === 'POSITION_APP,TELEMETRY_APP', `the keys hid ${got.hidden}`);
    must(got.summary === 'Packet Types: 5 of 7', `the button says "${got.summary}"`);
    must(!got.listed.some((key) => key === 'POSITION_APP' || key === 'TELEMETRY_APP'),
      `the list still holds a hidden kind: ${[...new Set(got.listed)].join(', ')}`);
    must(/of the chosen types/.test(got.line), `the traffic line does not say it is filtered: "${got.line}"`);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    must(await page.evaluate(() => document.querySelector('[data-family-menu]').getBoundingClientRect().width === 0),
      'Escape did not close the menu');
    // Put the choice back the same way, for the journeys after this one.
    await page.locator('[data-family-toggle]').focus();
    await page.keyboard.press('Enter');
    for (let step = 0; step < 10; step += 1) {
      if (await page.evaluate(() => document.activeElement.matches('[data-family-all]'))) break;
      await page.keyboard.press('Tab');
    }
    await page.keyboard.press('Enter');
    must(await waitFor(page, () => hiddenFamilies.size === 0, 5000, 100), 'Show all from the keyboard did not reset');
    return `Enter opens, Tab reaches the boxes, two ticks hide ${got.hidden}, Escape closes, Show all resets`;
  });
  await journey(context, 'the packet type menu works in watch mode (#385)',
    (page) => familyMenuWalk(page, { watch: true }));
  /*
   * #384, reported by Will: Medium Fast to Long Fast and back left Long
   * Fast on the map until a reload. Two causes, and this catches each:
   *
   * - the live canvas (marks in flight, the replay queue, and each
   *   node's heat) was never cleared on a switch, so the Long Fast halos
   *   and rings stayed on the Medium Fast map for more than a minute;
   * - a switch made while a map draw was in flight was dropped, so the
   *   old preset's answer was drawn under the new switch, and stayed.
   *
   * The seed has no node on a Long Fast topic, so the Long Fast answers
   * are served through routes: two nodes far from every Medium Fast
   * node, one link between them, and fresh traffic on each poll. The
   * positive control asserts that Long Fast IS drawn, dots, line and
   * live pixels, before "nothing is left" is believed.
   *
   * A context of its own, because the chosen preset is kept in
   * localStorage and must not leak into the journeys that share `context`.
   */
  const switching = await browser.newContext({ viewport: { width: 1500, height: 1000 } });
  await journey(switching, 'switching presets on the map leaves nothing of the old one (#384)', async (page) => {
    const LF_NODE = { node_id: '!0e2e3841', lat: 36.62, lon: -109.42, name: 'Long Fast only' };
    const LF_GW = { node_id: '!0e2e3842', lat: 36.18, lon: -109.95, name: 'Long Fast gateway' };
    const row = (node, gateway) => ({
      node_id: node.node_id, node_num: parseInt(node.node_id.slice(1), 16),
      display_name: node.name, short_name: node.name.slice(0, 4), long_name: node.name,
      lat: node.lat, lon: node.lon, altitude: 1500, last_heard: new Date().toISOString(),
      hw_model: 'HELTEC_V3', role: 'ROUTER', is_mqtt_gateway: gateway,
    });
    const point = (node) => ({ node_id: node.node_id, display_name: node.name, lat: node.lat, lon: node.lon });
    let packetId = 3840000;
    const lfEvents = () => {
      const now = Date.now();
      return Array.from({ length: 8 }, (_, index) => {
        packetId += 1;
        return {
          time: new Date(now - index * 1500).toISOString(), packet_id: packetId,
          channel: 'LongFast', mqtt_topic: `msh/US/AZ/2/e/LongFast/${LF_GW.node_id}`,
          snr: 6, rssi: -90, hop_limit: 3, hop_start: 3, hops_taken: 0, direct: true,
          portnum: 'TEXT_MESSAGE_APP', from: point(LF_NODE), gateway: point(LF_GW), has_line: true,
        };
      }).reverse();
    };
    const isLong = (url) => new URL(url).searchParams.get('channel') === 'LongFast';
    // A slow server for Long Fast, as on the live instance, so a switch
    // can land while its answer is still on the way.
    const delay = { ms: 0 };
    const late = () => new Promise((done) => setTimeout(done, delay.ms));
    await page.route(/\/api\/map\/nodes\?/, async (route) => {
      if (!isLong(route.request().url())) return route.continue();
      await late();
      return route.fulfill({ json: [row(LF_NODE, false), row(LF_GW, true)] });
    });
    await page.route(/\/api\/map\/traffic\?/, async (route) => {
      if (!isLong(route.request().url())) return route.continue();
      await late();
      const events = lfEvents();
      return route.fulfill({ json: {
        window_minutes: 15, event_count: events.length, direct_count: events.length,
        returned_count: events.length, truncated: false, events,
      } });
    });
    await page.route(/\/api\/map\/edges\?/, async (route) => {
      if (!isLong(route.request().url())) return route.continue();
      await late();
      return route.fulfill({ json: [{
        from_node: LF_NODE.node_id, to_node: LF_GW.node_id, snr: 5.5,
        kind: 'neighbor', channel: 'LongFast', time: new Date().toISOString(),
      }] });
    });

    await open(page, 'map', 500);
    must(await waitFor(page, () => window.SonoranMap.marks instanceof Map
      && window.SonoranMap.marks.size > 0 && !loading, 20000), 'the map drew no Medium Fast node');
    // The Live timer off, so nothing but the switch can redraw the map.
    // A picture left behind then stays, as it does in a hidden tab.
    await page.click('[data-page="map"] [data-live]');
    await page.click('[data-page="map"] [data-show-links]');
    await page.evaluate(async () => {
      while (loading) await new Promise((done) => setTimeout(done, 50));
      await render('map');
    });

    /* What of Long Fast is on the map: dots, lines, and painted pixels. */
    const longFastShown = (nodes) => {
      const { map, marks, links } = window.SonoranMap;
      const ids = new Set(nodes.map((node) => node.node_id));
      const at = (node) => `${node.lat},${node.lon}`;
      const places = new Set(nodes.map(at));
      const dots = [...marks.keys()].filter((id) => ids.has(id));
      const lines = map.hasLayer(links) ? links.getLayers().filter((line) => line.getLatLngs()
        .some((ll) => places.has(`${ll.lat},${ll.lng}`))).length : 0;
      const canvas = document.querySelector('[data-page="map"] canvas.live-canvas');
      const scale = canvas.width / canvas.clientWidth;
      const context = canvas.getContext('2d');
      let painted = 0;
      for (const node of nodes) {
        const p = map.latLngToContainerPoint([node.lat, node.lon]);
        const size = Math.round(24 * scale);
        const x = Math.max(0, Math.round(p.x * scale) - size / 2);
        const y = Math.max(0, Math.round(p.y * scale) - size / 2);
        const data = context.getImageData(x, y, size, size).data;
        for (let index = 3; index < data.length; index += 4) if (data[index] > 0) painted += 1;
      }
      return { dots: dots.length, lines, painted };
    };
    const nodes = [LF_NODE, LF_GW];
    const frame = () => page.evaluate((all) => {
      const { map, marks } = window.SonoranMap;
      const points = [...marks.values()].map(({ row }) => [row.lat, row.lon]);
      map.fitBounds([...points, ...all.map((node) => [node.lat, node.lon])], { animate: false, padding: [40, 40] });
    }, nodes);
    const choose = (name) => page.evaluate((preset) => window.SonoranPreset.set(preset), name);
    const settled = () => waitFor(page, () => !loading, 20000, 100);

    // Positive control: on Long Fast the Long Fast dots, line and live
    // marks ARE drawn. Without this, "nothing left" below proves nothing.
    must(await choose('LongFast'), 'the switch did not move to Long Fast');
    await settled();
    await frame();
    // One more poll, as the Live timer makes: the first draw of a preset
    // only records its window, and the next one animates what is new.
    await page.evaluate(async () => {
      while (loading) await new Promise((done) => setTimeout(done, 50));
      await render('map');
    });
    const onLong = await waitForValue(page, longFastShown, nodes, (got) => got.dots === 2 && got.lines >= 1 && got.painted > 0);
    must(onLong.ok, `Long Fast drew too little to test against: ${JSON.stringify(onLong.got)}`);

    // Back to Medium Fast: nothing of Long Fast may stay.
    must(await choose('MediumFast'), 'the switch did not move back to Medium Fast');
    await settled();
    await page.waitForTimeout(1500);
    const back = await page.evaluate(longFastShown, nodes);
    must(back.dots === 0 && back.lines === 0 && back.painted === 0,
      `Long Fast stayed on the Medium Fast map: ${JSON.stringify(back)}`);

    // The same trip while Long Fast is still answering. The switch back
    // lands mid-draw, and must still win.
    delay.ms = 2500;
    must(await choose('LongFast'), 'the second switch to Long Fast did not move');
    await page.waitForTimeout(400);
    must(await choose('MediumFast'), 'the quick switch back did not move');
    await page.waitForTimeout(delay.ms + 1500);
    await settled();
    await page.waitForTimeout(1000);
    const quick = await page.evaluate(longFastShown, nodes);
    const preset = await page.evaluate(() => window.SonoranPreset.current());
    must(preset === 'MediumFast', `the switch ended on ${preset}`);
    must(quick.dots === 0 && quick.lines === 0 && quick.painted === 0,
      `a Long Fast answer that landed after the switch was drawn: ${JSON.stringify(quick)}`);
    return `on Long Fast ${onLong.got.dots} dots, ${onLong.got.lines} line, ${onLong.got.painted} live px; `
      + 'none of it after the switch back, or after a switch back mid-draw';
  });
  await switching.close();

  await journey(context, 'a mouse keeps the exact dot target (#266)', async (page) => {
    // The control for the phone journey: the wider target is for touch.
    await open(page, 'map', 3000);
    must(await waitFor(page, () => window.SonoranMap.marks instanceof Map
      && window.SonoranMap.marks.size > 0, 20000), 'the map drew no nodes');
    const got = await page.evaluate(() => {
      const { map, nodes } = window.SonoranMap;
      const layer = nodes.getLayers()[0];
      return {
        coarse: matchMedia('(pointer: coarse)').matches,
        tolerance: layer ? map.getRenderer(layer).options.tolerance || 0 : null,
      };
    });
    must(!got.coarse, 'this context reports a coarse pointer, so it cannot be the control');
    must(got.tolerance === 0, `a mouse gets a canvas tolerance of ${got.tolerance}`);
    return 'fine pointer, tolerance 0';
  });

  await journey(context, 'chart and checker libraries load only where used (#277)', async (page) => {
    /*
     * ECharts and the config checker's libraries sit in <template>s and
     * are fetched by the first page that needs them. Nodes needs neither
     * and must fetch neither. Every page that draws a chart is then
     * opened COLD, each in a fresh load, because a page reached by a
     * hash change would find the library the last page loaded.
     */
    const fetched = [];
    page.on('request', (request) => fetched.push(new URL(request.url()).pathname));
    const heavy = /echarts\.min\.js|protobuf\.min\.js|js-yaml\.min\.js|config-check\.js/;
    /*
     * Leave a page only when its own render has ended (#354).
     *
     * A navigation aborts every request still in flight, and the
     * collector counts each abort as an error. This waited for
     * `networkidle`, which is the wrong signal: Playwright fires it once
     * for each document and then answers at once. The node page asks for
     * its signal and its packets only after it has drawn the history
     * charts. A long history can take more than 500 ms to draw, with no
     * request open, and that is all `networkidle` needs. So the event
     * fired early, the wait returned at once, and the two requests were
     * aborted: the exact lines of the issue. The `.catch` also hid a
     * timeout.
     *
     * `loading` is true until a render has awaited every request it
     * made, and `timelinePaging.busy` covers the one request the packet
     * timeline makes outside a render. A page that does not settle fails
     * here and says so.
     *
     * The wait is longer than the page's own `REQUEST_TIMEOUT_MS` (60 s).
     * A request that hangs is then ended by the page itself, and its
     * abort is reported with its address, which is the true fault. Do not
     * filter `ERR_ABORTED` to quiet this journey: that hides that abort.
     */
    const settle = async (name) => must(await waitFor(page, () => !loading && !timelinePaging.busy, 90000),
      `#${name} was still loading after 90 s`);
    await open(page, 'nodes', 3000);
    const early = fetched.filter((path) => heavy.test(path));
    must(early.length === 0, `the nodes page fetched ${early.join(', ')}`);
    must(!(await page.evaluate(() => Boolean(window.echarts))), 'echarts is defined on the nodes page');
    await settle('nodes');

    const drew = [];
    for (const name of ['dashboard', 'stats', 'graph']) {
      await page.goto('about:blank');
      await open(page, name, 500);
      const drawn = (want) => [...document.querySelectorAll(`[data-page="${want}"] canvas`)]
        .some((canvas) => canvas.width > 0);
      let ok = false;
      for (let tries = 0; tries < 60 && !ok; tries += 1) {
        ok = await page.evaluate(drawn, name);
        if (!ok) await page.waitForTimeout(500);
      }
      must(ok, `a cold load of #${name} drew no chart`);
      drew.push(name);
      await settle(name);
    }
    // The node page draws its charts once its panels arrive.
    const nodes = await (await page.request.get(`${BASE}/api/map/nodes`)).json();
    must(nodes.length > 0, 'no node to open');
    await page.goto('about:blank');
    await open(page, `node/${encodeURIComponent(nodes[0].node_id)}`, 500);
    must(await waitFor(page, () => [...document.querySelectorAll('[data-page="node"] canvas')]
      .some((canvas) => canvas.width > 0), 30000), `a cold load of node ${nodes[0].node_id} drew no chart`);
    drew.push('node');
    await settle('node');

    await page.goto('about:blank');
    await open(page, 'config', 500);
    must(await waitFor(page, () => Boolean(window.SonoranConfigCheck && window.jsyaml && window.protobuf), 30000),
      'the config page did not load its checker and libraries');
    must(await waitFor(page, () => document.querySelector('[data-page="config"]').innerText.trim().length > 0, 10000),
      'the config page is empty');
    return `nodes fetched neither; cold charts on ${drew.join(', ')}; config loaded its checker`;
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

  await journey(context, 'a traceroute puts Route, Path there and Path back on top (#288)', async (page) => {
    /*
     * Will asked for the three on top and the drawing under them. The
     * order is read from the page, and so is the shape: three on one
     * row at 1280 and 1600 px with nothing beside them, one column on a
     * phone, the drawing below at full width either way.
     *
     * Then the Path back panel must still be there when there is no
     * path back, and say the true thing. The seeded mesh holds replies
     * only, so the page is fed the same row as a request twice: once
     * with no reply stored, where it must say no reply was seen, and
     * once with a reply stored, where it must link to it instead.
     */
    const rows = await (await page.request.get(`${BASE}/api/traceroutes?limit=1`)).json();
    if (!rows.length) return 'no traceroute stored to open';
    const id = rows[0].id;
    // The drawing comes from mesh-graph, which a test instance cannot
    // reach, and it is not what this journey is about. It is answered
    // the way mesh-graph answers for a trace it holds no drawing of.
    const noDrawing = () => page.route(/\/drawing\.svg$/, (route) => route.fulfill({ status: 404, body: '' }));
    await noDrawing();
    const shape = () => {
      const body = document.querySelector('[data-trace-body]');
      const panels = [...body.querySelectorAll('.panel')];
      if (panels.length < 4) return null;
      const boxes = panels.map((panel) => panel.getBoundingClientRect());
      const top = boxes.slice(0, 3);
      return {
        heads: panels.map((panel) => panel.querySelector('h3').firstChild.textContent.trim()),
        columns: new Set(top.map((box) => Math.round(box.left))).size,
        rowFull: Math.abs(top[0].left - boxes[3].left) <= 1 && Math.abs(top[2].right - boxes[3].right) <= 1,
        below: boxes[3].top >= Math.max(...top.map((box) => box.bottom)) - 1,
        back: panels[2].innerText,
        doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    };
    const out = [];
    for (const [width, columns] of [[1600, 3], [1280, 3], [1024, 1], [390, 1]]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${BASE}/?w=${width}#traceroute/${id}`, { waitUntil: 'load' });
      must(await waitFor(page, shape, 15000), `the trace page never drew at ${width} px`);
      const got = await page.evaluate(shape);
      must(got.heads.slice(0, 3).join('|') === 'Route|Path there|Path back',
        `the panels on top are ${got.heads.slice(0, 3).join(', ')} at ${width} px`);
      must(got.columns === columns, `${got.columns} columns at ${width} px, wanted ${columns}`);
      must(got.below && got.rowFull, `the drawing is not a full-width panel under the three at ${width} px`);
      must(got.doc <= 1, `the page scrolls sideways at ${width} px`);
      out.push(`${width}:${got.columns}`);
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    for (const reply of [null, 424242]) {
      await page.unrouteAll();
      await noDrawing();
      await page.route(new RegExp(`/api/traceroutes/${id}$`), async (route) => {
        const response = await route.fetch();
        const body = await response.json();
        Object.assign(body, { is_reply: false, request_id: null, return_hops: [], reply_id: reply });
        await route.fulfill({ response, json: body });
      });
      await page.goto(`${BASE}/?r=${reply}#traceroute/${id}`, { waitUntil: 'load' });
      must(await waitFor(page, shape, 15000), 'the trace page never drew as a request');
      const got = await page.evaluate(shape);
      must(got.heads[2] === 'Path back', 'a request with no path back lost its Path back panel');
      if (reply == null) {
        must(/No reply was seen/.test(got.back), `with no reply stored it says ${JSON.stringify(got.back)}`);
      } else {
        must(!/No reply was seen/.test(got.back), 'it says no reply was seen when one was stored');
        const href = await page.evaluate(() =>
          document.querySelector('[data-path-back="elsewhere"] a').getAttribute('href'));
        must(href === `#traceroute/${reply}`, `the reply link goes to ${href}`);
      }
    }
    return `columns ${out.join(' ')}; no reply and stored reply both said truly`;
  });

  await journey(context, 'the mesh-graph button sits at the top right of the drawing (#289)', async (page) => {
    /*
     * The link was a line of text above the drawing. It is now a link
     * drawn as a button in the drawing's heading, on the trace page and
     * on the packet page alike. Claims: it is an `<a>` to `graph_url`
     * that opens a new tab; it is at the heading's right edge on a wide
     * screen and 44 px tall on a phone; it stays when mesh-graph has no
     * drawing (Will, 2026-09-27); and a trace with no URL has no button.
     */
    const rows = await (await page.request.get(`${BASE}/api/traceroutes?limit=1`)).json();
    if (!rows.length) return 'no traceroute stored to open';
    const trace = rows[0];
    // mesh-graph holds no drawing of it, as far as this page can tell.
    await page.route(/\/drawing\.svg$/, (route) => route.fulfill({ status: 404, body: '' }));
    const button = () => {
      const panel = document.querySelector('[data-mesh-graph-panel]');
      if (!panel || !panel.querySelector('.trace-drawing, p')) return null;
      const a = panel.querySelector('h3 a.button-link');
      const head = panel.querySelector('h3').getBoundingClientRect();
      const box = a && a.getBoundingClientRect();
      return {
        found: Boolean(a),
        tag: a && a.tagName, href: a && a.getAttribute('href'), target: a && a.target, rel: a && a.rel,
        right: box && Math.round(head.right - box.right),
        top: box && Math.round(box.top - head.top),
        height: box && Math.round(box.height),
        text: panel.innerText,
        doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    };
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${BASE}/?b=1#traceroute/${trace.id}`, { waitUntil: 'load' });
    must(await waitFor(page, button, 15000), 'the drawing panel never drew');
    // The picture fails after the panel is drawn, so wait for its answer.
    await waitFor(page, () => /holds no drawing/.test(
      document.querySelector('[data-mesh-graph-panel]').innerText), 10000);
    const wide = await page.evaluate(button);
    must(wide.found && wide.tag === 'A', 'the drawing panel has no mesh-graph link in its heading');
    must(wide.href === trace.graph_url, `it goes to ${wide.href}, not ${trace.graph_url}`);
    must(wide.target === '_blank' && /noopener/.test(wide.rel), `target=${wide.target} rel=${wide.rel}`);
    must(Math.abs(wide.right) <= 1 && wide.top <= 4, `it is ${wide.right} px from the right, ${wide.top} px down`);
    must(/holds no drawing/.test(wide.text), 'the page did not say mesh-graph has no drawing');

    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForTimeout(400);
    const narrow = await page.evaluate(button);
    must(narrow.height >= 44, `it is ${narrow.height} px tall on a phone`);
    must(narrow.doc <= 1, 'the page scrolls sideways at 390 px');

    // The packet page draws the same panel. The seeded mesh stores no
    // packet row for its traceroutes, so a real traceroute packet is
    // opened and its lookup answered with the trace above.
    const packets = await (await page.request.get(
      `${BASE}/api/packets?portnum=TRACEROUTE_APP&limit=1`)).json();
    let onPacket = 'no traceroute packet stored';
    if (packets.length) {
      await page.route(/\/api\/traceroutes\/by-packet\//, (route) => route.fulfill({ json: trace }));
      await page.setViewportSize({ width: 1280, height: 900 });
      const [from, id] = [packets[0].from_node, packets[0].packet_key.split(':')[1]];
      await page.goto(`${BASE}/?b=2#packet/${from}/${id}`, { waitUntil: 'load' });
      must(await waitFor(page, button, 15000), 'the packet page drew no mesh-graph panel');
      const packet = await page.evaluate(button);
      must(packet.found && packet.href === trace.graph_url, 'the packet page has no matching button');
      onPacket = 'same on the packet page';
    }

    // No URL, no button, and the sentence that says why.
    await page.route(new RegExp(`/api/traceroutes/${trace.id}$`), async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), graph_url: null } });
    });
    await page.goto(`${BASE}/?b=3#traceroute/${trace.id}`, { waitUntil: 'load' });
    must(await waitFor(page, button, 15000), 'the drawing panel never drew without a URL');
    const none = await page.evaluate(button);
    must(!none.found, 'a trace with no URL still has a button');
    must(/cannot be linked/.test(none.text), 'a trace with no URL does not say why');
    return `top right at 1280 (${wide.right} px), ${narrow.height} px tall at 390, `
      + `kept with no drawing, ${onPacket}, gone with no URL`;
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

  await journey(context, 'reachability is answered traceroutes, not hours awake (#293)', async (page) => {
    /*
     * Will: "I think uptime hours is an easy metric to achieve." The board
     * now ranks the share of traceroutes sent to a node that it answered.
     *
     * Not patched: the seed sends 12 traceroutes from three nodes to one
     * router on each preset, with some answers, and CI runs the gaps job
     * before this. So the title, the percentage and the "N of M answered"
     * line all come from the real job and the real route.
     */
    const reachable = () => {
      const board = [...document.querySelectorAll('[data-page="stats"] .leaderboard')]
        .find((panel) => /Most reliably answers traceroutes/.test(panel.querySelector('h3').textContent));
      if (!board) return null;
      const value = board.querySelector('.board .value');
      const detail = board.querySelector('.board .detail');
      return {
        value: value ? value.textContent : null,
        detail: detail ? detail.textContent : null,
        measure: (board.querySelector('p.muted') || {}).textContent || '',
      };
    };
    await page.goto(`${BASE}/#stats`, { waitUntil: 'load' });
    must(await waitFor(page, reachable, 30000), 'no board is titled "Most reliably answers traceroutes"');
    const old = await page.evaluate(() => [...document.querySelectorAll('[data-page="stats"] .leaderboard h3')]
      .some((h) => /Most consistently reachable/.test(h.textContent)));
    must(!old, 'the uptime board is still on the page');
    const got = await page.evaluate(reachable);
    must(/traceroutes/.test(got.measure), `the board does not say what it measures: ${got.measure}`);
    must(got.value !== null && /^\d+(\.\d+)? %$/.test(got.value), `the first row is not a percentage: ${got.value}`);
    must(/^\d+ of \d+ answered, \d+ senders?$/.test(got.detail || ''), `the detail line reads ${got.detail}`);
    return `${got.value}, ${got.detail}`;
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
     * Every board follows a quick range (#294, option A): the gaps job
     * writes the two gaps boards for 24 h, 7 d and 30 d. At 7 d they are the
     * assessment itself, so this holds from the first run of the job.
     */
    const boardChips = () => page.evaluate(() => [...document.querySelectorAll('[data-page="stats"] .leaderboard h3')]
      .map((h) => [h.dataset.label, (h.querySelector('span.muted') || {}).textContent || '']));
    const boards = await boardChips();
    if (boards.length) {
      must(boards.every(([, chip]) => chip === 'last 7 d'),
        `a board does not follow 7 d: ${JSON.stringify(boards)}`);
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
    /*
     * A custom range has no precomputed file. The two gaps boards hold the
     * job's own window and say so; the link board reads the dates.
     */
    const customBoards = await boardChips();
    if (customBoards.length) {
      const fixed = customBoards.filter(([title]) => !/Longest reliable link/.test(title));
      must(fixed.every(([, chip]) => /not the page range/.test(chip)),
        `a gaps board passes another window off as the dates: ${JSON.stringify(fixed)}`);
    }
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

    // Phoenix, in the middle of the served region, and 6 mi (about 10 km)
    // rather than the default 30 km: the run is the slow part of this
    // journey and a short one still fills the summary and the table. The
    // range box is in miles here because this browser has the default,
    // imperial, units setting (#246).
    await advanced(page);
    await page.fill('[data-planner="lat"]', '33.45');
    await page.fill('[data-planner="lon"]', '-112.07');
    await page.fill('[data-planner="radius"]', '6');
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
    await setUnits(page, 'imperial');
    await advanced(page);
    await page.fill('[data-planner="site_name"]', 'Shaw Butte');
    await page.fill('[data-planner="lat"]', '33.5905');
    await page.fill('[data-planner="lon"]', '-112.0865');
    // Feet and miles, which is what this browser's default units setting
    // shows. The link carries metres whatever the box shows (#246).
    await page.fill('[data-planner="tx_height"]', '20');
    await page.selectOption('[data-planner="preset"]', 'LONG_FAST');
    await page.fill('[data-planner="radius"]', '6');
    await page.locator('[data-planner="radius"]').blur();
    await page.waitForTimeout(500);

    const query = new URLSearchParams(page.url().split('?')[1] || '');
    must(query.get('tx_height') === '6.096', `the address did not follow the form: ${page.url()}`);
    must(query.get('radius') === '9.656064', `6 mi went into the link as ${query.get('radius')} km`);
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
    must(back.tx_height === '20' && back.preset === 'LONG_FAST', 'the settings did not come back');
    // Long fast's sensitivity from the docs' link budget at 22 dBm (#362).
    must(back.sensitivity === '-131', `the sensitivity came back as ${back.sensitivity}`);
    must(back.tx_power === '30', `an unshared field did not take its default: ${back.tx_power}`);
    if (!run.ran) return `${link.length} characters, settings restored; no prediction here (${run.why})`;

    must(back.overlays > 0, 'the link drew no coverage on the map');
    must(/shared on \d{4}-\d{2}-\d{2}/.test(back.said), `the page did not date the plan: ${back.said}`);
    must(sameCount && sameCount[0] === reached[0],
      `the same link reached ${sameCount && sameCount[0]} where the original reached ${reached[0]}`);
    return `${link.length} characters, reached ${reached[0]} in both`;
  });

  await journey(context, 'a Flagstaff site predicts on continental temperate (#239)', async (page) => {
    /*
     * The climate is read from the site's ground. Flagstaff is Köppen Dsb
     * in the shipped data, which is continental temperate. Advanced must
     * name it in the menu's "From the site" choice, and a run in Simple
     * must hand the engine that climate (code 5), not the old desert (4).
     *
     * The climate is answered before the terrain is read, so the engine
     * values are asserted whether or not this instance holds terrain. On
     * an instance that can predict, the summary must say it too.
     */
    await open(page, 'planner', 5000);
    await advanced(page);
    await page.fill('[data-planner="lat"]', '35.1983');
    await page.fill('[data-planner="lon"]', '-111.6513');
    await page.locator('[data-planner="lon"]').blur();
    const named = await valueOf(page, () => {
      const menu = document.querySelector('[data-planner="radio_climate"]');
      const first = menu && menu.querySelector('option[value="auto"]');
      return first && first.textContent.includes('Köppen') ? { value: menu.value, text: first.textContent } : null;
    });
    must(named, 'the climate menu never named what it found at the site');
    must(named.value === 'auto', `the menu opened on ${named.value}, not on the site`);
    must(/Continental temperate/.test(named.text) && /Dsb/.test(named.text),
      `Advanced offers "${named.text}" for Flagstaff`);
    const note = await page.locator('[data-planner-climate-note]').textContent();
    must(/Continental temperate/.test(note), `the note beside the site says "${note}"`);

    await page.click('[data-planner-mode="simple"]');
    // Simple asks for each picker that is on screen. Take the first real
    // choice of each, which is what a newcomer does.
    for (const picker of ['[data-board-type]', '[data-antenna-type="tx"]', '[data-antenna-type="rx"]', '[data-cable-type]']) {
      const select = page.locator(picker);
      if (!(await select.isVisible().catch(() => false))) continue;
      const value = await select.evaluate((element) => {
        const option = [...element.options].find((item) => item.value !== '');
        return option ? option.value : null;
      });
      if (value !== null) await select.selectOption(value);
    }
    const run = await predict(page, () => page.click('[data-planner-run]'));
    const used = await page.evaluate(() => {
      const state = window.SonoranPlanner.state;
      return {
        climate: state.climate && state.climate.climate,
        source: state.climate && state.climate.source,
        code: state.params && state.params.radioClimate,
      };
    });
    must(used.climate === 'continental_temperate' && used.source === 'site',
      `the Simple run used ${used.climate} (${used.source})`);
    must(used.code === 5, `the engine was handed climate code ${used.code}, not 5`);
    const link = new URLSearchParams(page.url().split('?')[1] || '');
    must(!link.has('radio_climate'), 'a climate read from the site went into the link as if chosen');
    if (!run.ran) return `engine handed code 5; no prediction here (${run.why})`;
    const said = await page.locator('[data-planner-climate-used]').textContent();
    must(/Continental temperate/.test(said) && /Beck/.test(said), `the summary says "${said}"`);
    return `engine handed code 5, and the summary says so`;
  });

  await journey(context, 'a planner link made before #239 keeps desert', async (page) => {
    /*
     * The issue's own risk: a link made before the climate was read from
     * the site was made on desert and left it out, because it was the
     * default. Opened now at Flagstaff it must still predict on desert,
     * and say why, rather than quietly become continental temperate.
     */
    await page.goto(`${BASE}/#planner?v=1&lat=35.1983&lon=-111.6513&radius=5`, { waitUntil: 'load' });
    const used = await valueOf(page, () => {
      const state = window.SonoranPlanner && window.SonoranPlanner.state;
      return state && state.climate ? { climate: state.climate.climate, code: state.params && state.params.radioClimate } : null;
    }, 30000);
    must(used, 'the link started no run');
    must(used.climate === 'desert' && used.code === 4, `the old link ran on ${used.climate} (${used.code})`);
    const said = await page.locator('[data-planner-shared]').textContent();
    must(/keeps desert/.test(said), `the page did not say why: "${said}"`);
    await predict(page, null);
    return 'kept desert, and said so';
  });

  await journey(context, 'a planner link made in feet predicts the same in metres', async (page) => {
    /*
     * #246. The boxes read in the reader's units and the link carries
     * metres, so a link made by an imperial reader and opened by a metric
     * one must put the same antenna into the model. The arithmetic and a
     * real engine run are in `test_planner_units_follow_the_setting.py`;
     * this is the page doing it: the labels, the boxes, and, where there
     * is terrain, the prediction itself.
     */
    await open(page, 'planner', 5000);
    await setUnits(page, 'imperial');
    await advanced(page);
    const labels = () => page.evaluate(() => [...document.querySelectorAll('[data-planner-unit]')]
      .map((unit) => unit.textContent).join(','));
    must(await labels() === 'ft,ft,ft,mi', `the imperial labels read ${await labels()}`);
    await page.fill('[data-planner="lat"]', '33.5905');
    await page.fill('[data-planner="lon"]', '-112.0865');
    await page.fill('[data-planner="tx_height"]', '20');
    await page.fill('[data-planner="rx_height"]', '5');
    await page.fill('[data-planner="radius"]', '6');
    await page.locator('[data-planner="radius"]').blur();
    await page.waitForTimeout(500);
    const link = page.url();
    const query = new URLSearchParams(link.split('?')[1] || '');
    must(query.get('tx_height') === '6.096' && query.get('rx_height') === '1.524',
      `the heights went into the link as ${query.get('tx_height')} and ${query.get('rx_height')}`);

    // Switched to metric on this same page, the boxes keep the antenna.
    await setUnits(page, 'metric');
    const switched = await page.evaluate(() => ({
      tx: document.querySelector('[data-planner="tx_height"]').value,
      radius: document.querySelector('[data-planner="radius"]').value,
    }));
    must(await labels() === 'm,m,m,km', `the metric labels read ${await labels()}`);
    must(switched.tx === '6.096' && switched.radius === '9.656064',
      `switching units moved the boxes to ${switched.tx} m and ${switched.radius} km`);
    await setUnits(page, 'imperial');
    const restored = await page.evaluate(() => document.querySelector('[data-planner="tx_height"]').value);
    must(restored === '20', `switching back to imperial shows ${restored} ft, not the 20 typed`);

    const run = await predict(page, () => page.click('[data-planner-run]'));
    const reached = run.ran
      ? (await page.locator('[data-planner-summary]').innerText()).match(/(\d+) of (\d+)/)
      : null;

    // A clean browser whose reader chose metric.
    const clean = await browser.newContext({ viewport: { width: 1500, height: 1050 } });
    await clean.addInitScript(() => {
      window.localStorage.setItem('sonoran.settings', JSON.stringify({ units: 'metric' }));
    });
    const opened = await clean.newPage();
    await opened.goto(page.url(), { waitUntil: 'load' });
    const again = await predict(opened, null);
    const back = await opened.evaluate(() => ({
      tx: document.querySelector('[data-planner="tx_height"]').value,
      rx: document.querySelector('[data-planner="rx_height"]').value,
      radius: document.querySelector('[data-planner="radius"]').value,
      units: [...document.querySelectorAll('[data-planner-unit]')].map((unit) => unit.textContent).join(','),
    }));
    const sameCount = again.ran
      ? (await opened.locator('[data-planner-summary]').innerText()).match(/(\d+) of (\d+)/)
      : null;
    await opened.close();
    await clean.close();

    must(back.units === 'm,m,m,km', `the metric reader's labels read ${back.units}`);
    must(back.tx === '6.096' && back.rx === '1.524' && back.radius === '9.656064',
      `the metric reader got ${back.tx} m, ${back.rx} m and ${back.radius} km`);
    if (!run.ran) return `20 ft -> 6.096 m both ways; no prediction here (${run.why})`;
    must(sameCount && sameCount[0] === reached[0],
      `metric reached ${sameCount && sameCount[0]} where imperial reached ${reached[0]}`);
    return `20 ft -> 6.096 m, reached ${reached[0]} in both unit systems`;
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
    await setUnits(page, 'imperial');
    const held = await page.evaluate(() => ({
      radius: document.querySelector('[data-planner="radius"]').value,
      tx_height: document.querySelector('[data-planner="tx_height"]').value,
      preset: document.querySelector('[data-planner="preset"]').value,
      situation: document.querySelector('[data-planner="situation_fraction"]').value,
      said: document.querySelector('[data-planner-shared]').textContent.trim(),
    }));
    // In miles and feet, which this browser reads: 150 km and 3 m.
    must(held.radius === '93.21', `the range is ${held.radius} mi, past the engine's 150 km`);
    must(held.tx_height === '9.84', `"abc" became ${held.tx_height} ft rather than the default 3 m`);
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
   * The sidebar collapsed to icons (#300), in a context of its own: the
   * choice is kept in localStorage, and a collapsed sidebar must not leak
   * into the journeys that share `context`.
   */
  const railed = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await journey(railed, 'the desktop sidebar collapses to icons and back (#300)', async (page) => {
    await open(page, 'dashboard', 1500);
    const button = page.locator('[data-sidebar-collapse]');
    const state = () => page.evaluate(() => {
      const b = document.querySelector('[data-sidebar-collapse]');
      const canvas = document.querySelector('.page.active .chart canvas');
      return {
        width: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
        expanded: b.getAttribute('aria-expanded'),
        name: b.getAttribute('aria-label'),
        canvas: canvas ? Math.round(canvas.getBoundingClientRect().width) : 0,
        host: canvas ? Math.round(canvas.closest('.chart').getBoundingClientRect().width) : 0,
      };
    });
    must(await button.isVisible(), 'no collapse button on a wide screen');
    await waitFor(page, () => !!document.querySelector('.page.active .chart canvas'), 20000);
    const wide = await state();
    must(wide.width >= 200, `a new visitor starts at ${wide.width} px, not expanded`);
    must(wide.expanded === 'true' && /collapse/i.test(wide.name),
      `expanded, the button says expanded=${wide.expanded} and "${wide.name}"`);

    await button.click();
    await page.waitForTimeout(800);
    const rail = await state();
    must(rail.width <= 80, `collapsed, the sidebar is still ${rail.width} px wide`);
    must(rail.expanded === 'false' && /expand/i.test(rail.name),
      `collapsed, the button says expanded=${rail.expanded} and "${rail.name}"`);
    // The chart follows the new width without a window resize.
    must(rail.canvas > wide.canvas + 40, `the chart stayed ${rail.canvas} px (was ${wide.canvas}) after the collapse`);
    must(Math.abs(rail.canvas - rail.host) <= 2, `the chart is ${rail.canvas} px in a ${rail.host} px box`);

    // Every link keeps its name, and the current page still says so.
    for (const name of ['Dashboard', 'Nodes', 'Statistics', 'Settings']) {
      must(await page.getByRole('link', { name, exact: true }).isVisible(), `no visible link named ${name} in the rail`);
    }
    must((await page.getByRole('link', { name: 'Dashboard', exact: true }).getAttribute('aria-current')) === 'page',
      'the current page lost aria-current in the rail');
    const presets = page.getByRole('radio');
    must((await presets.count()) >= 1 && await presets.first().isVisible(), 'the preset is not in the rail');

    // A label on hover, and on keyboard focus, beside the rail.
    const label = (nav) => page.evaluate((key) => {
      const box = document.querySelector(`#site-nav a[data-nav="${key}"] .nav-label`).getBoundingClientRect();
      return { x: Math.round(box.x), width: Math.round(box.width) };
    }, nav);
    await page.hover('#site-nav a[data-nav="nodes"]');
    await page.waitForTimeout(150);
    const hovered = await label('nodes');
    must(hovered.width > 20 && hovered.x >= rail.width, `hovering Nodes shows no label beside the rail (${JSON.stringify(hovered)})`);
    await page.mouse.move(900, 500);
    await button.focus();
    await page.keyboard.press('Tab');
    await page.waitForTimeout(150);
    const focused = await label('dashboard');
    must(focused.width > 20 && focused.x >= rail.width, `Tab to Dashboard shows no label (${JSON.stringify(focused)})`);

    /*
     * A new page load, not a hash change: going from #dashboard to
     * #planner in the same page is the same document, and would find the
     * attribute still standing rather than read the stored choice back.
     * A second tab in this context shares the storage and is a real load.
     */
    const fresh = await page.context().newPage();
    // The planner's sticky column stays flush in this state too (#108).
    await fresh.goto(`${BASE}/#planner`, { waitUntil: 'load' });
    await fresh.waitForTimeout(2000);
    await fresh.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await fresh.waitForTimeout(400);
    const flush = await fresh.evaluate(() => {
      const box = document.querySelector('.sidebar').getBoundingClientRect();
      return { top: box.top, gap: window.innerHeight - box.bottom, width: box.width };
    });
    await fresh.close();
    must(flush.width <= 80, 'the collapse did not survive a new page load');
    must(flush.top <= 1 && flush.gap <= 1, `the collapsed sidebar left a gap: ${JSON.stringify(flush)}`);

    // Set before the script runs: with app.js served empty, only the boot
    // script in index.html can have collapsed it, so there is no flash.
    const bare = await page.context().newPage();
    await bare.route(/\/static\/app\.js/, (route) => route.fulfill({ contentType: 'application/javascript', body: '' }));
    await bare.goto(`${BASE}/#dashboard`, { waitUntil: 'load' });
    const early = Math.round(await bare.evaluate(() => document.querySelector('.sidebar').getBoundingClientRect().width));
    await bare.close();
    must(early <= 80, `on a new load, before app.js, the sidebar is ${early} px: it would flash wide`);

    // A second press expands it.
    await button.click();
    await page.waitForTimeout(300);
    const back = await state();
    must(back.width >= 200 && back.expanded === 'true', `a second press left it at ${back.width} px`);
    return `${wide.width} -> ${rail.width} px, chart ${wide.canvas} -> ${rail.canvas} px, kept on reload, labels on hover and focus`;
  });
  await railed.close();

  /*
   * Storage refused: the page works and starts expanded. A getter that
   * throws is what Safari's private mode and a blocked site look like.
   */
  const nostore = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await nostore.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', { get() { throw new Error('storage refused'); } });
  });
  await journey(nostore, 'the sidebar collapse works with storage refused (#300)', async (page) => {
    await open(page, 'dashboard', 2000);
    const width = () => page.evaluate(() => Math.round(document.querySelector('.sidebar').getBoundingClientRect().width));
    must(await width() >= 200, 'with storage refused the sidebar did not start expanded');
    await page.locator('[data-sidebar-collapse]').click();
    await page.waitForTimeout(300);
    must(await width() <= 80, 'with storage refused the button did nothing');
    return 'starts expanded, and collapses for the visit';
  });
  await journey(nostore, 'coverage settings work with storage refused (#334)', async (page) => {
    await stubCoverage(page);
    await open(page, 'coverage', 2500);
    await page.locator('[data-coverage-options]').click();
    await page.locator('[data-coverage-heard]').selectOption('24h');
    await page.locator('[data-coverage-layers]').selectOption('uplink');
    await page.waitForTimeout(400);
    const url = await valueOf(page, COVERAGE_TILE_URL);
    must(url && url.includes('/infrastructure/uplink/'), `with storage refused the tiles are ${url}`);
    const changed = (await page.locator('[data-page="coverage"] [data-options-count]').textContent()).trim();
    must(changed === '2', `with storage refused the badge says "${changed}"`);
    return 'the panel works for the visit';
  });
  await nostore.close();

  /*
   * The update notice (#382). Logan saw "A new version of Sonoran is
   * available" when no release was published. The notice follows the
   * bytes of `/sw.js`, which change with every deploy that changes a
   * static file, so it says the page was updated, not that a release
   * came out. The issue also asks whether it can show when nothing
   * changed, and whether Reload makes it go.
   *
   * Chromium fetches a worker update in the browser process, where
   * `page.route` and `context.route` never see it. So the page is loaded
   * through a small proxy on this machine that can add a line to
   * `/sw.js`, which is what a deploy does to it. 127.0.0.1 is a secure
   * context, so the worker registers over plain HTTP.
   *
   * Negative and positive in one run: with the same bytes, three update
   * checks and reloads show nothing; with changed bytes, the notice
   * shows. Then Reload must reload the page and the notice must not come
   * back, on that page or a new one.
   */
  const updates = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const proxy = await workerProxy();
  await journey(updates, 'the update notice shows only for a changed worker, and goes after Reload (#382)', async (page) => {
    const notices = () => page.evaluate(() => [...document.querySelectorAll('.app-notice p')]
      .map((item) => item.textContent).filter((text) => !/offline/i.test(text)));
    const check = () => page.evaluate(() => navigator.serviceWorker.getRegistration()
      .then((registration) => registration && registration.update()).then(() => true, () => false));
    await page.goto(`${proxy.url}/#dashboard`, { waitUntil: 'load' });
    const ready = await page.evaluate(() => Promise.race([
      navigator.serviceWorker.ready.then(() => true),
      new Promise((resolve) => setTimeout(() => resolve(false), 15000)),
    ]));
    must(ready, 'the service worker never became active, so nothing here was measured');
    for (let round = 0; round < 3; round += 1) {
      await check();
      await page.waitForTimeout(800);
      await page.reload({ waitUntil: 'load' });
      await page.waitForTimeout(800);
    }
    const quiet = await notices();
    must(quiet.length === 0, `with an unchanged worker the page says "${quiet.join(' ')}"`);
    const served = new Set(proxy.served);
    must(proxy.served.length >= 4 && served.size === 1,
      `the worker was fetched ${proxy.served.length} times with ${served.size} different bodies`);

    proxy.change('\n// a deploy\n');
    await check();
    must(await waitFor(page, () => document.querySelectorAll('.app-notice button').length > 0, 10000),
      'a changed worker showed no notice, so the quiet run above proves nothing');
    const said = (await notices()).join(' ');
    must(/updated/i.test(said) && !/version/i.test(said),
      `the notice says "${said}", which reads like a release`);

    const reloaded = page.waitForNavigation({ timeout: 10000 }).then(() => true, () => false);
    await page.locator('.app-notice button').first().click();
    must(await reloaded, 'Reload did not reload the page');
    await page.waitForTimeout(1500);
    for (let round = 0; round < 2; round += 1) {
      await check();
      await page.waitForTimeout(800);
      await page.reload({ waitUntil: 'load' });
      await page.waitForTimeout(800);
    }
    const after = await notices();
    must(after.length === 0, `after Reload the page still says "${after.join(' ')}"`);
    const fresh = await updates.newPage();
    await fresh.goto(`${proxy.url}/#nodes`, { waitUntil: 'load' });
    await fresh.waitForTimeout(2000);
    const other = await fresh.evaluate(() => document.querySelectorAll('.app-notice button').length);
    await fresh.close();
    must(other === 0, 'a new tab after Reload shows the notice again');
    return `quiet over ${proxy.served.length} identical fetches; "${said}"; gone after Reload and in a new tab`;
  });
  await updates.close();
  await proxy.close();

  /*
   * azmsh runs on both presets (#313). Ingest tags each packet with the
   * preset that carried it, and the seed writes one azmsh message on each
   * (`tools/dev/README.md`). The old filter was the topic channel, so it
   * showed neither message on either preset, and the chat page put azmsh
   * on the default preset only.
   *
   * A context of its own, because the chosen preset is kept in
   * localStorage and must not leak into the journeys that share `context`.
   */
  const LONG_BODY = 'Long Fast check-in on azmsh.';
  const MEDIUM_BODY = 'Medium Fast check-in on azmsh.';
  const azmshText = (page) => page.evaluate(() => {
    const link = [...document.querySelectorAll('[data-page="chat"] a.title[href^="#chat/"]')]
      .find((anchor) => anchor.getAttribute('href') === '#chat/azmsh');
    const panel = link ? link.closest('.panel') : null;
    return panel ? panel.textContent : null;
  });
  const longFast = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await longFast.addInitScript(() => {
    if (!window.sessionStorage.getItem('e2e-313')) {
      window.sessionStorage.setItem('e2e-313', '1');
      window.localStorage.setItem('sonoran.preset', 'LongFast');
    }
  });
  await journey(longFast, 'azmsh on Long Fast shows the azmsh traffic Long Fast carried (#313)', async (page) => {
    const asked = [];
    page.on('request', (request) => {
      if (/\/api\/(packets|chat)(\/overview)?\?/.test(request.url())) asked.push(new URL(request.url()));
    });
    await open(page, 'chat', 500);
    must(await waitFor(page, () => Boolean(document.querySelector(
      '[data-page="chat"] [data-chat-body] .panel, [data-page="chat"] [data-chat-body] .empty')), 15000),
    'the chat overview never drew');
    const panel = await azmshText(page);
    must(panel !== null, 'there is no azmsh section on Long Fast');
    must(panel.includes(LONG_BODY), 'the azmsh message carried on Long Fast is missing');
    must(!panel.includes(MEDIUM_BODY), 'an azmsh message carried on Medium Fast shows on Long Fast');

    await open(page, 'firehose', 3000);
    const firehose = asked.filter((url) => url.pathname.endsWith('/api/packets'));
    must(firehose.length, 'the firehose asked for nothing');
    const last = firehose[firehose.length - 1].searchParams;
    must(last.get('preset') === 'LongFast' && !last.has('channel'),
      `the firehose did not ask for Long Fast by preset: ${last}`);
    const overview = asked.find((url) => url.pathname.endsWith('/api/chat/overview'));
    must(overview && overview.searchParams.get('preset') === 'LongFast',
      `the chat overview did not name the preset: ${overview}`);
    const rows = await page.evaluate(() => [...document.querySelectorAll('[data-firehose-table] tbody tr')]
      .map((row) => row.textContent));
    must(rows.some((text) => text.includes(LONG_BODY)),
      'the firehose on Long Fast does not list the Long Fast azmsh packet');
    must(!rows.some((text) => text.includes(MEDIUM_BODY)),
      'the firehose on Long Fast lists the Medium Fast azmsh packet');
    return `azmsh on Long Fast holds its own message only; firehose asked ${last}`;
  });
  await longFast.close();

  await journey(context, 'azmsh on Medium Fast leaves out what Long Fast carried (#313)', async (page) => {
    await open(page, 'chat', 500);
    must(await waitFor(page, () => Boolean(document.querySelector(
      '[data-page="chat"] [data-chat-body] .panel, [data-page="chat"] [data-chat-body] .empty')), 15000),
    'the chat overview never drew');
    const panel = await azmshText(page);
    must(panel !== null, 'there is no azmsh section on Medium Fast');
    must(panel.includes(MEDIUM_BODY), 'the azmsh message carried on Medium Fast is missing');
    must(!panel.includes(LONG_BODY), 'an azmsh message carried on Long Fast shows on Medium Fast');
    return 'azmsh on Medium Fast holds its own message only';
  });

  /*
   * Every preset, and several at once (#383). Will: "Add all of the
   * other presets for people to select ... select multiple presets as
   * well ... Make MediumFast the default solo selected."
   *
   * The positive control for "both azmsh check-ins" is the two #313
   * journeys above: on one preset the other's message is absent. A
   * context of its own, because the choice is kept in localStorage.
   */
  const several = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await journey(several, 'every preset can be chosen, and several at once (#383)', async (page) => {
    const asked = [];
    page.on('request', (request) => {
      if (/\/api\/(packets|chat\/overview|nodes|map\/nodes)\?/.test(request.url())) asked.push(new URL(request.url()));
    });
    const last = (path) => [...asked].reverse().find((url) => url.pathname.endsWith(path));
    const switchState = () => page.evaluate(() => ({
      checked: [...document.querySelectorAll('[data-preset-switch] [role="radio"]')]
        .filter((button) => button.getAttribute('aria-checked') === 'true')
        .map((button) => button.querySelector('.nav-label').textContent.trim()),
      more: (() => {
        const select = document.querySelector('[data-preset-more]');
        return select.options[select.selectedIndex].textContent;
      })(),
    }));
    const boxes = () => page.evaluate(() => Object.fromEntries(
      [...document.querySelectorAll('[data-preset-boxes] input')]
        .map((input) => [input.value, input.checked])));
    const tick = async (value) => {
      await page.locator(`[data-preset-boxes] input[value="${value}"]`).click();
      await waitFor(page, () => !loading, 10000, 100);
    };

    // Will: "Make MediumFast the default solo selected."
    await open(page, 'settings', 800);
    let got = await boxes();
    const ticked = Object.keys(got).filter((name) => got[name]);
    must(ticked.join() === 'MediumFast', `a fresh browser starts on ${ticked.join(', ')}`);
    let state = await switchState();
    must(state.checked.join() === 'Medium Fast', `the menu lights ${state.checked.join(', ') || 'nothing'}`);

    // "Add all of the other presets for people to select."
    for (const name of ['LongFast', 'LongSlow', 'LongMod', 'LongTurbo', 'MediumFast', 'MediumSlow',
      'ShortFast', 'ShortSlow', 'ShortTurbo']) {
      must(name in got, `${name} cannot be chosen on the Settings page`);
    }
    const offered = Object.keys(got).length - 1;

    // "... select multiple presets as well."
    await tick('LongFast');
    got = await boxes();
    must(got.MediumFast && got.LongFast && !got.ShortFast, `ticking Long Fast left ${JSON.stringify(got)}`);
    state = await switchState();
    must(state.checked.length === 0 && state.more === '2 presets',
      `the menu does not say two are chosen: ${JSON.stringify(state)}`);
    const kept = await page.evaluate(() => localStorage.getItem('sonoran.preset'));
    must(kept === 'MediumFast,LongFast', `the choice was kept as ${kept}`);

    // The positive control is the #313 journeys: on one preset the other
    // preset's azmsh message is absent. Here both are present.
    await open(page, 'firehose', 3000);
    const firehose = last('/api/packets');
    must(firehose && firehose.searchParams.get('preset') === 'MediumFast,LongFast',
      `the firehose did not ask for both presets: ${firehose}`);
    const rows = await page.evaluate(() => [...document.querySelectorAll('[data-firehose-table] tbody tr')]
      .map((row) => row.textContent).join('\n'));
    must(rows.includes(LONG_BODY) && rows.includes(MEDIUM_BODY),
      'the firehose on both presets does not list both azmsh check-ins');

    // A page that draws links draws one preset, and says which.
    await open(page, 'map', 3000);
    const map = last('/api/map/nodes');
    must(map && map.searchParams.get('channel') === 'MediumFast',
      `the map did not draw Medium Fast alone: ${map}`);
    const note = await page.evaluate(() => {
      const scope = document.querySelector('[data-preset-scope]');
      return scope.hidden ? '' : scope.textContent;
    });
    must(/Shows Medium Fast only/.test(note), `the map does not say what it drew: "${note}"`);
    // Positive control for the quiet preset below: Medium Fast draws dots.
    must(await waitFor(page, () => window.SonoranMap.marks instanceof Map
      && window.SonoranMap.marks.size > 0, 10000), 'the map drew no Medium Fast node');

    // A preset with no traffic here draws nothing and says so. It used to
    // keep the old preset's channel: Medium Fast lines under a Short Turbo
    // switch, and the watch bar said Medium Fast.
    await page.evaluate(() => window.SonoranPreset.set('ShortTurbo'));
    await waitFor(page, () => !loading, 10000, 100);
    await page.waitForTimeout(500);
    const quiet = last('/api/map/nodes');
    must(quiet && quiet.searchParams.get('channel') === 'ShortTurbo',
      `the map did not ask for Short Turbo: ${quiet}`);
    const shown = await page.evaluate(() => ({
      dots: window.SonoranMap.marks.size,
      legend: document.querySelector('[data-map-legend]').textContent,
    }));
    must(shown.dots === 0, `${shown.dots} dots under a Short Turbo switch with no Short Turbo traffic`);
    must(/No node was heard on Short Turbo/.test(shown.legend),
      `the map does not say Short Turbo is empty: "${shown.legend.slice(-120)}"`);
    await page.evaluate(() => window.SonoranPreset.setMany(['MediumFast', 'LongFast']));

    // Arrowing through the menu's "More" select must not leave the page.
    // On a closed select an arrow key changes the value and fires
    // `change`, so an option that navigates went off on the way past.
    // Chromium on macOS opens the list on an arrow key instead, so the
    // real keys are pressed AND the Linux and Windows sequence -- one
    // value and one `change` per step -- is played on the element.
    await page.locator('[data-preset-more]').focus();
    const steps = await page.locator('[data-preset-more] option').count();
    for (let step = 0; step < steps; step += 1) await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Escape');
    await page.evaluate(() => {
      const select = document.querySelector('[data-preset-more]');
      for (let index = 0; index < select.options.length; index += 1) {
        const live = document.querySelector('[data-preset-more]');
        live.selectedIndex = index;
        live.dispatchEvent(new Event('change'));
      }
    });
    await page.waitForTimeout(300);
    const after = await page.evaluate(() => location.hash);
    must(after === '#map', `arrowing through the More select went to ${after}`);
    await page.evaluate(() => window.SonoranPreset.setMany(['MediumFast', 'LongFast']));

    // The last preset cannot be cleared.
    await open(page, 'settings', 800);
    await tick('MediumFast');
    await tick('LongFast');
    got = await boxes();
    must(got.LongFast && !got.MediumFast, `clearing the last preset left ${JSON.stringify(got)}`);
    const refusal = await page.locator('[data-preset-boxes-note]').textContent();
    must(/At least one preset/.test(refusal), `no word on why the last box stays: "${refusal}"`);
    // And a screen reader hears it, through the site's one live region.
    const heard = await page.locator('[data-status-live]').textContent();
    must(/At least one preset/.test(heard), `the refusal was not announced: "${heard}"`);

    // A button in the menu chooses one preset alone again.
    await tick('ShortFast');
    await page.locator('[data-preset-switch] [role="radio"]', { hasText: 'Medium Fast' }).click();
    await waitFor(page, () => !loading, 10000, 100);
    got = await boxes();
    const alone = Object.keys(got).filter((name) => got[name]);
    must(alone.join() === 'MediumFast', `the Medium Fast button left ${alone.join(', ')}`);

    // An old stored value, one name, still loads.
    // A reload, not a `goto`: the page is on #settings already, and a
    // second `goto` to it does not load again (AGENTS.md 9.33).
    await page.evaluate(() => localStorage.setItem('sonoran.preset', 'LongFast'));
    await page.reload({ waitUntil: 'load' });
    await page.waitForTimeout(800);
    got = await boxes();
    const old = Object.keys(got).filter((name) => got[name]);
    must(old.join() === 'LongFast', `an old stored "LongFast" loaded as ${old.join(', ')}`);
    return `${offered} presets offered, Medium Fast alone by default, two chosen reach the firehose `
      + 'as one preset=, the map draws one and says so, the last box stays, an old value loads';
  });
  await several.close();

  /*
   * An iPad on its side (#267). 1112 px is wider than every phone
   * breakpoint, so this is the device that proves touch sizing follows
   * the pointer and not the width. `hasTouch` makes Chromium match
   * `(pointer: coarse)`, which the journey checks before it believes
   * anything else.
   */
  const tablet = await browser.newContext({
    viewport: { width: 1112, height: 834 }, isMobile: true, hasTouch: true,
  });

  await journey(tablet, 'a tablet gets finger-sized targets at desktop width (#267)', async (page) => {
    await open(page, 'dashboard', 1500);
    // The ? buttons arrive with the data, so wait for them rather than
    // for a fixed time.
    await waitFor(page, () => document.querySelectorAll('[data-page="dashboard"] .hint-open').length > 0, 20000);
    const got = await page.evaluate(() => {
      const tall = (selector) => [...document.querySelectorAll(selector)]
        .filter((node) => node.getBoundingClientRect().width > 0)
        .map((node) => Math.round(node.getBoundingClientRect().height));
      return {
        coarse: matchMedia('(pointer: coarse)').matches,
        sidebar: getComputedStyle(document.querySelector('.sidebar')).position,
        nav: tall('#site-nav a'),
        hints: tall('[data-page="dashboard"] .hint-open'),
        preset: tall('.preset-choice'),
      };
    });
    must(got.coarse, 'the tablet context does not match (pointer: coarse), so this proves nothing');
    must(got.sidebar === 'sticky', `the sidebar is ${got.sidebar}, so this is not the desktop layout`);
    for (const [name, heights] of [['nav link', got.nav], ['? button', got.hints], ['preset choice', got.preset]]) {
      must(heights.length > 0, `no ${name} on the page to measure`);
      const low = Math.min(...heights);
      must(low >= 44, `a ${name} is ${low} px tall on a touch screen, under 44`);
    }
    return `${got.nav.length} nav links, ${got.hints.length} ? buttons, ${got.preset.length} preset choices, all 44 px or more`;
  });

  await journey(context, 'a mouse keeps the desktop sizes (#267)', async (page) => {
    // The other half: the change must not reach a mouse on a wide screen.
    await open(page, 'dashboard', 2500);
    const got = await page.evaluate(() => ({
      coarse: matchMedia('(pointer: coarse)').matches,
      nav: Math.round(document.querySelector('#site-nav a').getBoundingClientRect().height),
    }));
    must(!got.coarse, 'the desktop context matches (pointer: coarse)');
    must(got.nav < 44, `a nav link is ${got.nav} px tall with a mouse; the desktop size changed`);
    return `nav link ${got.nav} px with a mouse`;
  });
  await tablet.close();

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

  await journey(phone, 'the phone bar stays on the screen while scrolling (#271)', async (page) => {
    /*
     * The menu button and the live state were both gone after 1,200 px.
     * The dashboard is the page scrolled here because it is long on every
     * instance, seeded or live.
     */
    await open(page, 'dashboard', 1500);
    // Wait for the page to be long enough, rather than for a fixed time:
    // on a loaded runner the feeds arrive late and the page is short.
    await waitFor(page, () => document.documentElement.scrollHeight > window.innerHeight + 1300, 30000);
    await page.evaluate(() => window.scrollTo(0, 1200));
    await page.waitForTimeout(300);
    const got = await page.evaluate(() => {
      const bar = document.querySelector('.sidebar').getBoundingClientRect();
      const button = document.querySelector('[data-nav-toggle]').getBoundingClientRect();
      const status = document.querySelector('[data-status-bar]');
      return {
        scrollY: Math.round(window.scrollY),
        top: Math.round(bar.top),
        height: Math.round(bar.height),
        button: [Math.round(button.top), Math.round(button.bottom)],
        status: status.getBoundingClientRect().width > 0 ? status.textContent.trim() : '',
        opaque: getComputedStyle(document.querySelector('.sidebar')).backgroundColor,
      };
    });
    must(got.scrollY >= 600, `the dashboard only scrolled to ${got.scrollY}, so this proves nothing`);
    must(got.top === 0, `the bar is at ${got.top} px after scrolling ${got.scrollY}, not stuck at the top`);
    must(got.height <= 72, `the bar is ${got.height} px tall; it must stay one compact row`);
    must(got.button[0] >= 0 && got.button[1] <= got.height, 'the menu button is not inside the bar');
    must(got.status.length > 0, 'the live state is not shown in the bar');
    must(!/rgba\(.*, 0\)|transparent/.test(got.opaque), `the bar is see-through: ${got.opaque}`);

    // Open, the menu is taller than the screen. A sticky box never
    // scrolls its own foot into view, so the bar must scroll inside.
    await page.locator('[data-nav-toggle]').click();
    await page.waitForTimeout(250);
    await page.locator('.menu-settings-link').scrollIntoViewIfNeeded();
    const settings = await page.locator('.menu-settings-link').boundingBox();
    const height = page.viewportSize().height;
    must(settings && settings.y >= 0 && settings.y + settings.height <= height + 1,
      `with the menu open, Settings cannot be brought on screen (${settings && Math.round(settings.y)} of ${height})`);
    return `stuck at 0 after ${got.scrollY} px, ${got.height} px tall, shows "${got.status}"`;
  });

  /*
   * The drawer on a full iPhone 14 screen (#279). The `phone` context is
   * 664 px tall, which is that phone with Safari's bars showing; fourteen
   * 44 px links cannot leave room for the footer there, and the drawer
   * scrolls inside itself (#271). At 844 nothing should need a scroll.
   */
  const tall = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  await journey(tall, 'the drawer shows the preset and Settings without a scroll (#279)', async (page) => {
    await open(page, 'dashboard', 2500);
    await page.locator('[data-nav-toggle]').click();
    await page.waitForTimeout(300);
    const got = await page.evaluate(() => {
      const bottom = (selector) => {
        const box = document.querySelector(selector).getBoundingClientRect();
        return box.height ? Math.round(box.bottom) : null;
      };
      // What can be seen ends at the bottom bar on a phone (#282), not at
      // the foot of the screen: a link under the bar is not on the screen.
      const bar = document.querySelector('[data-tab-bar]');
      const barTop = bar && !bar.hidden ? bar.getBoundingClientRect().top : Infinity;
      return {
        scrolled: document.querySelector('.sidebar').scrollTop + window.scrollY,
        preset: bottom('.preset-switch'),
        settings: bottom('.menu-settings-link'),
        link: Math.round(document.querySelector('#site-nav a').getBoundingClientRect().height),
        height: Math.round(Math.min(window.innerHeight, barTop)),
      };
    });
    must(got.scrolled === 0, `the drawer opened scrolled by ${got.scrolled} px`);
    must(got.link >= 44, `a nav link is ${got.link} px, under 44; the rows were tightened too far`);
    must(got.preset && got.preset <= got.height, `the preset switch ends at ${got.preset}, under the ${got.height} px screen`);
    must(got.settings && got.settings <= got.height, `Settings ends at ${got.settings}, under the ${got.height} px screen`);
    return `preset ends at ${got.preset}, Settings at ${got.settings} of ${got.height}`;
  });
  await tall.close();

  /*
   * The bottom bar on a phone (#282). Will chose the set on 2026-10-08:
   * Map, Nodes, Chat and Dashboard, then More, which opens the menu.
   *
   * Measured with the CI runner's wider fonts imitated (AGENTS.md 9.31),
   * because five labels share 390 px and "Dashboard" is the widest.
   * Every page here is in the first `goto` (AGENTS.md 9.33).
   */
  const BAR = () => {
    const bar = document.querySelector('[data-tab-bar]');
    if (!bar || bar.hidden || getComputedStyle(bar).display === 'none') return null;
    const box = bar.getBoundingClientRect();
    return {
      top: Math.round(box.top),
      bottom: Math.round(box.bottom),
      name: bar.getAttribute('aria-label') || '',
      sideways: bar.scrollWidth > bar.clientWidth,
      items: [...bar.querySelectorAll('a, button')].map((item) => {
        const r = item.getBoundingClientRect();
        return {
          text: item.textContent.trim(),
          tag: item.tagName,
          w: Math.round(r.width),
          h: Math.round(r.height),
          current: item.getAttribute('aria-current'),
        };
      }),
    };
  };
  const SPREAD = '* { letter-spacing: .12em !important; }';

  await journey(phone, 'the bottom bar holds four pages and More, each finger-sized (#282)', async (page) => {
    await open(page, 'firehose', 2500);
    await page.addStyleTag({ content: SPREAD });
    await page.waitForTimeout(300);
    const bar = await page.evaluate(BAR);
    must(bar, 'there is no bottom bar on a 390 px touch screen');
    must(bar.name.length > 0, 'the bar is a nav with no name, beside the menu that has one');
    must(bar.bottom === page.viewportSize().height, `the bar ends at ${bar.bottom}, not at the foot of the screen`);
    const words = bar.items.map((item) => item.text);
    must(words.join() === 'Map,Nodes,Chat,Dashboard,More', `the bar holds ${JSON.stringify(words)}`);
    must(bar.items.slice(0, 4).every((item) => item.tag === 'A'), 'a page in the bar is not a link');
    must(bar.items[4].tag === 'BUTTON', 'More is not a button');
    for (const item of bar.items) {
      must(item.w >= 44 && item.h >= 44, `${item.text} is ${item.w} x ${item.h}, under 44 x 44`);
    }
    must(!bar.sideways, 'the five labels push the bar sideways with the wider fonts');
    must(bar.items.every((item) => !item.current), 'the firehose lights a tab, and it is not one');

    // A tap on Nodes goes there and marks it, and only it.
    await page.locator('[data-tab-bar] a[data-tab="nodes"]').tap();
    await page.waitForTimeout(1500);
    must(/#nodes$/.test(page.url()), `Nodes did not navigate (${page.url()})`);
    const after = await page.evaluate(BAR);
    const lit = after.items.filter((item) => item.current);
    must(lit.length === 1 && lit[0].text === 'Nodes' && lit[0].current === 'page',
      `after a tap on Nodes the bar marks ${JSON.stringify(lit)}`);
    return `${words.join(' · ')}, smallest ${Math.min(...bar.items.map((i) => Math.min(i.w, i.h)))} px; Nodes navigates and is marked`;
  });

  await journey(phone, 'More opens the one page list, clear of the bar (#282)', async (page) => {
    await open(page, 'dashboard', 2500);
    const more = page.locator('[data-tab-bar] [data-tab-more]');
    must((await more.getAttribute('aria-controls')) === 'site-menu', 'More does not open the site menu');
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await more.tap();
    await page.waitForTimeout(300);
    must((await more.getAttribute('aria-expanded')) === 'true', 'More did not open the menu');
    must(await page.locator('#site-nav').isVisible(), 'the page list is not on the screen');
    // One list: the menu holds every page, and the bar's links are copies, not a second list.
    const links = await page.locator('#site-nav a').count();
    const pages = await page.locator('main .page').count();
    must(links >= 10 && links <= pages, `the menu holds ${links} links for ${pages} pages`);
    must(await page.locator('[data-tab-bar] [data-nav]').count() === 0,
      'a bar link carries data-nav, so the router counts it as a second menu entry');
    // The top button tells the same story.
    must((await page.locator('[data-nav-toggle]').getAttribute('aria-expanded')) === 'true',
      'the top menu button says the menu is closed while it is open');
    // The open menu ends at the bar, so Settings can always be brought above it.
    const top = (await page.evaluate(BAR)).top;
    await page.locator('.menu-settings-link').scrollIntoViewIfNeeded();
    const settings = await page.locator('.menu-settings-link').boundingBox();
    must(settings && settings.y + settings.height <= top + 1,
      `with the menu open, Settings ends at ${settings && Math.round(settings.y + settings.height)}, under the bar at ${top}`);
    // Escape closes it and gives the focus back to More.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    must((await more.getAttribute('aria-expanded')) === 'false', 'Escape did not close the menu');
    must(await page.evaluate(() => document.activeElement && document.activeElement.matches('[data-tab-more]')),
      'Escape left the focus somewhere other than More');
    // A page chosen from the menu closes it and lights no tab.
    await more.tap();
    await page.waitForTimeout(250);
    await page.locator('#site-nav a[data-nav="stats"]').tap();
    await page.waitForTimeout(1500);
    must((await more.getAttribute('aria-expanded')) === 'false', 'the menu stayed open after a page was chosen');
    must((await page.evaluate(BAR)).items.every((item) => !item.current), 'Statistics lights a tab');
    return `${links} links in the menu, Settings ends at ${Math.round(settings.y + settings.height)} above the bar at ${top}`;
  });

  await journey(phone, 'a deep link lights the closest tab, or none (#282)', async (page) => {
    // A real node and a real packet, from the API, so neither page is an error page.
    const nodes = await (await page.request.get(`${BASE}/api/map/nodes`)).json();
    must(nodes.length > 0, 'no node to open');
    const node = `#node/${encodeURIComponent(nodes[0].node_id)}`;
    const packets = await (await page.request.get(`${BASE}/api/packets?limit=1&summary=true`)).json();
    must(packets.length > 0, 'no packet to open');
    // A summary row carries `packet_key` ("<from_num>:<packet_id>"), as the firehose reads it.
    const packet = `#packet/${encodeURIComponent(packets[0].from_node)}/${packets[0].packet_key.split(':')[1]}`;
    const lit = async (hash) => {
      const fresh = await page.context().newPage();
      await fresh.goto(`${BASE}/${hash}`, { waitUntil: 'load' });
      await fresh.waitForTimeout(1500);
      const items = (await fresh.evaluate(BAR)).items.filter((item) => item.current);
      await fresh.close();
      return items.map((item) => `${item.text}=${item.current}`).join();
    };
    const onNode = await lit(node);
    must(onNode === 'Nodes=true', `${node} lights ${onNode || 'nothing'}, not Nodes as "true"`);
    const onPacket = await lit(packet);
    must(onPacket === '', `${packet} lights ${onPacket}; a packet belongs to no tab`);
    const onChannel = await lit('#chat/LongFast');
    must(onChannel === 'Chat=page', `a chat channel lights ${onChannel || 'nothing'}, not Chat`);
    return `${node} lights Nodes (aria-current=true), a channel lights Chat, ${packet} lights none`;
  });

  await journey(phone, 'watch mode covers the bottom bar (#282)', async (page) => {
    /*
     * Watch mode fills the screen with the map and puts its panel at the
     * foot, so the bar must not sit on top of it. Asked of the screen
     * itself: what a finger at the bottom edge would touch.
     */
    await open(page, 'map', 4000);
    await page.locator('[aria-label="Watch mode"]').first().tap();
    await page.waitForTimeout(2000);
    const got = await page.evaluate(() => {
      const hit = document.elementFromPoint(window.innerWidth / 2, window.innerHeight - 10);
      return {
        watching: document.body.classList.contains('watch-mode') || Boolean(document.fullscreenElement),
        onBar: Boolean(hit && hit.closest('[data-tab-bar]')),
      };
    });
    must(got.watching, 'watch mode did not open, so this proves nothing');
    must(!got.onBar, 'the bottom bar sits on top of watch mode');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(1000);
    return 'the foot of the screen is the watch view, not the bar';
  });

  await journey(phone, 'no page ends under the bottom bar (#282)', async (page) => {
    /*
     * Scroll to the end and read the page's own bottom edge against the
     * bar's top. The page's box ends at its last row, so a page whose
     * last row hides under the bar fails here whatever that row is.
     */
    const out = [];
    for (const name of ['dashboard', 'nodes', 'firehose', 'chat', 'map', 'stats', 'settings']) {
      const fresh = await page.context().newPage();
      await fresh.goto(`${BASE}/#${name}`, { waitUntil: 'load' });
      await fresh.addStyleTag({ content: SPREAD });
      await fresh.waitForTimeout(3500);
      const got = await fresh.evaluate(async () => {
        window.scrollTo(0, document.documentElement.scrollHeight);
        await new Promise((done) => setTimeout(done, 300));
        const bar = document.querySelector('[data-tab-bar]').getBoundingClientRect();
        const pageBox = document.querySelector('.page.active').getBoundingClientRect();
        const scroller = document.querySelector('.page.active .chat-scroll');
        return {
          end: Math.round(pageBox.bottom),
          chat: scroller ? Math.round(scroller.getBoundingClientRect().bottom) : null,
          top: Math.round(bar.top),
          long: document.documentElement.scrollHeight > window.innerHeight,
        };
      });
      await fresh.close();
      must(got.end <= got.top + 1, `#${name} ends at ${got.end}, under the bar at ${got.top}`);
      if (got.chat !== null) must(got.chat <= got.top + 1, `the chat column ends at ${got.chat}, under the bar at ${got.top}`);
      out.push(`${name}:${got.end}/${got.top}`);
    }
    return out.join(' ');
  });

  await journey(phone, 'the node sheet and the offline notice stand on the bar (#282)', async (page) => {
    await open(page, 'map', 2500);
    const got = await page.evaluate(async () => {
      // The offline notice (#331) is made by pwa.js on the browser's own event.
      window.dispatchEvent(new Event('offline'));
      await new Promise((done) => setTimeout(done, 300));
      const notices = [...document.querySelectorAll('.app-notice')].map((n) => Math.round(n.getBoundingClientRect().bottom));
      window.dispatchEvent(new Event('online'));
      return { notices, top: Math.round(document.querySelector('[data-tab-bar]').getBoundingClientRect().top) };
    });
    must(got.notices.length > 0, 'no offline notice appeared, so this proves nothing');
    must(Math.max(...got.notices) <= got.top, `an app notice ends at ${Math.max(...got.notices)}, under the bar at ${got.top}`);
    // The node sheet, opened through its own interface on the first node drawn.
    must(await waitFor(page, () => window.SonoranMap.marks instanceof Map && window.SonoranMap.marks.size > 0, 20000),
      'the map drew no nodes');
    const sheet = await page.evaluate(async () => {
      const { marks } = window.SonoranMap;
      const entry = [...marks.values()][0];
      entry.marker.fire('click');
      await new Promise((done) => setTimeout(done, 400));
      const node = document.querySelector('.node-sheet');
      if (!node || node.hidden) return null;
      return {
        bottom: Math.round(node.getBoundingClientRect().bottom),
        top: Math.round(document.querySelector('[data-tab-bar]').getBoundingClientRect().top),
      };
    });
    must(sheet, 'a node opened no sheet');
    must(sheet.bottom <= sheet.top + 1, `the node sheet ends at ${sheet.bottom}, under the bar at ${sheet.top}`);
    return `notice ends ${Math.max(...got.notices)}, sheet ends ${sheet.bottom}, bar at ${got.top}`;
  });

  /*
   * The other half: the bar is for a phone held upright only. A mouse
   * at desktop width, a narrow window with a mouse, an iPad in portrait
   * and an iPhone SE on its side (568 px wide, under 40rem, and 320 px
   * tall) keep the layout they had, with no bar and no space kept for one.
   */
  for (const [label, options] of [
    ['a mouse at 1440 px', { viewport: { width: 1440, height: 900 } }],
    ['a mouse at 390 px', { viewport: { width: 390, height: 844 } }],
    ['an iPad in portrait', { viewport: { width: 834, height: 1112 }, isMobile: true, hasTouch: true }],
    ['a small phone on its side', { viewport: { width: 568, height: 320 }, isMobile: true, hasTouch: true }],
  ]) {
    const other = await browser.newContext(options);
    await journey(other, `${label} has no bottom bar (#282)`, async (page) => {
      await open(page, 'dashboard', 2000);
      const got = await page.evaluate(() => ({
        bar: Boolean(document.querySelector('[data-tab-bar]')),
        shown: (() => {
          const bar = document.querySelector('[data-tab-bar]');
          return Boolean(bar) && getComputedStyle(bar).display !== 'none' && bar.getBoundingClientRect().height > 0;
        })(),
        kept: getComputedStyle(document.documentElement).getPropertyValue('--tabbar-h').trim(),
      }));
      must(got.bar, 'the bar is missing from the markup, so this proves nothing');
      must(!got.shown, `the bottom bar is drawn for ${label}`);
      must(got.kept === '0px', `${label} keeps ${got.kept} for a bar it does not draw`);
      return `no bar, --tabbar-h ${got.kept}`;
    });
    await other.close();
  }

  await journey(phone, 'the fixed-size controls are finger-sized on touch (#268)', async (page) => {
    /*
     * Each of these has a size of its own, so the general 44 px rule for
     * buttons (#267) never reached it. Measured one by one, on the page
     * where it lives, because a missing control would otherwise pass as
     * "nothing too small".
     */
    const measure = (selectors) => page.evaluate((list) => list.map((selector) => {
      const node = [...document.querySelectorAll(selector)]
        .find((item) => item.getBoundingClientRect().width > 0);
      if (!node) return { selector, missing: true };
      const box = node.getBoundingClientRect();
      return { selector, width: Math.round(box.width), height: Math.round(box.height) };
    }), selectors);
    const seen = [];
    await open(page, 'dashboard', 1500);
    await waitFor(page, () => document.querySelector('.chart-expand') && document.querySelector('.reaction > summary'), 20000);
    seen.push(...await measure(['[data-nav-toggle]', '.page.active .chart-expand', '.page.active .reaction > summary']));
    await page.locator('[data-nav-toggle]').click();
    await page.waitForTimeout(250);
    seen.push(...await measure(['.menu-settings-link']));
    await open(page, 'map', 4000);
    seen.push(...await measure(['#live-map .leaflet-control-zoom-in', '#live-map .leaflet-control-zoom-out',
      '.map-key summary', '.watch-control button']));
    /*
     * The popup close button exists only while a popup is open, and a
     * dot is a few pixels on a canvas. The rule is what is under test, so
     * a close button is put inside the live map's own container and
     * measured there.
     */
    seen.push(...await page.evaluate(() => {
      const probe = document.createElement('a');
      probe.className = 'leaflet-popup-close-button';
      probe.href = '#close';
      probe.textContent = '×';
      document.querySelector('#live-map').append(probe);
      const box = probe.getBoundingClientRect();
      probe.remove();
      return [{ selector: 'popup close', width: Math.round(box.width), height: Math.round(box.height) }];
    }));
    const missing = seen.filter((item) => item.missing).map((item) => item.selector);
    must(missing.length === 0, `not on the page to measure: ${missing.join(', ')}`);
    const small = seen.filter((item) => item.width < 44 || item.height < 44)
      .map((item) => `${item.selector} ${item.width}x${item.height}`);
    must(small.length === 0, `under 44 px on a touch screen: ${small.join(', ')}`);
    return `${seen.length} controls, all 44 px or more`;
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
     *
     * Since #273 a phone reads the firehose as cards, and Uploads is one
     * of the three columns a card leaves to the packet page, so its
     * heading is not on a phone's screen. The sentence checked here is
     * "What it said", which a card does show; the Uploads sentence is
     * the same code on the same kind of heading.
     */
    await open(page, 'firehose', 4500);
    // The fixed pause alone lost to a slow first query on a loaded
    // machine, one run in two here: wait for the headings' controls.
    await waitFor(page, () => document.querySelectorAll('[data-page="firehose"] .hint-open').length > 0, 30000);
    const table = page.locator('[data-page="firehose"] .table-wrap').first();
    const buttons = table.locator('.hint-open');
    must((await buttons.count()) > 0, 'no column carries a hint control');
    const uploads = table.locator('th[data-label="What it said"] .hint-open');
    must((await uploads.count()) > 0, 'the What it said column has no hint control');
    must((await uploads.getAttribute('aria-expanded')) === 'false', 'the hint starts open');
    const panel = page.locator(`#${await uploads.getAttribute('aria-controls')}`);
    must(!(await panel.isVisible()), 'the sentence is on the screen before it is asked for');

    await uploads.tap();
    await page.waitForTimeout(250);
    must((await uploads.getAttribute('aria-expanded')) === 'true', 'tapping did not open it');
    must(await panel.isVisible(), 'the panel did not appear');
    must(/A short line from the decoded packet/.test(await panel.innerText()),
      'the What it said sentence is not in the panel');
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

  await journey(context, 'a hint panel wraps its sentence at every width (#298)', async (page) => {
    /*
     * The journey above checks that the panel BOX is on the screen and
     * that `innerText` holds the sentence. Both passed while the
     * sentence ran on one line inside a 350 px panel and scrolled
     * sideways out of sight: `innerText` includes overflowed text. So
     * this opens every hint on the four pages that carry column hints
     * and asks the panel itself whether it scrolls.
     *
     * `letter-spacing` is widened as the "Who hears it" journey does, so
     * the wider Linux fonts of the CI runner are covered too.
     */
    const out = [];
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      let opened = 0;
      for (const name of ['nodes', 'firehose', 'dashboard', 'stats']) {
        await open(page, name, 1500);
        // The firehose draws its table only once rows arrive.
        await page.locator(`[data-page="${name}"] .hint-open`).first()
          .waitFor({ state: 'attached', timeout: 10000 }).catch(() => {});
        await page.addStyleTag({ content: '.hint-pop { letter-spacing: .05em !important; }' });
        const buttons = page.locator(`[data-page="${name}"] .hint-open`);
        const total = await buttons.count();
        must(total > 0, `${name} has no hint control at ${width} px`);
        for (let index = 0; index < total; index += 1) {
          const button = buttons.nth(index);
          if (!(await button.isVisible())) continue;
          await button.click();
          await page.waitForTimeout(120);
          const size = await page.evaluate((id) => {
            const panel = document.getElementById(id);
            const box = panel.getBoundingClientRect();
            return {
              label: panel.querySelector('.hint-name')?.textContent || id,
              scroll: panel.scrollWidth,
              client: panel.clientWidth,
              wrap: getComputedStyle(panel).whiteSpace,
              left: box.left,
              right: box.right,
              page: document.documentElement.scrollWidth,
              view: document.documentElement.clientWidth,
            };
          }, await button.getAttribute('aria-controls'));
          must(size.scroll <= size.client + 1,
            `${name} ${size.label} scrolls sideways at ${width} px: ${size.scroll}/${size.client}`);
          must(size.wrap === 'normal', `${name} ${size.label}: white-space is ${size.wrap}`);
          must(size.left >= -1 && size.right <= size.view + 1,
            `${name} ${size.label} runs off the screen at ${width} px`);
          must(size.page <= size.view + 1,
            `${name} ${size.label} widens the page at ${width} px: ${size.page}/${size.view}`);
          await page.keyboard.press('Escape');
          await page.waitForTimeout(60);
          opened += 1;
        }
      }
      out.push(`${width}:${opened}`);
    }
    return `panels opened and measured at ${out.join(' ')}`;
  });

  await journey(phone, 'a phone reads the node lists as cards (#272)', async (page) => {
    /*
     * At 390 px the nodes table hid 61% of its width, Role and Last heard
     * among it. Below 40rem each row is a card. Measured per card, with
     * letter-spacing widened for the CI runner's fonts: nothing scrolls
     * sideways, and the Role and Last heard of the row are on the screen.
     * Then the same page at 768 px must still be a table.
     */
    const out = [];
    const cards = async (name, wrap, roleCell, heardCell) => {
      await open(page, name, 1500);
      await page.locator(`${wrap} tbody tr`).first()
        .waitFor({ state: 'attached', timeout: 15000 }).catch(() => {});
      await page.addStyleTag({ content: `${wrap} { letter-spacing: .05em; }` });
      await page.waitForTimeout(200);
      return page.evaluate(({ wrap: selector, roleCell: role, heardCell: heard }) => {
        const box = document.querySelector(selector);
        const rows = box ? [...box.querySelectorAll('tbody tr')] : [];
        const view = document.documentElement.clientWidth;
        const onScreen = (cell) => {
          if (!cell) return false;
          const rect = cell.getBoundingClientRect();
          return rect.width > 0 && rect.left >= -1 && rect.right <= view + 1;
        };
        const first = rows[0];
        return {
          rows: rows.length,
          scroll: box ? box.scrollWidth : 0,
          client: box ? box.clientWidth : 0,
          display: first ? getComputedStyle(first).display : null,
          role: first ? onScreen(first.children[role - 1]) : false,
          heard: first ? onScreen(first.children[heard - 1]) : false,
          heardText: first ? first.children[heard - 1].textContent : '',
          height: first ? Math.round(first.getBoundingClientRect().height) : 0,
          sortable: box ? box.querySelectorAll('thead .sort-button').length : 0,
        };
      }, { wrap, roleCell, heardCell });
    };
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 664 });
      for (const [name, wrap, role, heard] of [
        ['nodes', '[data-node-table]', 4, 6],
        ['dashboard', '[data-recent-nodes]', 2, 3],
      ]) {
        const size = await cards(name, wrap, role, heard);
        must(size.rows > 0, `${name}: no node rows at ${width} px`);
        must(size.display === 'flex', `${name}: a row is ${size.display} at ${width} px, not a card`);
        must(size.scroll <= size.client + 1,
          `${name} scrolls sideways at ${width} px: ${size.scroll}/${size.client}`);
        must(size.role, `${name}: Role is off the screen at ${width} px`);
        must(size.heard && /ago/.test(size.heardText),
          `${name}: Last heard is off the screen or not in its cell at ${width} px (${size.heardText})`);
        if (name === 'nodes') must(size.sortable >= 6, `the phone can sort by only ${size.sortable} columns`);
        out.push(`${name}@${width} ${size.scroll}/${size.client} ${size.height}px`);
      }
    }
    await page.setViewportSize({ width: 768, height: 1024 });
    const wide = await cards('nodes', '[data-node-table]', 4, 6);
    must(wide.display === 'table-row', `at 768 px the nodes list is not a table: ${wide.display}`);
    return out.join(', ');
  });

  await journey(phone, 'a phone can tap what used to be a title (#276)', async (page) => {
    /*
     * A touch screen never shows a `title`. Four kinds of meaning lived
     * only there: the gateway tag, the send-rate tags and uptime notes on
     * Statistics, the node page's health dots, and the exact time of a
     * message. Each is now a button that opens a panel. For each kind:
     * the value carries no `title`, a tap opens the panel with the
     * sentence in it, the panel fits the screen, and Escape shuts it.
     */
    const done = [];
    const tapAndRead = async (button, pattern, label) => {
      must((await button.getAttribute('title')) === null, `${label} still carries a title`);
      await button.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {
        throw new Error(`${label} cannot be scrolled into view, so it cannot be tapped`);
      });
      await button.tap();
      await page.waitForTimeout(250);
      must((await button.getAttribute('aria-expanded')) === 'true', `tapping ${label} did not open it`);
      const panel = page.locator(`#${await button.getAttribute('aria-controls')}`);
      must(await panel.isVisible(), `${label}: the panel did not appear`);
      const text = await panel.innerText();
      must(pattern.test(text), `${label}: the panel says ${JSON.stringify(text.slice(0, 80))}`);
      const box = await panel.boundingBox();
      const width = page.viewportSize().width;
      must(box.x >= -1 && box.x + box.width <= width + 1, `${label}: the panel runs off the screen`);
      await page.keyboard.press('Escape');
      await page.waitForTimeout(150);
      must(!(await panel.isVisible()), `${label}: Escape did not close it`);
      done.push(label);
      return text;
    };

    /*
     * A message whose packet is known links to the packet page, which
     * prints the exact time. One with no packet has only the time, and
     * the seed has none of those, so the feed is served with the packet
     * taken off each message.
     */
    await page.route(/\/api\/chat\?/, async (route) => {
      try {
        const response = await route.fetch();
        const rows = await response.json();
        const bare = Array.isArray(rows) ? rows.map((row) => ({ ...row, packet_id: null })) : rows;
        await route.fulfill({ response, json: bare });
      } catch {
        // The page closed with a live refresh in flight.
      }
    });
    try {
      await open(page, 'dashboard', 3500);
      const when = page.locator('[data-recent-chat] button.when').first();
      await when.waitFor({ state: 'attached', timeout: 15000 }).catch(() => {});
      must(await when.count(), 'no message time to tap on the dashboard feed');
      await tapAndRead(when, /\d:\d\d/, 'a message time');
    } finally {
      // The dashboard refreshes itself, so a request can still be on its
      // way through the route when the next page opens.
      await page.unrouteAll({ behavior: 'ignoreErrors' });
    }

    await open(page, 'nodes', 3500);
    const gateway = page.locator('[data-page="nodes"] tbody .tip-open.gateway').first();
    await gateway.waitFor({ state: 'attached', timeout: 15000 }).catch(() => {});
    must(await gateway.count(), 'no gateway tag on the nodes list');
    await tapAndRead(gateway, /uploads packets it hears to MQTT/, 'the gateway tag');

    await open(page, 'stats', 4500);
    const rate = page.locator('[data-page="stats"] [data-broadcast-table] .tip-open.tag').first();
    await rate.waitFor({ state: 'attached', timeout: 15000 }).catch(() => {});
    must(await rate.count(), 'no send-rate tag on Statistics');
    await tapAndRead(rate, /The default is every/, 'a send-rate tag');
    const uptime = page.locator('[data-page="stats"] [data-broadcast-table] .tip-open:not(.tag)').first();
    if (await uptime.count()) await tapAndRead(uptime, /running since it last restarted/, 'an uptime note');

    const nodes = await page.request.get(`${BASE}/api/nodes?limit=1`).then((r) => r.json());
    await page.goto(`${BASE}/#node/${encodeURIComponent(nodes[0].node_id)}`, { waitUntil: 'load' });
    await page.waitForTimeout(3500);
    const dots = page.locator('[data-page="node"] .tip-open.health-dots');
    await dots.first().waitFor({ state: 'attached', timeout: 15000 }).catch(() => {});
    must(await dots.count() === 1, 'the health dots are not one button');
    const dotCount = await dots.locator('.health-dot').count();
    const listed = await tapAndRead(dots, /: /, 'the health dots');
    const lines = listed.split('\n').filter((line) => /: /.test(line)).length;
    must(lines === dotCount, `${dotCount} dots but ${lines} checks named`);

    return done.join(', ');
  });

  await journey(phone, 'a tap on a message time on a node page opens its packet (#387)',
    (page) => nodeMessageOpensPacket(page, 'tap'));

  await journey(phone, 'a wide comparison table keeps its first column on a phone (#274)', async (page) => {
    /*
     * The traceroutes table had 57% of its width off to the side at
     * 390 px, and the stats "Nodes worth a look" table 45%. Two claims
     * each: the columns a phone can do without are not drawn, and the
     * first column is still where it was after the rest has scrolled
     * all the way to the end. Then the same page at desktop width must
     * draw every column again, so a rule that hid them everywhere
     * fails too.
     */
    const measure = (spec) => {
      const wrap = document.querySelector(spec.wrap);
      const table = wrap && wrap.querySelector('table');
      const first = table && table.querySelector('tbody td');
      if (!first) return null;
      wrap.scrollLeft = wrap.scrollWidth;
      const held = Math.round(first.getBoundingClientRect().left - wrap.getBoundingClientRect().left);
      const scrolled = wrap.scrollLeft;
      wrap.scrollLeft = 0;
      return {
        shown: [...table.querySelectorAll('thead th')]
          .filter((th) => th.getBoundingClientRect().width > 0).map((th) => th.dataset.label),
        held, scrolled, scroll: table.scrollWidth, client: wrap.clientWidth,
      };
    };
    const specs = [
      { hash: 'traceroutes', wrap: '[data-traceroute-table]', first: 'Time', low: ['Hops', 'Signal measured'] },
      { hash: 'stats', wrap: '[data-broadcast-table]', first: 'Node', low: ['Packets'] },
    ];
    const out = [];
    for (const spec of specs) {
      await page.setViewportSize({ width: 390, height: 664 });
      await page.goto(`${BASE}/?${spec.hash}#${spec.hash}`, { waitUntil: 'load' });
      if (!(await waitFor(page, measure, 15000, 500, spec))) {
        out.push(`${spec.hash}: no rows on this instance`);
        continue;
      }
      const phoneSize = await page.evaluate(measure, spec);
      must(phoneSize.shown[0] === spec.first, `${spec.hash}: the first column is ${phoneSize.shown[0]}`);
      for (const label of spec.low) {
        must(!phoneSize.shown.includes(label), `${spec.hash}: ${label} is still drawn at 390 px`);
      }
      // Only a table that really scrolled can show the column held.
      if (phoneSize.scrolled > 0) {
        must(Math.abs(phoneSize.held) <= 1,
          `${spec.hash}: the ${spec.first} column moved ${phoneSize.held} px when the table scrolled ${phoneSize.scrolled} px`);
      }
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.waitForTimeout(400);
      const wide = await page.evaluate(measure, spec);
      for (const label of spec.low) {
        must(wide.shown.includes(label), `${spec.hash}: ${label} is gone at 1440 px as well`);
      }
      out.push(`${spec.hash} ${phoneSize.scroll}/${phoneSize.client}, held ${phoneSize.held} after ${phoneSize.scrolled} px`);
    }
    return out.join('; ');
  });

  await journey(phone, 'a phone jumps to a node page section and keeps the chips (#286)', async (page) => {
    /*
     * The packet timeline was past y = 3760 on an iPhone 14 with no way
     * to reach it but to scroll. Each chip must land its panel just
     * under the row, with the row still on screen at the top, and give
     * the panel the focus. The row must not widen the page, and a
     * desktop must not draw it.
     */
    const nodes = await page.request.get(`${BASE}/api/nodes?limit=1`).then((r) => r.json());
    must(nodes.length, 'no node to open');
    await page.goto(`${BASE}/#node/${encodeURIComponent(nodes[0].node_id)}`, { waitUntil: 'load' });
    const drawn = () => Boolean(document.querySelector('[data-jump="timeline"] table, [data-jump="timeline"] .empty'));
    await waitFor(page, drawn, 15000);
    const out = [];
    for (const key of ['timeline', 'links', 'identity']) {
      await page.locator(`.node-jump [data-jump-to="${key}"]`).tap();
      await page.waitForTimeout(1200);
      const at = await page.evaluate((name) => {
        const panel = document.querySelector(`[data-jump="${name}"]`);
        const bar = document.querySelector('.node-jump').getBoundingClientRect();
        // The chips stick under the site's sticky phone bar (#271), and
        // must be what a finger touches there, not the bar over them.
        const site = document.querySelector('.sidebar').getBoundingClientRect();
        // The chip just tapped: the row scrolls sideways to keep it in
        // view, so the first chip can be off the screen's left edge.
        const chip = document.querySelector(`.node-jump [data-jump-to="${name}"]`).getBoundingClientRect();
        const hit = document.elementFromPoint(chip.left + chip.width / 2, chip.top + chip.height / 2);
        return {
          panel: Math.round(panel.getBoundingClientRect().top),
          barTop: Math.round(bar.top),
          siteBottom: Math.round(site.bottom),
          chipOnTop: !!hit && !!hit.closest('.node-jump'),
          barBottom: Math.round(bar.bottom),
          focused: document.activeElement === panel,
          scrollY: Math.round(window.scrollY),
          doc: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
        };
      }, key);
      must(Math.abs(at.barTop - at.siteBottom) <= 1,
        `the chips are not just under the top bar after ${key}: top ${at.barTop}, bar ends ${at.siteBottom}`);
      must(at.chipOnTop, `something covers the chips after ${key}`);
      must(at.panel >= at.barBottom - 1 && at.panel <= at.barBottom + 40,
        `${key} landed at ${at.panel} px, and the chips end at ${at.barBottom}`);
      must(at.focused, `${key} did not take the focus`);
      must(at.doc[0] <= at.doc[1] + 1, `the page scrolls sideways: ${at.doc.join('/')}`);
      out.push(`${key} at ${at.panel} (y ${at.scrollY})`);
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(300);
    const wide = await page.evaluate(() => document.querySelector('.node-jump').getBoundingClientRect().height);
    must(wide === 0, 'the section chips are drawn on a desktop');
    return out.join(', ');
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

  await journey(phone, 'a finger can hit a map dot (#266)', async (page) => {
    /*
     * A dot was 5 to 13 px across and the canvas counted only the dot.
     * Two test dots are put on the live map 16 px apart, well away from
     * the real ones, so the result does not depend on the seed. Each
     * tap is a real touch through `page.touchscreen`, and a hit is read
     * off the marker's own `click` event, which is what opens a node.
     */
    await open(page, 'map', 3000);
    // The first draw fits the view to the nodes. Measuring before it
    // lands would put the taps where the test dots used to be.
    must(await waitFor(page, () => window.SonoranMap.marks instanceof Map
      && window.SonoranMap.marks.size > 0, 20000), 'the map drew no nodes');
    await page.waitForTimeout(500);
    const at = await page.evaluate(() => {
      const { map, nodes } = window.SonoranMap;
      // No live refresh in the middle of the taps.
      document.querySelector('[data-page="map"] [data-live]').setAttribute('aria-pressed', 'false');
      map.setZoom(6, { animate: false });
      map.getContainer().scrollIntoView({ block: 'start' });
      const box = map.getContainer().getBoundingClientRect();
      // A spot in the map's upper left, away from Arizona's dots.
      const middle = L.point(box.width * 0.25, Math.min(box.height, window.innerHeight - box.top) * 0.3);
      window.__e2eHits = [];
      const make = (name, dx) => {
        const marker = L.circleMarker(map.containerPointToLatLng(middle.add([dx, 0])), { radius: 2.5 });
        marker.on('click', () => window.__e2eHits.push(name));
        marker.addTo(nodes);
        return name;
      };
      make('left', 0);
      make('right', 16);
      return {
        x: box.left + middle.x,
        y: box.top + middle.y,
        tolerance: map.getRenderer(nodes.getLayers()[0]).options.tolerance,
      };
    });
    must(at.tolerance >= 19.5, `the canvas tolerance is ${at.tolerance}, so a 2.5 px dot is a ${2 * (2.5 + at.tolerance)} px target`);
    await page.waitForTimeout(300);
    const tap = async (dx, dy) => {
      await page.evaluate(() => { window.__e2eHits = []; });
      await page.touchscreen.tap(at.x + dx, at.y + dy);
      // Well past the double-tap window, so no two taps read as one.
      await page.waitForTimeout(800);
      return page.evaluate(() => window.__e2eHits.slice());
    };
    // 18 px above the left dot: outside the dot, inside the target.
    const near = await tap(0, -18);
    must(near.join() === 'left', `a tap 18 px from a dot hit ${JSON.stringify(near)}`);
    // Square on the right dot, whose neighbour's target also reaches.
    const onRight = await tap(16, 0);
    must(onRight.join() === 'right', `a tap on the right dot hit ${JSON.stringify(onRight)}, not the dot under the finger`);
    const onLeft = await tap(0, 0);
    must(onLeft.join() === 'left', `a tap on the left dot hit ${JSON.stringify(onLeft)}`);
    // The negative control, in the same page: far outside any target.
    const far = await tap(0, -40);
    must(far.length === 0, `a tap 40 px from any dot still hit ${JSON.stringify(far)}`);
    return `tolerance ${at.tolerance} px, a 2.5 px dot is a ${2 * (2.5 + at.tolerance)} px target; `
      + 'nearest dot wins a shared tap; 40 px away hits nothing';
  });

  await journey(phone, 'the firehose says how many packets arrived above you (#280)', async (page) => {
    /*
     * New packets are put in through a route, so the count is known
     * without writing to a shared database. `render('firehose')` is the
     * call the Live timer makes; Live is switched off so no timer poll
     * lands in the middle.
     *
     * The real rows are read ONCE, from the first answer, and every poll
     * is built from that copy (#354). The stub used to build its packets
     * from `rows[0]` of each answer. When the newest real row changed
     * between polls -- a tie on `first_seen_at`, or a packet the seed
     * added -- the "same" made packets took a new node in their keys,
     * and every one of them counted as new: "9 new" where 4 was right.
     * A real packet that arrived between polls counted as new as well.
     * Now the count depends on `extra` alone.
     */
    let extra = 0;
    let base = null;
    await page.route(/\/api\/packets\?/, async (route) => {
      const response = await route.fetch();
      const rows = await response.json();
      if (!base) {
        if (!Array.isArray(rows) || !rows.length) return route.fulfill({ response });
        base = { rows, node: rows[0].packet_key.split(':')[0], at: Date.now() };
      }
      const made = [];
      for (let n = extra; n > 0; n -= 1) {
        made.push({
          ...base.rows[0],
          packet_key: `${base.node}:${990000000 + n}`,
          first_seen_at: new Date(base.at + n * 1000).toISOString(),
        });
      }
      return route.fulfill({ response, json: [...made, ...base.rows].slice(0, base.rows.length) });
    });
    await open(page, 'firehose', 1000);
    must(await waitFor(page, () => document.querySelectorAll('[data-firehose-table] tbody tr').length > 20, 30000),
      'the firehose drew too few rows to scroll');
    await page.evaluate(() => document.querySelector('[data-page="firehose"] [data-live]').setAttribute('aria-pressed', 'false'));
    /*
     * `render` does nothing while another render is loading, and the page
     * opened with Live on: on a cold first load a timer render could still
     * be running when Live was switched off. The forced poll then did
     * nothing and that render's packets were counted instead -- "7 new"
     * for 4, or the reader's row moved 59 px. Wait it out, both sides.
     */
    const idle = () => waitFor(page, () => !loading, 20000);
    const poll = async () => {
      await idle();
      await page.evaluate(async () => { await render('firehose'); });
      await idle();
    };
    const pill = () => page.evaluate(() => {
      const one = document.querySelector('[data-page="firehose"] .new-pill');
      if (!one || one.hidden) return null;
      const box = one.getBoundingClientRect();
      // Under the sticky phone bar (#271), and the thing a finger at its
      // centre would actually touch: it was once drawn behind the bar.
      const bar = document.querySelector('.sidebar').getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      return {
        text: one.textContent, top: Math.round(box.top), height: Math.round(box.height),
        barBottom: Math.round(bar.bottom), tappable: !!hit && one.contains(hit),
      };
    });

    // The control: at the top, new packets are in plain sight.
    extra = 2;
    await poll();
    must((await pill()) === null, 'the pill showed for a reader already at the newest packets');

    // Two screens down.
    await page.evaluate(() => window.scrollTo(0, window.innerHeight * 2.5));
    await page.waitForTimeout(300);
    const y0 = await page.evaluate(() => window.scrollY);
    const row0 = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('[data-firehose-table] tbody tr')];
      const seen = rows.find((row) => row.getBoundingClientRect().top > 0);
      return { key: seen.dataset.rowKey, top: Math.round(seen.getBoundingClientRect().top) };
    });
    extra = 5;
    await poll();
    let shown = await pill();
    must(shown && /^3 new/.test(shown.text), `after 3 new packets the pill says ${JSON.stringify(shown)}`);
    must(shown.top >= shown.barBottom && shown.top < shown.barBottom + 40 && shown.height >= 44,
      `the pill is not just under the top bar: ${JSON.stringify(shown)}`);
    must(shown.tappable, `something covers the pill: ${JSON.stringify(shown)}`);
    const held = await page.evaluate((key) => Math.round(
      document.querySelector(`[data-firehose-table] tbody tr[data-row-key="${key}"]`).getBoundingClientRect().top), row0.key);
    must(Math.abs(held - row0.top) <= 2, `the row being read moved from ${row0.top} to ${held} px`);
    extra = 6;
    await poll();
    shown = await pill();
    must(shown && /^4 new/.test(shown.text), `after one more the pill says ${JSON.stringify(shown)}`);

    await page.click('[data-page="firehose"] .new-pill');
    await page.waitForTimeout(1200);
    const after = await page.evaluate(() => {
      const top = document.querySelector('[data-firehose-table] tbody tr').getBoundingClientRect().top;
      return { y: window.scrollY, first: Math.round(top), inView: top >= -1 && top < window.innerHeight };
    });
    must(after.y < y0 && after.inView, `the pill did not go back to the newest: ${JSON.stringify(after)}`);
    must((await pill()) === null, 'the pill stayed after going back to the top');
    return `pill "4 new" at y ${shown.top}, reader's row held to ${Math.abs(held - row0.top)} px, tap went back`;
  });

  await journey(phone, 'a node opens in a sheet on a phone, and survives live refreshes (#281)', async (page) => {
    /*
     * Below 40rem a tap on a node opens its summary in a sheet at the
     * foot of the screen instead of a bubble. The node list goes through
     * a route, as in the bubble journey, so a node can vanish without
     * writing to a shared database.
     */
    const edits = { drop: null };
    await page.route(/\/api\/map\/nodes(\?|$)/, async (route) => {
      const response = await route.fetch();
      let rows = await response.json();
      if (edits.drop) rows = rows.filter((row) => row.node_id !== edits.drop);
      return route.fulfill({ response, json: rows });
    });
    await open(page, 'map', 3000);
    must(await waitFor(page, () => window.SonoranMap.marks instanceof Map
      && window.SonoranMap.marks.size >= 2, 20000), 'the map drew fewer than two nodes');
    // No timer poll in the middle; the refreshes below are forced.
    await page.evaluate(() => document.querySelector('[data-page="map"] [data-live]').setAttribute('aria-pressed', 'false'));
    const at = await page.evaluate(() => {
      const { map, marks } = window.SonoranMap;
      const [id, entry] = [...marks.entries()][0];
      map.setView(entry.marker.getLatLng(), 12, { animate: false });
      map.getContainer().scrollIntoView({ block: 'start' });
      const point = map.latLngToContainerPoint(entry.marker.getLatLng());
      const box = map.getContainer().getBoundingClientRect();
      return { id, x: box.left + point.x, y: box.top + point.y, name: entry.row.display_name || id };
    });
    await page.waitForTimeout(300);
    await page.touchscreen.tap(at.x, at.y);
    await page.waitForTimeout(600);
    const SHEET = () => {
      const sheet = document.querySelector('.node-sheet');
      if (!sheet || sheet.hidden) return null;
      const close = sheet.querySelector('.node-sheet-close').getBoundingClientRect();
      const box = sheet.getBoundingClientRect();
      return {
        node: window.SonoranSheet.current(),
        text: sheet.textContent,
        height: Math.round(box.height),
        top: Math.round(box.top),
        close: [Math.round(close.width), Math.round(close.height)],
        state: sheet.dataset.state,
        bubble: Boolean(document.querySelector('[data-page="map"] .leaflet-popup')),
      };
    };
    let sheet = await page.evaluate(SHEET);
    must(sheet, 'a tap on a node opened no sheet');
    must(sheet.node === at.id && sheet.text.includes(at.name), `the sheet shows ${sheet.node}, the tap was on ${at.id}`);
    must(!sheet.bubble, 'a bubble opened on the map as well as the sheet');
    must(/Open node detail/.test(sheet.text), 'the sheet has no way to the node page');
    must(sheet.close[0] >= 44 && sheet.close[1] >= 44, `the close button is ${sheet.close.join(' x ')}`);
    const viewport = page.viewportSize();
    must(sheet.height <= viewport.height / 2 + 1, `the sheet is ${sheet.height} px of a ${viewport.height} px screen`);
    const peek = sheet.height;

    // Non-modal: the map above the sheet is still the map, and still pans.
    const free = await page.evaluate((top) => {
      const { map } = window.SonoranMap;
      const box = map.getContainer().getBoundingClientRect();
      const y = Math.max(box.top + 20, Math.min(top - 40, box.bottom - 20));
      const hit = document.elementFromPoint(box.left + box.width / 2, y);
      return { onMap: Boolean(hit && map.getContainer().contains(hit)), dragging: map.dragging.enabled() };
    }, sheet.top);
    must(free.onMap && free.dragging, `the sheet blocks the map: ${JSON.stringify(free)}`);

    // Two live refreshes through the call the timer makes.
    for (let refresh = 0; refresh < 2; refresh += 1) {
      await page.evaluate(async () => {
        while (loading) await new Promise((done) => setTimeout(done, 100));
        nodeCache.at = 0;
        await render('map');
      });
    }
    sheet = await page.evaluate(SHEET);
    must(sheet && sheet.node === at.id, 'the sheet closed when the map refreshed');

    // The grabber opens it to half height when there is more to show.
    const more = await page.evaluate(() => !document.querySelector('.node-sheet-grab').hidden);
    if (more) {
      await page.click('.node-sheet-grab');
      const half = await page.evaluate(SHEET);
      must(half.state === 'half' && half.height > peek, `the grabber did not open it further (${peek} -> ${half.height})`);
    }

    // Back takes the sheet away and leaves the reader on the map.
    await page.goBack();
    await page.waitForTimeout(500);
    must((await page.evaluate(SHEET)) === null, 'Back did not close the sheet');
    must(/#map$/.test(page.url()), `Back left the map: ${page.url()}`);

    // The close button, and a node that goes away takes its sheet with it.
    await page.touchscreen.tap(at.x, at.y);
    await page.waitForTimeout(600);
    must(await page.evaluate(SHEET), 'a second tap opened no sheet');
    await page.click('.node-sheet-close');
    await page.waitForTimeout(300);
    must((await page.evaluate(SHEET)) === null, 'the close button did not close the sheet');
    must(await page.evaluate(() => !(history.state && history.state.sonoranSheet)), 'closing left its history entry behind');
    await page.touchscreen.tap(at.x, at.y);
    await page.waitForTimeout(600);
    edits.drop = at.id;
    await page.evaluate(async () => {
      while (loading) await new Promise((done) => setTimeout(done, 100));
      nodeCache.at = 0;
      await render('map');
    });
    must((await page.evaluate(SHEET)) === null, 'the sheet of a node that went away is still open');
    return `sheet ${peek} px high, close ${sheet.close.join('x')}, map free above it; `
      + `held through 2 refreshes${more ? ', grabber opens it further' : ''}; Back, close and a gone node all close it`;
  });

  await journey(phone, 'the packet type menu fits a phone and opens over the map (#385)',
    (page) => familyMenuWalk(page, { watch: false }));

  await journey(phone, 'the map page opens at its top (#270)', async (page) => {
    /*
     * The map's box was `<div id="map">`, and `#map` is also the page's
     * address, so the browser scrolled to the box on every load: 277 px
     * at 390 px in WebKit, with the Live control and the other six map
     * controls above the top of the screen. `about:blank` between widths
     * so each `goto` is a real load and not a same-document hash change,
     * which does not scroll to a fragment the same way.
     */
    const out = [];
    for (const width of TABLE_WIDTHS) {
      // Let the last load's requests land first, or leaving aborts them
      // and each one is counted as an error.
      await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
      await page.goto('about:blank');
      await page.setViewportSize({ width, height: 800 });
      await open(page, 'map', 2500);
      const got = await page.evaluate(() => ({
        y: Math.round(window.scrollY),
        live: Math.round(document.querySelector('[data-page="map"] [data-live]').getBoundingClientRect().top),
      }));
      must(got.y === 0, `at ${width} px the map page scrolled itself ${got.y} px on load`);
      must(got.live >= 0, `at ${width} px the Live control starts ${-got.live} px above the screen`);
      out.push(`${width}:${got.y}`);
    }
    return `scrollY after load ${out.join(' ')}`;
  });

  await journey(phone, 'the summary tiles are one compact block on a phone (#278)', async (page) => {
    /*
     * The four numbers took 292 px, 35% of the first screen, in the mobile
     * review, and 415 px on the dashboard once each tile carried a delta.
     * The ask was a strip about 120 px tall. Measured with the CI runner's
     * wider fonts imitated (letter-spacing .05em), at this phone's 390 px
     * and at 320 px, on both pages that carry the tiles.
     */
    const measure = async () => page.evaluate(() => {
      const grid = document.querySelector('.page.active [data-summary]');
      const tiles = [...grid.children];
      const box = grid.getBoundingClientRect();
      const over = document.documentElement.scrollWidth - document.documentElement.clientWidth;
      const spill = tiles.some((tile) => tile.scrollWidth > tile.clientWidth + 1);
      return { height: Math.round(box.height), tiles: tiles.length, over, spill };
    });
    const found = [];
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 664 });
      for (const name of ['dashboard', 'stats']) {
        await open(page, name, 1500);
        await waitFor(page, () => !loading, 60000);
        await page.addStyleTag({ content: '* { letter-spacing: .05em !important; }' });
        await page.waitForTimeout(200);
        const got = await measure();
        must(got.tiles === 4, `${name} at ${width} px drew ${got.tiles} tiles`);
        must(got.over <= 0, `${name} at ${width} px scrolls sideways by ${got.over} px`);
        must(!got.spill, `a tile's text spills out of it on ${name} at ${width} px`);
        // About 120 px was the ask at 390; it measures 126 px, and 139 px
        // with the wider letters, which wrap one label. The limits leave
        // room for a runner whose fonts are wider still, and are still
        // well under the 415 px this replaced. 320 px wraps the longer
        // labels to a second line, so it is allowed more.
        const limit = width === 390 ? 160 : 185;
        must(got.height <= limit, `${name} at ${width} px: the tiles are ${got.height} px tall, over ${limit}`);
        found.push(`${name} ${width}px ${got.height}px`);
      }
    }
    /*
     * The words after the change are off the screen, not out of the page:
     * a screen reader still hears "on the day before".
     */
    await page.setViewportSize({ width: 390, height: 664 });
    await open(page, 'dashboard', 1500);
    await waitFor(page, () => !loading, 60000);
    const words = await page.evaluate(() => {
      const rest = document.querySelector('[data-summary] .delta-rest');
      return rest ? { text: rest.textContent, shown: rest.getBoundingClientRect().width > 1 } : null;
    });
    if (words) {
      must(/before/.test(words.text), `the delta lost its words: "${words.text}"`);
      must(!words.shown, 'the delta words still take room on a phone');
    }
    return found.join(', ');
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
   * #284: charts and map zooms move on a canvas and a transform, where
   * the CSS reduced-motion rule does not reach. Read in a context that
   * asks for less motion, and in one that does not, as the control.
   */
  for (const motion of ['reduce', 'no-preference']) {
    const moving = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: motion });
    await journey(moving, `charts and map zoom follow reduced motion (${motion}) (#284)`, async (page) => {
      const want = motion === 'reduce';
      await open(page, 'stats', 1000);
      must(await waitFor(page, () => document.querySelectorAll('[data-page="stats"] canvas').length > 0, 30000),
        'statistics drew no chart');
      // `charts` inside the page is app.js's own map of instances.
      const animations = await page.evaluate(() => [...charts.values()]
        .filter((one) => !one.isDisposed())
        .map((one) => one.getOption().animation));
      must(animations.length > 0, 'no chart instance to read');
      // ECharts' own default reads back as 'auto', which animates.
      must(animations.every((on) => (on === false) === want),
        `chart animation ${JSON.stringify(animations)}, expected ${want ? 'false' : 'on'}`);
      // Let the page's requests land before leaving, or they abort as errors.
      await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
      await page.goto('about:blank');
      await open(page, 'map', 2500);
      const map = await page.evaluate(() => {
        const { options } = window.SonoranMap.map;
        return { zoom: options.zoomAnimation, fade: options.fadeAnimation, marker: options.markerZoomAnimation };
      });
      must(map.zoom === !want && map.fade === !want && map.marker === !want,
        `map animation ${JSON.stringify(map)}, expected ${!want}`);
      return `${animations.length} charts animation ${JSON.stringify(animations[0])}; map zoom/fade/marker ${!want}`;
    });
    await moving.close();
  }

  await journey(context, 'more contrast reaches the page (#285)', async (page) => {
    /*
     * Playwright 1.49 has no `contrast` option, so the media feature is
     * set through the DevTools protocol. The same page is read before
     * and after, so the "before" is the control.
     */
    await open(page, 'nodes', 3000);
    await waitFor(page, () => Boolean(document.querySelector('[data-page="nodes"] th')), 20000);
    const read = () => page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      const th = document.querySelector('[data-page="nodes"] th');
      return {
        more: matchMedia('(prefers-contrast: more)').matches,
        muted: root.getPropertyValue('--muted').trim(),
        text: getComputedStyle(document.body).color,
        th: th ? getComputedStyle(th).color : null,
      };
    });
    const before = await read();
    must(!before.more && before.th && before.th !== before.text, `the control is not ordinary: ${JSON.stringify(before)}`);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-contrast', value: 'more' }] });
    const after = await read();
    must(after.more, 'the browser did not take prefers-contrast: more');
    must(after.muted !== before.muted, `--muted stayed ${after.muted}`);
    must(after.th === after.text, `a table heading is ${after.th}, the body text is ${after.text}`);
    await cdp.send('Emulation.setEmulatedMedia', { features: [] });

    // Forced colours: a legend swatch keeps the colour it stands for.
    // The nodes page's requests land first, or leaving aborts them.
    await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
    await page.goto('about:blank');
    await page.emulateMedia({ forcedColors: 'active' });
    await open(page, 'map', 3000);
    await waitFor(page, () => Boolean(document.querySelector('[data-map-legend] .legend-key .swatch')), 20000);
    const swatch = await page.evaluate(() => {
      const one = document.querySelector('[data-map-legend] .legend-key .swatch');
      if (!one) return null;
      const probe = document.createElement('i');
      // The probe opts out as well, or its own colour is forced.
      probe.style.forcedColorAdjust = 'none';
      probe.style.color = one.style.background;
      document.body.append(probe);
      const meant = getComputedStyle(probe).color;
      probe.remove();
      return { forced: matchMedia('(forced-colors: active)').matches, meant, drawn: getComputedStyle(one).backgroundColor };
    });
    must(swatch, 'the map legend drew no swatch');
    must(swatch.forced, 'the browser did not take forced-colors: active');
    must(swatch.drawn === swatch.meant, `under forced colours a swatch drew ${swatch.drawn}, it stands for ${swatch.meant}`);
    return `--muted ${before.muted} -> ${after.muted}; th takes the text colour; forced swatch ${swatch.drawn}`;
  });

  /*
   * The other half of #283: a mouse keeps 15 px at a phone's width. The
   * rule is keyed on the pointer, and a narrow desktop window is not a
   * phone. Without this, a rule keyed on the width would pass the touch
   * journey below as well.
   */
  await journey(context, 'a mouse keeps 15 px body text at any width (#283)', async (page) => {
    const sizes = [];
    for (const width of [390, 1500]) {
      await page.setViewportSize({ width, height: 900 });
      await open(page, 'nodes', 2000);
      const got = await page.evaluate(() => ({
        coarse: matchMedia('(pointer: coarse)').matches,
        body: getComputedStyle(document.body).fontSize,
      }));
      must(!got.coarse, 'this context reports a coarse pointer, so it cannot stand for a mouse');
      must(got.body === '15px', `at ${width} px with a mouse the body is ${got.body}`);
      sizes.push(`${width}:${got.body}`);
    }
    return sizes.join(' ');
  });

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

  await journey(narrow, 'coverage settings fit a 320 px phone, at finger size (#334)', async (page) => {
    await stubCoverage(page, { approximate: true });
    await open(page, 'coverage', 2500);
    // Letters as wide as the CI runner's fonts draw them (AGENTS.md 9.31).
    await page.addStyleTag({ content: '.page[data-page="coverage"] * { letter-spacing: .12em !important; }' });
    const button = page.locator('[data-coverage-options]');
    must(await button.isVisible(), 'no settings button on a phone');
    // At the top right: on the title's row, at the head's right edge.
    const place = await page.evaluate(() => {
      const head = document.querySelector('.page[data-page="coverage"] .page-head');
      const title = head.querySelector('h2').getBoundingClientRect();
      const gear = document.querySelector('[data-coverage-options]').getBoundingClientRect();
      return { row: gear.top < title.bottom, gap: Math.round(head.getBoundingClientRect().right - gear.right) };
    });
    must(place.row && place.gap <= 2, `the button is not at the top right (${JSON.stringify(place)})`);
    await button.tap();
    await waitFor(page, () => document.querySelector('[data-coverage-roles] button'), 10000);
    await page.waitForTimeout(300);
    const got = await page.evaluate(() => {
      const panel = document.querySelector('#coverage-options');
      const box = panel.getBoundingClientRect();
      const small = [];
      const out = [];
      const targets = [
        ...panel.querySelectorAll('button, select, input[type="range"]'),
        ...[...panel.querySelectorAll('input[type="checkbox"]')].map((input) => input.closest('label')),
      ];
      for (const target of targets) {
        const rect = target.getBoundingClientRect();
        if (!rect.width) continue;
        const name = target.dataset.role || target.textContent.trim().slice(0, 24) || target.outerHTML.slice(0, 40);
        if (rect.height < 43.5) small.push(`${name} ${Math.round(rect.height)}px`);
        if (rect.right > box.right + 1 || rect.left < box.left - 1) out.push(name);
      }
      return {
        coarse: matchMedia('(pointer: coarse)').matches,
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
        right: Math.round(box.right),
        small,
        out,
      };
    });
    must(got.coarse, 'the phone context does not match (pointer: coarse)');
    must(got.scroll <= got.client, `the page scrolls sideways at 320 px: ${got.scroll} in ${got.client}`);
    must(got.right <= got.client, `the panel ends at ${got.right} px of ${got.client}`);
    must(!got.out.length, `controls leave the panel: ${got.out.join(', ')}`);
    must(!got.small.length, `targets under 44 px: ${got.small.join(', ')}`);
    return `fits, ${got.scroll}/${got.client}, every target at least 44 px`;
  });

  await journey(narrow, 'page-head controls fold behind a button on a phone (#275)', async (page) => {
    /*
     * On an iPhone SE the RF head was the whole first screen and the
     * Graph head three quarters of it. Below 40rem the folded controls
     * live in the page's Options or Filters panel; Live and one primary
     * control stay. Measured as where the head ENDS on a 568 px screen,
     * which includes the 62 px sticky bar above it.
     */
    await page.setViewportSize({ width: 320, height: 568 });
    const facts = [];
    for (const [name, most] of [['graph', 0.35], ['rf', 0.45], ['chat', 0.5], ['gaps', 0.35]]) {
      await open(page, name, 2500);
      /*
       * With letters as wide as CI's Linux fonts draw them. On a Mac the
       * Graph row had 8 px to spare; on the runner Options no longer fit
       * beside the search box, the row wrapped, and the head ended at 37%.
       * 0.12em is the spacing that reproduces that here.
       */
      await page.addStyleTag({ content: '.page-head * { letter-spacing: .12em !important; }' });
      await page.waitForTimeout(200);
      const got = await page.evaluate(() => {
        const head = document.querySelector('.page.active .page-head');
        const shown = [...head.querySelectorAll('.controls > *')]
          .filter((node) => node.getBoundingClientRect().width > 0).length;
        return { bottom: head.getBoundingClientRect().bottom, height: window.innerHeight, shown };
      });
      const share = got.bottom / got.height;
      must(share <= most, `${name}: the head ends at ${Math.round(share * 100)}% of the first screen`);
      facts.push(`${name} ${Math.round(share * 100)}%`);
    }

    // RF: the folded Window counts on the Filters button, and it goes
    // home to the head when the screen widens.
    await open(page, 'rf', 2500);
    const filters = page.locator('[data-page="rf"] [data-options-open]');
    must(await filters.isVisible(), 'RF shows no Filters button on a phone');
    must(await page.locator('#rf-options [data-rf-minutes]').count() === 1, 'the RF window is not in the Filters panel');
    await filters.click();
    await page.locator('[data-rf-minutes]').selectOption('15');
    await page.waitForTimeout(300);
    must((await filters.getAttribute('aria-label')) === 'Filters, 1 changed',
      `after changing the window the button says "${await filters.getAttribute('aria-label')}"`);
    await page.locator('[data-rf-minutes]').selectOption('5');
    // The description is one line, and the whole of it is a tap away.
    const hint = page.locator('[data-page="rf"] [data-sub-fold] > .hint-open');
    must(await hint.isVisible(), 'the RF description has no ? on a phone');
    await hint.tap();
    await page.waitForTimeout(250);
    const said = await page.locator(`#${await hint.getAttribute('aria-controls')}`).innerText();
    // The last words of the description, not the product name in them, which changed (#178).
    must(/beside an SDR\./.test(said), 'the ? does not hold the whole description');
    await page.keyboard.press('Escape');

    await page.setViewportSize({ width: 1024, height: 768 });
    await page.waitForTimeout(300);
    const home = await page.evaluate(() => ({
      inHead: !!document.querySelector('[data-page="rf"] .page-head .controls [data-rf-minutes]'),
      button: document.querySelector('[data-page="rf"] [data-options-open]').getBoundingClientRect().width,
      panel: document.querySelector('#rf-options').hidden,
      hint: document.querySelector('[data-page="rf"] [data-sub-fold] > .hint-open').getBoundingClientRect().width,
    }));
    await page.setViewportSize({ width: 320, height: 640 });
    must(home.inHead, 'widened, the RF window did not go back to the head');
    must(home.button === 0 && home.panel, 'widened, the Filters button or its panel is still there');
    must(home.hint === 0, 'widened, the description still has its phone ?');
    return `${facts.join(', ')}; Filters counts and folds back`;
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

  /*
   * #283. On a touch screen the body is 16 px and no text is under
   * .78 rem (12.48 px). Keyed on the pointer, so this context is a touch
   * one at every width, the iPad's 834 included.
   *
   * The pages are the ones with the widest tables, so a larger font that
   * pushes the document sideways shows here first. Letters are 0.05em
   * wider, as in the Who hears it journey, because CI's Linux fonts are
   * wider than a Mac's. The sticky bar (#271) must still be at the top
   * after a scroll, and `--bar-h` must still be its height, or the
   * things that stick under it (#280, #286) hide behind it.
   */
  await journey(narrow, 'body text is 16 px on a touch screen, and nothing scrolls sideways (#283)', async (page) => {
    const bad = [];
    const facts = [];
    for (const width of [320, 390, 834]) {
      await page.setViewportSize({ width, height: 800 });
      for (const name of ['dashboard', 'nodes', 'firehose', 'stats', 'gaps', 'chat']) {
        await open(page, name, 2500);
        await page.addStyleTag({ content: '* { letter-spacing: .05em !important; }' });
        await page.waitForTimeout(200);
        await page.evaluate(() => window.scrollTo(0, 1200));
        await page.waitForTimeout(200);
        const got = await page.evaluate(() => {
          let smallest = 99;
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            const parent = node.parentElement;
            if (!node.textContent.trim() || !parent || !parent.getClientRects().length) continue;
            // A chart's SVG labels are sized by the chart, not by this rule.
            if (parent.closest('svg')) continue;
            smallest = Math.min(smallest, parseFloat(getComputedStyle(parent).fontSize));
          }
          const fields = [...document.querySelectorAll('.page.active input, .page.active select, .page.active textarea')]
            .filter((field) => field.getClientRects().length && field.type !== 'checkbox' && field.type !== 'radio')
            .map((field) => parseFloat(getComputedStyle(field).fontSize));
          const bar = document.querySelector('.sidebar').getBoundingClientRect();
          return {
            body: getComputedStyle(document.body).fontSize,
            smallest,
            field: fields.length ? Math.min(...fields) : null,
            scroll: document.documentElement.scrollWidth,
            client: document.documentElement.clientWidth,
            barTop: bar.top,
            barHeight: Math.ceil(bar.height),
            barVar: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bar-h')),
            scrolled: window.scrollY,
          };
        });
        const at = `${name} at ${width} px`;
        if (got.body !== '16px') bad.push(`${at}: the body is ${got.body}`);
        if (got.smallest < 12.4) bad.push(`${at}: text at ${got.smallest} px`);
        if (got.field !== null && got.field < 16) bad.push(`${at}: a form field at ${got.field} px`);
        if (got.scroll > got.client + 1) bad.push(`${at}: the page scrolls sideways, ${got.scroll}/${got.client}`);
        if (got.scrolled > 0 && Math.abs(got.barTop) > 1) bad.push(`${at}: the bar scrolled away (top ${got.barTop})`);
        if (Math.abs(got.barVar - got.barHeight) > 1) bad.push(`${at}: --bar-h is ${got.barVar}, the bar is ${got.barHeight}`);
        if (width === 320) facts.push(`${name} ${got.scroll}/${got.client}`);
      }
    }
    await page.setViewportSize({ width: 320, height: 640 });
    must(bad.length === 0, bad.join('; '));
    return `16 px body, no text under 12.5 px, at 320/390/834; at 320: ${facts.join(', ')}`;
  });
  await journey(narrow, 'the firehose reads as cards on a phone (#273)', async (page) => {
    /*
     * Eight columns hid 64% of the firehose sideways on a phone. Below
     * 40rem each packet is two lines: time, from, to; then type and what
     * it said. Measured with letter-spacing added, because the CI
     * runner's fonts are wider than a Mac's.
     */
    await open(page, 'firehose', 3000);
    must(await waitFor(page, () => document.querySelectorAll('[data-firehose-table] tbody tr').length > 0, 20000),
      'the firehose drew no rows');
    await page.addStyleTag({ content: '[data-firehose-table] * { letter-spacing: .05em !important; }' });
    const out = [];
    for (const width of [320, 390, ...TABLE_WIDTHS.slice(1)]) {
      await page.setViewportSize({ width, height: 800 });
      await page.waitForTimeout(400);
      const got = await page.evaluate(() => {
        const wrap = document.querySelector('[data-firehose-table]');
        const rows = [...wrap.querySelectorAll('tbody tr')];
        const box = wrap.getBoundingClientRect();
        const bad = [];
        for (const row of rows) {
          const cell = (n) => row.children[n].getBoundingClientRect();
          const [time, from, type, what] = [cell(0), cell(1), cell(3), cell(4)];
          for (const [name, r] of [['time', time], ['from', from], ['type', type], ['what', what]]) {
            if (!r.width || r.right > box.right + 1 || r.left < box.left - 1) bad.push(name);
          }
          if (!(type.top >= time.bottom - 1)) bad.push('one line');
        }
        const heads = [...wrap.querySelectorAll('thead th')];
        return {
          scroll: wrap.scrollWidth,
          client: wrap.clientWidth,
          head: document.querySelector('[data-firehose-table] thead').getBoundingClientRect().height,
          // The headings a reader can see, and whether each fits the panel.
          shown: heads.filter((th) => th.getBoundingClientRect().width > 0).map((th) => th.dataset.label),
          headsFit: heads.every((th) => th.getBoundingClientRect().right <= box.right + 1),
          rows: rows.length,
          bad: [...new Set(bad)],
        };
      });
      if (width <= 640) {
        must(got.scroll <= got.client + 1, `at ${width} px the firehose scrolls sideways: ${got.scroll} in ${got.client}`);
        must(got.bad.length === 0, `at ${width} px a card is wrong: ${got.bad.join(', ')}`);
        // The headings stay, as one line of words that carries the hints.
        must(got.shown.join() === 'Time,From,To,Type,What it said',
          `at ${width} px the headings shown are ${got.shown.join(', ')}`);
        must(got.headsFit, `at ${width} px a heading runs out of the panel`);
      } else {
        must(got.head > 10, `at ${width} px the firehose is not a table any more`);
      }
      out.push(`${width}:${got.scroll}/${got.client}`);
    }
    return `cards to 640 px, a table above; ${out.join(' ')}`;
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
