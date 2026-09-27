/*
 * Sonoran dashboard.
 *
 * This file has no build step. It uses Leaflet for the map and ECharts
 * for the graphs. Both come from the local static directory.
 *
 * The file has these parts:
 *   1. Configuration and fetch helpers
 *   2. Formatting helpers
 *   3. Document helpers
 *   4. Page loaders, one for each page
 *   5. The router and the live refresh timer
 */

'use strict';

/* ---------------------------------------------------------------- 1 */

const CONFIG = window.SONORAN || {};
const API_BASE = CONFIG.apiBase || '';

const api = (path) =>
  new URL(String(path).replace(/^\//, ''), API_BASE || document.baseURI).toString();

/*
 * Say WHICH request failed, not just that one did.
 *
 * "Request failed (500)" was the whole message. A page that makes six
 * requests then reports one number, and a reader -- or a maintainer
 * reading a bug report -- cannot tell which. A 500 was reported on the
 * node page and took a long scan of every endpoint at every window
 * value to chase, because the report could not name the path. It is
 * still unreproduced.
 *
 * The path only. No query string: those carry node ids, and a message
 * that ends up in a screenshot or an issue should not widen what is
 * shared beyond what the page already shows.
 */
function requestFailed(path, status) {
  const where = String(path).split('?')[0];
  return new Error(`Request failed (${status}) on ${where}`);
}

async function get(path) {
  const response = await fetch(api(path));
  if (!response.ok) throw requestFailed(path, response.status);
  return response.json();
}

/**
 * Run several requests together.
 * A failed request becomes null. A null path stays null and makes no
 * request, so a caller can skip one item of a set.
 */
/** Fetch a list, and the count of everything that matched it.
 *
 * `/api/nodes` answers with a bare array, because it is documented and
 * something outside this repository may read it. The count of the whole
 * matching set rides in `X-Total-Count`, which is the only way the page
 * can say "2,372 nodes, showing 300" instead of counting the rows it
 * was handed and calling that the answer.
 */
async function getList(path) {
  const response = await fetch(api(path));
  if (!response.ok) throw requestFailed(path, response.status);
  const rows = await response.json();
  const header = response.headers.get('X-Total-Count');
  // No header is not zero. An older server, or a proxy that dropped it,
  // means we do not know the total — and then we say what we do know.
  const total = header == null ? null : Number(header);
  return { rows, total: Number.isFinite(total) ? total : null };
}

async function getAll(paths) {
  return Promise.all(
    paths.map((path) =>
      path == null
        ? null
        : get(path).catch((error) => {
            console.warn('request failed', path, error);
            return null;
          }),
    ),
  );
}

/**
 * Colours come from the CSS custom properties in app.css, so the
 * stylesheet stays the single source of the palette. Charts and map
 * layers cannot read CSS variables on their own, so they read them
 * here once.
 */
const CSS = getComputedStyle(document.documentElement);
const colour = (name, fallback) =>
  (CSS.getPropertyValue(`--${name}`) || '').trim() || fallback;

const PALETTE = {
  text: colour('text', '#f6ece2'),
  muted: colour('muted', '#b59c88'),
  line: colour('line', '#422f23'),
  panel: colour('panel', '#221811'),
  panel2: colour('panel-2', '#2f2219'),
  accent: colour('accent', '#ff8c42'),
  good: colour('good', '#8cb369'),
  warn: colour('warn', '#edc04b'),
  bad: colour('bad', '#ef6f5c'),
  link: colour('map-link', '#6ea9c9'),
  relayed: colour('traffic-relayed', '#ded2c6'),
  // Roles have a colour each, read by `roleColour`. This one is for a
  // node or a link with nothing to say for itself.
  stale: colour('role-stale', '#7d6857'),
};

/** Say what one packet's uploads actually amount to.
 *
 * `direct` is false for a node gatewaying its own packet, because there
 * was no radio hop to measure — but calling that "relayed" says another
 * node carried it, which is the one thing it rules out. The packet page
 * has always distinguished the two.
 *
 * A packet is direct when any one gateway heard it with no hop. Failing
 * that, the fewest hops any gateway burned is the closest this data gets
 * to how far it travelled, and the ground it crossed is recorded nowhere
 * (AGENTS.md 9.20), so the count is said and nothing else is claimed.
 */
function trafficKind(packet) {
  if (packet.any_direct) return 'direct';
  if (packet.self_upload && packet.gateway_count === 1) return 'its own upload';
  if (packet.min_hops == null) return 'hops not recorded';
  return `${packet.min_hops} hop${packet.min_hops === 1 ? '' : 's'}`;
}

function trafficKindClass(packet) {
  return packet.any_direct ? 'tag router' : 'tag';
}

/** Return the colour for a signal quality, dimmed when there is none.
 *
 * An unmeasured link used to come back as the accent, which is the
 * brightest colour on the map: the one link nobody had a figure for
 * drew louder than every link that had been measured. Unknown is not a
 * grade, and it must not outrank one.
 */
function snrColour(snr) {
  if (snr == null) return PALETTE.stale;
  if (snr >= 0) return PALETTE.good;
  if (snr >= -10) return PALETTE.warn;
  return PALETTE.bad;
}

/* ---------------------------------------------------------------- 2 */

const NUMBER = new Intl.NumberFormat();

/*
 * Every time on the page is shown in the mesh's own timezone, not the
 * viewer's.
 *
 * The API answers in UTC. Arizona does not observe daylight saving, so
 * it stays on MST all year, and `America/Phoenix` carries that rule.
 * Left to itself the browser would use its own zone, and somebody
 * reading this from another state would see every time shifted.
 */
const TZ = CONFIG.timezone || 'America/Phoenix';
const TIME = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit', minute: '2-digit', timeZone: TZ,
});
const DATE = new Intl.DateTimeFormat(undefined, {
  month: 'short', day: 'numeric', timeZone: TZ,
});
const DATETIME = new Intl.DateTimeFormat(undefined, {
  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: TZ,
});

const count = (value) => (value == null ? '-' : NUMBER.format(value));

/** Return a short relative age, such as "4m" or "3d". */
function ago(value) {
  if (!value) return 'never';
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (!Number.isFinite(seconds)) return 'unknown';
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

const clock = (value) => (value ? TIME.format(new Date(value)) : '-');
const stamp = (value) => (value ? DATETIME.format(new Date(value)) : '-');

/** Return the age of a value in hours, or Infinity when it is missing. */
function ageHours(value) {
  if (!value) return Infinity;
  return (Date.now() - new Date(value).getTime()) / 3600000;
}

const round = (value, digits = 1) =>
  value == null ? null : Math.round(value * 10 ** digits) / 10 ** digits;

/** Return the quality class of an SNR value. */
function snrClass(snr) {
  if (snr == null) return '';
  if (snr >= 0) return 'good';
  if (snr >= -10) return 'ok';
  return 'bad';
}

const CELSIUS = (value) => (
  // null, not '', because callers test for null to omit the whole row.
  value == null ? null : SonoranUnits.temperatureFromC(value)
);

/** Human labels and units for the weather fields the API returns. */
const WEATHER_LABELS = {
  temperature: ['Temperature', (v) => CELSIUS(v)],
  relative_humidity: ['Humidity', (v) => `${round(v, 0)} %`],
  barometric_pressure: ['Pressure', (v) => `${round(v, 1)} hPa`],
  wind_speed: ['Wind speed', (v) => `${round(v, 1)} m/s`],
  wind_direction: ['Wind direction', (v) => `${round(v, 0)} deg`],
  rainfall: ['Rainfall', (v) => `${round(v, 1)} mm`],
  lux: ['Light', (v) => `${round(v, 0)} lx`],
  uv_lux: ['UV', (v) => `${round(v, 0)} lx`],
  iaq: ['Air quality index', (v) => `${round(v, 0)}`],
  gas_resistance: ['Gas resistance', (v) => `${round(v, 0)} ohm`],
};

const DEVICE_LABELS = {
  battery_level: ['Battery', (v) => `${round(v, 0)} %`],
  voltage: ['Voltage', (v) => `${round(v, 2)} V`],
  channel_utilization: ['Channel use', (v) => `${round(v, 1)} %`],
  air_util_tx: ['Air time TX', (v) => `${round(v, 1)} %`],
  uptime_seconds: ['Uptime', (v) => `${round(v / 86400, 1)} d`],
};

/* ---------------------------------------------------------------- 3 */

/** Create an element. Properties set attributes, text, or class names. */
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

/*
 * Tooltip content as a DOM node, for libraries that would take a string
 * and set `innerHTML` with it.
 *
 * Both Leaflet and ECharts do exactly that, and the values we put in a
 * tooltip include a node's name, which is chosen by whoever owns the
 * radio. A name of `<img src=x onerror=...>` therefore executed on this
 * origin. Everything passed here lands through `createTextNode` or
 * `el({text})`, so markup in a name is shown and never run.
 *
 * Pass a string for a plain line, or an element when a line needs
 * markup of our own. Empty lines are dropped, as the old `.filter`
 * did, so a node with no hardware model still reads correctly.
 */
function tooltipLines(...lines) {
  const wrap = document.createElement('div');
  for (const line of lines.flat()) {
    if (line == null || line === '') continue;
    if (wrap.childNodes.length) wrap.append(document.createElement('br'));
    wrap.append(line.nodeType ? line : document.createTextNode(String(line)));
  }
  return wrap;
}

/*
 * Who a packet was addressed to.
 *
 * `^all` is the broadcast address. The word for it is written once
 * here because it used to be written out at four call sites and they
 * drifted: three of them show it as a field value, where it reads as a
 * label and takes a capital, and one puts it inside a sentence, where
 * a capital would be wrong. Pass `sentence` for that one.
 */
const BROADCAST = 'Everyone';

function toLabel(packet, { sentence = false } = {}) {
  const broadcast = !packet.to_node || packet.to_node === '^all';
  if (broadcast) return sentence ? BROADCAST.toLowerCase() : BROADCAST;
  return packet.to_name || packet.to_node;
}

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function replace(target, ...children) {
  if (!target) return;
  target.replaceChildren(...children.flat().filter((child) => child != null));
}

const empty = (message) => el('p', { class: 'empty', text: message });
const failure = (error) => el('p', { class: 'error', text: error.message || String(error) });

/** Render a list that shows a few rows, then opens to the rest in place.
 *
 * These lists used to be a fixed-height box with its own scrollbar. A
 * panel that scrolls inside a page that also scrolls hides how much is
 * in it, and the wheel stops working the moment the pointer leaves the
 * box. Showing a few rows and counting the rest says the same thing
 * without trapping anything.
 *
 * A list no longer than `limit` gets no button, because there would be
 * nothing behind it.
 */
function expandingList(items, render, options = {}) {
  const limit = options.limit ?? 5;
  const noun = options.noun || 'messages';
  const list = el('ul', { class: options.class || 'messages' },
    items.slice(0, limit).map(render));
  if (items.length <= limit) return [list];

  /*
   * "View all", only when it IS all (#200).
   *
   * `items` is whatever the API sent, and several endpoints cap what
   * they send. "Messages sent" offered "View all 25 messages" on a node
   * that had sent 1,184, because 25 was the API's limit and this helper
   * had no way to know. AGENTS.md 9.19: a row limit must not decide
   * what the page says exists.
   *
   * `cut` says the caller knows the list is not everything. The true
   * total stays in the panel heading, which is read from a count the
   * API measures rather than from the length of a truncated list.
   *
   * This also carries #193.5: there is no "N more" span beside the
   * button. The button names the number it is about, and the two
   * together read as two different facts when they were one.
   */
  const closed = options.cut
    ? `Show the ${items.length} newest ${noun}`
    : `View all ${items.length} ${noun}`;
  const button = el('button', {
    class: 'more', type: 'button', 'aria-expanded': 'false', text: closed,
  });
  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') === 'true';
    replace(list, (open ? items.slice(0, limit) : items).map(render));
    button.setAttribute('aria-expanded', open ? 'false' : 'true');
    button.textContent = open ? closed : `Show fewer ${noun}`;
  });
  return [list, el('p', { class: 'more-wrap' }, button)];
}

/** Render one node as a clickable identity chip. */
function nodeChip(node) {
  if (!node) return el('span', { class: 'muted', text: 'unknown' });
  const id = node.node_id || node.gateway || '';
  const name = node.display_name || node.long_name || node.short_name || id;
  const chip = el(
    'span',
    { class: 'node-name' },
    el('span', { class: 'long', text: name }),
    node.short_name && node.short_name !== name
      ? el('span', { class: 'short', text: node.short_name })
      : null,
  );
  if (!id) return chip;
  return el('button', { class: 'linky', type: 'button', title: id, onclick: () => openNode(id) }, chip);
}

/*
 * One sentence, used by both tables that print an age.
 *
 * "Heard" is the dashboard's word and it hides two things: the observer
 * is always a gateway (AGENTS.md 9.5.1), and the clock is this
 * process's, never the node's (9.4).
 */
const HEARD_HINT = "How long ago a gateway last uploaded a packet from this node. It is the time this dashboard received the upload, not the node's own clock.";

/**
 * Build a table from column definitions and rows.
 *
 * `options.rowHref(row)`, when given, makes each whole row open that
 * address: a click anywhere on it that is not on a link or a button of
 * its own. The row also carries the address for keyboards and screen
 * readers through the link a column puts in it.
 */
function table(columns, rows, emptyMessage = 'No data.', options = {}) {
  if (!rows || !rows.length) return empty(emptyMessage);
  /*
   * A column may carry a `hint`: one plain sentence for the reader who
   * does not know the word in the heading. "Gateway", "hops" and a
   * `!hex` node ID are all exact and none of them explains itself.
   *
   * The hint used to live only in the `title` attribute. On a phone
   * there is no hover, so it could not be read at all — and the hint
   * exists for the newcomer, who is exactly the reader most likely to
   * be on a phone. The HTML Living Standard says so in as many words:
   * "Relying on the title attribute is currently discouraged as many
   * user agents do not expose the attribute in an accessible manner
   * ... which excludes keyboard-only users and touch-only users, such
   * as anyone with a modern phone or tablet."
   * https://html.spec.whatwg.org/multipage/dom.html#the-title-attribute
   *
   * So the sentence is carried in `data-hint`, and `revealHints` turns
   * it into a button on the heading that opens the sentence in a
   * panel. `title` is gone rather than kept beside it: two copies of
   * one sentence drift, and a native tooltip opening on hover over a
   * heading that now has its own control is one affordance too many.
   *
   * Not an inline note in the cell either — that widens the column,
   * and the table is the one part of the page WCAG 2.2 SC 1.4.10
   * Reflow excepts, so it is the one place extra width costs a reader
   * the most.
   */
  const head = el('tr', {}, columns.map((column) => {
    const classes = [column.num ? 'num' : ''];
    /*
     * A column may also carry `sort`: the name the server knows the
     * column by. The heading then becomes a button that asks the
     * server to reorder, never the browser.
     *
     * That distinction is the whole point. This list is capped, so
     * reordering the rows a page happens to hold would sort the most
     * recently heard few hundred by name and present the answer as the
     * first few hundred by name. Different sets, and a reader cannot
     * tell them apart by looking.
     */
    if (!column.sort) {
      return el('th', {
        // Implicit column scope usually resolves, but "usually" is
        // decided by the assistive technology rather than by us.
        scope: 'col',
        class: classes.join(' ').trim() || null,
        'data-hint': column.hint || null,
        'data-label': column.label,
        text: column.label,
      });
    }
    const active = column.sortState && column.sortState.key === column.sort;
    const direction = active ? column.sortState.order : null;
    classes.push('sortable');
    if (active) classes.push('sorted');
    return el('th', {
      scope: 'col',
      class: classes.join(' ').trim() || null,
      'data-hint': column.hint || null,
      'data-label': column.label,
      'aria-sort': active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none',
    }, el('button', {
      type: 'button',
      class: 'sort-button',
      onclick: () => column.onSort(column.sort, active && direction === 'asc' ? 'desc' : 'asc'),
    },
    el('span', { text: column.label }),
    // An arrow, and never only an arrow: `aria-sort` carries the same
    // fact, and the heading is bold when it is the one in force.
    el('span', { class: 'sort-arrow', 'aria-hidden': 'true',
      text: active ? (direction === 'asc' ? '\u2191' : '\u2193') : '\u2195' })));
  }));
  const body = rows.map((row) => {
    const href = options.rowHref ? options.rowHref(row) : null;
    const open = (event) => {
      if (event.target.closest('a, button, input, summary')) return;
      location.hash = href.replace(/^#/, '');
    };
    return el('tr', href ? { class: 'row-link', onclick: open } : {}, columns.map((column) => {
      const value = column.cell(row);
      return el('td', { class: [column.num ? 'num' : '', column.wrap ? 'wrap' : ''].join(' ').trim() || null },
        value && value.nodeType ? value : el('span', { text: value == null ? '-' : String(value) }));
    }));
  });
  return el('table', {}, el('thead', {}, head), el('tbody', {}, body));
}

/** Render a table that shows a few rows, then opens to the rest in place.
 *
 * Same bargain as `expandingList`: a node page carries several of these
 * at once, and a hundred-row neighbour table pushes everything below it
 * off the screen. Five rows and a count says how big it is; the button
 * says the rest is one click away rather than hidden.
 */
function expandingTable(columns, rows, emptyMessage, options = {}) {
  const limit = options.limit ?? 5;
  const noun = options.noun || 'rows';
  if (!rows || !rows.length) return [empty(emptyMessage)];
  const wrap = el('div', { class: 'table-wrap' },
    table(columns, rows.slice(0, limit), emptyMessage));
  if (rows.length <= limit) return [wrap];

  // "View all", only when it is all. See `expandingList` (#200).
  const closed = options.cut
    ? `Show the ${rows.length} newest ${noun}`
    : `View all ${rows.length} ${noun}`;
  const button = el('button', {
    class: 'more', type: 'button', 'aria-expanded': 'false', text: closed,
  });
  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') === 'true';
    replace(wrap, table(columns, open ? rows.slice(0, limit) : rows, emptyMessage));
    // Opening the table brings rows with it, and those rows may hold
    // exact values the shorter list never showed. The notes under it
    // have to be rebuilt from what is now there, or they under-report.
    markScrollableTables(wrap.parentElement || wrap);
    revealHints(wrap.parentElement || wrap);
    button.setAttribute('aria-expanded', open ? 'false' : 'true');
    button.textContent = open ? closed : `Show fewer ${noun}`;
  });
  // As in `expandingList`: the total is on the button already (#193.5).
  return [wrap, el('p', { class: 'more-wrap' }, button)];
}

/* A summary tile. Its `hint` travels the same way a column's does: in
 * `data-hint`, for `revealHints` to turn into a button on the label.
 * See the note in `table()`. */
function statTile(label, value, delta, hint) {
  return el('div', { class: 'panel' },
    el('div', { class: 'stat' },
      el('span', { class: 'value', text: value }),
      el('span', {
        class: 'label',
        'data-hint': hint || null,
        'data-label': label,
        text: label,
      }),
      delta ? el('span', { class: 'delta', text: delta }) : null));
}

/** Render an SNR value with its quality colour. */
const snrCell = (snr) =>
  snr == null
    ? el('span', { class: 'muted', text: '-' })
    : el('span', { class: `snr ${snrClass(snr)}`, text: `${round(snr, 1)} dB` });

/** Split a message body so hashtags are highlighted. */
/*
 * A URL in a message body, shown short and NOT made clickable (#199).
 *
 * 21 of the latest 50 messages carry one, mostly long Maps links that
 * wrap mid-token and are often longer than the message.
 *
 * **They stay text.** A message body is text anyone on the mesh can
 * send and nothing checks who sent it, so a clickable link here would
 * put an unchecked destination on the project's own page, wearing the
 * project's credibility. That is the #81 shape -- stored XSS through a
 * node name -- in a new place. Showing the URL shortened needs none of
 * the mitigations a link would: no scheme allowlist, no `rel`, no
 * question about whether a message can dress a link as something else.
 * A reader who wants it can still select and copy it, and the full URL
 * is on the element for anyone who hovers or opens the hint.
 *
 * Making them links is a separate decision, and #199 says so too. It
 * must not ride along inside a visual change.
 */
const URL_IN_TEXT = /(https?:\/\/[^\s]+)/g;

/** `https://www.google.com/maps?q=33.35%2C-111.91` as `google.com/maps`. */
function shortUrl(raw) {
  try {
    const url = new URL(raw);
    const host = url.hostname.replace(/^www\./, '');
    const path = url.pathname.replace(/\/$/, '');
    const shown = `${host}${path}`;
    // A long path is still a long token. Keep the host, which is the
    // part that tells a reader where this would go.
    return shown.length > 40 ? `${host}\u2026` : shown;
  } catch {
    return raw;
  }
}

function messageBody(text) {
  const node = el('span', { class: 'body' });
  for (const chunk of String(text ?? '').split(URL_IN_TEXT)) {
    if (!chunk) continue;
    // A stateless test. `URL_IN_TEXT` is global, and `.test()` on a
    // global regex advances `lastIndex`, so using it here would give a
    // different answer on every other chunk.
    if (/^https?:\/\//.test(chunk)) {
      // A span, not an anchor. See the note above.
      node.append(el('span', { class: 'link-text', title: chunk, text: shortUrl(chunk) }));
      continue;
    }
    for (const part of chunk.split(/(#[A-Za-z0-9_]+)/g)) {
      if (!part) continue;
      node.append(part.startsWith('#') ? el('span', { class: 'hash', text: part }) : part);
    }
  }
  return node;
}

/**
 * Render the tapback reactions on one message.
 * The phone apps send a tapback as a text message carrying the emoji,
 * so the API groups them and the page shows one chip per emoji.
 */
/*
 * How many reaction chips show before the rest fold into "+N more".
 *
 * A busy message collected enough distinct emoji to wrap three lines on
 * a phone, which pushed the next message off the screen. The most sent
 * come first, so the fold hides the least said.
 */
const REACTION_CAP = 4;

/*
 * The auto-ack rule lives in `labels.js`, as `SonoranLabels.isAutoAck`.
 * It is pure -- an emoji and a channel in, a yes or no out -- so it is
 * tested directly rather than through this page, and there is one
 * definition of which marks count and where.
 */



/** The senders of one reaction, each a node link with its own packet. */
function reactionSenders(reaction) {
  return el('ul', { class: 'reaction-senders' }, (reaction.senders || []).map((sender) =>
    el('li', {},
      el('button', {
        class: 'linky', type: 'button', title: sender.node_id,
        text: sender.display_name,
        onclick: () => openNode(sender.node_id),
      }),
      sender.packet_id == null
        ? null
        : el('a', {
            class: 'linky packet',
            href: `#packet/${encodeURIComponent(sender.node_id)}/${sender.packet_id}`,
            title: `Open the packet that carried this ${reaction.emoji}`,
            text: '↗',
          }))));
}

/**
 * One reaction: the emoji and how many sent it, with the senders a tap away.
 *
 * The names used to sit inline in the chip, which is how a tapback with
 * several senders took the whole chat page sideways at 320 px (#44). A
 * `details` holds them now: it opens on a tap or a key, needs no hover,
 * and a closed chip is only as wide as an emoji and a number.
 */
function reactionChip(reaction, label, extra) {
  const n = reaction.count ?? (reaction.senders || []).length;
  return el('details', { class: extra ? `reaction ${extra}` : 'reaction' },
    el('summary', { title: `${label || reaction.emoji}, sent by ${n}` },
      el('span', { class: 'glyph', text: label || reaction.emoji }),
      n > 1 ? el('span', { class: 'count', text: String(n) }) : null),
    reactionSenders(reaction));
}

function reactionChips(reactions, channel) {
  if (!reactions || !reactions.length) return null;
  /*
   * A mark only counts as an ack on a channel where it cannot be
   * anything else. Off those channels every tapback is a reaction, which
   * is what puts Trivia's 1-4 back with the people who sent them.
   *
   * The channel is passed in rather than read from a global, because this
   * renders inside a message row and the row already knows.
   */
  const isAck = (reaction) => SonoranLabels.isAutoAck(reaction.emoji, channel);
  const acks = reactions.filter(isAck);
  const people = reactions
    .filter((reaction) => !isAck(reaction))
    .sort((a, b) => (b.count || 0) - (a.count || 0));
  const shown = people.slice(0, REACTION_CAP);
  const folded = people.slice(REACTION_CAP);
  const ackSenders = acks.reduce((sum, reaction) => sum + (reaction.count || 0), 0);
  return el('div', { class: 'reactions' },
    shown.map((reaction) => reactionChip(reaction)),
    folded.length
      ? el('details', { class: 'reaction more-reactions' },
          el('summary', { text: `+${folded.length} more` }),
          el('div', { class: 'reactions' }, folded.map((reaction) => reactionChip(reaction))))
      : null,
    acks.length
      ? reactionChip({
          emoji: acks.map((reaction) => reaction.emoji).join(' '),
          count: ackSenders,
          senders: acks.flatMap((reaction) => (reaction.senders || []).map((sender) => ({
            ...sender, display_name: `${sender.display_name}: ${SonoranLabels.autoAckMeaning(reaction.emoji)}`,
          }))),
        }, 'Auto-acked', 'auto-ack')
      : null);
}

/** Render the message this one replies to, as a short quote. */
function replyQuote(parent) {
  if (!parent) return null;
  const quote = el('div', { class: 'reply-quote' },
    el('span', { class: 'who', text: parent.from_name }),
    el('span', { class: 'text', text: parent.body }));
  if (parent.packet_id == null) return quote;
  // The message being replied to is a packet of its own.
  return el('a', {
    class: 'reply-link',
    href: `#packet/${encodeURIComponent(parent.from_node)}/${parent.packet_id}`,
    title: 'Open the message this replies to',
  }, quote);
}

/** Render one chat message list item. */
/*
 * The channels whose messages are drawn quietly (#199).
 *
 * In the latest 50 messages one automated sender had posted 23 and
 * another 5; in the latest 12, which is what the dashboard shows, one
 * sender had 7. A person's message is easy to lose among them.
 *
 * The reporter decided that every message stays -- no filter, no
 * folding behind a count -- so this changes **weight, not presence**.
 * Same size, same position, muted colour. Nothing is hidden and
 * nothing is unreadable.
 */
const QUIET_CHANNELS = new Set(['Traffic', 'Weather']);

function messageItem(message, options = {}) {
  const direct = message.to_node && message.to_node !== '^all';
  const quiet = QUIET_CHANNELS.has(message.channel);
  return el('li', { class: [direct ? 'dm' : null, quiet ? 'quiet' : null].filter(Boolean).join(' ') || null },
    replyQuote(message.reply_to),
    /*
     * One accent on this line, not three (#199).
     *
     * The sender was an orange button, the channel a boxed chip pressed
     * against it, and the time an orange underlined link -- the loudest
     * of the three and the least important. Now: the name carries the
     * line, the channel is a quiet label with a real gap, and the time
     * sits muted on the right. The time is still the way into the
     * packet and still a real link; it just stops competing.
     */
    el('div', { class: 'who' },
      el('button', {
        class: 'name', type: 'button', title: message.from_node,
        onclick: () => openNode(message.from_node),
        text: message.from_name || message.from_node,
      }),
      options.showChannel && message.channel
        ? el('span', { class: 'channel-label', text: message.channel }) : null,
      message.packet_id == null
        ? el('time', { class: 'when', datetime: message.seen_at || '',
            title: stamp(message.seen_at), text: `${ago(message.seen_at)} ago` })
        : el('a', {
            class: 'when', title: `Open packet ${message.packet_id}`,
            href: `#packet/${encodeURIComponent(message.from_node)}/${message.packet_id}`,
            text: `${ago(message.seen_at)} ago`,
          })),
    messageBody(message.body),
    reactionChips(message.reactions, message.channel));
}

/* ECharts instances are kept so a redraw does not leak canvases. */
const charts = new Map();
/*
 * The option each chart was last drawn with.
 *
 * Full screen adds a zoom control to a chart and has to take it away
 * again on the way out. ECharts merges by default, so `dataZoom` put on
 * an instance stays on it; the only way back is to set the whole option
 * again with `notMerge`, and that needs the option the caller gave.
 */
const chartOptions = new Map();

/*
 * Let the whole canvas pan and zoom the mesh graph (#233, after #223).
 *
 * ECharts gates a graph series' roam on the bounding rect of what it
 * DREW. From the vendored build:
 *
 *     setPointerChecker(function (e, x, y) {
 *       var o = a.getBoundingRect();
 *       o.applyTransform(a.transform);
 *       return o.contain(x, y) && !hT(e, n, t);
 *     })
 *
 * `a` is the series group, so the region is the box around the outermost
 * nodes -- which is exactly what returnzork described and drew a red
 * rectangle around: "an invisible box that has corners of outlier nodes".
 * Drag or scroll outside it and nothing happens at all, which reads as a
 * dead page rather than as a control with edges. Measured before this
 * change: a drag inside the box moved the group from (80,48) to
 * (176,108); the same drag from the empty canvas above and below it
 * moved nothing, and the wheel did nothing there either. The report was
 * about dragging; zoom was broken in the same place for the same reason.
 *
 * No series option changes this -- the rect is computed in the view, not
 * read from the option -- so the checker itself is replaced.
 *
 * COMPOSED, not overridden, and that is the careful part. The original
 * answer is asked first and honoured, so every case ECharts already
 * allowed keeps working, including the `hT` guard that stops a drag
 * starting on another component from being stolen by the graph. Only one
 * case is ADDED: a pointer inside the canvas with nothing drawn under
 * it. `findHover` returns null there, and it returns a real element over
 * the legend -- checked on the running page, because the legend sits at
 * `top: 0` over what looks like empty space and panning from it would be
 * wrong.
 *
 * PRIVATE API, and treated that way. `_chartsViews` and `_controller`
 * are internals of a pinned build; every step is guarded and anything
 * missing leaves the chart exactly as it was. A graph that pans only in
 * the middle is a poor control; a graph that throws is a broken page.
 * `tests/unit/test_graph_roam.py` fails if these internals move, so an
 * ECharts upgrade reports this rather than silently dropping it.
 */
function widenGraphRoam(instance) {
  if (!instance || typeof instance.getZr !== 'function') return false;
  let views;
  try {
    views = instance._chartsViews;
  } catch {
    return false;
  }
  if (!Array.isArray(views)) return false;
  const view = views.find((candidate) => candidate && candidate.type === 'graph');
  const controller = view && view._controller;
  if (!controller || typeof controller.setPointerChecker !== 'function') return false;
  // Already composed. `_updateController` installs a fresh checker on
  // every render, so this is re-applied rather than applied once -- but a
  // double wrap would ask the original twice and grow a chain on every
  // redraw.
  if (controller.pointerChecker && controller.pointerChecker.sonoranWidened) return true;
  const original = controller.pointerChecker;
  const zr = instance.getZr();
  const widened = (event, x, y) => {
    // Whatever ECharts allowed, we allow.
    if (typeof original === 'function') {
      try {
        if (original.call(controller, event, x, y)) return true;
      } catch {
        /* A throwing original must not take the gesture with it. */
      }
    }
    // Inside the canvas? `x` and `y` are already chart-local.
    const width = instance.getWidth();
    const height = instance.getHeight();
    if (!(x >= 0 && y >= 0 && x <= width && y <= height)) return false;
    // Nothing drawn under the pointer. Anything drawn -- the legend, a
    // node, a label -- keeps whatever behaviour it had.
    try {
      const hovered = zr.handler.findHover(x, y);
      return !(hovered && hovered.target);
    } catch {
      return false;
    }
  };
  widened.sonoranWidened = true;
  controller.setPointerChecker(widened);
  return true;
}

function chart(target, option) {
  if (!target) return null;
  // The box collapses while it holds a sentence instead of a chart, and
  // ECharts measures the box when it starts, so the height comes back
  // before the instance is made. See `chartEmpty`.
  target.classList.remove('chart-empty');
  let instance = charts.get(target);
  if (!instance || instance.isDisposed()) {
    instance = echarts.init(target, null, { renderer: 'canvas' });
    charts.set(target, instance);
  }
  instance.setOption(option, true);
  chartOptions.set(target, option);
  /*
   * After `setOption`, because the graph view installs its own pointer
   * checker while rendering, and on `finished` because a force layout
   * keeps rendering after this call returns.
   */
  widenGraphRoam(instance);
  if (!instance.__sonoranRoamWired) {
    instance.__sonoranRoamWired = true;
    instance.on('finished', () => widenGraphRoam(instance));
  }
  /*
   * Name the region, and let ECharts describe the data inside it.
   *
   * `aria.enabled` in CHART_BASE generates the description of what was
   * plotted. That says "a line chart with 2 series"; it does not say
   * which question this chart answers. The panel's own heading does,
   * and it is right above the canvas, so it is used as the label.
   *
   * `role="img"` stops a reader walking into the canvas and finding
   * nothing, and gives the generated description something to attach
   * to.
   */
  if (!target.getAttribute('role')) target.setAttribute('role', 'img');
  if (!target.getAttribute('aria-label')) {
    const title = chartTitle(target);
    if (title) target.setAttribute('aria-label', `Chart: ${title}`);
  }
  fitChartExpand(target);
  return instance;
}

/**
 * Say why a chart panel is blank.
 *
 * Every chart on this page used to be drawn inside `if (rows.length)`
 * with no else. An endpoint that answered with an empty list left a
 * titled panel holding nothing at all, and a panel holding nothing
 * reads as "measured, and the answer is nothing". The daily activity
 * chart is the plain case: the snapshot job writes that table, so a
 * dashboard whose jobs service has never run shows an empty box where
 * a month of history belongs.
 *
 * "We have not been told" and "there is none" are different sentences,
 * so each caller passes its own.
 */
function chartEmpty(target, message) {
  if (!target) return;
  const instance = charts.get(target);
  if (instance && !instance.isDisposed()) instance.dispose();
  charts.delete(target);
  chartOptions.delete(target);
  // The control sits beside the box rather than inside it, because
  // ECharts owns everything inside. So it outlives a chart that turns
  // into a sentence, unless it is taken away here.
  const tools = target.previousElementSibling;
  if (tools && tools.classList.contains('chart-tools')) tools.remove();
  target.classList.add('chart-empty');
  target.removeAttribute('_echarts_instance_');
  replace(target, empty(message));
}

const CHART_BASE = {
  backgroundColor: 'transparent',
  /*
   * A canvas with no text alternative is nothing at all to a screen
   * reader (WCAG 1.1.1, Level A). Every chart here was an unlabelled
   * canvas: no role, no aria-label, empty textContent, and ECharts
   * defaults `aria.enabled` to false so not even its own generated
   * description existed.
   *
   * Turning it on makes ECharts build a description from the series
   * and the data it was given, which is the honest thing to expose --
   * it describes what was drawn rather than what we meant. Each chart
   * also gets its own label where it is created, because "a line
   * chart with 2 series" does not say which mesh question it answers.
   */
  aria: { enabled: true },
  textStyle: { color: PALETTE.muted, fontFamily: 'system-ui, sans-serif' },
  grid: { left: 48, right: 16, top: 24, bottom: 32, containLabel: true },
  tooltip: {
    trigger: 'axis',
    backgroundColor: PALETTE.panel,
    borderColor: PALETTE.line,
    textStyle: { color: PALETTE.text },
  },
};

const AXIS = {
  axisLine: { lineStyle: { color: PALETTE.line } },
  splitLine: { lineStyle: { color: PALETTE.panel2 } },
  axisLabel: { color: PALETTE.muted },
};

addEventListener('resize', () => {
  markScrollableTables();
  for (const instance of charts.values()) {
    if (!instance.isDisposed()) instance.resize();
  }
});

/* --- A chart, full screen (#100) --------------------------------- */

/*
 * The box is moved into the overlay, never copied.
 *
 * `map-watch.js` made the same choice for the map and the reason is the
 * same: a second ECharts instance over the same series is a second
 * thing that can disagree with the first, and the day they disagree is
 * the day a reader is shown the wrong mesh. Moving the box keeps one
 * instance, one option and one `aria-label`, so nothing about what the
 * chart claims changes when it grows.
 *
 * The Fullscreen API first, because it hides the browser's own chrome,
 * which is most of what "look at this closely" is asking for. iOS
 * Safari does not grant `requestFullscreen` on an arbitrary element, so
 * the overlay is `position: fixed; inset: 0` in CSS on both paths and
 * the API only ever adds to it. That way there is one set of rules to
 * get right instead of two.
 */

/* What is full screen now, or null. One chart at a time. */
let chartStage = null;

/**
 * What a chart panel is called.
 *
 * Read from the children rather than from `textContent`, because a
 * panel heading is a heading and a muted note beside it with no space
 * between the two nodes. `textContent` runs them together: the node
 * page read "Battery and voltagefrom device telemetry", measured on
 * this deployment. The note is worth keeping — it says where the
 * numbers came from — so it is joined with a comma instead.
 *
 * Empty when there is no heading to read, so the caller decides what
 * to do about it. `chart` leaves the label off rather than writing a
 * name that says nothing.
 */
function chartTitle(box) {
  const panel = box.closest('.panel');
  const heading = panel ? panel.querySelector('h3, h4') : null;
  if (!heading) return '';
  return [...heading.childNodes]
    .map((child) => child.textContent.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join(', ');
}

/** An SVG icon from the sprite in `index.html`. */
function icon(id) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', id);
  svg.append(use);
  return svg;
}

/** Build the overlay once. It holds no chart until one is put into it. */
function chartStageShell() {
  const found = $('[data-chart-stage]');
  if (found) return found;
  const shell = el('div', {
    class: 'chart-stage', 'data-chart-stage': true, hidden: true,
    role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'chart-stage-title',
  },
  el('div', { class: 'chart-stage-head' },
    el('h2', { id: 'chart-stage-title', 'data-chart-stage-title': true }),
    el('button', {
      type: 'button', class: 'chart-stage-close', 'data-chart-stage-close': true,
      onclick: () => leaveChartStage(),
    }, icon('#i-fullscreen-exit'), el('span', { text: 'Close' }))),
  el('div', { class: 'chart-stage-body', 'data-chart-stage-body': true }));
  /*
   * Escape, and the Tab that would otherwise walk out of the back of
   * the overlay. Under the Fullscreen API the browser takes Escape
   * before the page sees it and `fullscreenchange` does the work
   * instead; this listener is what the CSS fallback has.
   *
   * The overlay holds exactly one focusable control, so the trap is
   * "Tab keeps the focus on Close". The chart itself is a canvas and
   * was never in the tab order.
   */
  shell.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { event.preventDefault(); leaveChartStage(); return; }
    if (event.key === 'Tab') {
      event.preventDefault();
      $('[data-chart-stage-close]', shell).focus();
    }
  });
  document.body.append(shell);
  return shell;
}

/*
 * A zoom control, but only where there is a time range to zoom into.
 *
 * `dataZoom` acts on an axis index, and on this dashboard the axis that
 * carries time is the x axis on the node history charts, the signal
 * chart, the daily history and the hourly activity chart. The other
 * three go through the same helper and must not get it: the graph page
 * draws a force layout with no axis at all, the packet-types chart and
 * the hardware chart are horizontal bars whose x axis is the count, and
 * zooming a count axis hides bars rather than showing a range.
 *
 * So the test is the x axis type, which is `time` or `category` for
 * exactly the charts that want it and `value` or absent for the rest.
 */
function chartZoomOption(option) {
  const axis = option.xAxis;
  const type = axis && !Array.isArray(axis) ? axis.type : null;
  if (type !== 'time' && type !== 'category') return option;
  return {
    ...option,
    // The slider needs the room, or it draws over the axis labels.
    grid: { ...(option.grid || CHART_BASE.grid), bottom: 76 },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0 },
      {
        type: 'slider', xAxisIndex: 0, bottom: 16, height: 28,
        borderColor: PALETTE.line,
        fillerColor: PALETTE.panel2,
        handleStyle: { color: PALETTE.accent },
        moveHandleStyle: { color: PALETTE.accent },
        textStyle: { color: PALETTE.muted },
        dataBackground: {
          lineStyle: { color: PALETTE.line },
          areaStyle: { color: PALETTE.panel2 },
        },
      },
    ],
  };
}

/**
 * Draw the staged chart again at its new size.
 *
 * ECharts measures its container when it is made and never again on its
 * own, so a box that changed size draws at the old one until `resize`
 * is called. Both entering and leaving change the size.
 */
function redrawChart(box, zoomed) {
  const instance = charts.get(box);
  if (!instance || instance.isDisposed()) return;
  const option = chartOptions.get(box);
  if (option) instance.setOption(zoomed ? chartZoomOption(option) : option, true);
  instance.resize();
}

async function enterChartStage(box, opener) {
  if (chartStage || !box) return;
  const shell = chartStageShell();
  const anchor = document.createComment('full-screen placeholder');
  box.parentNode.insertBefore(anchor, box);
  // The hardware chart sets its own height in a style attribute, which
  // would win over any rule here. It is put back on the way out.
  chartStage = { box, anchor, opener, height: box.style.height, api: false };
  box.style.height = '100%';
  $('[data-chart-stage-title]', shell).textContent = chartTitle(box) || 'Chart';
  $('[data-chart-stage-body]', shell).append(box);
  shell.hidden = false;
  document.body.classList.add('chart-staged');
  try {
    if (shell.requestFullscreen) {
      await shell.requestFullscreen({ navigationUI: 'hide' });
      chartStage.api = true;
    } else if (shell.webkitRequestFullscreen) {
      shell.webkitRequestFullscreen();
      chartStage.api = true;
    }
  } catch {
    /* iOS Safari, and anything that refuses. The CSS already did it. */
  }
  $('[data-chart-stage-close]', shell).focus();
  redrawChart(box, true);
  // The overlay grows over a transition on the fallback path, so one
  // more measurement after it has landed.
  setTimeout(() => { if (chartStage) redrawChart(chartStage.box, true); }, 260);
}

async function leaveChartStage() {
  if (!chartStage) return;
  const { box, anchor, opener, height, api } = chartStage;
  chartStage = null;
  if (api && document.fullscreenElement) {
    try {
      await document.exitFullscreen();
    } catch {
      /* Already out, by Escape or by the browser. Nothing to undo. */
    }
  }
  const shell = $('[data-chart-stage]');
  if (shell) shell.hidden = true;
  document.body.classList.remove('chart-staged');
  box.style.height = height;
  /*
   * The page may have been drawn again while the chart was full screen:
   * a live page replaces its panels every 15 s, and that takes the
   * anchor with them. Putting the box back into a tree nobody can see
   * would leave a canvas alive with no way to reach it, so it is
   * disposed instead. The page has already drawn its replacement.
   */
  if (anchor.parentNode) {
    anchor.parentNode.insertBefore(box, anchor);
    anchor.remove();
    redrawChart(box, false);
  } else {
    const instance = charts.get(box);
    if (instance && !instance.isDisposed()) instance.dispose();
    charts.delete(box);
    chartOptions.delete(box);
    box.remove();
  }
  // Back to the control that opened it, the way `wireNav` does for the
  // menu. A re-render takes that button away with the rest of the
  // panel, and focusing a detached node moves the focus to the body,
  // so it is checked first.
  if (opener && opener.isConnected) opener.focus();
}

/*
 * One place to learn that fullscreen ended, including Escape and every
 * route the page did not initiate.
 */
document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && chartStage && chartStage.api) leaveChartStage();
});

/**
 * Give a chart panel its full-screen control, once.
 *
 * A real `<button>`, and that is the point of this comment.
 * `map-watch.js` used to build its control as an `<a role="button">`,
 * which is the shape Leaflet's own controls take. An anchor runs its
 * click handler on Enter and not on Space, and `role="button"` does not
 * add the missing key: ARIA names a thing, it does not implement it.
 * Measured on this deployment at the time — focus the watch control and
 * press Space, and `SonoranWatch.isOn()` was still false; press Enter
 * and it was true. A `<button type="button">` answers to both with no
 * code.
 *
 * The watch control is a real button too now (#147), so the two agree.
 * The reasoning is kept because it is the reason for the choice here,
 * and it is the trap anybody reaching for a Leaflet-shaped control
 * falls into next.
 *
 * The control goes beside the box rather than in the `h3`, because a
 * button inside a heading joins the heading's own text when a screen
 * reader reads the outline, and two of these headings already carry a
 * live count.
 */
function fitChartExpand(target) {
  if (!target || !target.parentNode) return;
  // The staged box lives in the overlay, which is not a panel and has
  // no room for a second control. A live re-render still draws every
  // other chart on the page, and each of those gets its own.
  if (chartStage && chartStage.box === target) return;
  const label = `Full screen: ${chartTitle(target) || 'chart'}`;
  const found = target.previousElementSibling;
  if (found && found.classList.contains('chart-tools')) {
    // The heading carries a live count on two panels, so the name is
    // written again rather than assumed to be the one from last time.
    $('button', found).setAttribute('aria-label', label);
    return;
  }
  const button = el('button', {
    type: 'button', class: 'chart-expand', 'aria-label': label,
  }, icon('#i-fullscreen'), el('span', { text: 'Full screen' }));
  button.addEventListener('click', () => enterChartStage(target, button));
  target.parentNode.insertBefore(el('div', { class: 'chart-tools' }, button), target);
}

/* ---------------------------------------------------------------- 4 */

/** Shared summary tiles used by the dashboard and the statistics page. */
async function loadSummary(page) {
  const target = $('[data-summary]', page);
  if (!target) return;
  const [stats, snapshots] = await getAll(['api/stats', 'api/stats/snapshots/daily?days=2']);
  if (!stats) return replace(target, failure(new Error('Statistics are not available.')));
  const yesterday = snapshots && snapshots[1];
  const delta = (key) =>
    yesterday && yesterday[key] != null ? `${count(yesterday[key])} yesterday` : null;
  /*
   * "Observations" was the endpoint's word for `packet_seen`, printed
   * at the reader. A `packet_seen` row is one MQTT upload, and saying
   * so is the whole of AGENTS.md 9.5.1: the only observers this
   * database can hold are gateways, one gateway uploads the same packet
   * more than once, and every other node on the mesh hears plenty and
   * reports none of it. The firehose column says "Uploads" too, so the
   * dashboard has one word for it. No count changes.
   */
  replace(target,
    statTile('Nodes', count(stats.node_count), delta('node_count'),
      'How many nodes this database holds.'),
    statTile('Packets', count(stats.packet_count), delta('packet_count'),
      'Packets stored. The same packet uploaded by several gateways is counted once.'),
    statTile('Uploads', count(stats.observation_count), delta('observation_count'),
      'One for each time a gateway uploaded a packet to MQTT. One packet is often '
      + 'uploaded by several gateways, and by the same gateway more than once, so this '
      + 'is larger than the packet count and is not a count of gateways.'),
    statTile('Gateways', count(stats.gateway_count), delta('gateway_count'),
      'Nodes that upload what they hear to MQTT. They are the only observers this '
      + 'database has.'));
}

async function loadTopTalkers(page) {
  const target = $('[data-top-talkers]', page);
  if (!target) return;
  const rows = await get('api/stats/top?hours=24&limit=15').catch(() => null);
  if (!rows) return replace(target, failure(new Error('Cannot load the busiest nodes.')));
  replace(target, table([
    { label: 'Node', cell: (row) => nodeChip(row) },
    { label: 'Packets', num: true, cell: (row) => count(row.packet_count) },
    {
      label: 'Air time sending',
      num: true,
      hint: 'The share of the channel this node spent sending, from its own telemetry. Air time is shared, so a high figure is time nobody else can use.',
      cell: (row) => (row.air_util_tx == null ? '-' : `${round(row.air_util_tx, 1)} %`),
    },
  ], rows, 'No packets in the window.'));
}

/*
 * Leaderboards that reward what helps the mesh (#60).
 *
 * None of them counts packets. Each board says what it measures, over
 * what window, and what it cannot know, because a board that hides what
 * it cannot see is an argument and not a measurement.
 */
let leaderboardPreset = '';

async function loadLeaderboards(page) {
  const target = $('[data-leaderboards]', page);
  if (!target) return;
  /*
   * The preset comes from the menu now, not from a picker on this panel.
   *
   * `leaderboardPreset` was a page-local variable behind a <select> built
   * below. It was the fifth place on the site that asked the same
   * question, and the one easiest to miss because the control was built
   * in JavaScript rather than sitting in the markup.
   */
  const wanted = window.SonoranPreset ? SonoranPreset.current() : leaderboardPreset;
  const query = wanted ? `?channel=${encodeURIComponent(wanted)}` : '';
  const data = await get(`api/stats/leaderboards${query}`).catch(() => null);
  if (!data) return replace(target, failure(new Error('Cannot load the leaderboards.')));
  if (!data.available) {
    return replace(target, empty('No gap assessment has been written yet, so there is nothing to rank.'));
  }
  const note = $('[data-leaderboards-note]', page);
  if (note) {
    /*
     * Says which preset these boards are for, and no longer offers to
     * change it -- the menu does that for the whole site.
     *
     * Still said at all, because a leaderboard is a ranking and a reader
     * has to know what it ranks: nodes on different presets cannot hear
     * each other, so a merged board would rank links that cannot exist.
     */
    replace(note, `${SonoranLabels.presetLabel(data.preset)} only`);
    if (window.SonoranPreset && Array.isArray(data.presets) && data.presets.length) {
      SonoranPreset.setAvailable(data.presets);
    }
  }
  /*
   * "What this cannot know" moves onto the title as an info icon (Will,
   * 2026-09-26). It was a `<details>` under every board -- twelve
   * disclosures on one page, each holding a sentence most readers will
   * read once.
   *
   * `data-hint` on the `h3` is all this needs: `revealHints` already turns
   * that into a button on the heading and a panel that opens on a tap as
   * well as a hover, which is why nothing new was built for it. It is the
   * same control the table columns and the dashboard tiles use, so a
   * reader learns one affordance.
   *
   * `data-label` is set because `fitHint` names the button "What this
   * panel means: <label>", and the heading's own text node includes the
   * window chip -- without it the accessible name would read "...: Best
   * hop count last 24 h".
   *
   * The sentence is NOT dropped. It is the difference between a
   * leaderboard and a scoreboard: a ranking that does not say what it
   * cannot see invites somebody to read it as a judgement.
   */
  replace(target, data.boards.map((board) => el('div', { class: 'panel leaderboard' },
    el('h3', { 'data-hint': board.cannot_know || null, 'data-label': board.title }, board.title,
      board.window_hours ? el('span', { class: 'muted', text: `last ${board.window_hours} h` }) : null),
    el('p', { class: 'muted', text: board.measure }),
    board.rows.length
      ? el('ol', { class: 'board' }, board.rows.map((row) => el('li', {},
          el('span', { class: 'who' }, nodeChip(row),
            row.other_id ? [' to ', nodeChip({ node_id: row.other_id, display_name: row.other_name })] : null),
          el('span', { class: 'value', text: `${count(row.value)} ${row.unit}` }),
          el('span', { class: 'muted detail', text: row.detail }))))
      /*
       * "Nothing qualifies" is a measurement. "Not assessed" is an
       * admission, and the two must not read the same.
       *
       * The two gaps-backed boards are built from an empty list when
       * `read_assessment` returns nothing, so a preset the job has not
       * yet looked at used to report that nobody qualified -- a claim
       * about a mesh that had not been measured. The payload has said
       * `assessed: false` all along and this ignored it. Same rule the
       * gaps page holds: silence is not a finding.
       */
      : empty(data.assessed === false
          ? 'No assessment has been written for this preset yet, so these boards have nothing to rank.'
          : 'Nothing qualifies in the window.'))));
  /*
   * The hint buttons are added after the boards are in the DOM.
   *
   * `revealHints` walks what is already rendered, and `render` calls it
   * for the page -- but these boards are drawn by their own fetch, which
   * can land after that. Without this call the caveat would be in the
   * markup as `data-hint` and no button would ever appear: nothing would
   * look broken, and the sentence would simply be gone.
   */
  revealHints(target.parentElement || target);
}

const PAGES = {};

/*
 * The window the dashboard's packet-types chart covers.
 *
 * Written once because three things have to agree on it: the panel
 * heading, the request, and the firehose a slice links into (§7.1,
 * "over the same 24 hours"). They did not: the heading said 24 h and the
 * request had no window at all.
 */
const PORTNUM_CHART_HOURS = 24;

PAGES.dashboard = async (page) => {
  await Promise.all([loadSummary(page), loadTopTalkers(page)]);
  const [nodes, messages, portnums] = await getAll([
    'api/nodes?limit=15&active_hours=24',
    // Filtered like the Chat page: on LongFast this feed was showing
    // messages from channels a LongFast radio never hears.
    `api/chat?limit=12${chatFeedChannel()}`,
    /*
     * The same 24 hours and the same preset the chart's own heading and
     * the firehose it links into use (§7.1).
     *
     * This asked for `api/stats/portnums` with nothing on it, which
     * counts every packet the database holds on every channel, under a
     * panel headed "Packet types (24 h)". So the chart named a window it
     * was not holding, and once a slice became a link into a 24-hour
     * firehose on one preset the mismatch stopped being cosmetic: a band
     * counting 500 all-time packets would have opened a table with none
     * in it, and an empty filtered table reads as a quiet mesh.
     */
    `api/stats/portnums?hours=${PORTNUM_CHART_HOURS}${presetChannel() ? `&channel=${encodeURIComponent(presetChannel())}` : ''}`,
  ]);

  replace($('[data-recent-nodes]', page), nodes
    ? table([
        { label: 'Node', cell: (row) => nodeChip(row) },
        { label: 'Role', cell: (row) => roleCell(row.role) },
        { label: 'Heard', num: true, hint: HEARD_HINT, cell: (row) => `${ago(row.last_heard)} ago` },
      ], nodes, 'No nodes heard yet.')
    : failure(new Error('Cannot load nodes.')));

  replace($('[data-recent-chat]', page), messages
    ? (messages.length
        ? messages.map((message) => messageItem(message, { showChannel: true }))
        : [empty('No messages stored.')])
    : [failure(new Error('Cannot load messages.'))]);

  const portnumChart = $('[data-portnum-chart]', page);
  const preset = presetChannel();
  if (!portnums) {
    chartEmpty(portnumChart, 'Cannot load the packet types.');
  } else if (!portnums.length) {
    // Named, not "the window". The chart is now filtered two ways and
    // both of them can be the reason it is empty.
    chartEmpty(portnumChart, `No packet was stored in the last ${PORTNUM_CHART_HOURS} h${preset ? ` on ${preset}` : ''}.`);
  } else {
    const top = [...portnums].sort((a, b) => b.count - a.count).slice(0, 10).reverse();
    /*
     * One array, indexed the same way the series is.
     *
     * §7.1's stated risk: "its click events give a series index, not a
     * portnum. The mapping has to be explicit or the wrong filter opens
     * -- silently, because a valid-looking filter with no rows looks like
     * a quiet mesh."
     *
     * So the mapping is this array and `params.dataIndex`, which is the
     * index into the very array the bars were built from. Not the
     * category name: two rows can share a label (a port number the
     * protocol has renamed, say) and a name lookup would then send both
     * bands to one filter with nothing to say which.
     */
    const bands = top.map((row) => {
      const wire = row.name || String(row.portnum);
      return {
        wire,
        label: portnumLabel(wire),
        count: row.count,
        /*
         * Three of these are not port numbers at all (#157).
         *
         * `UNREADABLE_PKI`, `UNREADABLE_NO_KEY` and
         * `UNREADABLE_UNRECORDED` are what `traffic_label` calls the
         * three things a `portnum` of 0 turns out to be. `labels.js`
         * already records why they are kept out of the filter's
         * vocabulary: the API answers 422 for them. Filtering on `0`
         * instead would return all four groups, which is the wrong
         * filter arriving quietly -- exactly what §7.1 warns about.
         *
         * They stay on the chart, because they are most of the traffic
         * on this mesh and leaving them off would misstate it. They are
         * simply not doors.
         */
        filterable: !/^UNREADABLE_/.test(wire),
      };
    });
    const instance = chart(portnumChart, {
      ...CHART_BASE,
      tooltip: {
        ...CHART_BASE.tooltip,
        trigger: 'item',
        /*
         * `tooltipLines`, not a template literal.
         *
         * ECharts sets `innerHTML` from a returned string, and the
         * graph's tooltips already learned that: the string branch is the
         * only one that injects. Nothing in this tooltip is named by a
         * radio's owner today -- the label and the enum both come from
         * `traffic_label` -- but the line that says "today" is the line
         * somebody edits when they add the sender's name to it.
         *
         * `tooltipLines` returns an element and puts every value in as
         * text, so markup is shown rather than run. The formatter this
         * replaced interpolated into markup with an arrow's implicit
         * return, which `test_tooltip_escaping` did not catch because its
         * pattern looks for a `return` keyword.
         */
        formatter: (item) => {
          const band = bands[item.dataIndex];
          if (!band) return String(item.name);
          return tooltipLines(
            `${band.label} (${band.wire})`,
            `${count(band.count)} packets`,
            band.filterable
              ? 'Click to open these in the firehose'
              : 'Not a packet type, so the firehose cannot filter on it',
          );
        },
      },
      xAxis: { type: 'value', ...AXIS },
      yAxis: { type: 'category', data: bands.map((band) => band.label), ...AXIS },
      series: [{
        type: 'bar',
        // The cursor is the only thing on the canvas that can say a bar
        // is a door, and three of them are not.
        data: bands.map((band) => ({
          value: band.count,
          cursor: band.filterable ? 'pointer' : 'default',
        })),
        itemStyle: { color: PALETTE.accent, borderRadius: [0, 3, 3, 0] },
      }],
    });
    /*
     * `off` before `on`, and this is not defensive tidying.
     *
     * `chart()` reuses the ECharts instance for a box, and `setOption`
     * does not touch event handlers. The dashboard re-renders on a theme
     * change, on a preset change and on every return to the page, so
     * each visit adds another handler to the same instance. Measured
     * with the `off` taken out: four returns to the dashboard left FOUR
     * click listeners on the one instance, and the count has no ceiling
     * -- a reader who spends a session moving between pages accumulates
     * a handler per visit.
     *
     * Measured honestly, the navigation itself survives it, because
     * assigning a hash that is already set does nothing. So the harm is
     * a listener leak and a handler that runs N times per click, not a
     * broken Back button. It is still the bug, and it is invisible.
     */
    if (instance) {
      instance.off('click');
      instance.on('click', (params) => {
        const band = bands[params.dataIndex];
        // A click on an axis label or the grid has no data index. Doing
        // nothing is right; navigating to `#firehose?type=undefined`
        // would be a filter nobody asked for.
        if (!band || !band.filterable) return;
        location.hash = firehoseHref(band.wire, PORTNUM_CHART_HOURS).slice(1);
      });
    }
  }
};

/* --- Map ------------------------------------------------------- */

const mapState = { map: null, nodes: null, traffic: null, links: null, traces: null };

/*
 * Exposed so the map can be answered from the browser console: which
 * layers hold what, where the view is, and whether the live lines are
 * clearing themselves. Nothing reads it back.
 */
window.SonoranMap = mapState;

/*
 * The role table, the port number table and the words for both live in
 * labels.js, which loads first. Three files needed them and each used
 * to carry its own copy, so the same value had three spellings on
 * pages a reader moves between.
 */
const { ROLES, roleLabel, portnumLabel, portnumWire } = window.SonoranLabels;

const KNOWN_ROLES = new Set(ROLES.map((role) => role.key));
const roleColour = (role) => colour(`role-${role}`, PALETTE.muted);

/** A role as a table cell: readable, with the wire value beside it.
 *
 * These cells printed the protocol enum, and the column is narrow enough
 * on the dashboard that `CLIENT_MUTE` was cut to `CLIENT_` — which is
 * not a role, but reads exactly like one. Truncation that looks like a
 * value is worse than truncation that looks like truncation.
 *
 * `roleLabel` already existed and was already used by the map legend and
 * the node chips. The tables simply never called it.
 *
 * The exact wire value then lived only in `title`, which on a phone is
 * nowhere: there is no hover, so "Client mute" could not be turned back
 * into `CLIENT_MUTE` by anybody holding a touchscreen. `data-exact`
 * carries it into the DOM, and `revealHints` lists every distinct value
 * a column actually holds under the table, in plain sight and one tap
 * away. Per row it costs an attribute; the column keeps its width, which
 * is the whole reason the label is there.
 */
function roleCell(role) {
  if (!role) return el('span', { class: 'muted', text: '-' });
  return el('span', { title: role, 'data-exact': role, text: roleLabel(role) });
}

/** A port number as a table cell: readable, with the wire value beside it.
 *
 * Same bargain as `roleCell`, and the same fix. `TELEMETRY_APP` is the
 * exact thing the firmware sent and it is not a phrase anybody says out
 * loud, so the cell reads "Telemetry" and the exact value goes to
 * `revealHints` through `data-exact`. The packet page still prints the
 * enum in full, because that page exists to show the record rather than
 * to summarise it.
 */
function portnumCell(portnum) {
  if (portnum == null || portnum === '') return el('span', { class: 'muted', text: '-' });
  return el('span', {
    title: String(portnum), 'data-exact': String(portnum), text: portnumLabel(portnum),
  });
}

/**
 * The colour of one node.
 *
 * The role decides the colour. Being a gateway is not a role, so it
 * does not take the colour over: it draws a ring instead. A node not
 * heard recently keeps its colour and loses its opacity, so the role
 * can still be read.
 */
function nodeColour(node) {
  return node.role ? roleColour(node.role) : PALETTE.muted;
}

const isStale = (node) => ageHours(node.last_heard) > 24;

/** The circle style for one node. */
/*
 * How big a dot is at a given zoom (#196).
 *
 * Every node was a 5 px circle (7 px for a gateway) at EVERY zoom, so
 * at the opening view Phoenix and Tucson -- hundreds of nodes each --
 * merged into two solid blobs.
 *
 * Clustering was considered and rejected: a cluster replaces a
 * position with a count drawn at a centroid, and these positions are
 * already fuzzed to between 1.4 km and 5 km (#96). A centroid of
 * uncertain coordinates invents a place. The blob at least tells the
 * truth about density, so the fix is to make the marks fit the zoom
 * rather than to stop drawing them.
 */
function nodeRadius(zoom) {
  if (zoom <= 7) return 2.5;
  if (zoom <= 10) return 3.5;
  if (zoom <= 13) return 5;
  return 6.5;
}

/*
 * From which zoom a gateway wears its ring (#196).
 *
 * Sampled in light mode, the most common opaque colour on the whole
 * map was `#25190f` -- the gateway stroke. 80 rings were more of the
 * visible ink than any role colour, which inverts what the map is
 * about: a gateway is not a role, and the ring must not take the
 * colour over.
 *
 * At the opening view a gateway is a dot like any other. Where you can
 * actually tell two nodes apart, it gains its ring.
 */
const GATEWAY_RING_FROM_ZOOM = 9;

function nodeStyle(node, zoom) {
  const fill = nodeColour(node);
  const stale = isStale(node);
  // The node a `#map/node/<id>` link asked for keeps its mark through
  // every redraw and every zoom change (#193.6).
  const focused = mapState.focusNodeId && node.node_id === mapState.focusNodeId;
  const level = typeof zoom === 'number' ? zoom : GATEWAY_RING_FROM_ZOOM;
  const ringed = node.is_mqtt_gateway && level >= GATEWAY_RING_FROM_ZOOM;
  const radius = nodeRadius(level);
  return {
    radius: (node.is_mqtt_gateway ? radius + 1 : radius) + (focused ? 2 : 0),
    // A gateway wears a ring, in a mid tone rather than the text
    // colour, and only once the map is close enough to read it. A
    // focused node's ring takes the accent, which no role uses.
    color: focused ? PALETTE.accent : ringed ? PALETTE.muted : fill,
    weight: focused ? 3 : 1.5,
    fillColor: fill,
    fillOpacity: stale ? 0.15 : 0.6,
    opacity: stale ? 0.35 : 1,
  };
}

/*
 * The node a `#map/node/<id>` link asked the map to open on, or null.
 *
 * Cleared when the reader leaves the map, so a later visit opens
 * normally rather than jumping to whatever was linked once.
 */
let mapFocus = null;

/*
 * How far in a focus link may zoom (#193.6, #96).
 *
 * Deliberately short of street level. A position rounded by its owner
 * can be kilometres out, and a map zoomed to a building around a
 * coarse position asserts a precision nobody has. 13 is close enough
 * to see the node among its neighbours and far enough that the dot is
 * not read as an address.
 */
const MAP_FOCUS_ZOOM = 13;

/*
 * The roles the map is limited to. Empty means every role.
 *
 * The legend doubles as the control for it: each entry is a button.
 * Several roles can be on at once, so "routers and routers late" is one
 * click each rather than another control.
 */
const roleFilter = new Set();

const roleOf = (node) => node.role || '';
const passesRoleFilter = (node) => roleFilter.size === 0 || roleFilter.has(roleOf(node));

/**
 * Redraw after the filter changes.
 *
 * The node list is the one held from the last refresh, so this needs no
 * request and the map answers the click at once.
 */
function applyRoleFilter() {
  const rows = mapState.lastNodes || [];
  drawMapNodes(rows);
  drawMapLegend($('[data-map-legend]', $('[data-page="map"]')), rows);
}

/**
 * Build the map legend from the roles actually present.
 *
 * Listing all fifteen roles when the mesh runs seven of them is noise,
 * so this counts what came back and shows only those. Each entry is a
 * button that limits the map to that role.
 */
/*
 * What the dots on the map are, in words. The map draws one preset at a
 * time, so the count changes when the picker does, and a reader who
 * does not know that sees nodes disappear for no reason.
 */
let mapNodeScope = '';

function drawMapLegend(target, rows) {
  const counts = new Map();
  for (const row of rows) {
    const key = roleOf(row);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const order = [...ROLES.map((role) => role.key), ''];
  const present = [...counts.entries()]
    .sort((a, b) => {
      const rank = order.indexOf(a[0]) - order.indexOf(b[0]);
      return rank !== 0 ? rank : b[1] - a[1];
    });

  replace(target, [
    ...present.map(([role, total]) =>
      el('button', {
        type: 'button',
        class: 'legend-key',
        'aria-pressed': String(roleFilter.has(role)),
        title: `${total} node${total === 1 ? '' : 's'}. Click to show only these.`,
      },
      el('span', {
        class: 'swatch',
        style: `background:${role ? roleColour(role) : PALETTE.muted}`,
      }),
      `${roleLabel(role)} (${count(total)})`)),
    roleFilter.size
      ? el('button', { type: 'button', class: 'legend-key clear', text: 'Show every role' })
      : null,
    el('span', { class: 'legend-note' }, el('span', { class: 'swatch ring' }), 'MQTT gateway'),
    el('span', { class: 'legend-note' }, el('span', { class: 'swatch faded' }), 'Not heard in 24 h'),
    // The two kinds of traffic line mean different things, so both are
    // named. A relayed line is a path, not a radio link.
    el('span', { class: 'legend-note' }, el('span', { class: 'line direct' }), 'Heard direct'),
    el('span', { class: 'legend-note' }, el('span', { class: 'line relayed' }), 'Relayed, arrow shows where it went'),
    el('span', { class: 'legend-note' }, el('span', { class: 'line neighbour' }), 'Neighbor link'),
    /*
     * The two heat layers, named here as well as in the watch legend.
     *
     * They are drawn on this page too, and a mark that appears on the
     * default view with nothing to say what it is invites a reader to
     * invent a meaning for it — and the meaning they would invent for a
     * glow around a node is "this is how many nodes heard it", which is
     * the one reading AGENTS.md 9.5.1 exists to forbid. Short here,
     * because the collapsible legend has the room for the rest.
     */
    el('span', { class: 'legend-note' }, el('span', { class: 'swatch halo' }),
      'Halo: how much this node said'),
    el('span', { class: 'legend-note' }, el('span', { class: 'swatch upload-ring' }),
      'Ring: how much this node uploaded, as a gateway. Never added to the halo'),
    // Which nodes these dots are, so a shrunken map is never a mystery.
    mapNodeScope ? el('span', { class: 'legend-note muted', text: mapNodeScope }) : null,
  ]);

  // The handlers are attached after the fact so each button carries the
  // role it stands for, and the "show every role" button clears the lot.
  const buttons = $$('.legend-key', target);
  present.forEach(([role], index) => {
    buttons[index].addEventListener('click', () => {
      if (roleFilter.has(role)) roleFilter.delete(role);
      else roleFilter.add(role);
      applyRoleFilter();
    });
  });
  const clear = $('.legend-key.clear', target);
  if (clear) {
    clear.addEventListener('click', () => {
      roleFilter.clear();
      applyRoleFilter();
    });
  }
}

/* The region the map opens on, as Leaflet bounds, or null (#195).
 *
 * A deployment that has not set one falls back to the centre and zoom,
 * which is what every page did before this. */
function homeBounds() {
  const home = CONFIG.mapHome;
  if (!Array.isArray(home) || home.length !== 2) return null;
  const bounds = L.latLngBounds(home);
  return bounds.isValid() ? bounds : null;
}

function ensureMap() {
  if (mapState.map) return mapState.map;
  /*
   * `zoomSnap: 0.25` so a region can actually fill the box (#195).
   *
   * With the default snap of 1, `fitBounds` rounds down to a whole
   * zoom, which on a wide short box left Arizona filling under a third
   * of the width -- the same complaint the integer `mapZoom` produced.
   * A quarter step costs nothing and lets the fit land where it means.
   */
  const map = L.map('map', { preferCanvas: true, worldCopyJump: true, zoomSnap: 0.25 });
  const home = homeBounds();
  if (home) {
    // The deployment's own statement of what it is about, fitted to
    // whatever shape of screen the reader has.
    map.fitBounds(home, { padding: [20, 20] });
  } else {
    map.setView(CONFIG.mapCenter || [34.0, -111.5], CONFIG.mapZoom || 7);
  }
  /*
   * Resize the dots when the zoom changes (#196).
   *
   * `setStyle` on existing markers, so this costs no request and no
   * rebuild of the layer: at 1,268 nodes it is the same order of work
   * the live map already does on each poll.
   */
  map.on('zoomend', () => {
    const level = map.getZoom();
    for (const [marker, row] of mapState.marks || []) marker.setStyle(nodeStyle(row, level));
  });
  if (CONFIG.tileUrl) {
    L.tileLayer(CONFIG.tileUrl, {
      className: 'basemap-tiles',
      attribution: CONFIG.tileAttribution || '',
      maxZoom: 19,
    }).addTo(map);
  }
  mapState.nodes = L.layerGroup().addTo(map);
  mapState.links = L.layerGroup();
  mapState.map = map;
  /*
   * The live traffic and the live traceroutes are no longer Leaflet
   * layers. They are marks in one canvas, drawn by one animation loop.
   * See map-live.js for why: the old layer drew a polyline per upload
   * and faded it with twelve timers, which is hundreds of timers a
   * second and hundreds of thousands of Leaflet objects an hour.
   */
  mapState.live = SonoranLive.create(map, {
    colour,
    snrColour,
    // The backlog and the lag change every frame, so they are written
    // from the loop rather than once per fetch.
    onStats: liveCounters,
  });
  mapState.live.setFamilyFilter(hiddenFamilies);
  /*
   * `window.SonoranMap` is already how this map answers questions from
   * the console. The animation's own numbers go in the same place, so
   * the frame budget can be checked without a build step: marks alive,
   * marks dropped, and the draw time percentiles.
   */
  mapState.stats = mapState.live.stats;
  installWatchMode(map);
  installMapKey(map);
  return map;
}

function drawMapNodes(rows) {
  mapState.nodes.clearLayers();
  const bounds = [];
  const zoom = mapState.map ? mapState.map.getZoom() : undefined;
  // Every marker drawn this pass, so a zoom change can restyle them
  // without refetching or rebuilding the layer (#196).
  mapState.marks = [];
  for (const row of rows) {
    if (row.lat == null || row.lon == null) continue;
    if (!passesRoleFilter(row)) continue;
    bounds.push([row.lat, row.lon]);
    const marker = L.circleMarker([row.lat, row.lon], nodeStyle(row, zoom));
    mapState.marks.push([marker, row]);
    const popup = el('div', {},
      el('div', { style: 'font-weight:650' }, row.display_name || row.node_id),
      el('div', { class: 'muted', style: 'font-size:.8rem' },
        `${row.node_id} - heard ${ago(row.last_heard)} ago`),
      el('div', { style: `font-size:.8rem;color:${nodeColour(row)}` },
        roleLabel(row.role) + (row.is_mqtt_gateway ? ', MQTT gateway' : '')),
      row.hw_model ? el('div', { class: 'muted', style: 'font-size:.8rem', text: row.hw_model }) : null,
      el('button', { class: 'linky', type: 'button', text: 'Open node detail', onclick: () => openNode(row.node_id) }));
    marker.bindPopup(popup);
    marker.addTo(mapState.nodes);
  }
  return bounds;
}

/** The dashboard link to one packet's full record. */
const packetHref = (event) =>
  `#packet/${encodeURIComponent(event.from.node_id)}/${event.packet_id}`;


/*
 * The live traffic animation.
 *
 * The unit is the packet, not the upload. This is the whole of the
 * change and it is worth stating plainly. `packet_seen` holds MQTT
 * uploads, so one packet arrives as many rows: a live packet measured in
 * AGENTS.md 9.5.1 had 22 uploads from 15 gateways. Drawing a line per
 * row fired up to 22 strokes out of one node inside one refresh, and the
 * picture then said "this node was just heard by fifteen nodes", which is
 * the single reading 9.5.1 exists to forbid. Every one of those strokes
 * carried an honest tooltip, and nobody hovers a tooltip at fifty events
 * a second.
 *
 * So uploads are grouped into packets, at most three arcs are drawn to
 * the gateways that burned the fewest hops, and the rest become a
 * numeral beside the sender and an exact count in the panel.
 *
 * Geometry carries the honesty. A flat line claims a radio link, so only
 * a `direct` observation gets one; a relayed arc bows by its hop count,
 * and an unknown hop count is stippled. See map-live.js.
 */
/*
 * How many observations to ask for. It is the endpoint maximum. The
 * counts in the summary come from the endpoint and are of the whole
 * window whatever this is, and `truncated` says when the cap bit.
 */
const TRAFFIC_LIMIT = 2000;

// Each packet this tab has already animated, mapped to its own time in
// ms. The time is what the pruning reads: a packet older than the window
// can never come back, so its key is safe to forget, and nothing still
// inside the window is ever dropped. An earlier trim dropped by
// insertion order, which deleted the newest keys of the first pass and
// made the map re-draw traffic it had already drawn.
const trafficSeen = new Map();

/*
 * The packet kinds the viewer chose not to see, remembered per browser.
 *
 * The hidden set is stored rather than the shown one, so a family that a
 * later build adds is drawn by default instead of silently missing. A
 * key this build does not know is dropped on load. Storage can be
 * refused (a private window, a full quota), and then the map simply
 * forgets between visits.
 */
const FAMILY_FILTER_KEY = 'sonoran.map.hiddenFamilies';
const hiddenFamilies = recallHiddenFamilies();

function recallHiddenFamilies() {
  try {
    const saved = JSON.parse(localStorage.getItem(FAMILY_FILTER_KEY) || '[]');
    if (!Array.isArray(saved)) return new Set();
    return new Set(saved.filter((key) => Object.hasOwn(SonoranLive.FAMILIES, key)));
  } catch {
    return new Set();
  }
}

function keepHiddenFamilies() {
  try {
    localStorage.setItem(FAMILY_FILTER_KEY, JSON.stringify([...hiddenFamilies]));
  } catch {
    // Not kept. The choice still holds for this visit.
  }
}

/** Whether the packet filter lets a packet through. */
function familyShown(packet) {
  return !hiddenFamilies.has(SonoranLive.familyKey(packet.portnum));
}

/**
 * Build the packet kind chips, once.
 *
 * Each chip is a toggle with the family's own mark on it. "All Types"
 * appears only while something is hidden, as the way back.
 */
function wireFamilyFilter() {
  const chips = $('[data-family-chips]');
  if (!chips) return;
  const buttons = SonoranLive.FAMILY_ORDER.map((key) => {
    const family = SonoranLive.FAMILIES[key];
    return el('button', {
      type: 'button',
      class: 'family-chip',
      'aria-pressed': String(!hiddenFamilies.has(key)),
      dataset: { family: key },
      onclick: () => {
        if (hiddenFamilies.has(key)) hiddenFamilies.delete(key);
        else hiddenFamilies.add(key);
        familyFilterChanged();
      },
    }, familySwatch(family), family.label);
  });
  const all = el('button', {
    type: 'button',
    class: 'family-chip clear',
    text: 'All Types',
    onclick: () => {
      hiddenFamilies.clear();
      familyFilterChanged();
    },
  });
  replace(chips, buttons, all);
  paintFamilyFilter();
}

function paintFamilyFilter() {
  for (const button of $$('.family-chip[data-family]')) {
    button.setAttribute('aria-pressed', String(!hiddenFamilies.has(button.dataset.family)));
  }
  const all = $('.family-chip.clear');
  if (all) all.hidden = hiddenFamilies.size === 0;
  const total = SonoranLive.FAMILY_ORDER.length;
  const shown = total - hiddenFamilies.size;
  const summary = $('[data-family-summary]');
  if (summary) {
    summary.textContent = hiddenFamilies.size
      ? `Packet Types: ${shown} of ${total}`
      : 'Packet Types: all';
  }
}

function familyFilterChanged() {
  keepHiddenFamilies();
  paintFamilyFilter();
  if (mapState.live) mapState.live.setFamilyFilter(hiddenFamilies);
  if (currentPage === 'map') render('map');
}

/**
 * Hand the animation every packet it has not drawn yet.
 *
 * The first pass only records what is already in the window, so opening
 * the page does not fire fifteen minutes of traffic at once.
 *
 * `packets` is already keyed on (`from.node_id`, `packet_id`), which is
 * the identity AGENTS.md 9.1 gives. The old key was the observation's
 * packet ID, gateway and time: the time let a gateway's repeat upload
 * draw a second line over the first, and two coincident strokes at 0.7
 * opacity read as one at 0.91, which is a quantity nobody measured.
 */
function releaseTraffic(packets, firstPass, cutoffMs, intervalMs) {
  const fresh = [];
  for (const packet of packets) {
    const known = trafficSeen.has(packet.key);
    trafficSeen.set(packet.key, packet.timeMs || Date.now());
    if (known || firstPass) continue;
    // A packet of a hidden kind is still recorded as seen above, so
    // showing its kind again later does not replay it as if it were new.
    if (!familyShown(packet)) continue;
    // A packet whose only upload was the sender's own still fires its
    // emission pulse, so `arcs` being empty is not a reason to skip it.
    fresh.push(packet);
  }
  if (cutoffMs != null) {
    for (const [key, seenAt] of trafficSeen) {
      if (seenAt < cutoffMs) trafficSeen.delete(key);
    }
  }
  mapState.live.beginBatch();
  if (fresh.length) mapState.live.push(fresh, intervalMs);
  return fresh.length;
}

/*
 * The neighbour-link layer is background, not the subject.
 *
 * It draws a day and a half of reports, which is a lot of lines, so it
 * is kept faint. It must stay readable under the live traffic and the
 * traceroute animation, which are the things worth looking at.
 */
const LINK_HOURS = 32;

function drawLinks(edges, positions) {
  mapState.links.clearLayers();
  const seen = new Set();
  for (const edge of edges) {
    const a = positions.get(edge.from_node);
    const b = positions.get(edge.to_node);
    if (!a || !b) continue;
    const key = [edge.from_node, edge.to_node].sort().join('|');
    if (seen.has(key)) continue;
    seen.add(key);
    // A cool colour, so this layer reads as separate from the warm
    // traffic and traceroute lines rather than competing with them.
    //
    // 0.38 measured 2.04:1 against the page background in the dark
    // theme and 1.73:1 in the light one, both under the 3:1 floor for
    // meaningful non-text content (WCAG 1.4.11). At 0.85 it is 5.57
    // and 3.96. The dash pattern still separates it from the solid
    // traffic lines, and the cool colour still separates it by hue.
    //
    // The background here is basemap tiles rather than a panel, so the
    // page background is a stand-in rather than an exact figure. The
    // tiles are filtered dark, so the dark reading is the closer one.
    L.polyline([a, b], {
      color: PALETTE.link,
      weight: 1.3,
      opacity: 0.85,
      dashArray: '4 5',
    }).addTo(mapState.links);
  }
  return seen.size;
}

/* --- Live traceroutes ------------------------------------------- */

/*
 * A traceroute is drawn as it arrives, hop by hop, and then fades.
 *
 * The old map drew one straight line between the two ends of a trace.
 * Those ends can be many hops apart and often have no radio link at
 * all, so the line meant nothing. These are the hops the packet really
 * took, one segment for each.
 */
/*
 * Each traceroute this tab has already drawn, mapped to its own time in
 * ms — the same shape and the same reason as `trafficSeen`.
 *
 * It used to be a Set trimmed by slicing off the first thousand of two
 * thousand, which is an insertion-order prune: the exact bug that was
 * already found and fixed for traffic, where dropping the oldest *keys*
 * rather than the oldest *traces* deleted the newest entries of the
 * first pass and made the map redraw paths it had already drawn. It
 * survived here only because a traceroute arrives about 1.25 times a
 * minute, so two thousand keys is most of a day and the trim almost
 * never ran. Rare is not fixed.
 *
 * Time is what the prune reads. A trace older than the window can never
 * come back, so its key is safe to forget, and nothing still inside the
 * window is ever dropped.
 */
const traceSeen = new Map();

/**
 * Stop the animation and drop everything it holds.
 *
 * There is nothing left to cancel one mark at a time: the fades were
 * chains of setTimeout, thirteen per traffic line and twenty-five per
 * trace hop, up to five thousand pending. The whole page now runs on one
 * requestAnimationFrame loop, so stopping is one call.
 */
function stopMapAnimations() {
  if (mapState.live) mapState.live.clear();
}

/*
 * How many old traces to replay when the layer is switched on.
 *
 * The window already holds an hour of traces. Replaying all of them
 * would be a flash of lines and no information. Replaying none leaves
 * the layer looking broken until the next one arrives, which can be a
 * minute. A few of the newest shows what the layer does straight away.
 */
const TRACE_SEED = 3;

/**
 * Animate every trace that has not been shown yet.
 *
 * `traces` arrives newest first. After the first pass, only traces that
 * were not in the previous answer are drawn.
 */
function drawTraceroutes(traces, firstPass, cutoffMs) {
  let started = 0;
  let seeded = 0;
  for (const trace of traces) {
    const key = trace.trace_id || `${trace.time}-${trace.from.node_id}`;
    const known = traceSeen.has(key);
    traceSeen.set(key, Date.parse(trace.time) || Date.now());
    if (known) continue;

    const drawable = trace.hops.filter((hop) => hop.has_line);
    if (!drawable.length) continue;

    if (firstPass) {
      if (seeded >= TRACE_SEED) continue;
      // Stagger the seeded ones so they read as separate paths.
      mapState.live.pushTrace(drawable, seeded);
      seeded += 1;
      continue;
    }
    // A traceroute hop is the one mark on this map that is a measured
    // path, so it is the last thing the animation ever gives up. It stays
    // flat, and an unmeasured hop is stippled rather than coloured as if
    // it were weak: INT8_MIN means "not measured" (AGENTS.md 9.6).
    mapState.live.pushTrace(drawable, started);
    started += 1;
  }
  started += seeded;
  /*
   * Pruned by time, never by insertion order. The map would otherwise
   * grow for as long as the tab is open, and an order-based trim would
   * forget traces that are still inside the window and draw them again.
   */
  if (cutoffMs != null) {
    for (const [key, seenAt] of traceSeen) {
      if (seenAt < cutoffMs) traceSeen.delete(key);
    }
  }
  return started;
}

/* The modem preset every line layer on the map is drawn for. */
let linkChannel = '';

/**
 * Fill the preset selector.
 *
 * Every line layer draws one preset at a time. A node on LongFast
 * cannot hear a node on MediumFast, so a picture holding both would
 * show links that cannot exist. See AGENTS.md 9.7.
 */
/*
 * The channel list, cached for ten minutes.
 *
 * `api/graph/channels?hours=24` runs three 24-hour GROUP BY aggregates,
 * over `packet_seen`, `neighbor_metrics` and `traceroute`. It answers a
 * question that changes hourly and the map used to pay for it on every
 * refresh, which is four times a minute per open tab. Watch mode would
 * have made that worse.
 */
const CHANNELS_TTL_MS = 600000;
const channelCache = { at: 0, value: null };

/*
 * The preset every page filters by, or '' when there is nothing to add.
 *
 * One helper for the three pages that gained this -- the firehose, the
 * dashboard's message feed and the node list -- so they cannot drift into
 * asking for different things. Returns a plain string because all three
 * build a query rather than an object.
 *
 * Silent by design (Will, 2026-09-26): the menu says which preset is
 * selected, and a line on each page repeating it is the wordiness he had
 * just asked to be taken out of the nav.
 */
function presetChannel() {
  return window.SonoranPreset ? SonoranPreset.current() : '';
}

/** The same, ready to append to a query that already has one parameter. */
function chatFeedChannel() {
  const channel = presetChannel();
  return channel ? `&channel=${encodeURIComponent(channel)}` : '';
}

async function mapChannels() {
  const now = Date.now();
  if (channelCache.value && now - channelCache.at < CHANNELS_TTL_MS) return channelCache.value;
  const list = await get('api/graph/channels?hours=24').catch(() => null);
  if (!list) return channelCache.value;
  channelCache.at = now;
  channelCache.value = list;
  return list;
}

/*
 * The positioned nodes, cached for two minutes.
 *
 * Seven to nine hundred rows that change slowly, refetched on every
 * refresh. The key carries the preset and the "every node" toggle, so
 * changing either is an immediate refetch rather than a stale picture.
 */
const NODES_TTL_MS = 120000;
const nodeCache = { at: 0, key: '', value: null };

async function mapNodes(path) {
  const now = Date.now();
  if (nodeCache.value && nodeCache.key === path && now - nodeCache.at < NODES_TTL_MS) {
    return nodeCache.value;
  }
  const rows = await get(path).catch(() => null);
  if (!rows) return nodeCache.key === path ? nodeCache.value : null;
  nodeCache.at = now;
  nodeCache.key = path;
  nodeCache.value = rows;
  return rows;
}

async function linkChannelOptions(page) {
  const list = await mapChannels();
  const channels = (list && list.channels) || [];
  if (!channels.length) return null;

  /*
   * Which preset the link layer draws, in order of who gets to say.
   *
   * 1. `#map/node/<id>?preset=...` (#193.6). A link naming a preset means
   *    it, and applying it BEFORE the fetch is the whole point: the map
   *    draws one preset at a time (AGENTS.md 9.7), so a node on any other
   *    one is not drawn and the link lands on empty ground. Honoured only
   *    when this deployment actually carries that channel; otherwise the
   *    focus step below says the node is not here.
   * 2. the MENU's global preset, which is the normal case.
   * 3. whatever came first, so a deployment carrying neither still draws.
   *
   * The picker that used to be here is gone. It listed the modem presets
   * AND the topic channels beside them -- Weather, trivia -- so the link
   * layer could be pointed at any of them. Those rode on top of a preset
   * and never named one, so a reader could end up looking at Weather
   * links while the gaps page showed MediumFast and the graph showed
   * something else again. One global choice is what Will asked for, and
   * the trade is real: the topic link layers are no longer reachable
   * here. Worth restoring as a sub-choice WITHIN the preset if anybody
   * misses them.
   */
  if (mapFocus && mapFocus.preset
      && channels.some((item) => item.channel === mapFocus.preset)) {
    linkChannel = mapFocus.preset;
  } else if (window.SonoranPreset) {
    const wanted = SonoranPreset.current();
    if (channels.some((item) => item.channel === wanted)) linkChannel = wanted;
  }
  if (!channels.some((item) => item.channel === linkChannel)) {
    linkChannel = channels[0].channel;
  }

  /*
   * The name the live map's watch bar shows.
   *
   * Set here because this is where the channel is settled. Removing the
   * picker took the assignment with it, and the symptom was quiet: the
   * bar fell back to "Every preset" on a map drawing exactly one, so the
   * one thing a viewer must not forget -- which mesh they are watching --
   * would have been wrong rather than missing.
   */
  const chosen = channels.find((item) => item.channel === linkChannel);
  mapPresetLabel = (chosen && chosen.label) || linkChannel;

  /*
   * Tell the global control which presets this mesh actually carries.
   *
   * Filtered on the SERVER'S classification -- `api/channels.py` sets
   * `group: "Presets"` and a non-empty `preset` for a channel that names
   * a modem preset, and leaves `preset` empty for Weather, Traffic,
   * azmsh and the rest. Those ride on top of a preset without naming one
   * (AGENTS.md 9.7), so offering them in a preset switch would be a
   * choice that means nothing.
   *
   * The first version filtered against this module's own two-name
   * fallback, which was circular: it could only ever confirm the guess it
   * started from, so a deployment running ShortFast would never have
   * seen it offered.
   */
  if (window.SonoranPreset) {
    const presets = channels
      .filter((item) => item.group === 'Presets' && item.preset)
      .map((item) => String(item.preset));
    if (presets.length) SonoranPreset.setAvailable(presets);
  }
  return linkChannel;
}

/* The label of the preset the map is drawn for, for the watch status
 * line. The picker's own option text carries the counts, which are noise
 * once the choice is made. */
let mapPresetLabel = '';

/**
 * One packet as a feed row.
 *
 * The exact numbers are here rather than on the map: `gateway_count` is
 * distinct gateways and `upload_count` is rows, and the two are different
 * because one gateway uploads the same packet more than once. A live
 * packet had 22 uploads from 15 gateways. The list is of uploads, never
 * of listeners — only a gateway reports, so a node that heard this and is
 * not a gateway is invisible to this database. See AGENTS.md 9.5.1.
 */
function trafficRow(packet) {
  return el('li', {},
    el('div', {}, nodeChip(packet.from),
      /*
       * How many packets this row stands for, when a run of them from
       * one sender of one kind collapsed into it. Always present and
       * usually empty, so the keyed update has one cell to rewrite
       * rather than a row to rebuild.
       */
      el('span', {
        class: 'repeats',
        'data-repeats': '',
        text: packet.repeats > 1 ? `x${count(packet.repeats)}` : '',
      })),
    el('div', { class: 'meta' },
      el('span', { text: gatewayTally(packet) }),
      // Only a direct observation measures the sender's own link. On a
      // relayed one the SNR belongs to the last hop into the gateway,
      // which is a different pair of radios. The packet page has always
      // done this; the map feed did not, and two pages reading one
      // endpoint gave two answers.
      packet.any_direct && packet.direct_snr != null ? snrCell(packet.direct_snr) : null,
      el('span', { class: trafficKindClass(packet), text: trafficKind(packet) }),
      // The packet itself, so the whole record is one click away. The map
      // marks are canvas and carry no tooltip, so this is the route in.
      el('a', {
        class: 'linky',
        href: packetHref(packet),
        text: portnumLabel(packet.portnum),
      }),
      el('span', { text: clock(packet.time) })));
}

/* --- The feed under load ---------------------------------------- */

/* How far apart two packets from one sender may be and still be one
 * row. A tracker posting a position every thirty seconds is the case
 * this exists for, so the gap has to be comfortably longer than that. */
const COALESCE_MS = 60000;
/* Forty rows, trimmed rather than rebuilt. */
const FEED_ROWS = 40;

/**
 * Collapse a run of near-identical rows into one with a count.
 *
 * Consecutive packets from the same sender, of the same kind, inside a
 * minute. Without this one tracker posting a position every thirty
 * seconds owns the panel, and the panel is where the exact numbers live
 * — so a panel a viewer has stopped reading has taken the precision
 * with it.
 *
 * Only a consecutive run collapses. A row is never moved to join
 * another, so the order is still the order things happened in and a gap
 * in the middle is still a gap.
 *
 * The collapsed row keeps the newest packet, because that is the one
 * whose link and whose counts are about now, and carries `repeats` so
 * the row can say how many it stands for. Nothing is hidden: the number
 * of packets is on the row and the window summary above it is unchanged.
 */
function coalesceFeed(packets) {
  const rows = [];
  for (const packet of packets) {
    const last = rows[rows.length - 1];
    if (last
      && last.from.node_id === packet.from.node_id
      && last.portnum === packet.portnum
      && Math.abs(last.timeMs - packet.timeMs) <= COALESCE_MS) {
      last.repeats = (last.repeats || 1) + 1;
      continue;
    }
    rows.push({ ...packet, repeats: 1 });
  }
  return rows;
}

/**
 * Update the feed in place instead of rebuilding it.
 *
 * `replace()` of the whole list every fifteen seconds destroys the
 * scroll position and any text selection. On the ordinary page the list
 * is short and the loss is an irritation; in watch mode the panel is
 * tall and a viewer reading a row halfway down loses it four times a
 * minute, which makes the panel useless for the one thing it is for.
 *
 * So rows are keyed and reconciled: an unchanged row is left alone, a
 * new one is inserted where it belongs, a row whose repeat count grew
 * has that one cell rewritten, and the surplus is trimmed off the end.
 * A new row is marked for a moment so the eye can find what arrived.
 */
function updateFeed(list, rows, emptyText) {
  if (!rows.length) {
    replace(list, [empty(emptyText)]);
    return;
  }
  const existing = new Map();
  for (const item of [...list.children]) {
    if (item.dataset && item.dataset.key) existing.set(item.dataset.key, item);
    else item.remove();
  }
  let before = list.firstChild;
  for (const row of rows) {
    const held = existing.get(row.key);
    if (held) {
      existing.delete(row.key);
      // The count is the only cell that can change on a row that is
      // already drawn, so it is the only one rewritten.
      const badge = held.querySelector('[data-repeats]');
      const wanted = row.repeats > 1 ? `x${count(row.repeats)}` : '';
      if (badge && badge.textContent !== wanted) badge.textContent = wanted;
      if (held !== before) list.insertBefore(held, before);
      else before = held.nextSibling;
      continue;
    }
    const made = trafficRow(row);
    made.dataset.key = row.key;
    made.classList.add('feed-new');
    list.insertBefore(made, before);
    // One frame later, so the class change is a transition rather than
    // the state the row was born in.
    requestAnimationFrame(() => made.classList.remove('feed-new'));
  }
  for (const item of existing.values()) item.remove();
  while (list.children.length > FEED_ROWS) list.lastChild.remove();
}

/** "3 gateways, 5 uploads", with the singulars right. */
function gatewayTally(packet) {
  const gateways = `${count(packet.gateway_count)} gateway${packet.gateway_count === 1 ? '' : 's'}`;
  if (packet.upload_count === packet.gateway_count) return gateways;
  return `${gateways}, ${count(packet.upload_count)} uploads`;
}

/**
 * The expanded panel's table.
 *
 * Every column was already in the response and thrown away by the
 * renderer. There is no SNR column for a packet with no direct
 * observation, and that is not an omission: the reading on a relayed
 * observation belongs to the last hop into the gateway (AGENTS.md 9.5).
 */
function trafficTable(packets) {
  return table([
    { label: 'Time', cell: (row) => el('span', { text: clock(row.time) }) },
    { label: 'Sender', cell: (row) => nodeChip(row.from) },
    {
      label: 'Kind',
      cell: (row) => el('a', { class: 'linky', href: packetHref(row), text: portnumLabel(row.portnum) }),
    },
    {
      label: 'Hops',
      num: true,
      cell: (row) => (row.min_hops == null
        ? el('span', { class: 'muted', text: 'not recorded' })
        : el('span', { text: String(row.min_hops) })),
    },
    { label: 'Gateways', num: true, cell: (row) => el('span', { text: count(row.gateway_count) }) },
    { label: 'Uploads', num: true, cell: (row) => el('span', { text: count(row.upload_count) }) },
    {
      label: 'SNR',
      num: true,
      cell: (row) => (row.any_direct && row.direct_snr != null
        ? snrCell(row.direct_snr)
        : el('span', { class: 'muted', text: '-' })),
    },
    { label: 'Channel', cell: (row) => el('span', { text: row.channel || '-' }) },
  ], packets, 'No traffic in the window.');
}

/* --- The packets-per-second sparkline ---------------------------- */

/* Sixty one-second samples. The interval is stated beside the chart,
 * because a rate chart whose sample interval is not given is a chart
 * whose shape nobody can check. */
const SPARK_SECONDS = 60;

/**
 * Packets a second, raw, over the last minute.
 *
 * One bar per second and no smoothing. A smoothed line would hide the
 * bursts, and the bursts are the phenomenon: "there's so many nodes
 * hearing things" is a description of a burst, and a chart that averaged
 * it away would answer a question nobody asked.
 *
 * It counts packets, never uploads, for the same reason everything else
 * on this page does. `packet_seen` holds MQTT uploads, so a chart of
 * rows would rise when one gateway reconnected and uploaded a backlog,
 * and read as the mesh getting busier when nothing had changed about the
 * mesh. See AGENTS.md 9.5.1.
 *
 * Where the returned window does not cover a second, the bar is left out
 * rather than drawn as zero. An endpoint row limit is not evidence that
 * nothing happened (AGENTS.md 9.19), and a zero bar is exactly that
 * claim. The gap is drawn as a gap and named under the chart.
 */
function drawSparkline(canvas, packets, truncated) {
  if (!canvas) return;
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const width = canvas.clientWidth || 260;
  const height = canvas.clientHeight || 34;
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, width, height);
  if (!packets.length) return;

  const now = Date.now();
  const oldest = packets.reduce(
    (low, packet) => Math.min(low, packet.timeMs || now), now);
  const buckets = new Array(SPARK_SECONDS).fill(0);
  // A second older than the oldest row the endpoint returned is a second
  // this page knows nothing about, so it is not a zero.
  const known = buckets.map((_, index) => now - (SPARK_SECONDS - index) * 1000 >= oldest);
  for (const packet of packets) {
    const age = now - (packet.timeMs || now);
    if (age < 0 || age >= SPARK_SECONDS * 1000) continue;
    buckets[SPARK_SECONDS - 1 - Math.floor(age / 1000)] += 1;
  }
  const peak = Math.max(1, ...buckets.filter((_, index) => known[index]));
  const step = width / SPARK_SECONDS;
  ctx.fillStyle = colour('accent', '#f4703f');
  for (let index = 0; index < SPARK_SECONDS; index += 1) {
    if (!known[index]) continue;
    const tall = (buckets[index] / peak) * (height - 2);
    ctx.fillRect(index * step, height - tall, Math.max(1, step - 1), tall);
  }
  return { peak, truncated };
}

/* --- Watch mode ------------------------------------------------- */

/*
 * The system setting is the default of the toggle, not a lock.
 *
 * A viewer whose system says "reduce" may still want the animation on
 * this one page, and a viewer whose system says nothing may want it off
 * on a train. Nothing on this map is encoded in motion alone — direction
 * has a static form in the taper and the chevron, the hop count is in the
 * geometry, the packet kind is in the shape — so both states say the
 * same things.
 */
const REDUCED_MOTION = window.matchMedia
  ? window.matchMedia('(prefers-reduced-motion: reduce)')
  : { matches: false, addEventListener: () => {} };

function motionButton() {
  return $('[data-map-motion]');
}

/** Push the toggle's state into the animation. */
function applyMotionSetting() {
  const button = motionButton();
  if (!button || !mapState.live) return;
  mapState.live.setReduced(button.getAttribute('aria-pressed') !== 'true');
}

/**
 * Draw one packet family's mark, as the map draws it.
 *
 * The watch legend and the packet filter both use it, so a chip and the
 * mark it controls are the same shape and the same colour.
 */
function familySwatch(family) {
  const box = el('canvas', { class: 'pkt-swatch', width: '16', height: '16' });
  const ctx = box.getContext('2d');
  const paint = colour(family.token, family.fallback);
  ctx.strokeStyle = paint;
  ctx.fillStyle = paint;
  const size = Math.min(family.size, 10);
  const half = size / 2;
  if (family.shape === 'disc') { ctx.beginPath(); ctx.arc(8, 8, half, 0, Math.PI * 2); ctx.fill(); }
  else if (family.shape === 'ring') { ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(8, 8, half, 0, Math.PI * 2); ctx.stroke(); }
  else if (family.shape === 'square') ctx.fillRect(8 - half, 8 - half, size, size);
  else if (family.shape === 'capsule') { ctx.beginPath(); ctx.roundRect(8 - half, 6.5, size, 3, 1.5); ctx.fill(); }
  else if (family.shape === 'diamond') {
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(8, 8 - half); ctx.lineTo(8 + half, 8); ctx.lineTo(8, 8 + half); ctx.lineTo(8 - half, 8);
    ctx.closePath(); ctx.stroke();
  } else if (family.shape === 'cross') {
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(8 - half, 8); ctx.lineTo(8 + half, 8); ctx.moveTo(8, 8 - half); ctx.lineTo(8, 8 + half);
    ctx.stroke();
  } else {
    ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(8 - half, 8); ctx.lineTo(8 + half, 8); ctx.stroke();
  }
  return box;
}

/**
 * Build the legend, once, inside watch mode.
 *
 * It names what the marks mean in the terms the data supports, and the
 * shapes are drawn rather than described, because a described shape is
 * not a shape. The preset is in the status line above and never
 * collapses, so it is not repeated here.
 */
function watchLegend(target) {
  replace(target, ...mapKeyBody(),
    el('p', { class: 'muted', text: 'Press ? to close. F leaves watch mode, T switches tab, E changes the panel height.' }));
}

/**
 * What every mark on the live map means, in one place (#46).
 *
 * The watch legend and the key docked on the map both draw this, so
 * the two can never describe the map differently. It names all four
 * encodings the map uses: the shape of a mark, its colour, the colour
 * of a line, and the halo and ring. It also says what a line is not.
 */
function mapKeyBody() {
  return [
    el('p', { class: 'muted', text: 'Dots are nodes, coloured by role. The role key under the map filters them.' }),
    el('h3', { text: 'What the marks mean' }),
    el('div', { class: 'legend' },
      el('span', { class: 'legend-note' }, el('span', { class: 'line direct' }),
        'Flat line: a measured radio link'),
      el('span', { class: 'legend-note' }, el('span', { class: 'line relayed' }),
        'Bowed line: a relation whose route is not recorded. Higher bow, more hops'),
      el('span', { class: 'legend-note' }, el('span', { class: 'line stipple' }),
        'Stippled: not measured, for a hop count and for a signal alike'),
      el('span', { class: 'legend-note' }, el('span', { class: 'line neighbour' }),
        'Neighbor link, a node naming a node it hears itself')),
    el('p', { class: 'muted', text: 'A flat line takes the colour of its signal: green good, yellow fair, red weak. Every other line takes the colour of its packet.' }),
    el('h3', { text: 'What a packet was' }),
    el('div', { class: 'legend' },
      SonoranLive.FAMILY_ORDER.map((key) => {
        const family = SonoranLive.FAMILIES[key];
        return el('span', { class: 'legend-note' }, familySwatch(family), family.label);
      })),
    /*
     * The two heat layers, named in the design's own words, and named
     * separately because that is the whole of what keeps them honest.
     *
     * A halo is how much a node said: one point for each packet it
     * originated. A ring is how much it uploaded as a gateway: one point
     * for each upload row, other people's traffic included. They are
     * never added together. A busy gateway relaying other people's
     * traffic is not a chatty node, and one glow holding both would be
     * AGENTS.md 9.5.1 reappearing as an aggregate — the map would be
     * drawing uploads as though they were something the node did, which
     * is the reading phase 1 spent its whole budget removing.
     */
    el('h3', { text: 'How busy a node is' }),
    el('div', { class: 'legend' },
      el('span', { class: 'legend-note' }, el('span', { class: 'swatch halo' }),
        'Halo: how much this node said. Wider means more packets it sent itself, over the last half minute or so'),
      el('span', { class: 'legend-note' }, el('span', { class: 'swatch upload-ring' }),
        'Ring: how much this node uploaded. Thicker means more uploads it made as a gateway, of anybody’s traffic'),
      el('span', { class: 'legend-note muted' },
        'The two are never added together, and neither is a scale you can read a number off. A gateway carrying other people’s traffic is not a node with a lot to say.')),
    /*
     * The one line of prose the design insists on. "Heard by" is banned
     * from this feature and the word is "uploaded": `packet_seen` records
     * MQTT uploads, so every observer this database can hold is a
     * gateway, and a count of them says nothing about coverage.
     * See AGENTS.md 9.5.1.
     */
    el('p', { class: 'muted', text: 'Uploads, not listeners. Only a gateway reports, so a node that heard a packet and did not upload it is invisible here. A "+N" beside a sender counts the gateways whose arcs are not drawn.' }),
    el('p', { class: 'muted', text: 'A line from a node to a gateway is an upload, not a radio link. The packet may have crossed several relays on the way, and their route is not recorded.' }),
    el('p', { class: 'muted', text: 'Every mark flies for the same time, whatever the distance. Speed is not data: each gateway stamps its own clock, so latency cannot be measured.' }),
  ];
}

/* The key's open or closed state, kept for this browser only. */
const MAP_KEY_STORE = 'sonoran.mapKey';

function mapKeyOpen() {
  try {
    return localStorage.getItem(MAP_KEY_STORE) !== 'closed';
  } catch {
    return true;
  }
}

/**
 * Dock the key on the map, where the reader is already looking (#46).
 *
 * It opens on a first visit and remembers the choice after that. It is
 * a `details`, so it opens with a tap or a key and needs no hover. On a
 * phone it starts closed whatever was stored, because an open key would
 * cover most of a small map.
 */
function installMapKey(map) {
  const Key = L.Control.extend({
    options: { position: 'topright' },
    onAdd() {
      const small = matchMedia('(max-width: 40rem)').matches;
      const box = el('details', { class: 'map-key leaflet-control', open: !small && mapKeyOpen() },
        el('summary', { text: 'Key' }),
        el('div', { class: 'map-key-body' }, mapKeyBody()));
      box.addEventListener('toggle', () => {
        try {
          localStorage.setItem(MAP_KEY_STORE, box.open ? 'open' : 'closed');
        } catch {
          // Storage can be refused. The key still works; it only forgets.
        }
      });
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.disableScrollPropagation(box);
      return box;
    },
  });
  new Key().addTo(map);
}

/*
 * The two live numbers, written from inside the animation loop.
 *
 * Never sample silently. The eye cannot count marks, so when the pool
 * refuses a packet the real numbers are written down. Anything else is a
 * picture that is quietly wrong and cannot be caught by looking.
 *
 * "Drawing N of M" is only ever said when something really was refused. A
 * packet still in the replay buffer has not been dropped, and reporting
 * it as a shortfall would be the same fault pointing the other way.
 */
function liveCounters(counts) {
  const held = mapState.lastPackets ? mapState.lastPackets.length : 0;
  const kinds = hiddenFamilies.size ? ' of the chosen types' : '';
  const drawing = counts.dropped
    ? `drawing ${count(counts.offered - counts.dropped)} of ${count(counts.offered)} packets`
    : `${count(held)} packets${kinds} in the window`
      + (counts.queued ? `, ${count(counts.queued)} still to replay` : '');
  /*
   * The display runs about one poll behind live, because a batch is
   * spread across the interval that follows it instead of being fired in
   * one frame. That is the cost of being able to follow what happened and
   * it must be said rather than hidden: presenting a replay as
   * instantaneous is the one lie this feature could tell unnoticed.
   */
  const lag = counts.lagMs == null
    ? ''
    : `replaying, about ${Math.max(1, Math.round(counts.lagMs / 1000))} s behind`;

  /*
   * What the admission ladder did, and what it cost, in real numbers.
   *
   * The ladder drops from the bottom of its list when the measured rate
   * or the measured frame time says the map is over budget. Every rung
   * above the first is a thinner picture, so every rung above the first
   * has to say so and say by how much — "the eye cannot count marks"
   * cuts both ways, and a viewer who cannot see that two arcs of three
   * are missing is a viewer being quietly misled about how many gateways
   * uploaded a packet.
   *
   * The arcs are a separate refusal from the packets. A packet whose
   * arcs were cut is still on the map: it has an emission pulse and it
   * raised its sender's heat. So the two counts are both printed rather
   * than being folded into one number that would be true of neither.
   */
  const rung = counts.rungLabel
    ? counts.rungLabel
      + (counts.arcsDropped ? `, ${count(counts.arcsDropped)} arcs not drawn` : '')
    : '';
  /*
   * And the heat's own refusal. The halos and the rings are capped for
   * the frame budget like everything else, and a heat map that quietly
   * showed the loudest hundred and sixty nodes would be the same lie as
   * a sampled animation that does not say it is sampled.
   */
  const heat = counts.heatHidden
    ? `${count(counts.heatHidden)} quieter nodes not shown`
    : '';

  const pause = counts.paused
    ? 'paused - Space resumes from here, L skips to live'
    : '';

  SonoranWatch.status({
    count: drawing,
    lag,
    rung: [rung, heat].filter(Boolean).join(', '),
    pause,
  });
}

/** Write the status line, and the phone ticker. */
function updateWatchStatus(page, packets, traffic) {
  SonoranWatch.status({
    preset: mapPresetLabel ? `Preset ${mapPresetLabel}` : 'Every preset',
    scope: mapNodeScope,
  });
  liveCounters(mapState.live
    ? mapState.live.counts()
    : { offered: 0, drawn: 0, dropped: 0, queued: 0, lagMs: null });
  void traffic;
  void page;

  /*
   * The phone ticker. One event every two seconds, because a nine-column
   * table on a phone is worse than no table and pretending otherwise
   * would be the dishonest option.
   *
   * It runs only when the ticker is actually on screen. CSS shows it
   * below 47.9 rem and at the peek height alone, and the timer used to
   * run in watch mode at any width — so a desktop watching for three
   * hours woke a timer five thousand times to write text into an element
   * with `display: none`. The page is meant to hold two timers and a
   * frame loop, and a third that does invisible work for hours is
   * exactly what a long watch pays for.
   */
  clearInterval(mapState.tickerTimer);
  mapState.tickerTimer = null;
  const ticker = $('[data-watch-ticker]', $('[data-map-shell]', page));
  const visible = ticker && getComputedStyle(ticker).display !== 'none';
  const newest = packets.slice(-12).reverse();
  if (!newest.length || !SonoranWatch.isOn() || !visible) {
    SonoranWatch.ticker('');
    return;
  }
  let at = 0;
  const show = () => {
    const packet = newest[at % newest.length];
    at += 1;
    SonoranWatch.ticker(
      `${clock(packet.time)}  ${packet.from.display_name}  `
      + `${portnumLabel(packet.portnum)}  ${trafficKind(packet)}  ${gatewayTally(packet)}`);
  };
  show();
  mapState.tickerTimer = setInterval(show, 2000);
}

/** Give watch mode the handles it needs, once. */
function installWatchMode(map) {
  const page = $('[data-page="map"]');
  const shell = $('[data-map-shell]', page);
  SonoranWatch.install({
    map,
    page,
    shell,
    isMapActive: () => currentPage === 'map',
    legend: watchLegend,
    onResize: () => map.invalidateSize(),
    /*
     * The tab and the height live in the fragment, and writing the
     * fragment must not cost a request: a tab switch is a change of what
     * is tabulated, not of what is fetched. `route()` reads this flag and
     * skips the re-render when only the watch words changed.
     */
    writeFragment: (next) => {
      watchFragmentWrite = true;
      location.hash = next;
    },
    /*
     * Space. The engine freezes every mark's age and every heat decay,
     * and the replay buffer keeps filling behind the freeze, so nothing
     * that arrives while somebody is reading the panel is lost.
     *
     * The status line is written straight away rather than waiting for
     * the loop, because the loop is the thing that just stopped.
     */
    onPause: () => {
      if (!mapState.live) return;
      mapState.live.togglePaused();
      liveCounters(mapState.live.counts());
    },
    /*
     * The other half of the choice, and it reports what it gave up. A
     * backlog thrown away without a number is a gap in the record the
     * viewer has no way to notice, which is the same fault as sampling
     * without saying so.
     */
    onSkipToLive: () => {
      if (!mapState.live) return;
      const held = mapState.live.skipToLive();
      if (mapState.live.isPaused()) mapState.live.setPaused(false);
      SonoranWatch.status({
        pause: held ? `skipped to live, gave up ${count(held)} buffered packets` : '',
      });
    },
    /* Space is a watch-mode key, so leaving must not strand a paused map
     * with no visible way to start it again. */
    onLeavePaused: () => {
      if (mapState.live && mapState.live.isPaused()) mapState.live.setPaused(false);
    },
    /*
     * The phone ticker appears at the peek height alone, and the height
     * changes on a keypress while the feed refreshes on a fifteen second
     * timer. So a viewer who pressed E to get the ticker got an empty
     * line for up to fifteen seconds and no way to know whether it was
     * broken or the mesh was quiet. The status is rewritten from the
     * packets already held, which costs no request.
     */
    onHeightChange: () => {
      if (!mapState.lastPackets) return;
      updateWatchStatus($('[data-page="map"]'), mapState.lastPackets, null);
    },
  });

  const button = motionButton();
  if (button) {
    button.setAttribute('aria-pressed', String(!REDUCED_MOTION.matches));
    button.addEventListener('click', () => {
      const pressed = button.getAttribute('aria-pressed') === 'true';
      button.setAttribute('aria-pressed', String(!pressed));
      applyMotionSetting();
    });
  }
  if (REDUCED_MOTION.addEventListener) {
    REDUCED_MOTION.addEventListener('change', (event) => {
      if (!button) return;
      button.setAttribute('aria-pressed', String(!event.matches));
      applyMotionSetting();
    });
  }
  applyMotionSetting();

  /*
   * A tab that has been hidden for a while holds a replay buffer that is
   * no longer about now. Playing it out on return would manufacture
   * exactly the burst this whole change exists to remove, so it is thrown
   * away and the next poll starts clean.
   */
  document.addEventListener('visibilitychange', () => {
    if (!mapState.live) return;
    if (document.hidden) {
      mapState.hiddenAt = Date.now();
      return;
    }
    const held = mapState.live.discardQueue();
    /*
     * And say what happened, rather than showing stale content under a
     * stale "Updated HH:MM" with no warning at all. A tab hidden for
     * three hours comes back to a map that is about three hours ago, and
     * a viewer who cannot see that is being shown a picture of the past
     * labelled as the present. The next poll replaces it within a few
     * seconds; the line is there for those few seconds.
     */
    const away = mapState.hiddenAt ? Date.now() - mapState.hiddenAt : 0;
    mapState.hiddenAt = null;
    if (away > 60000) {
      const minutes = Math.round(away / 60000);
      SonoranWatch.status({
        count: `resumed, skipped ${count(minutes)} min`
          + (held ? `, gave up ${count(held)} buffered packets` : ''),
      });
    }
    if (held) console.info(`live map: discarded ${held} buffered packets on return`);
  });
}

PAGES.map = async (page) => {
  const map = ensureMap();
  setTimeout(() => map.invalidateSize(), 0);

  const minutes = $('[data-traffic-minutes]', page).value || '15';
  const showTraffic = $('[data-show-traffic]', page).getAttribute('aria-pressed') === 'true';
  const showLinks = $('[data-show-links]', page).getAttribute('aria-pressed') === 'true';
  const showTraces = $('[data-show-traces]', page).getAttribute('aria-pressed') === 'true';

  const channel = await linkChannelOptions(page);
  /*
   * The dots follow the preset that the lines follow. A node on
   * LongFast cannot hear a node on MediumFast, so showing every dot
   * under one preset's lines invites the reader to join two nodes that
   * have no way to reach each other. Every other layer already did
   * this. See AGENTS.md 9.7.
   *
   * The window is the one the neighbour links use, so a line always has
   * both of its nodes on the map.
   */
  /*
   * The channel always applies now.
   *
   * "Every preset, any time" used to override it and draw every preset on
   * one map. It was removed at Will's request, 2026-09-26, and reading its
   * `aria-pressed` here would have thrown on a missing element -- the same
   * failure that removing the map's preset picker caused, which is why
   * this is a deliberate simplification and not a left-behind flag.
   */
  const nodes = await mapNodes(
    'api/map/nodes'
    + (channel ? `?channel=${encodeURIComponent(channel)}&hours=${LINK_HOURS}` : ''),
  );
  if (!nodes) return;
  const [traffic, edges, traces] = await getAll([
    showTraffic
      ? `api/map/traffic?minutes=${minutes}&limit=${TRAFFIC_LIMIT}` +
        (channel ? `&channel=${encodeURIComponent(channel)}` : '')
      : null,
    showLinks && channel
      ? `api/map/edges?hours=${LINK_HOURS}&limit=1500&channel=${encodeURIComponent(channel)}`
      : null,
    showTraces
      ? 'api/map/traceroute-paths?minutes=30&limit=60' +
        (channel ? `&channel=${encodeURIComponent(channel)}` : '')
      : null,
  ]);

  /*
   * The scope line, which now only ever describes one preset.
   *
   * It used to branch on `allNodes`, the "Every preset, any time"
   * override. Removing that toggle left this reference behind and the map
   * page threw `allNodes is not defined` on every render -- caught by the
   * e2e journeys, which reported 23/23 passing while the console filled
   * with the error. The unit tests could not see it: they read source text
   * and a name that is merely absent looks the same as a name never used.
   *
   * The "every preset" wording is kept for the case where there is no
   * channel at all, which is a deployment with no preset channels rather
   * than a reader's choice.
   */
  mapNodeScope = channel
    ? `${count(nodes.length)} nodes seen on ${channel} in ${LINK_HOURS} h`
    : `${count(nodes.length)} nodes, every preset`;

  // Held so the legend filter can redraw without another request.
  mapState.lastNodes = nodes;
  const bounds = drawMapNodes(nodes);
  drawMapLegend($('[data-map-legend]', page), nodes);
  /*
   * A `#map/node/<id>` link centres on its node (#193.6).
   *
   * After the draw, so the marker exists to open. It runs instead of
   * the fit below -- `mapState.fitted` is set either way -- because a
   * reader who asked for one node does not want the whole mesh framed
   * on top of it.
   *
   * If the node is not in this preset's data the link says so rather
   * than leaving the reader on empty ground looking for a dot that was
   * never drawn. That is the trap the issue named.
   */
  if (mapFocus) {
    const wanted = mapFocus.nodeId;
    const found = nodes.find((row) => row.node_id === wanted);
    const target = (mapState.marks || []).find(([, row]) => row.node_id === wanted);
    if (found && found.lat != null && found.lon != null) {
      map.setView([found.lat, found.lon], MAP_FOCUS_ZOOM);
      /*
       * Mark the node, rather than opening its popup.
       *
       * A popup was the obvious choice and does not survive. The live
       * map polls, `drawMapNodes` clears the layer, and the popup goes
       * with it -- measured, it was already closed six seconds after
       * the link was followed.
       *
       * `focusNodeId` is read by `nodeStyle`, so the mark is reapplied
       * on every redraw and on every zoom change. A thicker ring in the
       * accent, which no role uses: a size and a hue together, so it
       * survives a greyscale render (the rule the live map's own layers
       * follow).
       */
      mapState.focusNodeId = found.node_id;
      if (target) target[0].setStyle(nodeStyle(found, map.getZoom()));
      mapState.fitted = true;
    } else {
      /*
       * Say why, on the legend's own note line, rather than adding a
       * second status mechanism to this page. The alternative is a
       * reader hunting a dot that was never drawn.
       */
      mapNodeScope = found
        ? `${found.display_name || wanted} has no position, so the map cannot centre on it.`
        : `${wanted} is not among the nodes shown here \u2014 it may be on another preset, `
          + 'or not heard in this window.';
      drawMapLegend($('[data-map-legend]', page), nodes);
      mapState.fitted = true;
    }
    mapFocus = null;
  }
  /*
   * Fit only when fitting would zoom IN. Never when it would zoom out.
   *
   * This used to fit to every positioned node, which threw away the
   * configured view. The mesh is not the shape that assumes: measured
   * on the live instance, 1260 positioned nodes run from 22.89 N to
   * 58.50 N and from 137.66 W to 80.08 W, with 148 of them outside
   * Arizona. Those are MQTT nodes reporting from elsewhere, and
   * `fitBounds` over that set opens the map on most of North America
   * with the Arizona mesh a speck in the middle. `maxZoom` did not
   * help, because it caps zooming in and this is zooming out.
   *
   * The configured view is the deployment's own statement of what it
   * is about, so it becomes the floor rather than a starting point to
   * be overridden. A deployment whose nodes really do sit in one town
   * still gets the zoom-in this was added for, and no geography is
   * hardcoded, so it stays right for a mesh that is not this one.
   *
   * Nothing is hidden either way: every node is drawn, and panning or
   * zooming out reaches them.
   */
  if (bounds.length && !mapState.fitted) {
    /*
     * Fit to the nodes at home, and only when that zooms in (#195).
     *
     * #114 stopped one far node zooming the map OUT. It did not stop
     * one far node CANCELLING the zoom in, which is what was left:
     * measured on the live instance at 1879x622, all 401 positioned
     * MediumFast nodes fit at zoom 6, below the configured 7, so no fit
     * ran at all -- and the 400 inside Arizona fit at 7, which would
     * have. One node near Oakland decided the view for the whole mesh.
     *
     * So the nodes outside the home region do not vote. They are still
     * drawn and still reached by panning or zooming out, which #114
     * requires; they just do not choose where the map opens.
     */
    const home = homeBounds();
    const voting = home ? bounds.filter((point) => home.contains(L.latLng(point))) : bounds;
    const floor = home || null;
    if (voting.length) {
      const padding = { padding: [30, 30], maxZoom: 11 };
      const box = L.latLngBounds(voting);
      // What `fitBounds` would settle on, asked before committing to it.
      const fitted = map.getBoundsZoom(box, false, L.point(30, 30));
      // The floor is the home view when there is one, so the first fit
      // still never opens wider than the deployment's own region.
      const wanted = floor
        ? map.getBoundsZoom(floor, false, L.point(20, 20))
        : (CONFIG.mapZoom || 7);
      if (fitted >= wanted) map.fitBounds(box, padding);
    }
    mapState.fitted = true;
  }

  const positions = new Map(
    nodes.filter((row) => row.lat != null && row.lon != null)
      .map((row) => [row.node_id, [row.lat, row.lon]]));

  /*
   * The watchdog.
   *
   * `getAll` turns a failed request into null rather than throwing, so a
   * traffic fetch that fails leaves the page rendering happily with the
   * last picture under a green dot and an "Updated HH:MM" that is a lie.
   * The animation would go on replaying its last buffer as though the
   * mesh were still talking, and a viewer watching for hours would have
   * no way at all to tell a quiet mesh from a broken pipe.
   *
   * Three in a row, because one failed request is a hiccup and a dot
   * that flickers on every hiccup is a dot nobody reads. After that the
   * status goes down, the animation stops rather than replaying, and
   * both panels say so in words.
   */
  if (showTraffic) {
    mapState.failures = traffic ? 0 : (mapState.failures || 0) + 1;
    if (mapState.failures >= 3) {
      mapState.live.clear();
      mapState.trafficPrimed = false;
      setStatus('down', `No traffic since ${clock(new Date())}`);
      $('[data-traffic-summary]', page).textContent =
        `The last ${count(mapState.failures)} traffic requests failed. The map has stopped`
        + ' rather than replay what it already had.';
      SonoranWatch.status({
        count: 'traffic requests are failing, the map has stopped',
        lag: '',
        rung: '',
        pause: '',
      });
      return;
    }
  } else {
    mapState.failures = 0;
  }

  if (showTraffic && traffic) {
    /*
     * One aggregation pass, two consumers. The animation takes the
     * packets it has not drawn; the panel shows the newest of all of
     * them with the exact counts. The counts live in the panel on
     * purpose: a panel row can be read and an 850 ms particle cannot.
     */
    const packets = SonoranLive.aggregate(traffic.events);
    /*
     * The packet filter. Everything below that draws or lists packets
     * reads `shown`. The counts in the summary stay those of the whole
     * window, with the shown number beside them, so a quiet filtered map
     * says it is filtered rather than looking like a quiet mesh.
     */
    const filtered = hiddenFamilies.size > 0;
    const shown = filtered ? packets.filter(familyShown) : packets;
    const nothing = filtered
      ? 'Nothing of the chosen packet types in the window.'
      : 'No traffic in the window.';
    // A refresh of slack past the window covers any late upload, so a
    // key is only forgotten once nothing can bring it back.
    const cutoff = Date.now() - (Number(minutes) * 60000 + LIVE_INTERVAL_MS);
    const fresh = releaseTraffic(
      packets, !mapState.trafficPrimed, cutoff, LIVE_INTERVAL_MS);
    mapState.trafficPrimed = true;
    mapState.lastPackets = shown;
    const direct = traffic.direct_count || 0;
    /*
     * The count is of uploads, not of listeners, and the packet count
     * beside it is the number of things that actually happened. See
     * AGENTS.md 9.5.1. This line said "observations", which is the
     * endpoint's word for the same rows; the summary tile and the
     * firehose column both say "uploads", so this one does too.
     */
    $('[data-traffic-summary]', page).textContent =
      `${count(traffic.event_count)} uploads in ${traffic.window_minutes} min, `
      + `${count(direct)} direct, from ${count(packets.length)} packets.`
      + (traffic.truncated ? ` Newest ${count(traffic.returned_count)} shown.` : '')
      + (filtered ? ` ${count(shown.length)} of the chosen types.` : '')
      + (fresh ? ` ${count(fresh)} new.` : '');
    /*
     * One coalesced list, two renderings. The list is updated in place
     * rather than replaced, so a viewer reading a row halfway down the
     * watch panel keeps their place across a refresh.
     */
    const newest = coalesceFeed(shown.slice().reverse()).slice(0, FEED_ROWS);
    updateFeed($('[data-traffic-feed]', page), newest, nothing);
    replace($('[data-traffic-table]', page),
      shown.length
        ? trafficTable(shown.slice().reverse().slice(0, FEED_ROWS))
        : empty(nothing));
    /*
     * The rate chart, raw. The window's row cap is named under it rather
     * than left to be inferred from a short chart, because a row limit
     * must never be what decides how much evidence a reader thinks there
     * is. See AGENTS.md 9.19.
     */
    drawSparkline($('[data-traffic-spark]', page), shown, traffic.truncated);
    $('[data-traffic-spark-note]', page).textContent =
      `Packets a second, 1 s samples, last ${SPARK_SECONDS} s`
      + (traffic.truncated
        ? `. The window returned its newest ${count(traffic.returned_count)} uploads, so anything`
          + ' before those is not drawn rather than drawn as nothing.'
        : '.');
    updateWatchStatus(page, shown, traffic);
    SonoranWatch.bump('traffic', fresh);
  } else {
    mapState.live.clear();
    mapState.trafficPrimed = false;
    mapState.lastPackets = [];
    $('[data-traffic-summary]', page).textContent = 'The traffic layer is off.';
    replace($('[data-traffic-feed]', page));
    replace($('[data-traffic-table]', page));
    updateWatchStatus(page, [], null);
  }

  if (showLinks && edges) {
    const drawn = drawLinks(edges, positions);
    if (!map.hasLayer(mapState.links)) map.addLayer(mapState.links);
    $('[data-link-summary]', page).textContent =
      `${count(drawn)} neighbor links over ${LINK_HOURS} h.`;
  } else {
    if (map.hasLayer(mapState.links)) map.removeLayer(mapState.links);
    $('[data-link-summary]', page).textContent = '';
  }

  if (showTraces && traces) {
    const seeding = !mapState.tracesPrimed;
    // A refresh of slack past the trace window, for the same reason the
    // traffic cutoff has one: a key is only forgotten once nothing can
    // bring the trace back.
    const traceCutoff = Date.now() - (traces.window_minutes * 60000 + LIVE_INTERVAL_MS);
    const started = drawTraceroutes(traces.traces, seeding, traceCutoff);
    mapState.tracesPrimed = true;
    // The seeded paths of the first pass are old news, so they do not
    // earn a badge. Only a trace that arrived while somebody was looking
    // the other way does.
    if (!seeding) SonoranWatch.bump('traces', started);
    $('[data-trace-summary]', page).textContent =
      `${count(traces.trace_count)} in the last ${traces.window_minutes} min` +
      (started ? `, ${count(started)} drawing.` : '. New ones draw as they arrive.');

    /*
     * The lines leave the map after a few seconds. This list does not,
     * so a trace can still be opened after its animation has gone.
     */
    replace($('[data-trace-feed]', page),
      traces.traces.length
        ? traces.traces.slice(0, 25).map((trace) => el('li', {},
            el('div', {},
              el('button', {
                class: 'linky',
                type: 'button',
                text: `${trace.from.display_name} to ${trace.to.display_name}`,
                onclick: () => openTraceroute(trace.id),
              })),
            el('div', { class: 'meta' },
              el('span', { text: `${trace.link_count} link${trace.link_count === 1 ? '' : 's'}` }),
              trace.channel ? el('span', { text: trace.channel }) : null,
              el('span', { text: clock(trace.time) }))))
        : [empty('No traceroutes in the window.')]);
  } else {
    mapState.tracesPrimed = false;
    $('[data-trace-summary]', page).textContent = 'The traceroute layer is off.';
    replace($('[data-trace-feed]', page));
  }
};

/* --- Mesh graph ------------------------------------------------ */

/*
 * The graph colours a node by its role, the same way the map does.
 *
 * It used to sort every node into router, client, gateway, or not
 * heard. The mesh runs many more roles than that and they behave
 * differently: a client mute never repeats anything, a router late
 * repeats only after the others have had their turn. Four buckets put
 * those under one colour and disagreed with the key on the map, so the
 * same node was one thing on one page and another thing on the next.
 *
 * Only the roles this graph actually holds become categories, so the
 * key stays as short as the mesh allows. They are clickable, which
 * gives the graph a filter it did not have: a click on "client mute"
 * takes all of them out of the picture.
 *
 * Being a gateway is not a role and does not take the colour over. It
 * draws as a ring, as it does on the map. See `nodeStyle`.
 */
function graphCategories(nodes) {
  const present = new Set(nodes.map((node) => node.role || ''));
  const categories = ROLES.filter((role) => present.has(role.key)).map((role) => ({
    name: role.label,
    itemStyle: { color: roleColour(role.key) },
  }));
  // A role this build has never heard of still needs a place to sit,
  // and so does a node that has never reported one. `KNOWN_ROLES` is
  // the set of roles this build knows.
  const other = [...present].filter((role) => role && !KNOWN_ROLES.has(role));
  for (const role of other.sort()) {
    categories.push({ name: roleLabel(role), itemStyle: { color: roleColour(role) } });
  }
  if (present.has('')) {
    categories.push({ name: roleLabel(null), itemStyle: { color: PALETTE.muted } });
  }
  return categories;
}

/** Where one node sits in the key built above. */
function graphCategory(node, categories) {
  const name = roleLabel(node.role || null);
  const index = categories.findIndex((category) => category.name === name);
  return index < 0 ? 0 : index;
}

/* How many links each node keeps in the backbone view. */
const BACKBONE_LINKS_PER_NODE = 3;

/* The node the focus view centres on. */
let graphFocus = null;

/**
 * Keep the strongest links of each node.
 * A dense graph stays readable when every node shows only its best few
 * links. Hubs still stand out, because many nodes point at them.
 */
function strongestLinks(links, perNode) {
  const byNode = new Map();
  for (const link of links) {
    for (const id of [link.source, link.target]) {
      if (!byNode.has(id)) byNode.set(id, []);
      byNode.get(id).push(link);
    }
  }
  const keep = new Set();
  for (const [, own] of byNode) {
    own
      .slice()
      .sort((a, b) => (b.snr ?? -999) - (a.snr ?? -999))
      .slice(0, perNode)
      .forEach((link) => keep.add(link));
  }
  return links.filter((link) => keep.has(link));
}

/** Pick the node the focus view centres on: the search, or the busiest. */
/*
 * Does this node answer what was typed into "Find a node" (#223)?
 *
 * All three names, because a reader types whichever one they know. The
 * highlight used to test `display_name` alone while `focusNode` tested
 * `display_name` and `node_id`, so a **short name** matched nothing at
 * all -- and a short name is exactly what the reporter typed.
 *
 * One function, so the node the search highlights and the node the
 * focus view centres on can never disagree again.
 */
function matchesGraphQuery(node, query) {
  if (!query) return false;
  const fields = [node.display_name, node.short_name, node.long_name, node.node_id];
  return fields.some((field) => String(field || '').toLowerCase().includes(query));
}

function focusNode(data, query) {
  if (query) {
    const found = data.nodes.find((node) => matchesGraphQuery(node, query));
    if (found) return found.node_id;
  }
  if (graphFocus && data.nodes.some((node) => node.node_id === graphFocus)) return graphFocus;
  const degree = new Map();
  for (const link of data.links) {
    degree.set(link.source, (degree.get(link.source) || 0) + 1);
    degree.set(link.target, (degree.get(link.target) || 0) + 1);
  }
  let best = null;
  let most = -1;
  for (const [id, count] of degree) {
    if (count > most) { best = id; most = count; }
  }
  return best;
}

/*
 * The mesh laid out over the ground it sits on.
 *
 * A force layout started from nowhere draws the same mesh a different
 * way every time and reads as a ball of wire. The mesh is a geographic
 * thing: the two knots a reader picks out are Phoenix and Tucson, and
 * seeding the layout with real positions puts them where they belong
 * and keeps them there between redraws.
 *
 * About six nodes in ten report a position. The rest are placed beside
 * the neighbours that do, so the picture stays whole. Nothing is
 * hidden and every node keeps its links.
 */

/* How each strength of link draws on the graph page, and reads in its
 * tooltip. The strengths come from the graph endpoint. */
/*
 * How each strength is drawn.
 *
 * Opacity used to carry the tier: .6 solid, .42 dashed, .3 dotted.
 * Composited over `--panel`, that put every link under the 3:1 floor
 * for meaningful non-text content (WCAG 1.4.11). Measured across all
 * fifteen role colours:
 *
 *   alpha .30   worst 1.37 dark, 1.39 light
 *   alpha .42   worst 1.59 dark, 1.61 light
 *   alpha .60   worst 2.00 dark, 2.02 light
 *
 * The worst case was 1.22:1, for an unconfirmed link at .2. A dash
 * pattern you cannot find is not a carrier of anything.
 *
 * Every role clears 3:1 only at alpha >= .92 dark and .89 light, so
 * opacity cannot separate the tiers AND stay legible. It no longer
 * tries. Width and dash pattern carry the strength -- they already
 * did, and the legend already names them in words -- and the opacity
 * is set once, high enough for the faintest role to clear the floor
 * with a little room.
 *
 * The cost is a denser picture. That is the right trade: a link drawn
 * so faintly that its dash pattern cannot be read is not conveying
 * "weak", it is conveying nothing.
 */
const LINK_OPACITY = 0.95;

const LINK_LINE = {
  two_way: { width: 2.0, type: 'solid', opacity: LINK_OPACITY },
  one_way: { width: 1.4, type: 'dashed', opacity: LINK_OPACITY },
  unknown: { width: 1.0, type: 'dotted', opacity: LINK_OPACITY },
};
/*
 * The third one is about OUR EVIDENCE, not about the link (#149).
 *
 * It read "Weak link: few packets crossed it", which states a property
 * of the link and then gives a reason that is a property of what we
 * have seen. 90% of links at 24 h were in it. That is #87 mirrored:
 * there an unknown node was coloured as a healthy one, here an unknown
 * link is described as a bad one.
 */
const LINK_STRENGTH = {
  two_way: 'Two-way link',
  one_way: 'One-way link: packets crossed it mostly one way',
  unknown: 'Too few packets crossed it to say whether it carries',
};

/*
 * A link's pull in the signal layout (#71).
 *
 * SNR on this mesh runs about -20 dB to +12 dB. The scale is shifted
 * so the worst reading still has a small positive pull rather than
 * none: a link that exists but carries badly is still a link, and an
 * edge of zero weight would be drawn at the full `edgeLength`, which
 * says "these two are unrelated" about a pair that demonstrably talk.
 *
 * An unmeasured link gets the floor. It is not evidence of a poor
 * signal -- only of no measurement -- so it neither pulls a cluster
 * together nor is pushed away as though it were bad.
 */
const SIGNAL_FLOOR = -20;
const SIGNAL_CEILING = 12;

function signalWeight(snr) {
  if (snr == null) return 1;
  const clamped = Math.max(SIGNAL_FLOOR, Math.min(SIGNAL_CEILING, snr));
  return 1 + ((clamped - SIGNAL_FLOOR) / (SIGNAL_CEILING - SIGNAL_FLOOR)) * 9;
}

/* Layout units. The graph fits whatever bounds it is given, so this
 * only sets the resolution the seed is worked out in. */
const GRAPH_SPAN = 1000;

/* Node positions the reader has dragged, so a redraw does not undo the
 * poking. The search box re-renders on every keystroke, and the graph
 * used to jump back under the hand. */
const graphPinned = new Map();

/* The picture those pins were placed on: channel, window, and layout. */
let graphArrangement = '';

/* Where that picture puts every node, before any dragging. */
let graphSeeds = new Map();

/**
 * Project the nodes that report a position onto flat layout units.
 *
 * Longitude is scaled by the cosine of the mean latitude, so a degree
 * east covers the same ground as a degree north and the state is not
 * stretched sideways. Latitude is negated because screen y grows down.
 * One factor scales both axes, which keeps the real aspect ratio.
 */
function projectPositions(nodes) {
  const placed = nodes.filter((node) => node.lat != null && node.lon != null);
  const seeds = new Map();
  // Two nodes cannot establish a shape to lay anything else out on.
  if (placed.length < 3) return seeds;

  const meanLat = placed.reduce((sum, node) => sum + node.lat, 0) / placed.length;
  const squeeze = Math.cos((meanLat * Math.PI) / 180);
  const points = placed.map((node) => ({
    id: node.node_id,
    x: node.lon * squeeze,
    y: -node.lat,
  }));
  const minX = Math.min(...points.map((point) => point.x));
  const maxX = Math.max(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  const maxY = Math.max(...points.map((point) => point.y));
  const factor = GRAPH_SPAN / (Math.max(maxX - minX, maxY - minY) || 1);
  for (const point of points) {
    seeds.set(point.id, [(point.x - minX) * factor, (point.y - minY) * factor]);
  }
  return seeds;
}

/**
 * Give every node a starting place.
 *
 * A node with no position of its own goes to the average of the
 * neighbours that have one, over a few passes, so it lands beside what
 * it actually talks to. Each pass is worked out before it is applied,
 * or a node seeded early in a pass would drag the rest of that pass
 * towards it and the result would depend on the order of the list.
 *
 * A node no pass can reach — nothing it links to knows where it is —
 * goes on a ring around the outside. That reads as "not placed" rather
 * than putting it somewhere it is not.
 */
function seedPositions(nodes, links) {
  const seeds = projectPositions(nodes);
  if (!seeds.size) return seeds;

  const neighbours = new Map();
  for (const link of links) {
    if (!neighbours.has(link.source)) neighbours.set(link.source, []);
    if (!neighbours.has(link.target)) neighbours.set(link.target, []);
    neighbours.get(link.source).push(link.target);
    neighbours.get(link.target).push(link.source);
  }

  for (let pass = 0; pass < 4; pass += 1) {
    const found = [];
    for (const node of nodes) {
      if (seeds.has(node.node_id)) continue;
      const known = (neighbours.get(node.node_id) || [])
        .map((id) => seeds.get(id))
        .filter(Boolean);
      if (!known.length) continue;
      found.push([
        node.node_id,
        [
          known.reduce((sum, point) => sum + point[0], 0) / known.length,
          known.reduce((sum, point) => sum + point[1], 0) / known.length,
        ],
      ]);
    }
    if (!found.length) break;
    for (const [id, point] of found) seeds.set(id, point);
  }

  const stranded = nodes.filter((node) => !seeds.has(node.node_id));
  stranded.forEach((node, index) => {
    const angle = (index / stranded.length) * Math.PI * 2;
    seeds.set(node.node_id, [
      GRAPH_SPAN / 2 + Math.cos(angle) * GRAPH_SPAN * 0.72,
      GRAPH_SPAN / 2 + Math.sin(angle) * GRAPH_SPAN * 0.72,
    ]);
  });
  return seeds;
}

/**
 * Open the mesh out until no two nodes crowd each other.
 *
 * Nodes on one rooftop, and the many that report the same default
 * position, land on the same point and bury their own links. Each pass
 * pushes any pair closer than the gap apart, and repeating it lets a
 * crowd spread outwards instead of only its outermost pair moving.
 *
 * The gap and the passes were measured rather than guessed. On the
 * busiest preset the spacing between neighbouring nodes runs about
 * three times what it was, while the mesh as a whole grows by under a
 * fifth, so the chart's fit to the canvas does not take the gain back.
 * Passes past this point buy very little: the pairs are already the
 * full gap apart and only the tightest knots are still opening.
 *
 * The sweep used to be every pair against every other, 28 passes,
 * and it was bounded at 1,500 nodes to stop the page locking up.
 * Timed with the function lifted out verbatim:
 *
 *     859 nodes (the mesh today)    121 ms
 *     1500 nodes (the old ceiling)  366 ms
 *
 * Two points further apart than `gap` can never push each other, so
 * the comparison only has to happen between near neighbours. Each pass
 * buckets the points into cells of `gap` a side and compares each
 * point against its own cell and the eight around it. The grid is
 * rebuilt per pass because the points move.
 *
 *     859 nodes    121 ms -> 27 ms    4.5x
 *     1500 nodes   366 ms -> 49 ms    7.5x
 *     3000 nodes   (used to bail out) -> 135 ms
 *
 * The layout it produces is the same. Median nearest-neighbour
 * distance, which is what the separation is FOR:
 *
 *              original   gridded
 *      500       41.4      41.3
 *      859       33.4      33.5
 *     1500       21.0      20.9
 *
 * and the 10th percentile -- the worst crowding left over -- comes out
 * slightly better gridded, 17.7 against 16.5 at 859 and 8.4 against
 * 6.4 at 1500. It is not bit-identical and cannot be: the points move
 * as they are compared, so a different visiting order gives different
 * floats. What matters is the distribution, and that is unchanged.
 *
 * The 1,500 ceiling is raised to 6,000 rather than removed. The cost
 * is linear now, but it is still work on the main thread, and a mesh
 * that large wants a different picture rather than a slower one.
 */
function separatePositions(seeds, nodes) {
  const ids = nodes.map((node) => node.node_id).filter((id) => seeds.has(id));
  if (ids.length > 6000) return seeds;

  // The seed arrays are held by reference, so moving one here moves the
  // same array in `seeds`.
  const points = ids.map((id) => seeds.get(id));
  const gap = GRAPH_SPAN / 24;
  const cells = new Map();
  for (let pass = 0; pass < 28; pass += 1) {
    cells.clear();
    for (let i = 0; i < points.length; i += 1) {
      const key = `${Math.floor(points[i][0] / gap)},${Math.floor(points[i][1] / gap)}`;
      const bucket = cells.get(key);
      if (bucket) bucket.push(i);
      else cells.set(key, [i]);
    }
    for (let a = 0; a < points.length; a += 1) {
      const first = points[a];
      const cx = Math.floor(first[0] / gap);
      const cy = Math.floor(first[1] / gap);
      for (let ox = -1; ox <= 1; ox += 1) {
        for (let oy = -1; oy <= 1; oy += 1) {
          const bucket = cells.get(`${cx + ox},${cy + oy}`);
          if (!bucket) continue;
          for (const b of bucket) {
            // `b <= a` keeps each pair to one comparison, exactly as
            // the `b = a + 1` of the old inner loop did.
            if (b <= a) continue;
            const second = points[b];
            let dx = second[0] - first[0];
            let dy = second[1] - first[1];
            let distance = Math.hypot(dx, dy);
            if (distance >= gap) continue;
            // Exactly on top of each other has no direction to push
            // along, so the pair is nudged apart on a fixed diagonal.
            if (distance === 0) {
              dx = gap * 0.5;
              dy = gap * 0.5;
              distance = Math.hypot(dx, dy);
            }
            const push = ((gap - distance) / distance) * 0.5;
            first[0] -= dx * push;
            first[1] -= dy * push;
            second[0] += dx * push;
            second[1] += dy * push;
          }
        }
      }
    }
  }
  return seeds;
}

/* The channel the graph page shows. Empty means "not chosen yet". */
let graphChannel = '';

/*
 * The window the graph page last drew. The link page has to ask about
 * the same window, or a click on a link found over seven days goes to a
 * page that only looks at the last day and reports no evidence at all.
 */
let graphHours = '24';

/**
 * Point the graph at the preset the menu has chosen.
 *
 * This drew a clickable tab per channel, so the graph was a sixth place
 * that asked which preset to show -- and its tabs included the topic
 * channels, which meant a reader could be looking at a Weather graph
 * while every other page showed MediumFast. The tabs are gone and the
 * menu decides, the same as the map, coverage, gaps and the rest.
 *
 * Channels with no link reports are still excluded. The list carries
 * channels that only have traffic, so the map can point its live layer at
 * them; those would open an empty graph.
 *
 * `preferredPreset` is what makes this safe rather than just consistent.
 * It takes the menu's choice where that channel HAS links, and otherwise
 * falls back to the first channel that has any -- because an empty graph
 * is worse than the wrong one (#177). A reader whose preset is quiet in
 * the window still sees a mesh.
 */
function graphTabs(page, all) {
  const channels = all.filter((item) => item.link_report_count > 0);
  if (!channels.length) return;
  const wanted = SonoranLabels.preferredPreset(channels, (item) => item.channel);
  if (wanted) graphChannel = wanted.channel;
  // Only the presets, and only those with links, so the menu never offers
  // a choice that opens an empty graph here.
  if (window.SonoranPreset) {
    const presets = channels
      .filter((item) => item.group === 'Presets' && item.preset)
      .map((item) => String(item.preset));
    if (presets.length) SonoranPreset.setAvailable(presets);
  }
}

/*
 * The coverage planner lives in planner.js, which loads before this
 * file. It has its own map, its own workers and a vendored WebAssembly
 * engine, so it is kept out of this file.
 */
/*
 * The coverage map lives in coverage.js, which loads before this file.
 * It draws what the coverage job already computed and predicts nothing
 * itself, so it needs no workers and no engine.
 */
PAGES.coverage = async (page) => {
  await window.SonoranCoverage.show(page);
};

/* The RF map lives in rf.js, which loads before this file. */
PAGES.rf = async (page) => {
  await window.SonoranRf.show(page);
};

/*
 * The coverage gaps page lives in gaps.js, which loads before this file.
 * It measures which nodes are not carried well and predicts nothing.
 */
PAGES.gaps = async (page) => {
  await window.SonoranGaps.show(page);
};

PAGES.planner = async () => {
  await window.SonoranPlanner.show();
};

/*
 * The config check page.
 *
 * Its code is in config-check.js, which is an ES module because it
 * imports the community checker's logic. A module runs after this file,
 * so the router has to wait for it: without this a reload on #config
 * would find nothing registered and fall back to the dashboard.
 *
 * Nothing about that page reaches the server. It reads a config in the
 * browser and sends it nowhere. See AGENTS.md 9.17.
 */
const configReady = new Promise((resolve) => {
  window.sonoranConfigLoaded = resolve;
});

PAGES.config = async (page) => {
  await configReady;
  await window.SonoranConfigCheck.show(page);
};

PAGES.graph = async (page) => {
  const hours = $('[data-graph-hours]', page).value || '24';
  graphHours = hours;
  const target = $('[data-graph-chart]', page);

  const list = await get(`api/graph/channels?hours=${hours}`).catch(() => null);
  const channels = (list && list.channels) || [];
  graphTabs(page, channels);
  if (!channels.length) {
    $('[data-graph-counts]', page).textContent = 'No mesh links in the window.';
    replace(target);
    return;
  }

  const data = await get(
    `api/graph?hours=${hours}&channel=${encodeURIComponent(graphChannel)}`,
  ).catch((error) => error);
  if (data instanceof Error) {
    $('[data-graph-counts]', page).textContent = 'Cannot load the graph.';
    return;
  }
  const selected = channels.find((item) => item.channel === graphChannel);
  const showUnconfirmed =
    $('[data-graph-unconfirmed]', page).getAttribute('aria-pressed') === 'true';
  const showWeak =
    $('[data-graph-weak]', page).getAttribute('aria-pressed') === 'true';
  const allLinks = data.links;
  const confirmed = allLinks.filter((link) => link.snr != null);
  const unconfirmed = allLinks.length - confirmed.length;

  /*
   * Where each node sits, worked out once for the whole mesh.
   *
   * It is done here, on everything the endpoint sent, rather than on
   * what the toggles and the view leave behind. A node then keeps its
   * place when the reader narrows the picture, instead of the whole
   * mesh rearranging itself underneath them.
   *
   * The result is kept because it is the expensive part of the page and
   * the search box redraws on every keystroke. Only a different
   * channel, window, or layout is a different arrangement.
   */
  const layout = $('[data-graph-layout]', page).value || 'spread';
  const arrangement = `${graphChannel}|${hours}|${layout}`;
  // A node the kept arrangement has never placed would be drawn at no
  // position at all, so a mesh that has grown since is worked out again.
  const covers = data.nodes.every((node) => graphSeeds.has(node.node_id));
  if (arrangement !== graphArrangement || !(covers || layout === 'free')) {
    // A pin belongs to the arrangement it was placed on.
    if (arrangement !== graphArrangement) graphPinned.clear();
    graphArrangement = arrangement;
    graphSeeds = layout === 'free' || layout === 'signal'
      ? new Map()
      : seedPositions(data.nodes, allLinks);
    if (layout === 'spread') separatePositions(graphSeeds, data.nodes);
  }
  /*
   * Two different weaknesses, two different toggles.
   *
   * A link is unconfirmed when the mesh reported no signal reading for
   * it. A traceroute hop with no reading is not proof of a working
   * radio link, so it is hidden by default.
   *
   * A link is unjudged when too few packets crossed it to call it
   * anything -- that is a statement about our evidence, not the link,
   * whichever way they went (see `strength` in the graph endpoint).
   * Those are shown by default, because they are true, and the toggle
   * takes them away for anyone who wants only the links that carry.
   *
   * Nodes left with no visible link are dropped too, so the graph does
   * not show a crowd of unconnected dots.
   */
  let visible = showUnconfirmed ? allLinks : confirmed;
  const unjudged = visible.filter((link) => link.strength === 'unknown').length;
  if (!showWeak) visible = visible.filter((link) => link.strength !== 'unknown');
  data.links = visible;

  /*
   * A dense mesh draws as a hairball. Three views make it readable:
   *
   *   focus     one node and everything one hop from it
   *   backbone  each node keeps only its strongest links
   *   all       everything, for when the whole picture is wanted
   *
   * Nothing is deleted. These only choose what to draw.
   */
  const view = $('[data-graph-view]', page).value || 'all';
  const queryShown = ($('[data-graph-search]', page).value || '').trim();
  const query = queryShown.toLowerCase();
  const total = data.links.length;

  if (view === 'backbone') {
    data.links = strongestLinks(data.links, BACKBONE_LINKS_PER_NODE);
  } else if (view === 'focus') {
    const centre = focusNode(data, query);
    graphFocus = centre;
    if (centre) data.links = data.links.filter(
      (link) => link.source === centre || link.target === centre);
  }

  const linked = new Set(data.links.flatMap((link) => [link.source, link.target]));
  data.nodes = data.nodes.filter((node) => linked.has(node.node_id));
  const hiddenByView = total - data.links.length;
  /*
   * Say what the search found (#223).
   *
   * "It does nothing" was the report, and the box really did look that
   * way: the highlight missed short names, and where it did match it
   * was a 2 px ring on a 3 px dot. Even fixed, a reader needs to know
   * the difference between "found, look for the ringed node" and "that
   * name is not in this graph" -- and between both of those and "it is
   * here but this view does not draw it", which is a real state when
   * the backbone view keeps only the strongest links.
   */
  const matches = query ? data.nodes.filter((node) => matchesGraphQuery(node, query)).length : 0;
  const searchNote = $('[data-graph-search-note]', page);
  if (searchNote) {
    searchNote.hidden = !query;
    if (query) {
      searchNote.textContent = matches
        ? `${count(matches)} node${matches === 1 ? '' : 's'} match "${queryShown}"`
          + `${view === 'focus' ? '' : ' - ringed in the graph'}`
        : `No node in this view matches "${queryShown}"`
          + (view === 'backbone'
            ? '. The backbone view draws only the strongest links, so try Whole preset.'
            : '');
    }
  }
  const heading = $('[data-graph-counts]', page);
  const label = selected ? selected.label : graphChannel;
  const focusName = graphFocus
    ? (data.nodes.find((node) => node.node_id === graphFocus) || {}).display_name
    : null;
  heading.textContent =
    (view === 'focus' && focusName ? `${focusName} - ` : `${label} - `)
    + `${count(data.nodes.length)} nodes, ${count(data.links.length)} links, `
    + `last ${data.window_hours} h`
    + (view === 'focus' ? ' - one hop' : view === 'backbone' ? ` - strongest ${BACKBONE_LINKS_PER_NODE} per node` : '')
    + (hiddenByView ? `, ${count(hiddenByView)} more not drawn` : '')
    + (showUnconfirmed ? '' : unconfirmed ? `, ${count(unconfirmed)} unconfirmed hidden` : '')
    + (unjudged
      ? showWeak
        ? `, ${count(unjudged)} unjudged`
        : `, ${count(unjudged)} unjudged hidden`
      : '');
  // Links stored before channel tracking mix every preset together, so
  // this one graph does show links that cannot exist. Say so plainly.
  const dotted = $('[data-legend-unconfirmed]', page);
  if (dotted) dotted.hidden = !showUnconfirmed;
  const faint = $('[data-legend-weak]', page);
  if (faint) faint.hidden = !(showWeak && unjudged);

  const warning = $('[data-graph-warning]', page);
  if (warning) {
    warning.hidden = !(selected && selected.mixed_presets);
    warning.textContent = warning.hidden
      ? ''
      : 'These links were recorded before the channel was tracked. They mix every preset '
        + 'together, so some lines here cannot exist on a real radio. They disappear as the '
        + 'window moves past them.';
  }

  const sizes = data.nodes.map((node) => node.packet_count || 0);
  const busiest = Math.max(1, ...sizes);

  /*
   * The arrangement worked out above, with whatever the reader has
   * since dragged laid over the top. Nothing reported a position at
   * all means there is no ground to lay the mesh on, and it falls back
   * to the force layout.
   */
  const onGround = graphSeeds.size > 0;
  /*
   * Real positions are a layout in themselves, so the solver is told to
   * leave them alone. Dragging still works: ECharts moves the node and
   * redraws its links whatever the layout. Geo-seeded force starts the
   * solver from them instead (#74). With no positions at all there is
   * no ground, and every layout falls back to force.
   */
  const solved = !onGround || layout === 'force-geo' || layout === 'signal';
  const seeds = new Map(graphSeeds);
  for (const [id, point] of graphPinned) {
    // On the ground the seed is already there and the pin moves it. In
    // free force there is no seed, so the pin has to become the node's
    // whole position. Without it a pinned node is marked fixed but
    // given no x or y, and the force solver drops it at a random point
    // and holds it there.
    if (onGround && !seeds.has(id)) continue;
    seeds.set(id, point.slice());
  }

  /*
   * A label for every one of four hundred nodes is a wall of text, and
   * none at all leaves a field of anonymous dots with no way to tell
   * where you are. The busiest few carry the names, which is enough to
   * recognise a part of the mesh, and the rest answer on hover.
   */
  const byTraffic = data.nodes.slice().sort(
    (a, b) => (b.packet_count || 0) - (a.packet_count || 0));
  const named = new Set(
    (data.nodes.length <= 90 ? byTraffic : byTraffic.slice(0, 30))
      .map((node) => node.node_id));

  /*
   * How crowded this graph is, from 0 for a handful of nodes to 1 for a
   * few hundred. `lerp` reads the setting for a small graph and the one
   * for a large graph, and gives the value in between. Every force
   * setting moves together, so the layout keeps one character over the
   * whole range instead of changing at a threshold.
   */
  const crowding = Math.min(1, Math.max(0, (data.nodes.length - 40) / 260));
  const lerp = (small, large) => small + (large - small) * crowding;

  /* The key, built from the roles this graph actually holds. */
  const categories = graphCategories(data.nodes);

  chart(target, {
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: PALETTE.panel, borderColor: PALETTE.line, textStyle: { color: PALETTE.text },
      /*
       * Returns a DOM node, never an HTML string.
       *
       * ECharts renders a string formatter result with `innerHTML`
       * (`if (U(t)) o.innerHTML = t + a`), and a node's name is chosen
       * by whoever owns the radio. Interpolating `display_name` into a
       * template literal therefore let a name of `<img src=x
       * onerror=...>` run script on this origin, which also holds Web
       * Serial for the config page. `tooltipLines` puts every value in
       * as text, so markup in a name is shown rather than executed.
       *
       * ECharts takes an HTMLElement here; the string branch is the
       * only one that injects.
       */
      formatter: (item) => {
        if (item.dataType === 'edge') {
          const snr = item.data.snr == null ? 'no SNR' : `${round(item.data.snr, 1)} dB`;
          const [there, back] = item.data.eachWay || [item.data.count, 0];
          const ends = [item.data.source, item.data.target].map((id) => {
            const node = data.nodes.find((each) => each.node_id === id);
            return node ? (node.short_name || node.display_name) : id;
          });
          return tooltipLines(
            LINK_STRENGTH[item.data.strength] || 'Link',
            `${snr}, seen ${item.data.count} times`,
            `${ends[0]} → ${ends[1]}: ${count(there)}`,
            `${ends[1]} → ${ends[0]}: ${count(back)}`,
            `from ${(item.data.kinds || [item.data.kind]).join(' and ')} reports`,
          );
        }
        const node = item.data.raw;
        return tooltipLines(
          el('b', { text: node.display_name }),
          node.node_id,
          // The same words the key uses, so the two agree.
          roleLabel(node.role) + (node.is_mqtt_gateway ? ', gateway' : ''),
          node.hw_model || '',
          `${count(node.packet_count)} packets`,
          `heard ${ago(node.last_heard)} ago`,
        );
      },
    },
    /*
     * The key carries a role for every colour on the canvas. A mesh can
     * run a dozen of them, which is more than fit on one line, so the
     * legend scrolls: it stays one row with paging arrows rather than
     * wrapping down over the canvas, and the graph keeps the room below.
     */
    legend: [{
      data: categories.map((category) => category.name),
      textStyle: { color: PALETTE.muted },
      top: 0,
      type: 'scroll',
      width: '92%',
    }],
    series: [{
      type: 'graph',
      layout: solved ? 'force' : 'none',
      roam: true,
      draggable: true,
      categories,
      center: ['50%', '52%'],
      /*
       * Force settings scale down as the graph grows. Every node pushes
       * every other, so a fixed repulsion that suits a dozen nodes
       * throws hundreds of them off the canvas. Gravity pulls the whole
       * layout back to the middle.
       *
       * The scale is smooth. It used to step at 120 nodes, so the
       * layout changed character the moment a channel or a window
       * crossed that line, and a graph either side of it looked like a
       * different page.
       *
       * Friction is the damping. A high value locks the web in place as
       * soon as it lands, which is what made it feel stiff to drag. A
       * low one lets the whole mesh keep answering the node in hand.
       */
      force: {
        repulsion: lerp(340, 90),
        edgeLength: [lerp(70, 34), lerp(190, 100)],
        gravity: lerp(0.05, 0.16),
        friction: lerp(0.10, 0.20),
        /*
         * The settling motion is the point, not a cost: it shows which
         * nodes are pulled together. Hundreds of nodes are still fast
         * enough to watch. Past that the animation is slow and lands in
         * a worse place, so the layout is solved before it is drawn.
         *
         * This option belongs to `force`. It sat on the series for a
         * while, where ECharts reads nothing, so the animation was
         * always on whatever the size of the graph.
         */
        layoutAnimation: data.nodes.length <= 500,
      },
      emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
      label: {
        // Each node says whether it carries a name. See `named` above.
        show: false,
        position: 'right',
        color: PALETTE.text,
        fontSize: 10,
        formatter: (item) => item.data.raw.short_name || item.data.raw.display_name,
      },
      /*
       * A curve separates two links that run between the same pair of
       * nodes and shows the direction of a path. At 0.08 the lines were
       * all but straight, which is what made a dense graph read as a
       * ball of wire. A busy graph curves less, or the arcs cross each
       * other more than the straight lines did.
       */
      lineStyle: { color: 'source', curveness: lerp(0.3, 0.16), opacity: 0.45 },
      data: data.nodes.map((node) => {
        const match = matchesGraphQuery(node, query);
        const seed = seeds.get(node.node_id);
        return {
          id: node.node_id,
          name: node.display_name,
          raw: node,
          category: graphCategory(node, categories),
          /*
           * A match is drawn large enough to find (#223).
           *
           * Past 120 nodes a dot is 3 px, and the match used to be a
           * 2 px border on it -- invisible in a mesh of four hundred,
           * which is why the box read as doing nothing. A match now
           * gets a floor of 14 px whatever the size of the graph, so it
           * is the thing the eye lands on.
           */
          symbolSize: match
            ? Math.max(14, (data.nodes.length > 120 ? 3 : 6)
              + (data.nodes.length > 120 ? 9 : 18) * Math.sqrt((node.packet_count || 0) / busiest))
            : (data.nodes.length > 120 ? 3 : 6)
              + (data.nodes.length > 120 ? 9 : 18) * Math.sqrt((node.packet_count || 0) / busiest),
          x: seed ? seed[0] : undefined,
          y: seed ? seed[1] : undefined,
          // A dragged node stays where it was put while the layout
          // solver is running. Real positions are not solved at all,
          // so there is nothing to hold it against.
          fixed: solved && graphPinned.has(node.node_id),
          /*
           * The role gives the colour. On top of it:
           *
           * A gateway wears a bright ring, because uploading to MQTT
           * is not a role and must not take the role's colour over.
           * The map draws it the same way.
           *
           * Opacity carries how sure the dot is. A node not heard in a
           * day fades hard, which is what the old "not heard" colour
           * said before the roles took the colours over, and the map
           * fades it the same way. A node placed from its neighbours
           * rather than from its own report fades a little, so a
           * reader can tell where the picture is reporting and where
           * it is inferring. A node that is both fades twice.
           *
           * A search match outranks all of it while it lasts.
           */
          itemStyle: match
            // The accent, which no role uses, and a ring thick enough
            // to read against a dense graph. Full opacity too: a stale
            // match is still the node that was asked for.
            ? { borderColor: PALETTE.accent, borderWidth: 3, opacity: 1 }
            : {
                borderColor: node.is_mqtt_gateway ? PALETTE.text : undefined,
                borderWidth: node.is_mqtt_gateway ? 1.5 : 0,
                opacity: (isStale(node) ? 0.35 : 1)
                  * (onGround && !node.has_position ? 0.75 : 1),
              },
          label: { show: Boolean(match || named.has(node.node_id)) },
        };
      }),
      /*
       * The line says how much the evidence supports the link (#73). A
       * neighbour report and a traceroute hop are the same evidence, one
       * packet heard across the link, so the source of it does not
       * change the line.
       *
       *   solid    enough packets crossed it both ways to call it usable
       *   dashed   plenty crossed it, but nearly all one way
       *   dotted   too few crossed it to say
       *
       * A link with no SNR is still a real link, but the mesh reported
       * no reading for it. It keeps its line and turns grey, so a
       * measured link is never confused with an unmeasured one.
       */
      links: data.links.map((link) => ({
        source: link.source,
        target: link.target,
        kind: link.kind,
        kinds: link.kinds,
        snr: link.snr,
        /*
         * The signal layout, and the answer to #71's "divide graph
         * based on ... snr".
         *
         * ECharts maps an edge's `value` across the `edgeLength`
         * range: a larger value draws a shorter edge. So handing it
         * the link's SNR makes nodes that hear each other well sit
         * close, and the clusters that fall out are the mesh's actual
         * communities rather than its map.
         *
         * `value` is only set for this layout. Everywhere else the
         * edge length must stay uniform, or the geographic layouts
         * would be pulled out of shape by signal -- a 45 km link with
         * a good SNR drawn shorter than a 2 km link with a poor one
         * puts nodes in the wrong place, which is the objection in
         * #71's own option 1.
         *
         * A link with NO reading is given the weakest weight rather
         * than being dropped or treated as zero. Unmeasured is not the
         * same as bad, and it keeps its grey line either way -- but it
         * cannot pull a cluster together on evidence nobody has.
         */
        ...(layout === 'signal' ? { value: signalWeight(link.snr) } : {}),
        count: link.count,
        eachWay: link.each_way,
        strength: link.strength,
        lineStyle: {
          ...(LINK_LINE[link.strength] || LINK_LINE.unknown),
          // Unconfirmed: the stale colour, not a fainter one. At .2 it
          // measured 1.22:1, the worst value on the page. `--role-stale`
          // at full strength is 3.31 dark and 4.59 light, so the colour
          // alone is enough to set it apart without hiding it.
          ...(link.snr == null ? { color: PALETTE.stale, opacity: LINK_OPACITY } : {}),
        },
      })),
    }],
  });

  const instance = charts.get(target);
  if (instance && !instance.__wired) {
    /*
     * Remember where a node was dragged to. Every redraw rebuilds the
     * chart from scratch, and the search box redraws on each keystroke,
     * so without this the mesh snapped back the moment the reader
     * typed.
     *
     * This reads the position on mouse up rather than on drag end. The
     * graph series moves the node itself and raises no event for it:
     * `dragnode` belongs to sankey, and zrender's own dragend is not
     * passed on. Mouse up lands after the drag either way, and a plain
     * click through it only records where the node already was.
     */
    instance.on('mouseup', (item) => {
      if (item.dataType !== 'node') return;
      const series = instance.getModel().getSeriesByIndex(0);
      const nodes = series && series.getData();
      const point = nodes && nodes.getItemLayout(item.dataIndex);
      if (point) graphPinned.set(nodes.getId(item.dataIndex), [point[0], point[1]]);
    });
    instance.on('click', (item) => {
      if (item.dataType === 'node' && item.data.raw) {
        // In focus view a click recentres. Elsewhere it opens the node.
        if (($('[data-graph-view]', page).value || 'all') === 'focus') {
          graphFocus = item.data.raw.node_id;
          render('graph');
        } else {
          openNode(item.data.raw.node_id);
        }
      } else if (item.dataType === 'edge') {
        location.hash =
          `link/${encodeURIComponent(item.data.source)}/${encodeURIComponent(item.data.target)}`;
      }
    });
    instance.__wired = true;
  }
};

/* --- Nodes ----------------------------------------------------- */

/* How the list is ordered and how far down it we have read.
 *
 * The order lives here and travels to the server, never to a sort
 * applied over the rows already on screen. See `table()`.
 */
/*
 * How many rows one request asks for.
 *
 * 100, not the 300 this list used to fetch. The cap was large because a
 * capped list plus a "Show more" button was the whole paging story, so
 * the first page had to be worth reading on its own. The list now goes
 * on for as long as the reader scrolls (§6.2), which turns the first
 * page into the first paint instead: 300 rows of six columns is 1,800
 * cells built before anything is on the screen. The API's own default is
 * 100 and its ceiling is 500.
 */
const NODE_PAGE = 100;
let nodeSort = { key: 'last_heard', order: 'desc' };
/* How far into the server's ordering we have read. Advanced by the rows
 * the SERVER served, never by the rows we kept -- see `mergeNodePage`. */
let nodeOffset = 0;
let nodeTotal = 0;
let nodeRows = [];
/*
 * True once a request came back short, which is the only trustworthy
 * sign that the list has ended.
 *
 * Never derived from `nodeRows.length >= nodeTotal` alone: the total
 * comes from a second query, so a node heard for the first time between
 * the two makes the two numbers disagree, and a list that stops fetching
 * on a stale total stops one row short with no way to ask for the rest.
 */
let nodeExhausted = false;
/*
 * One page in flight at a time.
 *
 * Two scroll events can land in the same frame and both pass an
 * `isIntersecting` test; without this they would both fetch the same
 * offset and the second answer would be dropped as duplicates — a
 * request that cost the server a query and the reader nothing.
 */
let nodeLoadingMore = false;
/* The observer watching the foot of the list. See `wireNodeScroll`. */
let nodeScrollWatch = null;

/** Add the next page of nodes to the rows already held.
 *
 * Pure, and pulled out here because it carries the two decisions that
 * infinite scroll gets wrong quietly.
 *
 * **The offset advances by what the server served, not by what we
 * kept.** Those differ the moment a row is dropped as a duplicate, and
 * advancing by the kept count would re-request the rows just dropped:
 * a list that pages forever and never reaches its end.
 *
 * **A duplicate is dropped rather than drawn.** The plan (§6.2) asks for
 * keyset pagination on a stable sort key to prevent this, and the API
 * offers `limit`/`offset` only — so the risk it names is real and is
 * answered here instead. If a node's `last_heard` changes between two
 * requests the server's ordering shifts under us, and a row that moved
 * back a page arrives twice. Dropping it by `node_id` keeps the list
 * from showing one node twice. The other half of that shift — a row
 * that moved FORWARD a page, and is therefore never seen — cannot be
 * detected from here, and this comment says so rather than implying the
 * problem is solved. Nothing on this page refreshes on a timer, so the
 * window for either is one reader's own scrolling rather than a
 * 15-second poll.
 */
function mergeNodePage(held, incoming, { offset, pageSize }) {
  const served = Array.isArray(incoming) ? incoming : [];
  const seen = new Set((held || []).map((row) => row.node_id));
  const added = [];
  for (const row of served) {
    if (!row || row.node_id == null || seen.has(row.node_id)) continue;
    seen.add(row.node_id);
    added.push(row);
  }
  return {
    rows: (held || []).concat(added),
    offset: offset + served.length,
    // A short page means the server had nothing more to give. An exactly
    // full page does NOT mean there is more, so the next request can
    // still come back empty — which is this same test, one page later.
    exhausted: served.length < pageSize,
    added,
  };
}

/** What the end of the list says about how much of it is on screen.
 *
 * A `total` of `null` means the server did not say — an older build, or
 * a proxy that dropped `X-Total-Count`. It must not read as zero, so
 * this is a function with a case for it rather than a template with
 * subtraction in it. `Number(null)` is 0 and that mistake has been made
 * five times in this repository.
 */
function nodeProgressWords(shown, total, exhausted) {
  /*
   * At the end, the number of rows on screen -- not the total.
   *
   * They can differ by one or two: the total is counted by a second
   * query, so a node first heard between the two queries is in one and
   * not the other. "All 570 shown" over 569 rows is a small lie and the
   * kind that gets reported as a bug in the list.
   */
  if (exhausted || (total != null && shown >= total)) return `All ${count(shown)} shown`;
  if (total == null) return `${count(shown)} loaded · the total is unknown`;
  return `Showing ${count(shown)} of ${count(total)}`;
}

function nodeQuery(page, offset = 0) {
  const params = new URLSearchParams({
    limit: String(NODE_PAGE),
    offset: String(offset),
    sort: nodeSort.key,
    order: nodeSort.order,
  });
  const value = (selector) => {
    const node = $(selector, page);
    return node ? node.value : '';
  };
  const search = value('[data-node-search]').trim();
  const active = value('[data-node-active]');
  const role = value('[data-node-role]');
  const gateway = $('[data-node-gateway]', page).getAttribute('aria-pressed') === 'true';
  if (search) params.set('q', search);
  if (active) params.set('active_hours', active);
  if (role) params.set('role', role);
  if (gateway) params.set('gateway', 'true');
  /*
   * The menu's preset, set BEFORE the panel loop below so a channel
   * chosen in the filter panel still overrides it -- the existing rule
   * that the panel wins, because the panel is the one that shows what it
   * chose.
   *
   * This is the riskiest of the three pages to filter, and worth naming:
   * it HIDES nodes, and this is where somebody goes to find a specific
   * one. A node quiet on the selected preset will not be in the list.
   * The search box and the filter panel are both still there to get past
   * it, and `nodeFacetQuery` derives from this function, so the counts
   * beside each filter agree with the rows rather than describing a
   * larger set.
   */
  const channel = presetChannel();
  if (channel) params.set('channel', channel);
  // The panel wins where both can say the same thing, because it is the
  // one that shows what it chose.
  for (const [key, chosen] of nodeFilters) params.set(key, chosen);
  return `api/nodes?${params}`;
}

/** The same filters, for the endpoint that counts them. */
function nodeFacetQuery(page) {
  const params = new URLSearchParams(nodeQuery(page).split('?')[1]);
  for (const key of ['limit', 'offset', 'sort', 'order']) params.delete(key);
  return `api/nodes/facets?${params}`;
}

/* Everything the filter panel can narrow on.
 *
 * `key` is the query parameter, `facet` the group of counts the server
 * returns for it. A filter with neither is one the panel draws itself.
 */
const NODE_FILTERS = [
  { key: 'role', facet: 'role', label: 'Role', words: roleLabel },
  {
    key: 'hw',
    facet: 'hw',
    label: 'Hardware',
    /*
     * The top ten and a search box (Will, 2026-09-26).
     *
     * Production reports 57 hardware models and 17 of them have two
     * nodes or fewer, so the honest shape of this facet is a long tail:
     * printed in full it is the tallest thing in the panel and pushes
     * every other filter below the fold, and a reader looking for their
     * own board reads 57 names to find it.
     *
     * Ten covers the models a reader is likely to want, the box finds
     * the other 47 by name, and "Show all" is there for the reader who
     * would rather look than type. See `facetSlice`.
     */
    top: 10,
    search: 'Find a hardware model',
  },
  { key: 'channel', facet: 'channel', label: 'Channel' },
  {
    key: 'position',
    facet: 'position',
    label: 'Position',
    hint: 'How exactly the node has said where it is. A coarse position cannot anchor a '
      + 'prediction, which is why the siting half of Gaps cannot see one.',
    words: (value) => ({ exact: 'Exact', coarse: 'Coarse', none: 'None reported' }[value] || value),
  },
  {
    key: 'gateway',
    facet: 'gateway',
    label: 'Uploads to MQTT',
    hint: 'A gateway uploads packets it hears. It is not a device role.',
    words: (value) => (value === 'true' ? 'Yes' : 'No'),
  },
  {
    key: 'licensed',
    facet: 'licensed',
    label: 'Amateur licence',
    words: (value) => (value === 'true' ? 'Claimed' : 'Not claimed'),
  },
];

/* Filters the server has no facet for, because they are ranges rather
 * than sets of values. */
const NODE_RANGES = [
  {
    key: 'active_hours',
    label: 'Heard within',
    options: [['', 'Any time'], ['1', 'An hour'], ['24', 'A day'], ['168', 'A week'], ['720', 'A month']],
  },
  {
    key: 'first_seen_hours',
    label: 'First seen within',
    hint: 'When the mesh first heard this node at all, which is how you find the new ones.',
    options: [['', 'Any time'], ['24', 'A day'], ['168', 'A week'], ['720', 'A month']],
  },
  /*
   * The quiet side of "Heard within" (§6.2: everything sortable becomes
   * filterable).
   *
   * Every other sortable column could already be narrowed -- name and
   * node ID through the search box, hardware, role, channel and position
   * through the facets above, first seen through the range above this
   * one. Last heard was the exception, and only in one direction: there
   * was a way to ask "heard since" and none to ask "not heard since",
   * which is what "which routers have gone quiet" actually is. The only
   * way to ask it was to widen the window to Any time, sort ascending,
   * and read from the top -- which answers a different question and puts
   * the answer first by luck.
   *
   * It composes with "Heard within" into a band rather than fighting it:
   * a week within and a day quiet is "heard this week but not today".
   * Both windows are measured by the server, for the reason `quiet_hours`
   * records in `routes/nodes.py`.
   */
  {
    key: 'quiet_hours',
    label: 'Not heard for',
    hint: 'Nodes the mesh has not heard from in that long. Set it with "Heard within" for a '
      + 'band: heard this week, but not today.',
    options: [['', 'Any time'], ['1', 'An hour'], ['24', 'A day'], ['168', 'A week'], ['720', 'A month']],
  },
];

/* What the panel currently holds, before Apply. */
const nodeFilters = new Map();

/* What has been typed into a long facet's own search box, by filter key.
 *
 * Kept outside the panel because the panel is rebuilt from scratch every
 * time a value is chosen; the text would otherwise vanish the moment the
 * reader clicked the model they had just found. */
const nodeFacetSearch = new Map();

/* Long facets the reader has opened past their top slice, by filter key. */
const nodeFacetOpen = new Set();

/** Choose which values of a long facet to draw.
 *
 * Pure, because every one of these rules is a way to lie to a reader
 * about what is in force.
 *
 * `top` is how many to show unopened, `query` what has been typed, and
 * `chosen` the value the filter currently holds.
 *
 * **The chosen value is always drawn.** It can be outside the top slice
 * (it usually is -- a reader filters on their own unusual board) and it
 * can fail to match what is now typed. Dropping it would leave the
 * fieldset showing "Any" as the chosen option while the filter was in
 * force, and the reader would have no way to take it off from here.
 *
 * `more` is how many values are being withheld, for the button that
 * shows them. Zero means there is no more to see, which is not the same
 * as a search that matched nothing -- `shown` empty with a query is that,
 * and it needs a different sentence.
 */
function facetSlice(values, { top, query, chosen } = {}) {
  const list = values || [];
  const wanted = (query || '').trim().toLowerCase();
  const matches = wanted
    ? list.filter((entry) =>
      String(entry.words == null ? entry.value : entry.words).toLowerCase().includes(wanted)
      || String(entry.value).toLowerCase().includes(wanted))
    : list;
  // No slice asked for, or nothing to hide.
  if (!top || matches.length <= top) return { shown: matches, more: 0, matched: matches.length };
  const shown = matches.slice(0, top);
  const held = matches.slice(top);
  const keep = chosen == null
    ? []
    : held.filter((entry) => String(entry.value) === String(chosen));
  return { shown: shown.concat(keep), more: held.length - keep.length, matched: matches.length };
}

/** Draw the panel from the counts the server just gave us. */
function drawNodeFilters(page, facets) {
  const grid = $('[data-node-filter-grid]', page);
  const groups = [];

  for (const filter of NODE_FILTERS) {
    const values = (facets && facets[filter.facet]) || [];
    if (!values.length) continue;
    groups.push(facetGroup(page, filter, values));
  }

  /*
   * Gaps is one control rather than two, because a state without a
   * preset is not a question this data can answer: a node can need help
   * on one mesh and be fine on another. Offering them separately would
   * let somebody build a combination the server has to refuse.
   */
  const gapsOptions = (facets && facets.gaps) || [];
  if (gapsOptions.length) {
    const chosen = nodeFilters.get('gaps');
    const chosenPreset = nodeFilters.get('gaps_preset');
    groups.push(el('fieldset', { class: 'filter-group' },
      el('legend', {
        class: 'hinted',
        title: 'Measured by the Gaps page, one modem preset at a time. "Cannot tell" is not '
          + 'a clean bill of health: it means there was not enough evidence to say.',
      }, 'Connection health'),
      el('div', { class: 'filter-options' },
        optionButton(page, { key: 'gaps' }, '', 'Any', null, chosen == null),
        ...gapsOptions.map((entry) => {
          const words = `${entry.state === 'bad' ? 'Needs help' : 'Cannot tell'} on ${entry.preset}`;
          const picked = chosen === entry.state && chosenPreset === entry.preset;
          const button = el('button', {
            type: 'button',
            class: `filter-option${picked ? ' chosen' : ''}`,
            'aria-pressed': String(picked),
          }, el('span', { text: words }), el('span', { class: 'filter-count', text: count(entry.count) }));
          button.addEventListener('click', () => {
            nodeFilters.set('gaps', entry.state);
            nodeFilters.set('gaps_preset', entry.preset);
            drawNodeFilters(page, nodeFacets);
          });
          return button;
        }))));
  }

  for (const range of NODE_RANGES) {
    const chosen = nodeFilters.get(range.key) || '';
    groups.push(el('fieldset', { class: 'filter-group' },
      el('legend', { title: range.hint || null, class: range.hint ? 'hinted' : null }, range.label),
      el('div', { class: 'filter-options' },
        ...range.options.map(([value, words]) =>
          optionButton(page, range, value, words, null, chosen === value)))));
  }

  replace(grid, groups);
  $('[data-node-filter-summary]', page).textContent =
    nodeFilters.size ? `${nodeFilters.size} chosen, not yet applied` : 'Nothing chosen';
}

/** One facet as a fieldset: its values, and a way through a long tail.
 *
 * A facet with more values than `filter.top` gains a search box and a
 * "show the rest" button (§6.2, the hardware filter). A short one gains
 * neither: a box to search four models and a button that opens nothing
 * are both controls that say there is more to find when there is not.
 */
function facetGroup(page, filter, values) {
  const chosen = nodeFilters.get(filter.key);
  /*
   * The words are worked out once, here, because the search matches on
   * what the reader can SEE as well as on the wire value. Role reads
   * "Client" and travels as `CLIENT`; typing either has to work.
   *
   * `count` is passed through untouched. A facet count of 0 never comes
   * back from the server -- it drops values nothing holds -- but an
   * ABSENT count is not a zero either, and `optionButton` draws no badge
   * at all for null rather than a badge reading "0".
   */
  const labelled = values.map((entry) => {
    const value = String(entry.value);
    return { value, words: String(filter.words ? filter.words(value) : value), count: entry.count };
  });
  const long = Boolean(filter.top) && labelled.length > filter.top;

  const options = el('div', { class: 'filter-options' });
  /*
   * A short facet gets NEITHER control, and does not get them hidden
   * either: a permanently hidden button is markup that reads as a
   * feature, and the seeded database has four hardware models, so that is
   * the shape most development sees.
   */
  const more = long ? el('button', { type: 'button', class: 'more' }) : null;
  const box = long && filter.search
    ? el('input', {
      type: 'search',
      class: 'filter-search',
      // `filter.search` is the placeholder AND the accessible name. A
      // placeholder alone names nothing: it is gone as soon as anything
      // is typed, and some screen readers never read it at all.
      placeholder: filter.search,
      'aria-label': filter.search,
      value: nodeFacetSearch.get(filter.key) || '',
    })
    : null;
  // Only a facet with a box can have a search that matched nothing.
  const note = box ? el('p', { class: 'muted filter-note', hidden: true }) : null;

  /*
   * Repaint the values alone, never the whole panel.
   *
   * Rebuilding the grid on every keystroke would destroy and rebuild the
   * search box the reader is typing into, which takes the caret and the
   * focus with it -- the box would accept one character and then stop
   * being the focused element.
   */
  const paint = () => {
    const query = nodeFacetSearch.get(filter.key) || '';
    const open = nodeFacetOpen.has(filter.key);
    const slice = facetSlice(labelled, { top: open ? 0 : filter.top, query, chosen });
    replace(options,
      // "Any" is a choice, and it is the one that undoes this filter. It
      // is never filtered out by a search: it is the way back.
      optionButton(page, filter, '', 'Any', null, chosen == null),
      ...slice.shown.map((entry) =>
        optionButton(page, filter, entry.value, entry.words, entry.count,
          chosen === entry.value)));
    if (note) {
      // A search that matched nothing is not the same as a facet with
      // nothing in it, and the difference has to be said rather than
      // shown as an empty row.
      note.hidden = !(query && slice.matched === 0);
      note.textContent = `Nothing here matches "${query}"`;
    }
    if (!more) return;
    // Nothing withheld and nothing opened: no button. The count on it is
    // of what MATCHED, not of the facet, or a search that narrows to
    // three would offer to show all 57.
    more.hidden = !open && slice.more === 0;
    more.textContent = open ? 'Show fewer' : `Show all ${count(slice.matched)}`;
    more.setAttribute('aria-expanded', String(open));
  };

  if (box) {
    box.addEventListener('input', () => {
      nodeFacetSearch.set(filter.key, box.value);
      paint();
    });
  }
  if (more) {
    more.addEventListener('click', () => {
      if (nodeFacetOpen.has(filter.key)) nodeFacetOpen.delete(filter.key);
      else nodeFacetOpen.add(filter.key);
      paint();
    });
  }
  paint();

  return el('fieldset', { class: 'filter-group' },
    el('legend', { title: filter.hint || null, class: filter.hint ? 'hinted' : null },
      filter.label),
    box,
    options,
    note,
    more);
}

/** One value of one filter, with how many nodes sit behind it. */
function optionButton(page, filter, value, words, total, chosen) {
  const button = el('button', {
    type: 'button',
    class: `filter-option${chosen ? ' chosen' : ''}`,
    'aria-pressed': String(Boolean(chosen)),
  }, el('span', { text: String(words) }),
  total == null ? null : el('span', { class: 'filter-count', text: count(total) }));
  button.addEventListener('click', () => {
    if (!value) {
      nodeFilters.delete(filter.key);
      // Gaps travels as a pair; dropping the state must drop the preset
      // with it or the query keeps a parameter nothing is asking for.
      if (filter.key === 'gaps') nodeFilters.delete('gaps_preset');
    } else {
      nodeFilters.set(filter.key, value);
    }
    drawNodeFilters(page, nodeFacets);
  });
  return button;
}

/** The chips under the controls: what is in force, and how to drop it. */
function drawNodeChips(page) {
  const chips = $('[data-node-chips]', page);
  const applied = [...nodeFilters.entries()].filter(([key]) => key !== 'gaps_preset');
  chips.hidden = applied.length === 0;
  if (!applied.length) return replace(chips, []);
  const words = (key, value) => {
    if (key === 'gaps') {
      const preset = nodeFilters.get('gaps_preset');
      return `${value === 'bad' ? 'Needs help' : 'Cannot tell'} on ${preset}`;
    }
    const filter = [...NODE_FILTERS, ...NODE_RANGES].find((entry) => entry.key === key);
    if (!filter) return `${key}: ${value}`;
    const options = filter.options && filter.options.find((option) => option[0] === value);
    const shown = options ? options[1] : (filter.words ? filter.words(value) : value);
    return `${filter.label}: ${shown}`;
  };
  replace(chips, [
    el('span', { class: 'muted', text: 'Showing only' }),
    ...applied.map(([key, value]) => {
      const chip = el('button', { class: 'chip chip-drop', type: 'button',
        title: `Remove the ${key} filter` },
      el('span', { text: words(key, value) }), el('span', { 'aria-hidden': 'true', text: ' \u00d7' }));
      chip.addEventListener('click', () => {
        nodeFilters.delete(key);
        if (key === 'gaps') nodeFilters.delete('gaps_preset');
        render('nodes');
      });
      return chip;
    }),
  ]);
}

let nodeFacets = null;

/** How many filters are narrowing the list, for the summary line. */
function nodeFilterCount(page) {
  const query = new URLSearchParams(nodeQuery(page).split('?')[1]);
  for (const key of ['limit', 'offset', 'sort', 'order']) query.delete(key);
  return [...query.keys()].length;
}

/*
 * Which node search is the current one.
 *
 * The box now searches as it is typed, so several requests can be in
 * the air at once and they do not have to come back in order. Without
 * this an earlier, slower answer lands last and the table then shows
 * the results of a query the box no longer holds.
 */
let nodeSearchToken = 0;

PAGES.nodes = async (page) => {
  await loadNodes(page, { reset: true });
};

/** Draw the nodes list, or append the next page of it.
 *
 * `reset` starts again from the top: a new sort, a new filter, a new
 * search. Without it the rows already on screen are kept and the next
 * page is appended, which is what both the scroll and the "Show more"
 * button ask for.
 */
async function loadNodes(page, { reset = false } = {}) {
  const token = ++nodeSearchToken;
  const target = $('[data-node-table]', page);
  if (reset) {
    nodeOffset = 0;
    nodeRows = [];
    nodeExhausted = false;
    replace(target, el('p', { class: 'loading', text: 'Loading' }));
  }
  nodeLoadingMore = true;
  drawNodeMore(page);
  const answer = await getList(nodeQuery(page, nodeOffset)).catch((error) => error);
  /*
   * A newer request has started, so this answer is stale.
   *
   * The flag has to be cleared on the way out or the list wedges: the
   * observer and the button both refuse to ask for another page while
   * one is in flight, and an abandoned page that never cleared the flag
   * is in flight forever. The newer request sets it again immediately.
   */
  if (token !== nodeSearchToken) return;
  nodeLoadingMore = false;
  if (answer instanceof Error) {
    /*
     * A failed FIRST page replaces the table with the error. A failed
     * later page must not: the rows already read are still correct, and
     * throwing them away to show a message about a page the reader never
     * asked for by name would lose their place as well as their rows.
     */
    if (reset) return replace(target, failure(answer));
    drawNodeMore(page, answer);
    return;
  }

  const merged = mergeNodePage(reset ? [] : nodeRows, answer.rows, {
    offset: nodeOffset,
    pageSize: NODE_PAGE,
  });
  const appended = reset ? null : merged.added;
  nodeRows = merged.rows;
  nodeOffset = merged.offset;
  nodeExhausted = merged.exhausted;
  nodeTotal = answer.total;

  const roleSelect = $('[data-node-role]', page);
  if (roleSelect.options.length <= 1) {
    for (const role of [...new Set(nodeRows.map((row) => row.role).filter(Boolean))].sort()) {
      // The value stays the enum, because the API filters on it. Only
      // the words a reader chooses between change.
      roleSelect.append(el('option', { value: role, text: roleLabel(role) }));
    }
  }
  describeNodeList(page);
  drawNodeChips(page);
  // The counts describe the filters in force, so they are fetched with
  // the rows rather than once when the panel opens.
  getList(nodeFacetQuery(page)).then((answer) => {
    if (token !== nodeSearchToken) return;
    nodeFacets = answer.rows;
    if (!$('[data-node-filters]', page).hidden) drawNodeFilters(page, nodeFacets);
  }).catch(() => { nodeFacets = null; });

  const columns = nodeColumns((key, order) => {
    nodeSort = { key, order };
    // A new order is a new list. Paging on from where we were would mix
    // two orderings in one table.
    loadNodes(page, { reset: true });
  });

  const body = $('tbody', target);
  if (appended && body) {
    /*
     * Append, never rebuild.
     *
     * `replace(target, table(...))` on every page would work and would
     * be wrong: rebuilding the rows the reader is looking at takes their
     * text selection and hands the browser's scroll anchoring a whole
     * new subtree to guess about. Building only the new rows and adding
     * them after the last one leaves everything above untouched, which
     * is what makes the scroll position survive without a single
     * measurement — the same finding `redrawLiveTable` records for the
     * firehose.
     *
     * `table()` builds them, rather than a second row renderer here, so
     * the appended rows cannot drift from the first page's.
     */
    if (appended.length) {
      const grown = $('tbody', table(columns, appended, ''));
      if (grown) body.append(...Array.from(grown.rows));
    }
  } else {
    replace(target, table(columns, nodeRows, 'No nodes match the filters.'));
  }
  drawNodeMore(page);
  rearmNodeScroll();
  /*
   * A scroll-driven page does not go through `render()`, so the two
   * passes it runs afterwards have to be run here. Both are idempotent
   * and both read the rows: the hint panels list the exact values found
   * in a column, and a wider value in an appended row can start the
   * table scrolling sideways, which is what gives it a tab stop.
   */
  markScrollableTables(page);
  revealHints(page);
}

/** The columns of the nodes list.
 *
 * Its own function because two calls build rows from it now — the first
 * page and every appended one — and a second copy of this list would
 * drift from the first the moment a column changed.
 *
 * Every column names the sort the SERVER knows it by. The browser never
 * reorders rows it already holds: this list is paged, so sorting the
 * rows in hand would order the first hundred by name and present the
 * answer as the first hundred by name of the whole mesh. See `table()`.
 */
function nodeColumns(onSort) {
  const sortable = (column) => ({ ...column, sortState: nodeSort, onSort });
  return [
    sortable({ label: 'Node', sort: 'name', cell: (row) => nodeChip(row) }),
    sortable({
      label: 'Node ID',
      sort: 'node_id',
      hint: 'The number the firmware gives the node, written in hexadecimal after a "!".',
      cell: (row) => el('code', { text: row.node_id }),
    }),
    sortable({
      label: 'Hardware',
      sort: 'hw',
      hint: 'The board model the node reports for itself.',
      cell: (row) => row.hw_model || '-',
    }),
    sortable({ label: 'Role', sort: 'role', cell: (row) => roleCell(row.role) }),
    sortable({
      label: 'Flags',
      // Flags is not one value, so sorting it is a decision rather than
      // a rule. It sorts by how exactly the position is known, which is
      // the half of this column somebody sorts it to find.
      sort: 'position',
      hint: 'Gateway: the node uploads packets it hears to MQTT. Position: it has reported where it is. '
        + 'Sorting this column orders by how exactly the position is known.',
      cell: (row) => el('span', {},
        row.is_mqtt_gateway
          ? el('span', {
              class: 'tag gateway',
              title: 'This node uploads packets it hears to MQTT. It is not a device role.',
              text: 'gateway',
            })
          : null,
        row.has_position ? el('span', { class: 'tag', text: 'position' }) : null),
    }),
    sortable({
      label: 'Last heard',
      sort: 'last_heard',
      num: true,
      hint: HEARD_HINT,
      cell: (row) => `${ago(row.last_heard)} ago`,
    }),
  ];
}

/** The foot of the list: where we are in it, and how to read on.
 *
 * The button and the status live in `index.html` rather than being built
 * here, for two reasons.
 *
 * **A live region has to exist before its contents change.** A
 * `role="status"` element created at the same moment as its text is not
 * reliably announced, so a reader on a screen reader would be told
 * nothing about pages that arrive without a click. Built once in the
 * markup, it announces every update.
 *
 * **It sits outside `.table-wrap`.** That box scrolls sideways, and the
 * old "Show more" button was appended inside it — so on a narrow screen,
 * with the table scrolled right to read the last column, the button had
 * scrolled off to the left.
 */
function drawNodeMore(page, error) {
  const wrap = $('[data-node-more]', page);
  if (!wrap) return;
  const button = $('[data-node-more-button]', wrap);
  const status = $('[data-node-progress]', wrap);
  /*
   * No rows, nothing to say. That covers the first page still loading
   * (the table says "Loading"), a filter that matched nothing (the table
   * says so), and a first page that failed (the table shows the error).
   * A foot reading "Showing 0 of 24" under any of them would be a second
   * voice saying less.
   */
  wrap.hidden = !nodeRows.length;
  if (wrap.hidden) return;
  /*
   * `aria-disabled` while a page is in flight, never `disabled`.
   *
   * Setting `disabled` on the button the reader is standing on blurs it,
   * and focus lands back at the top of the document — so a keyboard
   * reader loses their place every time they ask for another page.
   * `nodeMore` ignores the second click either way.
   */
  button.setAttribute('aria-disabled', String(nodeLoadingMore));
  const hadFocus = document.activeElement === button;
  button.hidden = nodeExhausted;
  if (nodeExhausted && hadFocus) {
    // The control they just operated has gone, because there is nothing
    // left to ask for. Focus moves to the line that says so rather than
    // to the top of the document.
    wrap.setAttribute('tabindex', '-1');
    wrap.focus();
  }
  if (error) {
    /*
     * A page that failed is a dead end unless it can be retried, and the
     * rows already read stay on the screen. So the button comes back and
     * says what happened, rather than the list simply stopping.
     */
    button.hidden = false;
    button.setAttribute('aria-disabled', 'false');
    button.textContent = 'Try again';
    status.textContent = error.message || String(error);
    return;
  }
  button.textContent = 'Show more nodes';
  status.textContent = nodeLoadingMore
    ? 'Loading more nodes'
    : nodeProgressWords(nodeRows.length, nodeTotal, nodeExhausted);
}

/** Ask for the next page, if there is one and nothing else is asking.
 *
 * Called by the button and by the observer watching the foot of the
 * list. Every reason not to fetch is tested here rather than at each
 * caller, so the two cannot disagree.
 */
function nodeMore() {
  if (nodeLoadingMore || nodeExhausted) return;
  const page = $('[data-page="nodes"]');
  // `currentPage` rather than the element's visibility: the observer is
  // attached for the life of the document and the pages are switched by
  // a class.
  if (!page || currentPage !== 'nodes') return;
  if (!nodeRows.length) return;
  loadNodes(page);
}

/** Load pages for as long as the foot of the list is in view.
 *
 * Wired once, over an element that is `hidden` whenever there is nothing
 * more to read — a `display: none` element never intersects, so a
 * finished list costs nothing.
 *
 * `rootMargin` starts the next page while the foot is still below the
 * fold, so the rows are usually there before the reader arrives.
 *
 * **The observer is re-attached after every page.** Without that the
 * list stalls on a tall screen: one page of rows is not always enough to
 * push the foot back out of view, the intersection state therefore never
 * changes, and no second callback is ever delivered. Re-observing
 * re-delivers the initial notification, which is the browser telling us
 * again that the foot is still in view.
 *
 * Kept as well as the button, not instead of it (§6.2): infinite scroll
 * has no affordance, gives a keyboard reader nothing to operate, and
 * breaks "jump to the end". The button is all three answers.
 */
function wireNodeScroll() {
  const wrap = $('[data-node-more]');
  if (!wrap) return;
  const button = $('[data-node-more-button]', wrap);
  if (button) button.addEventListener('click', nodeMore);
  // Not every browser has it, and the button is the whole feature
  // without it rather than a broken page.
  if (typeof IntersectionObserver !== 'function') return;
  nodeScrollWatch = new IntersectionObserver((entries) => {
    if (!entries.some((entry) => entry.isIntersecting)) return;
    nodeMore();
  }, { rootMargin: '400px 0px' });
  nodeScrollWatch.observe(wrap);
}

/** Re-arm the foot-of-list observer. See `wireNodeScroll`. */
function rearmNodeScroll() {
  const wrap = $('[data-node-more]');
  if (!nodeScrollWatch || !wrap) return;
  nodeScrollWatch.unobserve(wrap);
  nodeScrollWatch.observe(wrap);
}

/** Say what is on screen, and never mistake the page for the answer.
 *
 * This line used to read `${rows.length} nodes match`, which on a mesh
 * of 2,372 nodes said "300 nodes match" and meant "here are 300".
 */
function describeNodeList(page) {
  const filters = nodeFilterCount(page);
  /*
   * No longer says how it is sorted or how many filters are on (Will,
   * 2026-09-26). The column heading already carries the sort -- it is
   * bold, `aria-sort` names it and the arrow is orange -- and the count of
   * filters now rides on the Filters button, where it belongs: a control
   * that says what it is holding beats a sentence describing it from a
   * distance.
   *
   * And it no longer says "showing 300" either. That half of the line
   * existed because the list was capped; it now scrolls on to the end
   * (\u00a76.2), so how much of it has loaded is a fact about the foot of the
   * list and it is written there, next to the control that changes it.
   * Same rule as the filter count: the thing holding the state says so.
   *
   * What stays is the one thing no control on this page could say: how
   * many nodes match at all. `count()` prints an absent total as "-"
   * rather than 0, and "0 nodes" when the server did not say how many
   * there are would be a number we do not have.
   */
  $('[data-node-count]', page).textContent = nodeTotal == null
    ? `${count(nodeRows.length)} nodes shown`
    : `${count(nodeTotal)} nodes`;

  /*
   * The button shows the count, and says so in its accessible name too --
   * a superscript number is invisible to a screen reader.
   */
  const badge = $('[data-node-filter-count]', page);
  const button = $('[data-node-filter-open]', page);
  if (badge) {
    badge.textContent = filters ? String(filters) : '';
    badge.hidden = !filters;
  }
  if (button) {
    button.classList.toggle('has-filters', Boolean(filters));
    button.setAttribute(
      'aria-label',
      filters ? `Filters, ${filters} in force` : 'Filters',
    );
  }
}

/*
 * `NODE_SORT_WORDS` was here and is gone.
 *
 * It spelled the sort out for the "· sorted by name" tail on the line
 * above the table. That sentence was removed on 2026-09-26 (the column
 * heading carries the sort) and the map it read from was left behind,
 * declared and never read by anything -- the failure the session brief
 * names in as many words: after removing a control, sweep for the NAME
 * as well as the attribute. `node --check` cannot see this, and a unit
 * test reading source text cannot tell a name never used from a name
 * merely absent.
 */

/* --- Node detail ----------------------------------------------- */

let currentNodeId = null;

function openNode(nodeId) {
  if (!nodeId || nodeId === '^all') return;
  location.hash = `node/${nodeId}`;
}

function definitionList(values, labels) {
  const entries = Object.entries(values || {})
    .filter(([key, value]) => value != null && labels[key])
    .map(([key, value]) => {
      const [label, format] = labels[key];
      return [label, format(value)];
    });
  if (!entries.length) return null;
  return el('dl', { class: 'kv' }, entries.flatMap(([label, value]) =>
    [el('dt', { text: label }), el('dd', { text: value })]));
}

function neighborPanel(neighbors, windowHours) {
  return el('div', { class: 'panel' },
    el('h3', {}, 'Neighbors',
      el('span', { class: 'muted',
        text: `${count(neighbors.length)} in ${windowHours} h` })),
    expandingTable([
      { label: 'Node', cell: (row) => nodeChip(row) },
      { label: 'SNR', num: true, cell: (row) => snrCell(row.snr) },
      { label: 'Last RX', num: true, cell: (row) => `${ago(row.last_rx_time || row.time)} ago` },
    ], neighbors, 'This node reports no neighbors.', { noun: 'neighbors' }));
}

/*
 * What to say when a telemetry panel is empty (#192).
 *
 * Measured on the running instance over 7 days: of 1,189 active nodes,
 * **849 (71%) show an empty Device panel and 1,117 (94%) an empty
 * Weather panel**. This is not an edge case -- for most visitors the
 * dead end IS the node page.
 *
 * Those two numbers also decide the wording. At 94% empty, the
 * overwhelmingly common reason Weather is blank is that the node has
 * **no sensor**, and no setting helps. Guidance that led with "turn on
 * environment telemetry" would send about a thousand owners hunting
 * for a setting that cannot work, so the sensor comes first.
 *
 * Setting names are quoted from `meshtastic/module_config.proto`
 * (`ModuleConfig.TelemetryConfig`) at the revision in
 * `proto/UPSTREAM_REV.txt`. No default interval is stated, because the
 * proto does not state one and this project does not fill in what the
 * vendor left out (AGENTS.md 9.27).
 *
 * The third cause is in both, and it is the one this page cannot see:
 * telemetry has to reach an MQTT gateway to appear here at all. A node
 * can be sending perfectly and have nothing uploaded.
 */
const TELEMETRY_HELP = {
  device: 'Device telemetry is a setting, not a sensor: any node can send it. '
    + 'In Config check, look for `device_telemetry_enabled` and '
    + '`device_update_interval` under the Telemetry module. '
    + 'It also has to reach an MQTT gateway to appear here, so a node that is '
    + 'sending may still show nothing if no gateway uploaded it.',
  weather: 'Weather needs a physical sensor on the node, such as a BME280. '
    + 'Without one, no setting will fill this in. '
    + 'With one, look for `environment_measurement_enabled` and '
    + '`environment_update_interval` under the Telemetry module in Config check. '
    + 'It also has to reach an MQTT gateway to appear here.',
};

/** The empty line, plus a way to the guidance (#192). */
function telemetryEmpty(message) {
  return el('p', { class: 'empty' }, message, ' ',
    el('a', { class: 'linky', href: '#config', text: 'How to turn this on' }));
}
function heardByPanel(gateways) {
  return el('div', { class: 'panel' },
    // The explanation moves behind the heading's hint (#191). It
    // describes what the columns mean rather than qualifying a number
    // that is shown, so hiding it does not turn an absence into a fact.
    el('h3', {
      'data-label': 'Heard by',
      'data-hint': 'A gateway usually receives a packet after other nodes relayed it. '
        + 'Signal figures here come only from packets that arrived direct, with no hop used.',
    }, 'Heard by',
      el('span', { class: 'muted', text: `${count(gateways.length)} gateways` })),
    expandingTable([
      { label: 'Gateway', cell: (row) => nodeChip(row) },
      { label: 'Relayed', num: true, cell: (row) => count(row.relayed_count) },
      { label: 'Direct', num: true, cell: (row) => count(row.direct_count) },
      { label: 'Avg SNR', num: true, cell: (row) => snrCell(row.avg_snr) },
      { label: 'Best SNR', num: true, cell: (row) => snrCell(row.best_snr) },
      { label: 'Last', num: true, cell: (row) => `${ago(row.last_heard)} ago` },
    ], gateways, 'No gateway heard this node in the window.', { noun: 'gateways' }));
}

function weatherPanel(detail) {
  const list = definitionList(detail.weather, WEATHER_LABELS);
  return el('div', { class: 'panel' },
    el('h3', {
      'data-label': 'Weather',
      // Only when there is nothing to explain away. A panel with
      // readings needs no "why is this empty".
      'data-hint': list ? null : TELEMETRY_HELP.weather,
    }, 'Weather',
      detail.weather_time ? el('span', { class: 'muted', text: `${ago(detail.weather_time)} ago` }) : null),
    list || telemetryEmpty('This node sends no environment telemetry.'));
}

function devicePanel(detail) {
  const list = definitionList(detail.device, DEVICE_LABELS);
  return el('div', { class: 'panel' },
    el('h3', {
      'data-label': 'Device',
      'data-hint': list ? null : TELEMETRY_HELP.device,
    }, 'Device',
      detail.device && detail.device.time
        ? el('span', { class: 'muted', text: `${ago(detail.device.time)} ago` }) : null),
    list || telemetryEmpty('This node sends no device telemetry.'));
}

function messagesPanel(detail) {
  const messages = detail.messages.recent || [];
  // `recent` is capped by the API; `count` is measured (#200). When
  // they disagree the list is not everything, and the button must not
  // say "all" -- this node had 1,184 messages behind a "View all 25".
  const cut = (detail.messages.count || 0) > messages.length;
  return el('div', { class: 'panel' },
    el('h3', {}, 'Messages sent',
      el('span', { class: 'muted', text: `${count(detail.messages.count)} in ${detail.window_hours} h` })),
    messages.length
      ? expandingList(messages, (message) => messageItem(message, { showChannel: true }),
          { limit: 5, cut })
      : empty('This node sent no stored messages in the window.'));
}

function identityPanel(node) {
  const rows = [
    ['Node ID', node.node_id],
    ['Long name', node.long_name || 'not reported'],
    ['Short name', node.short_name || 'not reported'],
    ['Hardware', node.hw_model || 'unknown'],
    ['Role', node.role ? `${roleLabel(node.role)} (${node.role})` : 'unknown'],
    // Through `yesNo`, not inlined. These two were the reason #193.4
    // could be "fixed" in the helper and still show lower case here.
    ['Licensed', yesNo(node.is_licensed)],
    ['MQTT gateway', yesNo(node.is_mqtt_gateway)],
    ['Channel', node.last_channel || 'unknown'],
    ['First seen', stamp(node.first_seen)],
    ['Last heard', node.last_heard ? `${stamp(node.last_heard)} (${ago(node.last_heard)} ago)` : 'never'],
  ];
  if (node.position) {
    rows.push(['Position', `${round(node.position.lat, 5)}, ${round(node.position.lon, 5)}`]);
    rows.push([
      'Altitude',
      node.position.altitude == null ? 'unknown' : SonoranUnits.heightFromM(node.position.altitude),
    ]);
  }
  return el('div', { class: 'panel' },
    el('h3', {}, 'Identity'),
    el('dl', { class: 'kv' }, rows.flatMap(([label, value]) =>
      [el('dt', { text: label }), el('dd', { text: value })])));
}

/*
 * What the node sent, by type (#255).
 *
 * The table scrolled sideways inside its own panel. The panel is one of
 * four in `.summary-row`, whose tracks go down to 15 rem, so at 1440 px
 * the table has about 238 px to live in. Every cell was `nowrap`, and
 * the labels are long: "Unreadable, reason not recorded" alone is wider
 * than that at this font size. `.table-wrap` did exactly its job and
 * scrolled, for a two-column table that has no business scrolling.
 *
 * Three changes, and each one is needed:
 *
 * - The type column WRAPS (`wrap: true`, which `td.wrap` turns into
 *   `white-space: normal`), so a label takes two lines rather than the
 *   panel's width. Every label has spaces to break at: `portnumLabel`
 *   turns the underscores of a port name it does not know into spaces.
 * - The heading is "Type", not "Packet type". A `nowrap` heading sets
 *   a floor under its column, and the panel is already titled
 *   "Activity". The exact wire values still reach the reader through
 *   the heading's hint button, which `revealHints` builds from each
 *   cell's `data-exact`.
 * - The count stays `nowrap` and right-aligned with tabular figures.
 *   A number broken over two lines reads as two numbers.
 *
 * Asserted at 320, 768, 1024 and 1440 px by the e2e journey "the node
 * page tables fit their panels", which measures the table against its
 * wrapper. The reflow journey could not catch this: it measures the
 * document, and a table scrolling inside `.table-wrap` never widens it.
 */
function activityPanel(detail) {
  return el('div', { class: 'panel' },
    el('h3', {}, 'Activity',
      el('span', { class: 'muted', text: `${count(detail.activity.packet_count)} packets in ${detail.window_hours} h` })),
    el('div', { class: 'table-wrap' }, table([
      { label: 'Type', wrap: true, cell: (row) => portnumCell(row.portnum) },
      { label: 'Count', num: true, cell: (row) => count(row.count) },
    ], detail.activity.by_portnum, 'This node sent no packets in the window.')));
}

async function drawSignalChart(target, nodeId, hours) {
  const rows = await get(`api/nodes/${encodeURIComponent(nodeId)}/signal?hours=${hours}`)
    .catch(() => null);
  const byNeighbour = new Map();
  for (const row of rows || []) {
    if (row.snr == null) continue;
    if (!byNeighbour.has(row.neighbor_name)) byNeighbour.set(row.neighbor_name, []);
    byNeighbour.get(row.neighbor_name).push([new Date(row.time).getTime(), row.snr]);
  }
  if (!byNeighbour.size) {
    target.replaceWith(empty('This node reports no neighbors, so no direct link was measured.'));
    return;
  }
  chart(target, {
    ...CHART_BASE,
    tooltip: { ...CHART_BASE.tooltip, trigger: 'axis' },
    legend: { textStyle: { color: PALETTE.muted }, top: 0, type: 'scroll' },
    xAxis: { type: 'time', ...AXIS },
    yAxis: { type: 'value', name: 'SNR dB', ...AXIS },
    series: [...byNeighbour.entries()].slice(0, 8).map(([name, points]) => ({
      name, type: 'line', showSymbol: false, smooth: true, data: points, lineStyle: { width: 1.5 },
    })),
  });
}

/* --- Node health cards and potential issues (#52, #56) ----------- */

/*
 * Four states, and every one carries a word and a shape as well as a
 * colour (WCAG 1.4.1). `unknown` is never green: a node with nothing to
 * measure is not a node in good health, which is the line
 * `gaps/signals.py` holds for every signal.
 */
const HEALTH_STATES = {
  ok: { word: 'Good', glyph: '✓' },
  warn: { word: 'Check', glyph: '!' },
  bad: { word: 'Needs help', glyph: '✕' },
  unknown: { word: 'Unknown', glyph: '?' },
};

/* The battery band stats.py calls a brownout risk, and the level the
 * firmware reports for a node on external power. Same numbers, so the
 * two pages agree. */
const BATTERY_LOW = 5;
const BATTERY_WEAK = 35;
const ON_MAINS_ABOVE = 100;

/** Scroll to the potential issues panel, which holds every card's evidence. */
function showIssues() {
  const target = $('#node-issues');
  if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/**
 * One health card: a name, a state in words and a shape, the measurement
 * behind it, and what would make it green.
 */
function healthCard({ name, state, measure, green, evidence, glyph, link }) {
  const look = HEALTH_STATES[state] || HEALTH_STATES.unknown;
  return el('div', { class: `health-card state-${state}` },
    el('div', { class: 'health-head' },
      el('span', { class: 'health-glyph', 'aria-hidden': 'true', text: glyph || look.glyph }),
      el('h3', { text: name })),
    // The Settings entry is not a check and has no state to report.
    state === 'none' ? null : el('p', { class: 'health-state', text: look.word }),
    el('p', { class: 'health-measure', text: measure }),
    green ? el('p', { class: 'health-green muted', text: green }) : null,
    link ? el('a', { class: 'linky', href: link.href, text: link.text }) : null,
    evidence
      ? el('button', { class: 'linky', type: 'button', text: 'See the evidence', onclick: showIssues })
      : null);
}

/** The state of one gaps signal, as a card state. */
const signalState = (signal) => (signal ? signal.state : 'unknown');

/**
 * The health cards.
 *
 * Every card that reads a gap signal reads the same row the potential
 * issues panel draws, from `/api/nodes/<id>/gaps`. Nothing here decides
 * what a signal means; it only picks which signals each card shows.
 * Power and position come from the node record, as #52 proposes.
 */
function healthChecks(gaps, detail) {
  const primary = gaps && gaps.available && gaps.assessments.length ? gaps.assessments[0] : null;
  const row = primary ? primary.node : null;
  const signal = (name) => (row && row.signals ? row.signals[name] : null);
  const notAssessed = gaps && gaps.available
    ? 'The gap assessment does not list this node.'
    : 'No gap assessment has been written yet.';

  /*
   * "Heard over the air", and the case that used to read Good.
   *
   * `sole_observer` is `bad` at exactly one direct gateway and
   * `unknown` at zero (gaps/signals.py). Downgrading only on `bad`
   * therefore let the zero case through as green, and the severity came
   * out backwards: a node nothing had heard read Good, while a node one
   * gateway had heard read Needs help. Measured on the live mesh, 218
   * of 774 assessed nodes were in that state, each shown a green card
   * over the words "0 gateways heard it directly".
   *
   * `unknown` is not a shade of `ok` here. A node nothing heard may be
   * three hops deep and perfectly well, or it may be off the air, and
   * this check cannot tell those apart -- which is exactly what
   * `unknown` is for. It must not be coloured as health.
   */
  const isolated = signal('radio_isolated');
  const sole = signal('sole_observer');
  let heardState = signalState(isolated);
  if (heardState === 'ok' && sole) {
    if (sole.state === 'bad') heardState = 'warn';
    else if (sole.state === 'unknown') heardState = 'unknown';
  }

  const margin = signal('weak_best_link');
  const marginEvidence = margin ? margin.evidence || {} : {};
  const intermittent = signal('rf_intermittent');
  const heardBack = signal('hears_but_is_not_heard');

  const device = detail.device || {};
  const battery = device.battery_level;
  let powerState = 'unknown';
  let powerMeasure = 'This node sends no device telemetry.';
  if (battery != null) {
    if (battery > ON_MAINS_ABOVE) {
      powerState = 'ok';
      powerMeasure = 'On external power.';
    } else {
      powerState = battery > BATTERY_WEAK ? 'ok' : battery >= BATTERY_LOW ? 'warn' : 'bad';
      powerMeasure = `Battery ${round(battery, 0)} %`
        + (device.voltage != null ? `, ${round(device.voltage, 2)} V` : '')
        + (powerState === 'warn' ? '. Low enough to restart under load.' : '.');
    }
  } else if (device.voltage != null) {
    powerMeasure = `${round(device.voltage, 2)} V. It reports no battery level.`;
  }

  const confidence = detail.node.position_confidence || 'none';
  const deviation = row && row.position_deviation_m;
  /*
   * Sharing a position is optional, and rounding one is a choice.
   *
   * A rounded position used to read `warn`, over the sentence "Green
   * when it shares its position at full precision." The mesh asks for
   * neither. Rounding is how somebody keeps their house off a public
   * map, and marking it as a fault told a careful owner they had got
   * something wrong.
   *
   * So both of the shared cases are `ok`, and sharing nothing is
   * neutral rather than a warning: worth mentioning, because it can be
   * switched off by accident, but never scored against the node.
   *
   * The coverage and siting pages still hold their own line on this --
   * they need an exact position to place a marker, and they say so
   * where they need it. That is a statement about what a map can draw,
   * not about whether a node is set up correctly.
   */
  const position = {
    exact: ['ok', 'Shares its position.'],
    coarse: ['ok', deviation
      ? `Shares its position, rounded to about ${count(Math.round(deviation))} m.`
      : 'Shares its position at reduced precision.'],
    none: ['unknown', 'Shares no position. That is optional on this mesh.'],
  }[confidence] || ['unknown', 'Shares no position. That is optional on this mesh.'];

  const measured = (value, fallback) => (row ? value : fallback);
  /*
   * The checks as DATA, not as cards.
   *
   * Two views read this now -- the compact summary at the top of the
   * page and the full checklist behind "View all" (#95) -- and a
   * summary that counted rendered DOM would have to parse the words
   * back out of it.
   */
  return [
    ({
      name: 'Heard over the air',
      state: heardState,
      measure: measured(
        `${count(row && row.direct_gateways)} gateways heard it directly. `
          + `${count(row && row.rf_packets)} of ${count(row && row.packets)} packets reached a gateway over the air.`,
        notAssessed),
      green: 'Green when a gateway other than itself hears it over the air, and more than one gateway hears it directly. Grey when nothing heard it directly, which this check cannot tell apart from a node several hops deep.',
      evidence: Boolean(row),
    }),
    ({
      name: 'Signal margin',
      state: signalState(margin),
      measure: measured(
        marginEvidence.best_snr_db != null
          ? `Best link ${round(marginEvidence.best_snr_db, 1)} dB. ${primary && primary.preset} needs ${round(marginEvidence.required_snr_db, 1)} dB.`
          : (margin && margin.sentence) || 'No measured signal reading.',
        notAssessed),
      green: `Green when its best measured link is at least ${marginEvidence.margin_bad_db ?? 5} dB above what the preset needs.`,
      evidence: Boolean(row),
    }),
    ({
      name: 'Gets out consistently',
      state: signalState(intermittent),
      measure: measured(
        row && row.active_hours
          ? `Heard over the air in ${count(row.rf_hours)} of the ${count(row.active_hours)} hours it was awake.`
          : 'Not awake long enough in the window to judge.',
        notAssessed),
      green: 'Green when something on the air hears it in most of the hours it is awake.',
      evidence: Boolean(row),
    }),
    ({
      name: 'Heard back',
      state: signalState(heardBack),
      measure: measured((heardBack && heardBack.sentence) || 'Not measured.', notAssessed),
      green: 'Green when the nodes it hears also hear it.',
      evidence: Boolean(row),
    }),
    ({
      name: 'Power',
      state: powerState,
      measure: powerMeasure,
      green: `Green on external power, or with the battery above ${BATTERY_WEAK} %.`,
    }),
    ({
      name: 'Position',
      state: position[0],
      measure: position[1],
      green: 'Green whenever it shares a position, rounded or exact. Sharing one is optional.',
    }),
    ({
      name: 'Settings',
      // Not a check: there is nothing to pass or fail, so it is `none`
      // and the summary leaves it out of every count.
      state: 'none',
      glyph: '⚙',
      measure: 'Check a config file against the community recommendations. Nothing leaves the browser.',
      green: null,
      link: { href: '#config', text: 'Open Config check' },
    }),
  ];
}

/*
 * Where the node is (#103).
 *
 * The node page showed the position as two numbers in the Identity
 * panel, which is the one fact on that page that a map answers better
 * than text.
 *
 * Deliberately NOT drawn: lines to neighbours and to the nodes that
 * hear it. The issue offers that as "optional, and useful", from "data
 * the page already loads" -- but it does not. Measured against
 * `/api/nodes/{id}/detail`, neither `neighbors` nor `heard_by` carries
 * a latitude or a longitude:
 *
 *     neighbors  keys: node_id, display_name, snr, last_rx_time,
 *                      broadcast_interval_secs, time
 *     heard_by   keys: node_id, display_name, count, direct_count,
 *                      relayed_count, last_heard, avg_snr, best_snr,
 *                      avg_rssi
 *
 * Drawing them needs the endpoint to carry positions, which is a change
 * to the API rather than to this function.
 */
const nodeMaps = new Map();

function nodeMapPanel(detail) {
  const node = detail.node || {};
  const position = node.position;
  const confidence = node.position_confidence || 'none';

  /*
   * No position is a normal state, not an error.
   *
   * Sharing one is optional on this mesh, and #96 established that
   * treating a withheld or rounded position as a fault tells a careful
   * owner they got something wrong. So this says what is true and
   * stops.
   */
  if (!position || position.lat == null || position.lon == null) {
    return el('section', { class: 'panel' },
      el('h3', { text: 'Where it is' }),
      el('p', { class: 'muted', text: 'This node does not share a position. That is optional.' }));
  }

  const box = el('div', { class: 'node-map', 'data-node-map': '' });
  const panel = el('section', { class: 'panel' },
    /*
     * "Rounded by its owner" moves behind the heading's hint (#191),
     * which that issue allows by name. What stays printed is the thing
     * it qualifies: where the coordinates would be, the page now says
     * "Rounded" in their place rather than printing numbers that look
     * exact. The map still draws no radius (#96) -- the payload carries
     * the confidence but not the rounding distance, and a circle drawn
     * to a guessed radius would claim a precision we do not have.
     */
    el('h3', {
      'data-label': 'Where it is',
      'data-hint': confidence === 'coarse'
        ? 'This position is rounded to a coarser one by its owner, which is a normal '
          + 'privacy choice. It can be kilometres from where the node really is, so no '
          + 'distance is measured from it.'
        : null,
    }, 'Where it is',
      /*
       * A link to THIS node on the live map (#193.6).
       *
       * The old note said "Open the live map", which went to `#map` and
       * showed the whole mesh rather than this node.
       *
       * The node's channel rides along, because the map draws one
       * preset at a time (AGENTS.md 9.7) and since #177 it opens on the
       * deployment's own. Without the preset a node on any other one is
       * not drawn and the link lands on empty ground.
       */
      node.channel
        ? el('a', {
            class: 'linky node-map-link',
            href: `#map/node/${encodeURIComponent(node.node_id)}`
              + `?preset=${encodeURIComponent(node.channel)}`,
            text: 'View on full map',
          })
        : el('a', {
            class: 'linky node-map-link',
            href: `#map/node/${encodeURIComponent(node.node_id)}`,
            text: 'View on full map',
          })),
    box,
    el('p', { class: 'muted node-map-note' },
      confidence === 'coarse'
        ? 'Rounded position'
        : `${round(position.lat, 5)}, ${round(position.lon, 5)}`));

  // Leaflet needs the element in the document before it measures it.
  setTimeout(() => drawNodeMap(box, position, confidence), 0);
  return panel;
}

function drawNodeMap(target, position, confidence) {
  if (!target.isConnected || typeof L === 'undefined') return;

  /*
   * Let go of the maps whose panels are gone.
   *
   * `replace()` builds a new container on every node page load, so
   * keying on the element alone would never match the old entry: each
   * visit would leave a live Leaflet instance, its tile layer and its
   * listeners attached to a detached node, and `nodeMaps` would grow
   * for as long as somebody kept clicking through nodes.
   */
  for (const [element, old] of nodeMaps) {
    if (element === target || !element.isConnected) {
      old.remove();
      nodeMaps.delete(element);
    }
  }

  const point = [position.lat, position.lon];
  /*
   * The page's scroll gesture belongs to the page.
   *
   * A map that grabs the wheel traps a reader scrolling past it on a
   * laptop, and one that grabs the drag traps a thumb on a phone. Both
   * are handed back on a click or a tap, which is what Leaflet's
   * `tap`/`scrollWheelZoom` pair is for.
   */
  const map = L.map(target, {
    attributionControl: true,
    scrollWheelZoom: false,
    dragging: !L.Browser.mobile,
  }).setView(point, confidence === 'coarse' ? 11 : 14);
  nodeMaps.set(target, map);
  map.on('click', () => {
    map.scrollWheelZoom.enable();
    if (!map.dragging.enabled()) map.dragging.enable();
  });

  if (CONFIG.tileUrl) {
    L.tileLayer(CONFIG.tileUrl, {
      className: 'basemap-tiles',
      attribution: CONFIG.tileAttribution || '',
      maxZoom: 19,
    }).addTo(map);
  }

  L.circleMarker(point, {
    radius: 8,
    color: PALETTE.accent,
    fillColor: PALETTE.accent,
    // A rounded position is drawn hollow, so the shape says "about
    // here" without a radius that would claim a distance we were not
    // told.
    fillOpacity: confidence === 'coarse' ? 0.15 : 0.7,
    weight: 2,
  }).addTo(map);

  setTimeout(() => map.invalidateSize(), 0);
}

/*
 * The node's health in one panel, with everything behind one button.
 *
 * The health cards and "Potential issues" were the first two things on
 * the node page and between them filled the first screen, so somebody
 * opening the page to check the battery scrolled past two assessments
 * of the same gaps data to reach it (#95).
 *
 * Two product calls, made here rather than asked about:
 *
 * 1. A COUNT AND A ROW OF DOTS, not a score or a ring. Several checks
 *    can legitimately be `unknown`, so any single number would either
 *    hide them or invent a denominator. "5 of 6 checks good" states the
 *    denominator it used, and a screen reader gets it for nothing.
 * 2. EXPANDS IN PLACE, not a modal or its own route. The full list is
 *    long-form reading with evidence under each item, which a drawer
 *    fights; and a route would need the node page's own routing
 *    changed. If people turn out to want to link to it, the route is
 *    the cheap upgrade from here.
 *
 * `unknown` never counts against the node. That is required by the
 * issue and it is the same mistake as #87, where a node nothing had
 * heard read "Good".
 */
const HEALTH_GROUPS = [
  { key: 'bad', heading: 'Needs fixing', states: ['bad', 'warn'] },
  { key: 'ok', heading: 'Good', states: ['ok'] },
  { key: 'unknown', heading: "Can't tell yet", states: ['unknown'] },
];

function healthPanel(gaps, detail, evidencePanel) {
  const checks = healthChecks(gaps, detail);
  // `none` is the Settings entry, which is guidance rather than a
  // check. It appears in the full list and in no count.
  const judged = checks.filter((check) => check.state !== 'none');
  const attention = judged.filter((check) => check.state === 'bad' || check.state === 'warn');
  const good = judged.filter((check) => check.state === 'ok');
  const cannotTell = judged.filter((check) => check.state === 'unknown');

  const sentence = [
    `${count(good.length)} of ${count(judged.length - cannotTell.length)} checks good`,
    attention.length ? `${count(attention.length)} needs attention` : null,
    cannotTell.length ? `${count(cannotTell.length)} can't tell yet` : null,
  ].filter(Boolean).join(' · ');

  const dots = el('p', { class: 'health-dots', role: 'img', 'aria-label': sentence },
    ...judged.map((check) => el('span', {
      class: `health-dot state-${check.state}`,
      'aria-hidden': 'true',
      title: `${check.name}: ${(HEALTH_STATES[check.state] || HEALTH_STATES.unknown).word}`,
    })));

  const full = el('div', { class: 'health-full', hidden: true },
    ...HEALTH_GROUPS.map((group) => {
      const members = checks.filter((check) => group.states.includes(check.state));
      if (!members.length) return null;
      return el('section', { class: 'health-group' },
        el('h4', { text: group.heading }),
        el('div', { class: 'health-cards' }, ...members.map(healthCard)));
    }),
    // Guidance, not a check, so it sits below the three groups rather
    // than inside one of them.
    el('div', { class: 'health-cards' },
      ...checks.filter((check) => check.state === 'none').map(healthCard)),
    /*
     * "Potential issues" lives in here too.
     *
     * It was a second panel built from the same gaps assessment as the
     * cards, which is the duplication #95 is about. Inside the
     * disclosure it becomes the evidence layer of one feature rather
     * than a second opinion beside it -- and `showIssues`, which the
     * per-check "See the evidence" buttons call, still has something to
     * scroll to.
     */
    evidencePanel || null);

  const toggle = el('button', {
    class: 'linky',
    type: 'button',
    'aria-expanded': 'false',
    text: 'View all checks',
    onclick: () => {
      const open = full.hidden;
      full.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? 'Hide checks' : 'View all checks';
    },
  });

  return el('section', { class: 'panel health-panel' },
    el('h3', { text: 'Health' }),
    el('p', { class: 'health-headline', text: sentence }),
    dots,
    // Only what needs attention is named up here. Listing the good ones
    // is what made this two screens tall in the first place.
    attention.length
      ? el('ul', { class: 'health-attention' },
        ...attention.map((check) => el('li', {},
          el('span', { class: `health-dot state-${check.state}`, 'aria-hidden': 'true' }),
          el('span', { text: `${check.name}. ${check.measure}` }))))
      : null,
    toggle,
    full);
}

/** Say an evidence key in words: `rf_packets` is "rf packets". */
const evidenceLabel = (key) => key.replace(/_/g, ' ').replace(/\bsnr\b/, 'SNR').replace(/\brf\b/, 'RF')
  .replace(/\bdb\b/, 'dB').replace(/\bdbm\b/, 'dBm');

function evidenceValue(value) {
  if (value == null) return 'none';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none';
  if (typeof value === 'number') return count(round(value, 2));
  return String(value);
}

/** One signal of one assessment: state, name, sentence, evidence. */
/*
 * A gaps signal is named for the fault it looks for ("Reaches us only
 * through MQTT"), so its state reads as an answer to that question, in
 * the words the gaps page uses. "Good" beside a fault's name reads as
 * the fault being good.
 */
const ISSUE_WORDS = { bad: 'Found', ok: 'Not found', unknown: 'Cannot tell' };

function issueItem(name, found, labels) {
  const look = HEALTH_STATES[found.state] || HEALTH_STATES.unknown;
  const evidence = Object.entries(found.evidence || {});
  return el('li', { class: `issue state-${found.state}` },
    el('div', { class: 'issue-head' },
      el('span', { class: 'health-glyph', 'aria-hidden': 'true', text: look.glyph }),
      el('strong', { text: labels[name] || evidenceLabel(name) }),
      el('span', { class: 'issue-state', text: ISSUE_WORDS[found.state] || look.word })),
    el('p', { text: found.sentence || '' }),
    evidence.length
      ? el('details', {},
          el('summary', { text: 'What this is measured from' }),
          el('dl', { class: 'kv' }, evidence.flatMap(([key, value]) =>
            [el('dt', { text: evidenceLabel(key) }), el('dd', { text: evidenceValue(value) })])))
      : null);
}

/**
 * The potential issues panel: the per node report the gaps page already
 * holds, put where the owner looks for it.
 *
 * When nothing is flagged it says which checks ran and passed, because
 * silence must not read as approval. An unknown is listed as unknown.
 */
function issuesPanel(gaps) {
  const head = el('h3', {}, 'Potential issues',
    el('span', { class: 'muted', text: 'from the coverage gaps assessment' }));
  const links = el('p', { class: 'more-wrap' },
    el('a', { class: 'linky', href: '#gaps', text: 'The whole mesh on Coverage gaps' }),
    ' · ',
    el('a', { class: 'linky', href: '#config', text: 'Check its settings' }));
  const panel = (...body) => el('div', { class: 'panel span-2', id: 'node-issues' }, head, ...body, links);
  if (!gaps || !gaps.available) {
    return panel(empty('No gap assessment has been written yet. The gaps job writes one every half hour.'));
  }
  if (!gaps.assessments.length) {
    return panel(empty(
      `The gap assessment${gaps.not_listed.length ? ` for ${gaps.not_listed.join(', ')}` : ''} does not list this node. `
      + 'It was not heard on those presets in the assessment window.'));
  }
  return panel(gaps.assessments.map((assessment) => {
    const row = assessment.node;
    const order = (assessment.signal_order || []).filter((name) => row.signals && row.signals[name]);
    const states = order.map((name) => row.signals[name].state);
    const flagged = states.filter((state) => state === 'bad').length;
    const passed = states.filter((state) => state === 'ok').length;
    const unknown = states.length - flagged - passed;
    const summary = flagged
      ? `${flagged} of ${states.length} checks flag something.`
      : `Nothing flagged. ${passed} of ${states.length} checks ran and passed.`;
    return el('section', { class: 'issue-preset' },
      el('h4', { text: `${assessment.preset} - last ${assessment.window_hours} h` }),
      el('p', { class: 'muted' },
        `${summary}${unknown ? ` ${unknown} could not be measured, which is not the same as passing.` : ''}`
        + (row.mobile ? ' This node moves, so the position checks do not apply to it.' : '')
        + ` Assessed ${ago(assessment.generated_at)} ago.`),
      el('ul', { class: 'issues' }, order.map((name) =>
        issueItem(name, row.signals[name], assessment.signal_labels || {}))));
  }));
}

/* --- Node charts over time (#53) --------------------------------- */

/** A chart panel, left out entirely when it has nothing to draw. */
function historyChart(title, sub) {
  const box = el('div', { class: 'chart' });
  return [el('div', { class: 'panel' },
    el('h3', {}, title, sub ? el('span', { class: 'muted', text: sub }) : null), box), box];
}

function drawNodeHistory(target, history) {
  if (!history) return replace(target, el('div', { class: 'panel span-2' }, failure(new Error('Cannot load the history.'))));
  const panels = [];
  const draws = [];
  const time = (value) => new Date(value).getTime();
  const device = history.device || [];

  /*
   * A node on external power reports a battery above 100 % and often a
   * voltage of 0, and two flat lines say nothing the Power card does not.
   */
  const onBattery = device.some((row) => row.battery_level != null && row.battery_level <= 100);
  const hasVoltage = device.some((row) => row.voltage);
  if (onBattery || hasVoltage) {
    const [panel, box] = historyChart('Battery and voltage', 'from device telemetry');
    panels.push(panel);
    draws.push(() => chart(box, {
      ...CHART_BASE,
      tooltip: { ...CHART_BASE.tooltip, trigger: 'axis' },
      legend: { textStyle: { color: PALETTE.muted }, top: 0 },
      xAxis: { type: 'time', ...AXIS },
      // Above 100 % is how the firmware says "on external power".
      yAxis: [
        { type: 'value', name: '%', min: 0, max: 101, ...AXIS },
        { type: 'value', name: 'V', scale: true, ...AXIS, splitLine: { show: false } },
      ],
      series: [
        { name: 'Battery', type: 'line', showSymbol: false, connectNulls: false, yAxisIndex: 0,
          data: device.map((row) => [time(row.time), row.battery_level == null ? null : Math.min(row.battery_level, 101)]),
          itemStyle: { color: PALETTE.good } },
        { name: 'Voltage', type: 'line', showSymbol: false, connectNulls: false, yAxisIndex: 1,
          data: device.map((row) => [time(row.time), row.voltage]), itemStyle: { color: PALETTE.warn } },
      ],
    }));
  }

  if (device.some((row) => row.channel_utilization != null || row.air_util_tx != null)) {
    const [panel, box] = historyChart('Channel use and air time', 'from device telemetry');
    panels.push(panel);
    draws.push(() => chart(box, {
      ...CHART_BASE,
      tooltip: { ...CHART_BASE.tooltip, trigger: 'axis' },
      legend: { textStyle: { color: PALETTE.muted }, top: 0 },
      xAxis: { type: 'time', ...AXIS },
      yAxis: { type: 'value', name: '%', min: 0, ...AXIS },
      series: [
        { name: 'Channel use', type: 'line', showSymbol: false,
          data: device.map((row) => [time(row.time), row.channel_utilization]), itemStyle: { color: PALETTE.link } },
        { name: 'Air time sending', type: 'line', showSymbol: false,
          data: device.map((row) => [time(row.time), row.air_util_tx]), itemStyle: { color: PALETTE.accent } },
      ],
    }));
  }

  const packets = history.packets || { buckets: [], families: [] };
  if (packets.families.length) {
    // One band per packet family, in the family colours the live map
    // uses, so the two read the same.
    const live = window.SonoranLive;
    const bands = new Map();
    for (const family of packets.families) {
      const key = live ? live.familyKey(family.name) : 'OTHER';
      const counts = bands.get(key) || packets.buckets.map(() => 0);
      family.counts.forEach((value, index) => { counts[index] += value; });
      bands.set(key, counts);
    }
    const order = live ? live.FAMILY_ORDER.filter((key) => bands.has(key)) : [...bands.keys()];
    const [panel, box] = historyChart('What it sent', 'a gap is a quiet stretch');
    panels.push(panel);
    draws.push(() => chart(box, {
      ...CHART_BASE,
      legend: { textStyle: { color: PALETTE.muted }, top: 0, type: 'scroll' },
      grid: { ...CHART_BASE.grid, top: 36 },
      xAxis: { type: 'time', ...AXIS },
      yAxis: { type: 'value', minInterval: 1, ...AXIS },
      series: order.map((key) => {
        const family = live ? live.FAMILIES[key] : null;
        return {
          name: family ? family.label : key,
          type: 'bar',
          stack: 'all',
          barMaxWidth: 14,
          data: packets.buckets.map((bucket, index) => [time(bucket), bands.get(key)[index]]),
          itemStyle: { color: family ? colour(family.token, family.fallback) : PALETTE.muted },
        };
      }),
    }));
  }

  const signal = history.direct_signal || [];
  if (signal.length) {
    const [panel, box] = historyChart('Signal at gateways', 'heard directly, no hop used');
    panels.push(panel);
    draws.push(() => chart(box, {
      ...CHART_BASE,
      tooltip: { ...CHART_BASE.tooltip, trigger: 'axis' },
      legend: { textStyle: { color: PALETTE.muted }, top: 0, type: 'scroll' },
      grid: { ...CHART_BASE.grid, top: 36 },
      xAxis: { type: 'time', ...AXIS },
      yAxis: { type: 'value', axisLabel: { ...AXIS.axisLabel, formatter: '{value} dB' }, axisLine: AXIS.axisLine, splitLine: AXIS.splitLine },
      series: signal.map((gateway) => ({
        name: gateway.display_name,
        type: 'line',
        showSymbol: true,
        symbolSize: 4,
        data: gateway.points.map(([moment, snr]) => [time(moment), snr]),
      })),
    }));
  }

  if (!panels.length) {
    return replace(target, el('div', { class: 'panel span-2' },
      el('h3', { text: 'Over time' }),
      empty('This node reported no device telemetry and sent no packets in the window.')));
  }
  replace(target, panels);
  draws.forEach((draw) => draw());
}

/* --- Route and neighbour widgets (#55) ---------------------------- */

// Keeps the old precision rule -- a tenth under ten, whole above -- and
// hands the unit to SonoranUnits, which also drops to feet or metres
// below a thousand of them.
const km = (value) => (
  value == null ? '-' : SonoranUnits.distanceFromKm(value, { digits: value < 10 ? 1 : 0 })
);

function routesPanel(routes) {
  if (!routes) return el('div', { class: 'panel span-2' }, failure(new Error('Cannot load the routes.')));
  /*
   * The tile's explanation goes in `data-hint`, not `title` (#191).
   *
   * #99 removed `title` tooltips on purpose: a finger cannot hover and
   * a keyboard cannot reach one. These four tiles kept theirs, so the
   * only explanation of "Hops to the nearest gateway" was invisible to
   * anybody on a phone.
   *
   * The tile keeps its own class. An earlier draft added `stat` to
   * reuse that selector, and it only looked right by accident:
   * `.stat` and `.route-tile` have equal specificity, so the tiles kept
   * their padding and font size purely because `.route-tile` appears
   * later in app.css. `revealHints` scans `.label[data-hint]` instead,
   * which needs no class borrowed for its side effects.
   */
  const tile = (label, value, detail, hint) => el('div', { class: 'route-tile' },
    el('span', { class: 'label', text: label, 'data-label': label, 'data-hint': hint || null }),
    el('span', { class: 'value', text: value }),
    detail ? el('span', { class: 'muted', text: detail }) : null);
  const longest = routes.longest_segment;
  const heardBy = routes.furthest_heard_by;
  const heard = routes.furthest_heard;
  /*
   * Why there is no distance, said in the tile (#193.7).
   *
   * "None with an exact position" is true and reads as "nobody heard
   * it". On the node this was reported against, 26 nodes hear it and it
   * hears 48; the reason no distance exists is that **its own** position
   * is rounded, so every pair is excluded by the #55 rule.
   *
   * That is a different sentence from "the other ends are rounded", and
   * it is the one the reader can act on: it is their own privacy
   * setting, not somebody else's. The rule itself does not change --
   * a distance is still never measured from a rounded position.
   */
  const noDistance = routes.position === false
    ? 'Its own position is rounded, so no distance can be measured.'
    : 'None with an exact position.';
  const depth = routes.hop_depth || { packets: 0, counts: [] };
  /*
   * Three columns, not five (#260).
   *
   * "Who hears it" scrolled sideways at every width, desktop included:
   * at 1440 px the table was 633 px in a 543 px half-panel, and at
   * 320 px 633 in 254. Five `nowrap` columns -- Node, Reports, Best SNR,
   * From, Distance -- cannot fit half of a panel, and no amount of
   * padding would change that.
   *
   * The question the table answers is "who hears this node, and how
   * well?", which is a name, a signal and a distance. The other two
   * columns are evidence FOR the row, not answers of their own, so they
   * moved under the name as one muted line: "3 reports: neighbor report,
   * traceroute". Nothing was dropped, and the count keeps its own words
   * rather than becoming a bare number in a narrow cell.
   *
   * The name wraps as well (`.route-list` in app.css). `.node-name .long`
   * is `nowrap` with an ellipsis everywhere else, and inside a table cell
   * that is not a cut but a floor: the cell grows to the whole name first.
   * Long names are ordinary on this mesh ("UTOPIA PLANITIA G3"), and some
   * have no space in them at all, so it breaks anywhere.
   *
   * The headings are short and carry their meaning in hints, and the
   * numbers stay right-aligned with tabular figures (`num: true`), so a
   * narrower column still lines up.
   *
   * Asserted at 320, 768, 1024 and 1440 px on the node heard by the most
   * nodes, by the e2e journey "the Who hears it table fits its panel".
   */
  const evidence = (row) => {
    const kinds = row.kinds.map((kind) => (kind === 'neighbor' ? 'neighbor report' : 'traceroute')).join(', ');
    // `count` prints an absent number as "-", never as 0.
    return `${count(row.count)} ${row.count === 1 ? 'report' : 'reports'}: ${kinds}`;
  };
  const columns = [
    { label: 'Node', wrap: true,
      hint: 'Under each name: how many neighbor reports and traceroute hops show the link in this direction, and which of the two they were.',
      cell: (row) => el('div', { class: 'route-who' },
        nodeChip(row), el('span', { class: 'muted', text: evidence(row) })) },
    { label: 'SNR', num: true, hint: 'The best signal-to-noise ratio any of those reports measured on the link.', cell: (row) => snrCell(row.best_snr) },
    { label: 'Distance', num: true, hint: 'Only where both nodes share an exact position.', cell: (row) => km(row.distance_km) },
  ];
  return el('div', { class: 'panel span-2' },
    el('h3', {}, 'Links and routes',
      el('span', { class: 'muted', text: `from neighbor reports and traceroutes, last ${routes.window_hours} h` })),
    el('div', { class: 'route-tiles' },
      tile('Longest route segment',
        longest ? km(longest.distance_km) : '-',
        longest ? `${longest.from.display_name} to ${longest.to.display_name}` : 'No traceroute segment with two exact positions.',
        'The longest single hop of any traceroute this node took part in.'),
      tile('Furthest node that heard it', heardBy ? km(heardBy.distance_km) : '-',
        heardBy ? `${heardBy.display_name}${heardBy.best_snr != null ? `, ${round(heardBy.best_snr, 1)} dB` : ''}` : noDistance),
      tile('Furthest node it heard', heard ? km(heard.distance_km) : '-',
        heard ? `${heard.display_name}${heard.best_snr != null ? `, ${round(heard.best_snr, 1)} dB` : ''}` : noDistance),
      tile('Hops to the nearest gateway', depth.median == null ? '-' : String(depth.median),
        depth.packets
          ? `typical, over ${count(depth.packets)} packets: ${depth.counts.map((item) => `${item.hops} hop${item.hops === 1 ? '' : 's'} ${count(item.packets)}`).join(', ')}`
          : 'No other gateway heard it in the window.',
        'The fewest hops any gateway saw each packet use. Its own uploads are left out.')),
    el('p', { class: 'muted' },
      'Distances need an exact position at both ends. A rounded position can be kilometres out, so such pairs are left out'
      + (routes.coarse_excluded ? ` (${count(routes.coarse_excluded)} segments here).` : '.')
      + (routes.trace_limit_reached ? ` Only the newest ${count(routes.traces_read)} traceroutes were read.` : '')),
    el('div', { class: 'grid two' },
      el('div', { class: 'route-list' },
        el('h4', { text: `Who hears it (${count(routes.heard_by.length)})` }),
        expandingTable(columns, routes.heard_by, 'No node reports hearing it in the window.', { noun: 'nodes' })),
      el('div', { class: 'route-list' },
        el('h4', { text: `Who it hears (${count(routes.hears.length)})` }),
        expandingTable(columns, routes.hears, 'It reports hearing no node in the window.', { noun: 'nodes' }))));
}

/* --- Packet timeline (#54) ---------------------------------------- */

const TIMELINE_STEP = 50;
/* The observation sorts need a window of a week or less. See
 * `node_packets` in routes/nodes.py. */
const TIMELINE_SEEN_SORTS = new Set(['hops', 'gateways', 'snr', 'rssi']);
const TIMELINE_SEEN_MAX_HOURS = 168;
let timeline = null;

function resetTimeline(nodeId) {
  timeline = { nodeId, sort: 'time', order: 'desc', offset: 0, direction: 'sent', portnum: '', channel: '' };
}

async function drawTimeline(target, nodeId, hours, types) {
  if (!timeline || timeline.nodeId !== nodeId) resetTimeline(nodeId);
  const state = timeline;
  const seenSortable = Number(hours) <= TIMELINE_SEEN_MAX_HOURS;
  if (!seenSortable && TIMELINE_SEEN_SORTS.has(state.sort)) Object.assign(state, { sort: 'time', order: 'desc' });
  const params = new URLSearchParams({
    hours: String(hours), limit: String(TIMELINE_STEP), offset: String(state.offset),
    sort: state.sort, order: state.order, direction: state.direction,
  });
  if (state.portnum) params.set('portnum', state.portnum);
  if (state.channel) params.set('channel', state.channel);

  const redraw = () => drawTimeline(target, nodeId, hours, types);
  const response = await fetch(`api/nodes/${encodeURIComponent(nodeId)}/packets?${params}`)
    .catch((error) => error);
  const body = el('div', {});
  let rows = [];
  let total = 0;
  if (response instanceof Error || !response.ok) {
    body.append(failure(new Error('Cannot load the packets.')));
  } else {
    rows = await response.json();
    total = Number(response.headers.get('X-Total-Count') || rows.length);
  }

  const sortState = { key: state.sort, order: state.order };
  const onSort = (key, order) => { Object.assign(state, { sort: key, order, offset: 0 }); redraw(); };
  const sortable = (key) => (TIMELINE_SEEN_SORTS.has(key) && !seenSortable
    ? {} : { sort: key, sortState, onSort });
  const heard = state.direction === 'heard';
  const packetHref = (row) => `#packet/${encodeURIComponent(row.from_node)}/${row.packet_id}`;
  const columns = [
    { label: 'Time', ...sortable('time'), cell: (row) => el('a', { class: 'linky', href: packetHref(row), title: stamp(row.seen_at), text: stamp(row.seen_at) }) },
    heard ? { label: 'From', cell: (row) => nodeChip({ node_id: row.from_node, display_name: row.from_name }) } : null,
    { label: 'Type', ...sortable('type'), hint: 'What the packet carried: a position, telemetry, a message, and so on.', cell: (row) => portnumCell(row.portnum) },
    { label: 'To', ...sortable('to'), hint: 'Everyone for a broadcast, or the one node it was addressed to.', cell: (row) => toLabel(row) },
    { label: 'Channel', ...sortable('channel'), cell: (row) => row.channel || '-' },
    { label: 'Hops', num: true, ...sortable('hops'), hint: 'The fewest relays any gateway saw it use before it was uploaded.', cell: (row) => (row.fewest_hops == null ? '-' : String(row.fewest_hops)) },
    { label: 'Gateways', num: true, ...sortable('gateways'), hint: 'How many different gateways uploaded it, not counting the sender uploading its own packet.', cell: (row) => count(row.gateways) },
    { label: 'SNR', num: true, ...sortable('snr'), hint: 'The best signal at a gateway that heard it with no hop used. A relayed reading belongs to the last relay, so it is not shown.', cell: (row) => snrCell(row.direct_snr) },
    { label: 'RSSI', num: true, ...sortable('rssi'), cell: (row) => (row.direct_rssi == null ? '-' : `${row.direct_rssi} dBm`) },
    { label: 'Size', num: true, ...sortable('size'), cell: (row) => (row.size_bytes == null ? '-' : `${row.size_bytes} B`) },
  ].filter(Boolean);

  const typeSelect = el('select', { 'aria-label': 'Packet type', onchange: (event) => { Object.assign(state, { portnum: event.target.value, offset: 0 }); redraw(); } },
    el('option', { value: '', text: 'Every type' }),
    types.map((type) => el('option', { value: type, text: portnumLabel(type), selected: type === state.portnum })));
  const directionSelect = el('select', { 'aria-label': 'Direction', onchange: (event) => { Object.assign(state, { direction: event.target.value, offset: 0 }); redraw(); } },
    el('option', { value: 'sent', text: 'Sent by this node', selected: !heard }),
    el('option', { value: 'heard', text: 'Heard by it, as a gateway', selected: heard }));
  const channelInput = el('input', { type: 'search', placeholder: 'Channel', 'aria-label': 'Channel', value: state.channel,
    onchange: (event) => { Object.assign(state, { channel: event.target.value.trim(), offset: 0 }); redraw(); } });

  const first = total ? state.offset + 1 : 0;
  const last = state.offset + rows.length;
  const pager = el('p', { class: 'more-wrap' },
    el('span', { class: 'muted', text: total ? `${count(first)} to ${count(last)} of ${count(total)}` : '' }),
    state.offset > 0 ? el('button', { class: 'more', type: 'button', text: 'Newer', onclick: () => { state.offset = Math.max(0, state.offset - TIMELINE_STEP); redraw(); } }) : null,
    last < total ? el('button', { class: 'more', type: 'button', text: 'Older', onclick: () => { state.offset += TIMELINE_STEP; redraw(); } }) : null);

  if (!body.childNodes.length) {
    body.append(el('div', { class: 'table-wrap' }, table(columns, rows,
      heard ? 'It uploaded no packet from another node in the window.' : 'It sent no packet in the window that matches.',
      { rowHref: packetHref })));
  }
  replace(target,
    el('h3', {}, 'Packet timeline', el('span', { class: 'muted', text: `last ${heard ? Math.min(Number(hours), TIMELINE_SEEN_MAX_HOURS) : hours} h` })),
    el('p', { class: 'muted' },
      'A packet is one transmission: a position, a reading, a message, or a routine announcement. '
      + 'Open a row to see what it carried and which gateways heard it.'
      + (seenSortable ? '' : ' Sorting by hops, gateways or signal needs a window of 7 days or less: choose one above.')),
    el('div', { class: 'controls' }, directionSelect, typeSelect, channelInput),
    body, pager);
  markScrollableTables(target);
  revealHints(target);
}

async function loadNodeDetail(nodeId) {
  const page = $('[data-page="node"]');
  const hours = $('[data-node-hours]', page).value || '720';
  const body = $('[data-node-body]', page);
  replace(body, el('p', { class: 'loading', text: 'Loading' }));

  const detail = await get(`api/nodes/${encodeURIComponent(nodeId)}/detail?hours=${hours}`)
    .catch((error) => error);
  if (detail instanceof Error) {
    replace(body, failure(detail));
    return;
  }
  const node = detail.node;

  replace($('[data-node-title]', page),
    el('h2', { text: node.display_name }),
    el('p', { class: 'sub' },
      el('code', { text: node.node_id }),
      node.short_name ? ` - ${node.short_name}` : '',
      ` - heard ${ago(node.last_heard)} ago`));

  const link = $('[data-node-graph-link]', page);
  link.href = detail.graph.node_graph;
  link.hidden = false;

  const signalPanel = el('div', { class: 'panel span-2' },
    el('h3', {}, 'Direct link signal over time',
      el('span', { class: 'muted', text: 'from neighbor reports' })),
    el('div', { class: 'chart', 'data-signal-chart': '' }));

  /*
   * Short panels first, long ones after.
   *
   * Neighbours and Heard by are tables that grow with the mesh, and
   * putting them among the first cells pushed the identity, the device
   * and the activity of the node — the things somebody opening the page
   * came for — below the fold on a busy node. Both are capped at five
   * rows now and say how many more there are.
   */
  const health = el('div', { class: 'panel' }, el('p', { class: 'loading', text: 'Loading health checks' }));
  const routes = el('div', { class: 'panel span-2' },
    el('h3', { text: 'Links and routes' }), el('p', { class: 'loading', text: 'Loading' }));
  const history = el('div', { class: 'grid two span-2 history-grid' });
  const packets = el('div', { class: 'panel span-2 timeline' },
    el('h3', { text: 'Packet timeline' }), el('p', { class: 'loading', text: 'Loading' }));

  /*
   * The four short panels get a row of their own (#102).
   *
   * They were in the same `grid two` as everything else, whose track
   * minimum is 24 rem -- so on most laptops only two fitted and they
   * took two rows plus a screen of scrolling to see four short lists.
   * A narrower minimum lets all four sit side by side when there is
   * room and still fall back to two, then one, when there is not.
   */
  /*
   * Health sits under Device, inside the first row (#193.3).
   *
   * Device is short and Activity sets the row's height -- 473 px at
   * 1440 wide -- so there was empty space under Device while Health
   * ran as a full-width strip below the row.
   *
   * The pair share one grid track, which keeps #95's requirement that
   * the Health summary is on the first screen and in fact moves it
   * UP: it was measured at y=631 at 1440x900 and lands higher here,
   * because it starts where Device ends rather than where the whole
   * row ends.
   *
   * When the grid falls to fewer columns the pair travels together, so
   * a phone gets Device immediately followed by its Health rather than
   * the two separated by Activity and Weather.
   */
  const summary = el('div', { class: 'grid summary-row' },
    identityPanel(node),
    el('div', { class: 'summary-stack' }, devicePanel(detail), health),
    activityPanel(detail),
    weatherPanel(detail));

  /*
   * Identity and device first, health after (#95).
   *
   * The seven health cards used to open the page and fill the screen
   * above them, so somebody checking the battery scrolled past a full
   * assessment to reach it. Everything they showed is now behind
   * "View all checks".
   *
   * The summary sits between the identity row and the map, and that
   * position is measured rather than chosen. #95 asks for a first
   * screen that shows identity and device AND summarises health; #103
   * asks for the map "below the first row of panels". With the summary
   * inside the grid under the map, health landed at y=1069 on a
   * 1440x900 laptop and y=1081 at 1680x1050 -- below the fold on both,
   * so the page satisfied #103 and only half of #95. One panel's worth
   * of prose above the map costs the map nothing and puts the health
   * line on the first screen, which is what the issue asked for.
   */
  // `health` is inside `summary` now, so it is not passed again here.
  replace(body, summary, nodeMapPanel(detail), el('div', { class: 'grid two' },
    routes,
    history,
    messagesPanel(detail),
    neighborPanel(detail.neighbors, detail.window_hours),
    heardByPanel(detail.heard_by),
    signalPanel,
    packets));

  const id = encodeURIComponent(nodeId);
  const [gaps, historyData, routesData] = await getAll([
    `api/nodes/${id}/gaps`,
    `api/nodes/${id}/history?hours=${hours}`,
    `api/nodes/${id}/routes?hours=${hours}`,
  ]);
  // The page may have moved on to another node while these loaded.
  if (currentNodeId !== nodeId) return;
  health.replaceWith(healthPanel(gaps, detail, issuesPanel(gaps)));
  routes.replaceWith(routesPanel(routesData));
  drawNodeHistory(history, historyData);
  const types = (detail.activity.by_portnum || []).map((row) => row.portnum);
  await Promise.all([
    drawSignalChart($('[data-signal-chart]', body), nodeId, hours),
    drawTimeline(packets, nodeId, hours, types),
  ]);
}

PAGES.node = async () => {
  if (currentNodeId) await loadNodeDetail(currentNodeId);
};

/* --- Chat ------------------------------------------------------ */

/** The fragment of one channel's page, in one view. */
function chatHref(channel, view) {
  return `#chat/${encodeURIComponent(channel)}${view === 'table' ? '/table' : ''}`;
}

/*
 * One channel on the overview.
 *
 * "View all" used to expand the list in place, which is not a page: it
 * could not be linked, and it had no room beside a message for anything
 * but the message. It opens the channel's own page now. A channel with
 * no name has nothing to address it by, so it keeps the old list.
 */
function channelSection(section) {
  const named = Boolean(section.channel);
  const shown = section.messages.slice(0, 5);
  return el('div', { class: 'panel' },
    el('h3', { class: 'channel-head' },
      named
        ? el('a', { class: 'title', href: chatHref(section.channel), text: section.label })
        : el('span', { class: 'title', text: section.label }),
      el('span', { class: 'muted', text: `${count(section.count)} messages - last ${ago(section.last_seen)} ago` })),
    !section.messages.length
      ? empty('No messages in the window.')
      : named
        ? [
            el('ul', { class: 'messages' }, shown.map((message) => messageItem(message))),
            section.count > shown.length
              ? el('p', { class: 'more-wrap' },
                  el('a', { class: 'more', href: chatHref(section.channel),
                    text: `Open all ${count(section.count)} messages` }))
              : null,
          ]
        : expandingList(section.messages, (message) => messageItem(message), { limit: 5 }));
}

/*
 * One channel's page: `#chat/<channel>`, or `#chat/<channel>/table`,
 * either of them carrying `?from=…&to=…`.
 */
/*
 * The chat page's own state (§6.1).
 *
 * `CHAT_STEP`/`CHAT_MAX` are gone with the "Load older" button. That
 * button raised a LIMIT and re-asked for the whole list from the newest
 * message down, which is why it stopped at 500: every press re-fetched
 * everything it already had. Paging backwards with `before` asks only for
 * what is missing, so there is no ceiling to apologise for and the reader
 * scrolls instead of pressing.
 */
const CHAT_PAGE = 100;
/* How close to the top starts the next load. About a screen, so the rows
   are there before the reader reaches the end of what is drawn. */
const CHAT_NEAR_TOP = 240;
/*
 * How close to the bottom still counts as "at the bottom".
 *
 * Not zero. A reader who has scrolled a few pixels off the end is still
 * reading the newest messages and still wants to be carried along; a
 * strict test would strand them the moment a trackpad overshot.
 */
const CHAT_AT_BOTTOM = 48;
const CHAT_DEFAULT_HOURS = 168;

let currentChatChannel = null;
let chatView = 'chat';
/* Newest first, the order the API answers in. The reading view reverses
   at draw time; the table view uses it as it stands. One array, so the two
   views cannot disagree about what was loaded. */
let chatRows = [];
let chatOldestReached = false;
let chatBusy = false;
/* Which channel and range `chatRows` holds, so a changed channel or range
   starts again rather than mixing two conversations together. */
let chatRowsKey = null;

/** A Date from an address parameter, or null for anything unusable. */
function chatDate(raw) {
  if (!raw) return null;
  const when = new Date(raw);
  return Number.isNaN(when.getTime()) ? null : when;
}

/*
 * The range the address names, or null when it names none.
 *
 * Guarded to `#chat` on purpose. Every page keeps its settings after a
 * `?` in the one fragment, so reading `from`/`to` without checking the
 * page would apply the map's or the planner's query to the chat -- the
 * same bug the gaps page had when it read `?channel=` from another page's
 * link.
 */
function chatRangeFromAddress() {
  const hash = String(window.location.hash || '');
  if (!/^#chat(\/|\?|$)/.test(hash)) return null;
  const at = hash.indexOf('?');
  if (at < 0) return null;
  const params = new URLSearchParams(hash.slice(at + 1));
  const from = chatDate(params.get('from'));
  const to = chatDate(params.get('to'));
  if (!from && !to) return null;
  /*
   * Backwards is a typo, not a request for nothing. Swapped rather than
   * refused, because an empty page with a valid-looking range in the
   * address reads as "this channel is silent" -- a claim about the mesh
   * rather than about the form.
   */
  if (from && to && from > to) return { from: to, to: from };
  return { from, to };
}

/**
 * The range in force.
 *
 * `to: null` means "up to now", and it is not the same as `to: new
 * Date()`. A range with an explicit end is HISTORY: live must not append
 * to it, because a message that arrives now is outside what the reader
 * asked to see. A null end is an open one and live keeps filling it.
 */
function chatRange() {
  return chatRangeFromAddress()
    || { from: new Date(Date.now() - CHAT_DEFAULT_HOURS * 3600000), to: null };
}

/** True when the range has an end, so nothing new belongs in it. */
function chatRangeIsHistory(range) {
  return Boolean(range.to);
}

/*
 * `datetime-local` wants "YYYY-MM-DDTHH:mm" in LOCAL time.
 *
 * `toISOString` is UTC and would show a reader in Arizona a time seven
 * hours off their own clock, which looks like the control ignoring them.
 */
function chatLocalValue(when) {
  if (!when) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`
    + `T${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

/** Put a range in the address, so a shared link carries it. */
function chatWriteRange(from, to) {
  const channel = currentChatChannel;
  const base = `chat${channel ? `/${encodeURIComponent(channel)}` : ''}`
    + `${chatView === 'table' ? '/table' : ''}`;
  const params = new URLSearchParams();
  if (from) params.set('from', from.toISOString());
  if (to) params.set('to', to.toISOString());
  const query = params.toString();
  const next = `#${base}${query ? `?${query}` : ''}`;
  if (window.location.hash === next) return false;
  /*
   * `replaceState`, not an assignment. Changing a range is refining one
   * view, not travelling somewhere, so it must not put a stop in the back
   * button for every adjustment -- and an assignment to `location.hash`
   * fires the router, which would redraw the page underneath the control
   * that is still being used.
   */
  window.history.replaceState(null, '', next);
  return true;
}

/** Ask the API for one page of a channel. Newest first. */
async function chatFetch(channel, { since, before, limit = CHAT_PAGE }) {
  const params = new URLSearchParams({
    channel, limit: String(limit), metrics: 'true',
  });
  if (since) params.set('since', since.toISOString());
  if (before) params.set('before', before.toISOString());
  return get(`api/chat?${params}`);
}

/** The key `chatRows` was filled for. A change means start again. */
function chatKey(channel, range) {
  return [
    channel || '',
    range.from ? range.from.toISOString() : '',
    range.to ? range.to.toISOString() : '',
  ].join('|');
}


/** How a message travelled, in a few short facts. */
function messageMetrics(metrics) {
  if (!metrics) {
    return el('dl', { class: 'msg-metrics' },
      el('dt', { text: 'Record' }), el('dd', { class: 'muted', text: 'no packet stored' }));
  }
  const heard = metrics.gateway_count
    ? `${count(metrics.gateway_count)} gateway${metrics.gateway_count === 1 ? '' : 's'}`
      + (metrics.direct_gateways ? `, ${count(metrics.direct_gateways)} direct` : '')
    : 'only its own upload';
  return el('dl', { class: 'msg-metrics' },
    el('dt', { text: 'Heard by' }), el('dd', { text: heard }),
    el('dt', { text: 'Fewest hops' }),
    el('dd', { text: metrics.fewest_hops == null ? '-' : String(metrics.fewest_hops) }),
    el('dt', { text: 'Best direct' }),
    el('dd', {},
      snrCell(metrics.best_direct_snr),
      metrics.best_direct_rssi == null ? null : ` ${metrics.best_direct_rssi} dBm`),
    metrics.want_ack ? el('dt', { text: 'Ack' }) : null,
    metrics.want_ack ? el('dd', { text: 'asked for' }) : null);
}

/** The reading view: each message with its metrics beside it. */
function chatReading(messages) {
  return el('ul', { class: 'messages chat-reading' }, messages.map((message) => {
    const item = messageItem(message);
    const text = el('div', { class: 'msg-text' }, ...item.childNodes);
    item.append(text, messageMetrics(message.metrics));
    return item;
  }));
}

const METRICS_HINT = 'Gateways count distinct gateways, never uploads, and never the sender '
  + 'uploading its own packet. Only a gateway that heard it with no hop used measures the '
  + 'sender\u2019s own signal. Whether an acknowledgement came back is not recorded.';

/** The scanning view: one row per message. */
function chatTable(messages) {
  const metric = (message, key) => (message.metrics ? message.metrics[key] : null);
  return el('div', { class: 'table-wrap' }, table([
    {
      label: 'Time',
      cell: (message) => (message.packet_id == null
        ? clock(message.seen_at)
        : el('a', {
            class: 'linky',
            href: `#packet/${encodeURIComponent(message.from_node)}/${message.packet_id}`,
            title: stamp(message.seen_at),
            text: clock(message.seen_at),
          })),
    },
    { label: 'From', cell: (message) => nodeChip({ node_id: message.from_node, display_name: message.from_name }) },
    { label: 'Message', wrap: true, cell: (message) => messageBody(message.body) },
    { label: 'Gateways', num: true, hint: METRICS_HINT, cell: (message) => count(metric(message, 'gateway_count') ?? 0) },
    { label: 'Direct', num: true, cell: (message) => count(metric(message, 'direct_gateways') ?? 0) },
    {
      label: 'Hops',
      num: true,
      hint: 'The fewest relays any gateway saw this message use.',
      cell: (message) => {
        const hops = metric(message, 'fewest_hops');
        return hops == null ? '-' : String(hops);
      },
    },
    { label: 'SNR', num: true, cell: (message) => snrCell(metric(message, 'best_direct_snr')) },
    {
      label: 'RSSI',
      num: true,
      cell: (message) => {
        const rssi = metric(message, 'best_direct_rssi');
        return rssi == null ? '-' : `${rssi} dBm`;
      },
    },
    { label: 'Ack', cell: (message) => (metric(message, 'want_ack') ? 'asked' : '-') },
    {
      label: 'Reactions',
      num: true,
      cell: (message) => count((message.reactions || [])
        .reduce((sum, reaction) => sum + (reaction.count || 0), 0)),
    },
  ], messages, 'No messages in the window.'));
}

/** Set the page head for the overview or for one channel. */
/*
 * The head, and the count beside the title (§6.1).
 *
 * The sentence under the title used to read "The newest 100 messages in
 * the window, newest first." Will asked for it to go and for the number to
 * ride beside the channel name instead, which saves a line of height on
 * every visit and puts the figure where the eye already is.
 *
 * The count says `shown` while older messages remain and `messages` only
 * when the range is exhausted, and that distinction is the honest half. A
 * reading view pages backwards, so until it reaches the end of the range
 * it does not KNOW the total -- printing "142 messages" over the first 142
 * of 900 would be a confident false statement about the mesh, which is the
 * failure this repository keeps a standing rule against.
 */
function chatHead(page, channel, sub) {
  $('[data-chat-title]', page).textContent = channel || 'Chat';
  const subtitle = $('[data-chat-sub]', page);
  subtitle.textContent = sub || '';
  subtitle.hidden = !sub;
  $('[data-chat-back]', page).hidden = !channel;
  const views = $('[data-chat-view]', page);
  views.hidden = !channel;
  for (const button of $$('[data-chat-view-choice]', views)) {
    button.setAttribute('aria-pressed', String(button.dataset.chatViewChoice === chatView));
  }
  const tally = $('[data-chat-count]', page);
  if (tally) {
    if (!channel) {
      tally.textContent = '';
      tally.hidden = true;
    } else {
      tally.hidden = false;
      tally.textContent = chatOldestReached
        ? `${count(chatRows.length)} message${chatRows.length === 1 ? '' : 's'}`
        : `${count(chatRows.length)} shown`;
      tally.title = chatOldestReached
        ? 'Every message in the range is loaded.'
        : 'Older messages are still to load. Scroll up for more.';
    }
  }
}

/** Fill the two range boxes from the range in force. */
function chatDrawRange(page) {
  const range = chatRange();
  const from = $('[data-chat-from]', page);
  const to = $('[data-chat-to]', page);
  /*
   * Skipped while the box has focus. Rewriting the value under somebody
   * who is part-way through typing a date moves their caret and drops
   * what they had entered.
   */
  if (from && document.activeElement !== from) from.value = chatLocalValue(range.from);
  if (to && document.activeElement !== to) to.value = chatLocalValue(range.to);
}

/** Is the reader at the newest end? */
function chatAtBottom(scroller) {
  if (!scroller) return true;
  return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= CHAT_AT_BOTTOM;
}

/*
 * Draw the reading view: oldest at the top, newest at the bottom.
 *
 * `chatRows` is newest-first, so it is reversed here rather than stored
 * the other way round -- the API, the table view and the paging cursor all
 * think newest-first, and keeping one order in state means only the
 * drawing has to know about the other.
 */
function chatDrawRows(scroller) {
  const oldestFirst = [...chatRows].reverse();
  replace(scroller, [
    chatOldestReached
      ? el('p', { class: 'chat-edge muted', text: 'The start of this range.' })
      : el('p', { class: 'chat-edge muted', 'data-chat-older': '', text: 'Scroll up for older messages…' }),
    chatReading(oldestFirst),
  ]);
}

/*
 * Load the page of messages older than what is held, keeping the reader's
 * place.
 *
 * THE WHOLE POINT IS THE THREE LINES AROUND `mutate`. Rows added above the
 * viewport push everything down by their own height, so a list that simply
 * prepends jumps away from whatever was being read -- every time, and worse
 * the more it loads. The height before and after is measured and the
 * scroll offset moved by the difference, in the same frame, so the row
 * under the reader's eye stays under it.
 */
async function chatLoadOlder(page) {
  if (chatBusy || chatOldestReached || !currentChatChannel) return;
  const scroller = $('[data-chat-scroll]', page);
  if (!scroller) return;
  const oldest = chatRows.length ? chatRows[chatRows.length - 1] : null;
  if (!oldest) return;
  const range = chatRange();
  chatBusy = true;
  try {
    const older = await chatFetch(currentChatChannel, {
      since: range.from,
      before: new Date(oldest.seen_at),
    });
    if (!Array.isArray(older) || !older.length) {
      chatOldestReached = true;
    } else {
      /*
       * Dropped by id rather than trusted. `before` is exclusive on
       * `seen_at`, and two messages can share a timestamp to the
       * microsecond the column stores -- so the same row can arrive twice
       * and appear twice in the list.
       */
      const held = new Set(chatRows.map(chatRowKey));
      const fresh = older.filter((row) => !held.has(chatRowKey(row)));
      if (!fresh.length) chatOldestReached = true;
      else chatRows = [...chatRows, ...fresh];
      if (older.length < CHAT_PAGE) chatOldestReached = true;
    }
    const before = scroller.scrollHeight;
    const top = scroller.scrollTop;
    chatDrawRows(scroller);
    scroller.scrollTop = top + (scroller.scrollHeight - before);
    chatHead(page, currentChatChannel, '');
  } catch (error) {
    if (window.console) window.console.warn('could not load older messages', error);
  } finally {
    chatBusy = false;
  }
}

/*
 * A row's identity.
 *
 * `packet_id` is absent for a message with no packet stored, so it cannot
 * be the whole key on its own; the sender and the timestamp separate the
 * rest. Used to de-duplicate at both ends of the list.
 */
function chatRowKey(row) {
  return `${row.packet_id ?? ''}|${row.from_node_id ?? row.from_node_num ?? ''}|${row.seen_at ?? ''}`;
}

/*
 * Add whatever arrived since the newest message held (the live tick).
 *
 * Two rules, and both are about not fighting the reader:
 *
 * - a range with an END is history and gets nothing appended, because a
 *   message that arrives now is outside what was asked for;
 * - the view follows the newest message ONLY if it was already at the
 *   bottom. Somebody reading back through yesterday must not be yanked to
 *   the end because a radio keyed up.
 */
async function chatAppendNew() {
  const page = $('[data-page="chat"]');
  if (!page || !currentChatChannel || chatView !== 'chat' || chatBusy) return;
  const range = chatRange();
  if (chatRangeIsHistory(range)) return;
  const scroller = $('[data-chat-scroll]', page);
  if (!scroller) return;
  const newest = chatRows.length ? chatRows[0] : null;
  chatBusy = true;
  try {
    const rows = await chatFetch(currentChatChannel, {
      since: newest ? new Date(newest.seen_at) : range.from,
      before: null,
    });
    if (!Array.isArray(rows) || !rows.length) return;
    const held = new Set(chatRows.map(chatRowKey));
    const fresh = rows.filter((row) => !held.has(chatRowKey(row)));
    if (!fresh.length) return;
    const wasAtBottom = chatAtBottom(scroller);
    chatRows = [...fresh, ...chatRows];
    const top = scroller.scrollTop;
    chatDrawRows(scroller);
    if (wasAtBottom) scroller.scrollTop = scroller.scrollHeight;
    // Rows went on at the BOTTOM, so nothing above the reader moved: the
    // offset is put back exactly as it was rather than corrected by a
    // height difference that did not happen above them.
    else scroller.scrollTop = top;
    chatHead(page, currentChatChannel, '');
  } catch (error) {
    if (window.console) window.console.warn('could not load new messages', error);
  } finally {
    chatBusy = false;
  }
}

async function chatChannelPage(page, channel) {
  const range = chatRange();
  const key = chatKey(channel, range);
  const body = $('[data-chat-body]', page);
  chatDrawRange(page);

  // A different channel or range is a different conversation.
  if (key !== chatRowsKey) {
    chatRows = [];
    chatOldestReached = false;
    chatRowsKey = key;
  }

  if (!chatRows.length) {
    const first = await chatFetch(channel, { since: range.from, before: range.to })
      .catch((error) => error);
    if (first instanceof Error) return replace(body, failure(first));
    chatRows = Array.isArray(first) ? first : [];
    if (chatRows.length < CHAT_PAGE) chatOldestReached = true;
  }

  if (chatView === 'table') {
    page.classList.remove('chat-full');
    chatHead(page, channel, '');
    return replace(body, el('div', { class: 'panel' },
      chatRows.length
        ? chatTable(chatRows)
        : empty('No messages on this channel in this range.')));
  }

  /*
   * `chat-full` makes the page a column the height of the viewport, with
   * the head outside the scroller. That is what pins the head: it is not
   * `position: sticky` but simply not inside the thing that scrolls, which
   * cannot come unstuck and needs no containing-block reasoning.
   */
  page.classList.add('chat-full');
  chatHead(page, channel, '');

  if (!chatRows.length) {
    return replace(body, el('div', { class: 'panel' },
      empty('No messages on this channel in this range.')));
  }

  const scroller = el('div', { class: 'chat-scroll', 'data-chat-scroll': '', tabindex: '0' });
  replace(body, scroller);
  chatDrawRows(scroller);
  // Opens at the newest message, like every other chat.
  scroller.scrollTop = scroller.scrollHeight;
  scroller.addEventListener('scroll', () => {
    if (scroller.scrollTop <= CHAT_NEAR_TOP) chatLoadOlder(page);
  }, { passive: true });
  return undefined;
}

PAGES.chat = async (page) => {
  if (currentChatChannel) return chatChannelPage(page, currentChatChannel);
  // The overview is an ordinary scrolling page, not the pinned chat.
  page.classList.remove('chat-full');
  chatHead(page, null,
    'One section for each detected channel on the preset chosen in the menu, grouped by what it '
    + 'is for. New names land in Custom.');
  /*
   * The overview counts a WINDOW, not a range.
   *
   * `/api/chat/overview` takes `hours` and nothing else, and widening it
   * to a pair of instants is a change to a shared endpoint for the sake of
   * a list of channel names. The span of the chosen range is used instead,
   * rounded up to the hour and clamped to what the endpoint accepts, so
   * the channel list covers at least what the reader asked for.
   *
   * Rounded UP deliberately: a list that showed slightly less than the
   * range would hide a channel whose only message sits near the edge.
   */
  const range = chatRange();
  const end = range.to ? range.to.getTime() : Date.now();
  const start = range.from ? range.from.getTime() : end - CHAT_DEFAULT_HOURS * 3600000;
  const spanHours = Math.ceil(Math.max(1, (end - start) / 3600000));
  const hours = String(Math.min(8760, spanHours));
  chatDrawRange(page);
  const body = $('[data-chat-body]', page);
  const data = await get(`api/chat/overview?hours=${hours}`).catch((error) => error);
  if (data instanceof Error) return replace(body, failure(data));
  if (!data.sections.length) {
    return replace(body, empty('No channels have stored messages. Text storage may be off.'));
  }

  const shown = SonoranPreset.channelsFor(data.sections);
  if (!shown.length) {
    return replace(body, empty(
      `No channels on ${SonoranLabels.presetLabel(SonoranPreset.current())} have stored messages.`));
  }

  const groups = new Map();
  for (const section of shown) {
    if (!groups.has(section.group)) groups.set(section.group, []);
    groups.get(section.group).push(section);
  }
  replace(body, [...groups.entries()].map(([group, sections]) =>
    el('div', { class: 'channel-group' },
      el('h3', { text: `${group} (${sections.length})` }),
      el('div', { class: 'grid two' }, sections.map(channelSection)))));
};

/*
 * The rule for which channels belong to the preset in force lives in
 * `preset.js`, as `SonoranPreset.channelsFor`. It is pure, so it is
 * tested directly rather than through this page.
 */


/* --- Weekly check-in ------------------------------------------- */

/*
 * Which nodes checked in, and how many weeks running (§6.3).
 *
 * The page used to be a list of weeks, each holding its messages. That
 * answered "what was said" and left "who takes part, and who has
 * stopped" to be worked out by eye across eight collapsed sections.
 *
 * Every number drawn here is a claim about a person's participation, so
 * three things are deliberate and none of them should be simplified
 * away.
 *
 * **The arithmetic is not in this file.** `api/chat/tagged` computes the
 * runs, because a run is longer than the 4, 8 or 26 weeks this page
 * shows and a browser counting the weeks it was handed would report a
 * 30-week run as 8. The endpoint reads a year past the window for
 * exactly that reason and flags a run it cannot see the start of.
 *
 * **The words are in `meshnet.js`.** They are pure and they are the part
 * that turns a missing figure into a false one, so they are tested on
 * their own in `tests/unit/js/meshnet_streak_cases.mjs`.
 *
 * **An absence is an observation.** "No message found", never "missed",
 * and the week in progress is never described as having broken anything.
 */
const MESHNET = window.SonoranMeshnet;

/*
 * The week range, formatted in UTC rather than in the mesh's own zone.
 *
 * This is the one place on the site that deliberately does NOT use
 * `DATE`, and the reason is that a week boundary is not a time -- it is
 * the definition the streak is counted on. `api/chat/tagged` starts a
 * week at Monday 00:00 UTC, which in Arizona is Sunday at 17:00, so
 * `DATE` printed the week beginning Monday 21 September as
 * "Sep 20 - Sep 27": eight days wide, starting on a Sunday, for a week
 * the server calls Monday to Sunday. Measured on the running page
 * before this was changed.
 *
 * Every other stamp on this page stays in Arizona time, because those
 * are moments somebody experienced. This one is a boundary, and the note
 * under the controls says where it falls in local terms -- which is
 * worth saying out loud, because a Sunday-evening net in Arizona lands
 * in the following UTC week.
 */
const WEEK_DATE = new Intl.DateTimeFormat(undefined, {
  month: 'short', day: 'numeric', timeZone: 'UTC',
});

/*
 * Where a UTC week boundary falls on the mesh's own clock.
 *
 * Derived, never written out. "Sunday at 5pm" is right for Arizona and
 * wrong for a deployment east of Greenwich, where Monday 00:00 UTC is
 * Monday morning -- and a hard-coded day would be wrong in a way that
 * reads perfectly.
 */
const WEEK_LOCAL = new Intl.DateTimeFormat(undefined, {
  weekday: 'long', hour: '2-digit', minute: '2-digit', timeZone: TZ,
});

/** One check-in: who, and how many weeks running. */
function checkInRow(entry, streaks) {
  const floor = streaks && streaks.floor_week
    ? WEEK_DATE.format(new Date(streaks.floor_week)) : null;
  return el('li', { class: 'check-in' },
    nodeChip(entry),
    el('span', {
      class: `streak${entry.streak_at_least ? ' bounded' : ''}`,
      title: MESHNET.streakDetail(entry, floor),
      text: MESHNET.streakWord(entry),
    }),
    /*
     * The message count, and only when it is more than one.
     *
     * Two messages in a week are still one check-in -- the unit is the
     * week -- so this sits well away from the streak chip. An earlier
     * sketch put them side by side and "2 messages / 1 week in a row"
     * read as a contradiction.
     */
    MESHNET.counted(entry.message_count) > 1
      ? el('span', { class: 'muted small', text: `${count(entry.message_count)} messages` })
      : null);
}

/** One node that took part last week and not in this one. */
function absenceRow(entry, inProgress) {
  const said = MESHNET.absenceWord(entry, inProgress);
  return el('li', { class: `absence ${said.tone}` },
    nodeChip(entry),
    el('span', { class: 'absent-word', text: said.text }),
    // Visible rather than a `title`: this is the sentence that keeps the
    // page honest about somebody who was simply switched off, and on a
    // phone there is no hover to find it in (#44 made the same call).
    el('span', { class: 'muted small', text: said.detail }));
}

function meshnetWeek(week, streaks, index) {
  const ends = new Date(new Date(week.week_end).getTime() - 1);
  const range = `${WEEK_DATE.format(new Date(week.week_start))} - ${WEEK_DATE.format(ends)}`;
  const messages = week.messages || [];
  return el('details', { class: 'week', open: index === 0 },
    el('summary', {},
      el('span', { class: 'range', text: range }),
      week.in_progress ? el('span', { class: 'in-progress', text: 'in progress' }) : null,
      el('span', { class: 'count', text: MESHNET.weekWord(week) })),
    el('div', {},
      (week.check_ins || []).length
        ? el('ul', { class: 'check-ins' },
            week.check_ins.map((entry) => checkInRow(entry, streaks)))
        : null,
      (week.not_seen || []).length
        ? el('div', { class: 'absences' },
            el('h4', { text: week.in_progress ? 'Checked in last week, not yet this week' : 'Checked in the week before, no message found in this one' }),
            el('ul', {}, week.not_seen.map((entry) => absenceRow(entry, week.in_progress))))
        : null,
      /*
       * A week with nobody in it says so here as well as in its heading.
       * These weeks are drawn at all because a gap that is simply absent
       * from the list reads as a week that never happened.
       */
      !(week.check_ins || []).length && !(week.not_seen || []).length
        ? empty('No message carrying the tag was found in this week.') : null,
      messages.length
        ? el('ul', { class: 'messages' },
            messages.map((message) => messageItem(message, { showChannel: true })))
        : null,
      // The message list is capped by the endpoint's `limit` and the
      // count beside it is measured, so on a busy week they disagree.
      // AGENTS.md 9.19: a row limit must not decide what the page says
      // exists, so the page names the limit instead of hiding it.
      MESHNET.messagesTruncated(week)
        ? el('p', { class: 'muted small', text: `Showing ${count(week.messages_shown)} of ${count(week.message_count)} messages.` })
        : null));
}

PAGES.meshnet = async (page) => {
  const tag = ($('[data-meshnet-tag]', page).value || 'meshnet').replace(/^#/, '');
  const weeks = $('[data-meshnet-weeks]', page).value || '8';
  const body = $('[data-meshnet-body]', page);
  const note = $('[data-meshnet-note]', page);
  const data = await get(`api/chat/tagged?tag=${encodeURIComponent(tag)}&weeks=${weeks}`)
    .catch((error) => error);
  if (data instanceof Error) {
    replace(note);
    return replace(body, failure(data));
  }

  /*
   * "Nothing to compute from" and "nobody checked in" are two different
   * sentences, and the plan named this as its own risk: message text
   * storage can be off entirely, in which case there will never be a
   * check-in to find and an empty list would be a lie. The server says
   * which case this is; the page must not average them into one blank.
   */
  const blank = MESHNET.noAssessmentWord(data);
  if (blank) {
    replace(note);
    return replace(body, empty(blank));
  }

  /*
   * How far the runs were counted, and what an unfinished week means.
   *
   * Both belong in front of the reader rather than in a tooltip: the
   * first is the limit of the evidence, and the second is the difference
   * between "has stopped taking part" and "it is only Tuesday".
   */
  replace(note,
    el('span', { text: `A week runs Monday to Sunday in UTC, which on this mesh's clock begins ${WEEK_LOCAL.format(new Date(data.streaks.current_week))}. ` }),
    el('span', { text: `Runs are counted back to ${WEEK_DATE.format(new Date(data.streaks.floor_week))}; a run marked + began before that. ` }),
    el('span', { text: 'The current week is still open, so a node with no message yet has not broken its run.' }));

  if (!data.weeks.length) {
    return replace(body, empty(`No message carries ${data.tag} in the last ${count(data.window_weeks)} weeks.`));
  }
  replace(body, data.weeks.map((week, index) => meshnetWeek(week, data.streaks, index)));
};

/*
 * Redraw a live table without throwing away the rows that did not
 * change.
 *
 * Five pages replace a whole table every 15 seconds. On the firehose
 * that is 150 rows of 10 columns, four times a minute -- and a
 * `replaceChildren` takes the reader's scroll position and any text
 * selection with it. You cannot read the firehose and select a packet
 * ID at the same time: the selection is gone before you finish.
 *
 * Skipping identical redraws is not enough, and I measured that before
 * settling on this. The mesh is busy: a poll almost always brings a
 * new packet, the signature changes, and a whole-table rebuild happens
 * anyway. A selection still died every 15 seconds.
 *
 * So rows are matched by key. A row whose key is already on screen
 * keeps its existing DOM node -- moved if its position changed, never
 * recreated -- and a selection anchored inside it survives, because
 * the text nodes it points at are the same objects. Only genuinely new
 * rows are built, and only departed ones are removed.
 *
 * The scroll offsets are restored as well, for the case where the
 * table shortens under the reader.
 */
function redrawLiveTable(target, rows, keyOf, build) {
  if (!target) return;
  const wrap = target.querySelector('.table-wrap');
  const held = wrap ? { left: wrap.scrollLeft, top: wrap.scrollTop } : null;

  const body = target.querySelector('tbody');

  const fresh = build();

  // No table yet, or the shape changed (a filter emptied it, an error
  // replaced it). Nothing to reconcile against.
  const freshBody = fresh.querySelector ? fresh.querySelector('tbody') : null;
  // Key the rows on the way in, including the very first render. The
  // first draft did not, so the next poll found nothing to match
  // against, treated every row as new, and destroyed the selection
  // exactly as before -- with more code.
  if (freshBody) {
    const keys = rows.map((row) => String(keyOf(row)));
    Array.from(freshBody.rows).forEach((row, index) => {
      if (keys[index] != null) row.dataset.rowKey = keys[index];
    });
  }
  if (!body || !freshBody) {
    replace(target, fresh);
    const after = target.querySelector('.table-wrap');
    if (after && held) { after.scrollLeft = held.left; after.scrollTop = held.top; }
    return;
  }

  const existing = new Map();
  for (const row of Array.from(body.rows)) {
    const key = row.dataset.rowKey;
    if (key) existing.set(key, row);
  }

  const wanted = Array.from(freshBody.rows);
  const keys = rows.map((row) => String(keyOf(row)));
  const ordered = [];
  wanted.forEach((row, index) => {
    const key = keys[index];
    const kept = key != null ? existing.get(key) : null;
    if (kept) {
      existing.delete(key);
      ordered.push(kept);
    } else {
      if (key != null) row.dataset.rowKey = key;
      ordered.push(row);
    }
  });

  // Whatever is left in `existing` has fallen off the end of the
  // window.
  for (const gone of existing.values()) gone.remove();

  /*
   * Touch only the rows that actually have to move.
   *
   * `replaceChildren(...ordered)` reuses the right nodes but MOVES
   * every one of them, and a move removes and reinserts the node,
   * which collapses any selection inside it. Measured: the nodes
   * survived the poll and the selection still died.
   *
   * This feed is newest-first, so a poll prepends. Inserting a new row
   * BEFORE an existing one does not move the existing one, so a reader
   * partway down keeps both their place and their selection.
   */
  ordered.forEach((row, index) => {
    const current = body.children[index];
    if (current !== row) body.insertBefore(row, current || null);
  });
  while (body.children.length > ordered.length) body.lastElementChild.remove();

  /*
   * Deliberately NO manual scroll anchoring here.
   *
   * Because the mutation above is minimal, the browser's own scroll
   * anchoring keeps the reader on the same row for free. An earlier
   * draft measured the row's offset and called scrollBy() to correct
   * it, which stacked on top of the browser's correction and drifted
   * 280px -- WORSE than the 82px of doing nothing. Without it the same
   * harness measures 0-1px. Leave this alone.
   */

  if (wrap && held) { wrap.scrollLeft = held.left; wrap.scrollTop = held.top; }
}

/* --- Firehose --------------------------------------------------- */

/*
 * The firehose filter lives in the address (§5.1, for §7.1).
 *
 * `#firehose?type=POSITION_APP&hours=24`. It is in the fragment and not
 * in a variable because a filtered firehose has to be something you can
 * be SENT: the dashboard's packet-types chart links into it, and a link
 * that only works if you click it from one particular page is not a
 * link. The fragment also survives a reload and never rides on a
 * `Referer` (AGENTS.md 9.9.1), which is why the planner's share link and
 * `#chat/<channel>` are built the same way.
 *
 * `type` carries the WIRE value -- `POSITION_APP`, or a bare number --
 * and not the readable label. The request is built from it directly, so
 * it never depends on `portnumWire` round-tripping a phrase back into an
 * enum. The box shows the label; the URL carries the fact.
 *
 * `hours` is a window in hours. Absent means every packet the database
 * holds, which is what this page has always shown, and the header says
 * which of the two it is.
 */
const firehoseFilter = { type: '', hours: '' };

/** The address of the firehose, filtered. */
function firehoseHref(type, hours) {
  const params = new URLSearchParams();
  if (type) params.set('type', type);
  if (hours) params.set('hours', String(hours));
  const query = params.toString();
  return query ? `#firehose?${query}` : '#firehose';
}

/*
 * The window's name, for the header.
 *
 * "All time" rather than a blank, because a page showing 150 rows out of
 * a database and a page showing 150 rows out of one day look identical
 * and answer different questions. §5.1 asks for the window to be shown;
 * it is only worth showing if the unbounded case is named too.
 */
function firehoseWindowWord(hours) {
  const n = Number(hours);
  if (!Number.isFinite(n) || n <= 0) return 'All time';
  // 24 hours stays "24 h", which is the words the plan uses for it and
  // the words the dashboard panel it is linked from uses. "Last 1 day"
  // is the same length, reads worse, and makes the two pages disagree
  // about the name of the same window.
  if (n % 24 === 0 && n >= 48) return `Last ${n / 24} days`;
  return `Last ${n} h`;
}

/*
 * The suggestions under the firehose filter, filled once.
 *
 * They are the types this mesh has actually sent, not every type the
 * protocol defines, so the list is short and every entry returns rows.
 * The page refreshes on a timer, so this is fetched once per visit
 * rather than on every draw.
 */
let firehoseTypesFilled = false;

async function fillFirehoseTypes(page) {
  if (firehoseTypesFilled) return;
  const list = $('[data-firehose-types]', page);
  if (!list) return;
  firehoseTypesFilled = true;
  const rows = await get('api/stats/portnums').catch(() => null);
  if (!rows || !rows.length) return;
  replace(list, [...rows]
    .sort((a, b) => b.count - a.count)
    .map((row) => el('option', { value: portnumLabel(row.name || row.portnum) })));
}

PAGES.firehose = async (page) => {
  fillFirehoseTypes(page);
  /*
   * The address is the source of truth, and the controls are set from
   * it rather than read.
   *
   * Reading the box would mean two places held the filter -- the box and
   * the URL -- and the day they differ is the day the page shows one
   * thing and the link in the address bar means another. So `route()`
   * fills `firehoseFilter` from the fragment, this sets the controls to
   * match, and the Filter button writes a new fragment rather than
   * re-rendering directly.
   */
  const box = $('[data-firehose-portnum]', page);
  const window_ = $('[data-firehose-hours]', page);
  // The wire value from the URL, shown in the words the rest of the
  // page uses. `portnumLabel` handles a bare number and a name alike.
  box.value = firehoseFilter.type ? portnumLabel(firehoseFilter.type) : '';
  if (window_) window_.value = firehoseFilter.hours || '';
  const windowWord = firehoseWindowWord(firehoseFilter.hours);
  const head = $('[data-firehose-window]', page);
  if (head) head.textContent = windowWord;

  // The wire value, straight from the URL. Never round-tripped through
  // the box: `portnumWire(portnumLabel(x))` is x for every type in the
  // table today, and the day a label is added without its reverse entry
  // it would silently become `<LABEL>_APP` and 422.
  const portnum = firehoseFilter.type;
  const params = new URLSearchParams({ limit: '150', summary: 'true' });
  if (portnum) params.set('portnum', portnum);
  if (firehoseFilter.hours) {
    const since = new Date(Date.now() - Number(firehoseFilter.hours) * 3600000);
    params.set('since', since.toISOString());
  }
  /*
   * One preset, like every other page. The firehose showed all of them,
   * so a reader on LongFast watched MediumFast traffic scroll past that
   * their radio cannot hear (AGENTS.md 9.7).
   */
  const channel = presetChannel();
  if (channel) params.set('channel', channel);
  const target = $('[data-firehose-table]', page);
  const rows = await get(`api/packets?${params}`).catch((error) => error);
  if (rows instanceof Error) {
    // 422 here is always the filter, and the bare status tells the
    // reader nothing they can act on. The test is on the status, which
    // `requestFailed` still puts in the message ahead of the path.
    // Name the value that was actually sent, not the box.
    //
    // The box holds `portnumLabel(portnum)`, and for an unknown type that
    // is a tidied-up guess: `#firehose?type=NOT_A_REAL_APP` put
    // "Not a real" in the box, so the message named something nobody had
    // asked for. Measured on the running page.
    return replace(target, /422/.test(rows.message || '')
      ? failure(new Error(`No packet type is called "${portnum}". Try one of the suggestions, or a port number.`))
      : failure(rows));
  }
  /*
   * An empty filtered table names the filter it applied.
   *
   * This is §7.1's stated risk and it is not hypothetical: "a
   * valid-looking filter with no rows looks like a quiet mesh". The
   * filter has three parts and two of them are invisible -- the preset
   * comes from the menu and the window from the URL -- so "No packets
   * match the filter." left a reader with no way to tell a quiet mesh
   * from a type that never runs on the preset they are looking at.
   */
  const nothing = portnum || channel || firehoseFilter.hours
    ? `No ${portnum ? `${portnumLabel(portnum)} ` : ''}packets${channel ? ` on ${channel}` : ''}`
      + `${firehoseFilter.hours ? ` in the ${windowWord.toLowerCase()}` : ' at any time'}. `
      + 'The mesh may be quiet, or this may not be traffic that runs here.'
    : 'No packets match the filter.';
  /*
   * Every row opens its packet: a click anywhere on it, or the Open link
   * at its start for a keyboard or a screen reader. The time used to be
   * the only way in, drawn as plain text, so nothing said it could be
   * clicked. "What it said" puts the content on the row itself.
   */
  const packetHref = (row) =>
    `#packet/${encodeURIComponent(row.from_node)}/${row.packet_key.split(':')[1]}`;
  redrawLiveTable(target, rows, (row) => row.packet_key, () => table([
    /*
     * Time first, and it IS the link (Will, 2026-09-26).
     *
     * There was a leading "Packet / Open >" column whose only content was
     * the word Open, on every row, beside a Time column that was plain
     * text. The row is clickable as well -- `rowHref` below -- so the link
     * was the third way to do one thing.
     *
     * It stays a real `<a href>` rather than becoming part of the row's
     * click handler, and that is the point of the pattern: a handler has
     * no URL, so right-click, copy-link, middle-click and open-in-new-tab
     * all stop working, and none of them fail visibly.
     *
     * `title` keeps the full stamp, because the cell shows a clock and a
     * reader scanning a fast list needs the date somewhere.
     */
    {
      label: 'Time',
      cell: (row) => el('a', {
        class: 'linky', href: packetHref(row), title: stamp(row.first_seen_at),
        'aria-label': `Open the packet from ${row.from_name || row.from_node} at ${stamp(row.first_seen_at)}`,
        text: clock(row.first_seen_at),
      }),
    },
    { label: 'From', cell: (row) => nodeChip({ node_id: row.from_node, display_name: row.from_name }) },
    { label: 'To', cell: (row) => toLabel(row) },
    { label: 'Type', cell: (row) => portnumCell(row.portnum) },
    {
      label: 'What it said',
      wrap: true,
      hint: 'A short line from the decoded packet. Node info and routing packets store nothing to show, and neither does a text message while text storage is off.',
      cell: (row) => (row.summary
        ? el('span', { class: 'summary', text: row.summary })
        : el('span', { class: 'muted', text: '-' })),
    },
    { label: 'Channel', cell: (row) => row.channel || '-' },
    {
      label: 'Hops',
      num: true,
      // Named in #99 as the example of a hint written in the
      // protocol's words. "Hop start minus hop limit" is how the
      // number is worked out, not what it means to a reader.
      hint: 'How many times this packet was relayed before a gateway uploaded it.',
      cell: (row) => (row.hop_start == null ? '-' : `${row.hop_start - (row.hop_limit ?? row.hop_start)}`),
    },
    {
      /*
       * `seen_count` counts `packet_seen` rows, and a `packet_seen` row
       * is one MQTT upload. One gateway uploads the same packet several
       * times: AGENTS.md 9.5.1 measured 22 uploads from 15 gateways on
       * one live packet, and says to use `gateway_count` for a count of
       * gateways. This column has always shown the uploads. The heading
       * said "Gateways", so the page named a number it was not holding.
       * The number is untouched; only the word for it is corrected.
       */
      label: 'Uploads',
      num: true,
      hint: 'How many times a gateway uploaded this packet to MQTT. One gateway often uploads the same packet more than once, so this is not a count of gateways.',
      cell: (row) => count(row.seen_count),
    },
  ], rows, nothing, { rowHref: packetHref }));
};

/* --- Traceroutes ------------------------------------------------ */

PAGES.traceroutes = async (page) => {
  const target = $('[data-traceroute-table]', page);
  const rows = await get('api/traceroutes?limit=100').catch((error) => error);
  if (rows instanceof Error) return replace(target, failure(rows));
  replace(target, table([
    {
      label: 'Time',
      cell: (row) => el('a', {
        class: 'linky', href: `#traceroute/${row.id}`, text: stamp(row.seen_at),
      }),
    },
    { label: 'From', cell: (row) => nodeChip({ node_id: row.from_node, display_name: row.from_name }) },
    { label: 'To', cell: (row) => nodeChip({ node_id: row.to_node, display_name: row.to_name }) },
    { label: 'Path', wrap: true, cell: (row) => (row.route_names || []).join(' \u2192 ') || 'direct' },
    { label: 'Hops', num: true, cell: (row) => (row.hops || []).length },
    {
      label: 'Signal measured',
      num: true,
      hint: 'How many hops came back with a signal reading. The firmware reports no reading for a hop it could not measure, and often sends fewer readings than hops.',
      cell: (row) =>
        `${(row.hops || []).filter((hop) => hop.snr != null).length} of ${(row.hops || []).length}`,
    },
    /*
     * The Packet and Drawing columns were here (Will, 2026-09-26).
     *
     * Both were per-row links to somewhere else, on a table where the
     * first column is already a link to the trace itself -- which is the
     * pattern the whole site is moving to.
     *
     * NEITHER capability is lost, and both were checked rather than
     * assumed:
     *
     * - the drawing is on the individual trace page (see `graph_url` in
     *   the trace view), which is where Will said it belonged;
     * - the packet id was a link to `#packet/...`, and the reverse lookup
     *   `api/traceroutes/by-packet/...` is called from the PACKET page, so
     *   a reader can still get between the two. Removing the column does
     *   not remove the road.
     *
     * `packet_id` and `graph_url` are still sent by the API and are used
     * elsewhere, so nothing server-side changes.
     */
  /*
   * The whole row opens the trace, and the Time cell is still a real link
   * to the same place (Will, 2026-09-26). `rowHref` ignores clicks that
   * land on a link or a button, so the node chips in From and To still go
   * to their own pages.
   */
  ], rows, 'No traceroutes recorded.', { rowHref: (row) => `#traceroute/${row.id}` }));
};

/* --- Statistics -------------------------------------------------- */

/** A duration in seconds as something a person can read. */
function everySeconds(seconds) {
  if (seconds == null) return '-';
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  if (seconds < 172800) return `${round(seconds / 3600, 1)} h`;
  return `${round(seconds / 86400, 1)} days`;
}


/**
 * Draw the nodes that send the most often for their family.
 *
 * The point is not to shame anybody. A node at the top of this table is
 * usually restarting, and the health column says whether that looks
 * like a power problem. See the note in the panel.
 */
function drawBroadcastTable(page, data) {
  const target = $('[data-broadcast-table]', page);
  const note = $('[data-broadcast-note]', page);
  if (!data || !data.nodes) return replace(target, empty('No broadcast data.'));

  note.textContent =
    `${count(data.notable_count)} of ${count(data.node_count)} at ${data.notable_ratio}x ` +
    `the default or more, ${count(data.power_loop_count)} possibly power cycling`;

  const health = (row) => {
    const h = row.health;
    if (!h) return el('span', { class: 'muted', text: 'no telemetry' });
    const parts = [];
    if (h.likely_power_loop) {
      parts.push(el('span', { class: 'tag bad', text: 'maybe power cycling' }));
    } else if (h.restarted) {
      parts.push(el('span', { class: 'tag', text: 'restarted' }));
    }
    if (h.battery_level != null) {
      const mains = h.battery_level > 100;
      parts.push(el('span', {
        class: h.brownout_risk ? 'tag bad' : 'tag',
        title: mains
          ? 'The node reports a battery level above 100%, which the firmware uses for mains power.'
          : 'Battery level the node last reported.',
        text: mains ? 'on mains' : `Battery ${Math.round(h.battery_level)}%`,
      }));
    }
    if (h.uptime_seconds != null) {
      parts.push(el('span', {
        class: 'muted',
        title: 'How long the node says it has been running since it last restarted.',
        text: `up ${everySeconds(h.uptime_seconds)}`,
      }));
    }
    return el('span', { class: 'tags' }, parts.length ? parts : el('span', { text: 'ok' }));
  };

  const rates = (row) =>
    el('span', { class: 'tags' },
      Object.entries(row.families)
        .sort((a, b) => b[1].ratio - a[1].ratio)
        .slice(0, 3)
        .map(([name, rate]) => el('span', {
          class: rate.notable ? 'tag bad' : rate.faster_than_default ? 'tag' : 'tag muted',
          title: `every ${everySeconds(rate.interval_seconds)}, ` +
                 `default ${everySeconds(rate.default_seconds)}`,
          text: `${portnumLabel(name)} ${rate.ratio}x`,
        })));

  replace(target, table(
    [
      { label: 'Node', cell: (row) => nodeChip(row) },
      { label: 'Packets', num: true, cell: (row) => count(row.packet_count) },
      { label: 'Send rate against default', cell: rates },
      { label: 'Health', cell: health },
    ],
    data.nodes,
    'Nothing is sending faster than the defaults.',
  ));
}

/** Draw what the mesh sends each hour, stacked by packet family. */
function drawActivityChart(page, data) {
  const note = $('[data-activity-note]', page);
  const target = $('[data-activity-chart]', page);
  if (!data || !data.families) {
    note.textContent = '';
    return chartEmpty(target, 'Cannot load what the mesh is sending.');
  }
  if (!data.families.length) {
    note.textContent = '';
    return chartEmpty(target, `No packet was stored in the last ${data.window_hours} h.`);
  }
  const total = data.families.reduce((sum, family) => sum + family.total, 0);
  note.textContent = `${count(total)} packets over ${data.window_hours} h`;

  // Only the families worth a band. The rest become one "other" band, so
  // the legend stays readable.
  const top = data.families.slice(0, 6);
  const rest = data.families.slice(6);
  const bands = [...top];
  if (rest.length) {
    bands.push({
      name: 'other',
      counts: data.hours.map((_, index) =>
        rest.reduce((sum, family) => sum + (family.counts[index] || 0), 0)),
    });
  }
  const colours = [
    PALETTE.accent, PALETTE.good, PALETTE.warn, PALETTE.link,
    PALETTE.relayed, PALETTE.bad, PALETTE.muted,
  ];

  chart(target, {
    ...CHART_BASE,
    legend: {
      data: bands.map((band) => portnumLabel(band.name)),
      textStyle: { color: PALETTE.muted },
      top: 0,
    },
    xAxis: { type: 'category', data: data.hours.map((hour) => clock(hour)), ...AXIS },
    yAxis: { type: 'value', ...AXIS },
    series: bands.map((band, index) => ({
      name: portnumLabel(band.name),
      type: 'line',
      stack: 'all',
      areaStyle: { opacity: 0.75 },
      showSymbol: false,
      smooth: true,
      data: band.counts,
      itemStyle: { color: colours[index % colours.length] },
    })),
  });
}

PAGES.stats = async (page) => {
  await Promise.all([loadSummary(page), loadTopTalkers(page), loadLeaderboards(page)]);
  const [daily, hardware, activity, broadcast] = await getAll([
    'api/stats/snapshots/daily?days=30',
    'api/stats/hardware',
    'api/stats/activity?hours=24',
    'api/stats/broadcast?hours=24&limit=40',
  ]);
  drawActivityChart(page, activity);
  drawBroadcastTable(page, broadcast);

  const dailyChart = $('[data-daily-chart]', page);
  if (!daily) {
    chartEmpty(dailyChart, 'Cannot load the daily history.');
  } else if (!daily.length) {
    // The jobs service writes `daily_snapshot`. No row means nobody has
    // written one yet, which is not the same as thirty quiet days.
    chartEmpty(dailyChart, 'No daily snapshot has been written yet. The jobs service writes one each day.');
  } else {
    const rows = [...daily].reverse();
    chart(dailyChart, {
      ...CHART_BASE,
      legend: { textStyle: { color: PALETTE.muted }, top: 0 },
      xAxis: { type: 'category', data: rows.map((row) => row.day), ...AXIS },
      // Node counts are far smaller than packet counts. Give each its own axis.
      yAxis: [
        { type: 'value', name: 'Packets', ...AXIS },
        { type: 'value', name: 'Nodes', ...AXIS, splitLine: { show: false } },
      ],
      series: [
        { name: 'Packets', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 0, data: rows.map((row) => row.packet_count), itemStyle: { color: PALETTE.accent } },
        { name: 'Nodes', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 1, data: rows.map((row) => row.node_count), itemStyle: { color: PALETTE.good } },
      ],
    });
  }

  const hardwareChart = $('[data-hardware-chart]', page);
  if (!hardware) {
    chartEmpty(hardwareChart, 'Cannot load the hardware mix.');
  } else if (!hardware.length) {
    chartEmpty(hardwareChart, 'No node has reported its board model.');
  } else {
    const top = hardware.slice(0, 12).reverse();
    // Every bar carries its name (#72). ECharts drops every other label
    // when they do not fit, so the chart grows with the bars instead,
    // and `interval: 0` tells it never to skip one.
    hardwareChart.style.height = `${Math.max(15, top.length * 1.75 + 3)}rem`;
    chart(hardwareChart, {
      ...CHART_BASE,
      tooltip: { ...CHART_BASE.tooltip, trigger: 'item' },
      xAxis: { type: 'value', ...AXIS },
      yAxis: {
        type: 'category',
        data: top.map((row) => row.hw_model || 'unknown'),
        ...AXIS,
        axisLabel: { ...AXIS.axisLabel, interval: 0 },
      },
      series: [{ type: 'bar', data: top.map((row) => row.count), itemStyle: { color: PALETTE.accent, borderRadius: [0, 3, 3, 0] } }],
    });
  }
};

/* ---------------------------------------------------------------- 4b */

/*
 * A packet and a traceroute each get a page of their own, so they can
 * be linked to and read in full rather than glanced at in a panel.
 */

let currentPacket = null;
let currentTrace = null;

/** Put a packet in the address bar. */
function openPacket(fromNode, packetId) {
  location.hash = `packet/${encodeURIComponent(fromNode)}/${encodeURIComponent(packetId)}`;
}

/** Put a traceroute in the address bar. */
function openTraceroute(traceId) {
  location.hash = `traceroute/${encodeURIComponent(traceId)}`;
}

const packetLink = (fromNode, packetId, text) =>
  el('a', {
    class: 'linky',
    href: `#packet/${encodeURIComponent(fromNode)}/${encodeURIComponent(packetId)}`,
    text: text ?? String(packetId),
  });

/**
 * Draw the path a traceroute took, hop by hop.
 * Each hop shows the signal of that single radio link, so a long path
 * reads as a chain rather than one number.
 */
function traceroutePath(hops) {
  if (!hops || !hops.length) return empty('This traceroute recorded no path.');
  const chain = el('ol', { class: 'hops' });
  chain.append(el('li', { class: 'hop-node' },
    el('button', {
      class: 'linky', type: 'button', text: hops[0].from_name,
      onclick: () => openNode(hops[0].from_node),
    })));
  for (const hop of hops) {
    chain.append(
      el('li', { class: 'hop-link' },
        el('span', { class: 'arrow', text: '\u2193' }),
        hop.snr == null
          ? el('span', { class: 'muted', text: 'no signal reading' })
          : snrCell(hop.snr)),
      el('li', { class: 'hop-node' },
        el('button', {
          class: 'linky', type: 'button', text: hop.to_name,
          onclick: () => openNode(hop.to_node),
        })));
  }
  return chain;
}

/**
 * Embed the drawing mesh-graph renders for one trace.
 * mesh-graph keeps its own database, so it may hold no drawing for a
 * given trace. The image stays hidden until it loads.
 */
/*
 * The drawing comes through this API, recoloured for the dark site
 * (`api/trace_drawing.py`, issue #51). mesh-graph draws on white, and a
 * CSS filter over its picture would invert its colours too. The link
 * still opens mesh-graph itself.
 */
function meshGraphTrace(trace) {
  const url = trace && trace.graph_url;
  if (!url) return empty('This traceroute has no packet ID, so it cannot be linked.');
  const drawing = el('img', {
    src: trace.drawing_url ? api(trace.drawing_url) : url,
    alt: '',
    class: 'trace-drawing',
    loading: 'lazy',
    onload: (event) => { event.target.style.display = 'block'; },
    onerror: (event) => {
      event.target.replaceWith(el('p', {
        class: 'muted', style: 'margin:0',
        text: 'mesh-graph keeps its own database and holds no drawing for this trace.',
      }));
    },
  });
  return el('div', {},
    el('p', { style: 'margin:0 0 .5rem' },
      el('a', { class: 'linky', href: url, target: '_blank', rel: 'noopener',
        text: 'Open this trace in mesh-graph' })),
    drawing);
}


let currentLink = null;

PAGES.link = async (page) => {
  if (!currentLink) {
    replace($('[data-link-title]', page), el('h2', { text: 'Link' }));
    return replace($('[data-link-body]', page),
      empty('Open a link from the mesh graph or from a node page. '
        + 'A link is addressed by the two nodes at its ends.'));
  }
  const [a, b] = currentLink;
  const body = $('[data-link-body]', page);
  replace(body, el('p', { class: 'loading', text: 'Loading' }));
  const params = new URLSearchParams({ a, b, hours: graphHours });
  if (graphChannel) params.set('channel', graphChannel);
  const data = await get(`api/graph/link?${params}`).catch((error) => error);
  if (data instanceof Error) return replace(body, failure(data));

  replace($('[data-link-title]', page),
    el('h2', { text: `${data.a.display_name} to ${data.b.display_name}` }),
    el('p', { class: 'sub',
      text: `${count(data.report_count)} reports in the last ${data.window_hours} h` }));

  replace(body, el('div', { class: 'grid two' },
    el('div', { class: 'panel' },
      el('h3', {}, 'Link'),
      el('dl', { class: 'kv' },
        el('dt', { text: 'Between' }),
        el('dd', {}, nodeChip({ node_id: data.a.node_id, display_name: data.a.display_name })),
        el('dt', { text: 'And' }),
        el('dd', {}, nodeChip({ node_id: data.b.node_id, display_name: data.b.display_name })),
        el('dt', { text: 'Reports' }), el('dd', { text: count(data.report_count) }),
        el('dt', { text: 'Best SNR' }),
        el('dd', {}, data.best_snr == null
          ? el('span', { class: 'muted', text: 'never measured' })
          : snrCell(data.best_snr)))),
    el('div', { class: 'panel span-2' },
      el('h3', {}, 'Evidence'),
      el('div', { class: 'table-wrap' }, table([
        { label: 'When', cell: (row) => stamp(row.time) },
        { label: 'Kind', cell: (row) => row.kind },
        { label: 'Reported by', cell: (row) => row.reported_by },
        { label: 'Hop', num: true, cell: (row) => (row.hop == null ? '-' : `${row.hop} of ${row.path_length}`) },
        { label: 'SNR', num: true, cell: (row) => snrCell(row.snr) },
        {
          label: 'Packet',
          cell: (row) => (row.packet_id == null
            ? el('span', { class: 'muted', text: 'not recorded' })
            : packetLink(row.reported_by, row.packet_id)),
        },
      ], data.reports, 'No report evidences this link in the window.')))));
};

PAGES.traceroute = async (page) => {
  if (!currentTrace) {
    return replace($('[data-trace-body]', page),
      empty('Open a traceroute from the traceroutes page or from a node page.'));
  }
  const body = $('[data-trace-body]', page);
  replace(body, el('p', { class: 'loading', text: 'Loading' }));
  const trace = await get(`api/traceroutes/${encodeURIComponent(currentTrace)}`)
    .catch((error) => error);
  if (trace instanceof Error) return replace(body, failure(trace));

  const measured = trace.hops.filter((hop) => hop.snr != null).length;
  replace($('[data-trace-title]', page),
    el('h2', { text: `${trace.from_name} to ${trace.to_name}` }),
    el('p', { class: 'sub',
      text: `${trace.hops.length} hops, ${measured} with a signal reading, `
        + `${stamp(trace.seen_at)}` }));

  replace(body, el('div', { class: 'grid two' },
    el('div', { class: 'panel' },
      el('h3', {}, 'Route'),
      el('dl', { class: 'kv' },
        el('dt', { text: 'From' }), el('dd', {}, nodeChip({ node_id: trace.from_node, display_name: trace.from_name })),
        el('dt', { text: 'To' }), el('dd', {}, nodeChip({ node_id: trace.to_node, display_name: trace.to_name })),
        el('dt', { text: 'Channel' }), el('dd', { text: trace.channel || 'unknown' }),
        el('dt', { text: 'Hops' }), el('dd', { text: String(trace.hops.length) }),
        el('dt', { text: 'Measured' }), el('dd', { text: `${measured} of ${trace.hops.length}` }),
        el('dt', { text: 'When' }), el('dd', { text: stamp(trace.seen_at) }),
        el('dt', { text: 'Packet' }),
        el('dd', {}, trace.packet_id == null
          ? el('span', { class: 'muted', text: 'not recorded' })
          // A packet is keyed by the node that sent it. For a reply that
          // is the answering node, not the origin of the route.
          : packetLink(trace.packet_from_node, trace.packet_id)),
        el('dt', { text: 'Direction' }),
        el('dd', { text: trace.is_reply
          ? 'reply, shown in request order'
          : 'request' }),
        el('dt', { text: 'Answers request' }),
        el('dd', {}, trace.request_id
          ? packetLink(trace.from_node, trace.request_id, String(trace.request_id))
          : el('span', { class: 'muted', text: 'this is a request, not a reply' })))),
    el('div', { class: 'panel' },
      el('h3', {}, 'Path there'),
      traceroutePath(trace.hops)),
    el('div', { class: 'panel span-2' },
      el('h3', {}, 'mesh-graph drawing'),
      meshGraphTrace(trace)),
    trace.return_hops && trace.return_hops.length
      ? el('div', { class: 'panel' },
          el('h3', {}, 'Path back',
            el('span', { class: 'muted',
              text: trace.return_delivered ? 'delivered' : 'still in flight' })),
          trace.return_delivered
            ? null
            : el('p', { class: 'notice' },
                'The broker saw this reply while it was still travelling. It had reached '
                + `${trace.reply_reached} when it was captured. Whether it arrived back at `
                + `${trace.from_name} is not recorded.`),
          traceroutePath(trace.return_hops))
      : null));
};


/* Labels and units for the decoded values a packet can carry. */
const DECODED_LABELS = {
  ...WEATHER_LABELS,
  ...DEVICE_LABELS,
  latitude: ['Latitude', (v) => round(v, 5)],
  longitude: ['Longitude', (v) => round(v, 5)],
  altitude: ['Altitude', (v) => SonoranUnits.heightFromM(v)],
  ground_speed: ['Ground speed', (v) => `${v} m/s`],
  ground_track: ['Ground track', (v) => `${round(v, 0)} deg`],
  sats_in_view: ['Satellites', (v) => String(v)],
  precision_bits: ['Precision bits', (v) => String(v)],
  body: ['Message', (v) => v],
  channel: ['Channel', (v) => v],
  snr: ['SNR', (v) => `${round(v, 2)} dB`],
  neighbor_node_num: ['Neighbor', (v) => `!${(v >>> 0).toString(16).padStart(8, '0')}`],
  pm10_standard: ['PM1.0', (v) => `${v}`],
  pm25_standard: ['PM2.5', (v) => `${v}`],
  pm100_standard: ['PM10', (v) => `${v}`],
};

/** Render one decoded row as a labelled list. */
function decodedValues(values) {
  const entries = Object.entries(values)
    .filter(([key]) => key !== 'time' && key !== 'seen_at')
    .map(([key, value]) => {
      const label = DECODED_LABELS[key];
      return [label ? label[0] : key.replaceAll('_', ' '), label ? label[1](value) : String(value)];
    });
  return el('dl', { class: 'kv' }, entries.flatMap(([label, value]) =>
    [el('dt', { text: label }), el('dd', { text: String(value) })]));
}

/* Maps drawn on a packet page, kept so a redraw does not stack them. */
const packetMaps = new Map();

/**
 * Plot the position a packet reported.
 * A position packet is the one kind whose payload is a place, so it is
 * worth a map rather than a pair of numbers.
 */
function positionMap(target, rows) {
  const seen = new Set();
  const points = [];
  for (const row of rows) {
    if (row.latitude == null || row.longitude == null) continue;
    const key = `${row.latitude},${row.longitude}`;
    if (seen.has(key)) continue;
    seen.add(key);
    points.push([row.latitude, row.longitude]);
  }
  if (!points.length) return false;

  let map = packetMaps.get(target);
  if (map) map.remove();
  map = L.map(target, { attributionControl: true }).setView(points[0], 13);
  packetMaps.set(target, map);
  if (CONFIG.tileUrl) {
    L.tileLayer(CONFIG.tileUrl, {
      className: 'basemap-tiles',
      attribution: CONFIG.tileAttribution || '',
      maxZoom: 19,
    })
      .addTo(map);
  }
  for (const point of points) {
    L.circleMarker(point, {
      radius: 7, color: PALETTE.accent, fillColor: PALETTE.accent, fillOpacity: 0.6, weight: 2,
    }).addTo(map).bindPopup(`${round(point[0], 5)}, ${round(point[1], 5)}`);
  }
  if (points.length > 1) map.fitBounds(points, { padding: [30, 30] });
  setTimeout(() => map.invalidateSize(), 0);
  return true;
}

/*
 * The packet page, by kind.
 *
 * What is worth showing depends on what the packet was, and the list is
 * written down in docs/ARCHITECTURE.md 3.10.1. Each kind shows what the
 * database stored for it, in its own terms. A kind whose content is not
 * stored says so, rather than printing an empty box or a dump.
 */

/* The name of each decoded kind, as the heading of its panel. */
const DECODED_KIND = {
  text: 'Message',
  position: 'Position',
  neighbors: 'Neighbors it reported',
  device: 'Device readings',
  environment: 'Environment readings',
  air_quality: 'Air quality readings',
  power: 'Power readings',
};

/*
 * How wide the doubt is around a position sent with fewer bits, in
 * metres. The firmware keeps the top `bits` of each coordinate, so the
 * cell halves with each bit: 13 bits is about 2.9 km, 16 about 365 m.
 * 32 bits, and no value at all, both mean a full precision position.
 */
function precisionMetres(bits) {
  if (bits == null || bits >= 32 || bits <= 0) return null;
  return 23905787.925 / 2 ** bits;
}

/** One plain sentence that says what this packet was. */
function packetSentence(packet, decoded) {
  const from = packet.from_name || packet.from_node;
  const to = toLabel(packet, { sentence: true });
  const on = packet.channel ? ` on ${packet.channel}` : '';
  const kind = decoded && decoded.kind;
  switch (packet.portnum) {
    case 'TEXT_MESSAGE_APP': return `A text message from ${from} to ${to}${on}.`;
    case 'POSITION_APP': return `${from} reporting where it is.`;
    case 'NODEINFO_APP': return `${from} saying who it is: its name, hardware and role.`;
    case 'NEIGHBORINFO_APP': return `${from} listing the nodes it can hear directly.`;
    case 'TRACEROUTE_APP': return `A traceroute from ${from} to ${to}: a request to record the path between them.`;
    case 'ROUTING_APP': return `A routing message from ${from} to ${to}. It is usually an acknowledgement, or a report that a delivery failed.`;
    case 'TELEMETRY_APP':
      return kind && DECODED_KIND[kind]
        ? `${DECODED_KIND[kind]} from ${from}.`
        : `Telemetry from ${from}.`;
    default: return `A ${portnumLabel(packet.portnum).toLowerCase()} packet from ${from} to ${to}${on}.`;
  }
}

/* What the page can say about a kind whose content is not stored.
 *
 * Since ingest started keeping `payload_json` (see `decode/stored.py`),
 * these only apply to packets stored before then. The public API holds
 * no channel key, so an older packet cannot be decoded after the fact. */
const PAYLOAD_KEPT_SINCE = 'September 22, 2026';
const NOT_STORED = {
  NODEINFO_APP: `Node-info packets stored before ${PAYLOAD_KEPT_SINCE} were kept without what `
    + 'they said. The node page shows the newest identity.',
  ROUTING_APP: `Routing packets stored before ${PAYLOAD_KEPT_SINCE} were kept without what they said, `
    + 'so this one cannot show whether it was an acknowledgement or an error.',
};

/* Words for a routing error reason. `NONE` is a delivery report that
 * nothing went wrong: an acknowledgement. */
const ROUTING_WORDS = {
  NONE: 'Acknowledgement: the packet was delivered.',
  NO_ROUTE: 'No route to the destination.',
  GOT_NAK: 'The destination refused it.',
  TIMEOUT: 'No acknowledgement came back in time.',
  NO_INTERFACE: 'No radio interface could send it.',
  MAX_RETRANSMIT: 'Sent the most times allowed with no acknowledgement.',
  NO_CHANNEL: 'No channel matched it.',
  TOO_LARGE: 'The packet was too large.',
  NO_RESPONSE: 'The destination sent no response.',
  DUTY_CYCLE_LIMIT: 'Held back by the duty cycle limit.',
  BAD_REQUEST: 'The request was not valid.',
  NOT_AUTHORIZED: 'Not authorised.',
  PKI_FAILED: 'The public key encryption failed.',
  PKI_UNKNOWN_PUBKEY: 'The sender does not know the destination\u2019s public key.',
  ADMIN_BAD_SESSION_KEY: 'The admin session key was wrong.',
  ADMIN_PUBLIC_KEY_UNAUTHORIZED: 'That public key may not administer this node.',
  RATE_LIMIT_EXCEEDED: 'Refused by the rate limit.',
};

/** A list of labelled values, leaving out the ones that are missing. */
function kvList(entries) {
  const shown = entries.filter((entry) => entry && entry[1] != null && entry[1] !== '');
  if (!shown.length) return empty('The packet carried no values.');
  return el('dl', { class: 'kv' }, shown.flatMap(([label, value]) =>
    [el('dt', { text: label }), el('dd', { text: String(value) })]));
}

/* "Yes" and "No", capitalised, because they are values in a list and
 * not words in a sentence (#193.4). Changed here rather than at the
 * call sites so every page agrees. */
const yesNo = (value) => (value == null ? null : value ? 'Yes' : 'No');
const coordinate = (value) => (value == null ? null : round(value / 1e7, 5));

/**
 * What a packet carried, from `payload_json`.
 *
 * Ingest keeps it for node info, routing, traceroute, map reports and
 * pax counters, the families with no table of their own. Field names
 * are the protobuf's own, and an enum arrives as its name.
 */
function storedPanel(packet) {
  const values = packet.payload_json || {};
  const panel = (heading, ...body) => el('div', { class: 'panel span-2' }, el('h3', {}, heading), ...body);
  switch (packet.portnum) {
    case 'NODEINFO_APP':
      return panel('Who it said it is', kvList([
        ['Long name', values.long_name],
        ['Short name', values.short_name],
        ['Hardware', values.hw_model],
        ['Role', values.role ? `${roleLabel(values.role)} (${values.role})` : 'Client (not sent)'],
        ['Licensed', yesNo(values.is_licensed)],
        ['Accepts messages', values.is_unmessagable == null ? null : values.is_unmessagable ? 'no' : 'yes'],
        ['Public key', values.public_key ? `${values.public_key.slice(0, 16)}\u2026` : 'none sent'],
      ]));
    case 'ROUTING_APP': {
      const reason = values.error_reason || (values.route_request || values.route_reply ? null : 'NONE');
      return panel('What it reported', kvList([
        ['Result', reason ? (ROUTING_WORDS[reason] || reason) : null],
        ['Reason code', reason],
        values.route_request ? ['Route request', (values.route_request.route || []).length + ' hops'] : null,
        values.route_reply ? ['Route reply', (values.route_reply.route || []).length + ' hops'] : null,
      ]));
    }
    case 'MAP_REPORT_APP':
      return panel('What it published to the map', kvList([
        ['Long name', values.long_name],
        ['Short name', values.short_name],
        ['Hardware', values.hw_model],
        ['Role', values.role ? roleLabel(values.role) : null],
        ['Firmware', values.firmware_version],
        ['Region', values.region],
        ['Modem preset', values.modem_preset],
        ['Default channel', yesNo(values.has_default_channel)],
        ['Latitude', coordinate(values.latitude_i)],
        ['Longitude', coordinate(values.longitude_i)],
        ['Altitude', values.altitude == null ? null : SonoranUnits.heightFromM(values.altitude)],
        ['Position precision', values.position_precision == null ? null : `${values.position_precision} bits`],
        ['Nodes it sees online', values.num_online_local_nodes],
      ]));
    case 'PAXCOUNTER_APP':
      return panel('What it counted', kvList([
        ['Wi-Fi devices', values.wifi],
        ['Bluetooth devices', values.ble],
        ['Uptime', values.uptime == null ? null : `${round(values.uptime / 3600, 1)} h`],
      ]));
    default:
      // Traceroute and anything added later: the fields as they came.
      return panel('What it said', kvList(Object.entries(values).map(([key, value]) =>
        [evidenceLabel(key), Array.isArray(value) ? value.join(', ') || 'none' : typeof value === 'object' ? JSON.stringify(value) : value])));
  }
}

/** A position, with how wide the doubt around it is. */
function positionValues(row) {
  const doubt = precisionMetres(row.precision_bits);
  const entries = [
    ['Latitude', round(row.latitude, 5)],
    ['Longitude', round(row.longitude, 5)],
    row.altitude == null ? null : ['Altitude', SonoranUnits.heightFromM(row.altitude)],
    ['Precision', doubt == null
      ? 'full'
      : `about ${SonoranUnits.distanceFromM(doubt)} `
        + `(${row.precision_bits} bits). The node chose to send a rounded position.`],
    row.ground_speed == null ? null : ['Ground speed', `${row.ground_speed} m/s`],
    row.sats_in_view == null ? null : ['Satellites', String(row.sats_in_view)],
  ].filter(Boolean);
  return el('dl', { class: 'kv' }, entries.flatMap(([label, value]) =>
    [el('dt', { text: label }), el('dd', { text: String(value) })]));
}

/** The neighbours a node reported, as a table it can be read from. */
function neighbourValues(rows) {
  return el('div', { class: 'table-wrap' }, table([
    {
      label: 'Neighbor',
      cell: (row) => {
        /*
         * The name, not the number (#240).
         *
         * This column printed `!0a51a002` while "Who heard it", on the
         * same page and a few centimetres above it, printed "Usery Pass
         * Relay" for the same node. Both are the same question — which
         * node is this — so both must answer it the same way.
         *
         * `neighbor_name` comes from the API, which resolves it through
         * `name_of` and already falls back to the ID form for a node no
         * node-info packet has ever named. So the fallbacks below are
         * not the "no long name" case: that one is answered upstream.
         * They are for a row the API sent without the named fields at
         * all, and a bare number reads better than an empty chip.
         *
         * `>>> 0` because a node number above 2^31 is a negative signed
         * 32-bit integer in JavaScript, and `toString(16)` would put a
         * minus sign in front of the ID.
         */
        const id = row.neighbor_id
          || `!${(row.neighbor_node_num >>> 0).toString(16).padStart(8, '0')}`;
        return nodeChip({ node_id: id, display_name: row.neighbor_name || id });
      },
    },
    {
      label: 'SNR',
      num: true,
      hint: 'How well this node heard that neighbor, as it reported it. This is a measured radio link.',
      cell: (row) => snrCell(row.snr),
    },
  ], rows, 'It reported no neighbors.'));
}

/** The panels that show what a packet said. */
function decodedPanels(packet) {
  const decoded = packet.decoded;
  // An empty object is kept too: a traceroute request with no route yet
  // serialises to nothing. It says nothing, so the usual panel is shown.
  const stored = packet.payload_json;
  if ((!decoded || !decoded.values || !decoded.values.length)
      && stored && Object.keys(stored).length) {
    return storedPanel(packet);
  }
  if (!decoded || !decoded.values || !decoded.values.length) {
    return el('div', { class: 'panel span-2' },
      el('h3', {}, 'What it said'),
      NOT_STORED[packet.portnum]
        ? el('p', {}, NOT_STORED[packet.portnum], ' ',
            packet.portnum === 'NODEINFO_APP'
              ? el('button', {
                  class: 'linky', type: 'button', text: `Open ${packet.from_name || packet.from_node}`,
                  onclick: () => openNode(packet.from_node),
                })
              : null)
        : packet.portnum === 'TRACEROUTE_APP'
          ? el('p', { class: 'muted', text: 'The path is below, if this dashboard stored it.' })
          : empty('No decoded value is stored for this packet.'));
  }
  const heading = DECODED_KIND[decoded.kind] || 'What it said';
  if (decoded.kind === 'text') {
    return el('div', { class: 'panel span-2' },
      el('h3', {}, heading),
      decoded.values.map((row) => el('p', { class: 'packet-text' }, messageBody(row.body))));
  }
  if (decoded.kind === 'position') {
    const holder = el('div', { class: 'chart tall', 'data-position-map': '' });
    return [
      el('div', { class: 'panel' }, el('h3', {}, heading), decoded.values.map(positionValues)),
      el('div', { class: 'panel' }, el('h3', {}, 'On the map'), holder),
    ];
  }
  if (decoded.kind === 'neighbors') {
    return el('div', { class: 'panel span-2' }, el('h3', {}, heading), neighbourValues(decoded.values));
  }
  // Telemetry: named readings with their units.
  return el('div', { class: 'panel span-2' },
    el('h3', {}, heading),
    decoded.values.map((row) => decodedValues(row)));
}

/** The envelope: who, to whom, where, and how far it came. */
function envelopePanel(packet, packetId, observations) {
  const heard = observations.filter((row) => !row.self_reported && row.hops_taken != null);
  const fewest = heard.length ? Math.min(...heard.map((row) => row.hops_taken)) : null;
  const to = toLabel(packet);
  return el('div', { class: 'panel' },
    el('h3', {}, 'Envelope'),
    el('dl', { class: 'kv' },
      el('dt', { text: 'From' }), el('dd', {}, nodeChip({ node_id: packet.from_node, display_name: packet.from_name })),
      el('dt', { text: 'To' }), el('dd', { text: to }),
      el('dt', { text: 'Channel' }), el('dd', { text: packet.channel || 'unknown' }),
      el('dt', { text: 'Type' }),
      el('dd', { title: String(packet.portnum), text: portnumLabel(packet.portnum) }),
      el('dt', { text: 'Hops allowed' }),
      el('dd', { text: packet.hop_start == null ? 'unknown' : String(packet.hop_start) }),
      el('dt', { text: 'Fewest hops used' }),
      el('dd', { text: fewest == null ? 'unknown' : `${fewest}, by the nearest gateway` }),
      el('dt', { text: 'Encryption' }),
      el('dd', { text: packet.pki_encrypted == null
        ? 'not recorded'
        : packet.pki_encrypted
          ? 'the recipient\u2019s public key (PKI), so only it could read it'
          : 'the channel key' }),
      el('dt', { text: 'Asked for an ack' }),
      el('dd', { text: packet.want_ack ? 'yes. Whether one came back is not recorded.' : 'no' }),
      el('dt', { text: 'First seen' }), el('dd', { text: stamp(packet.first_seen_at) }),
      el('dt', { text: 'Packet ID' }), el('dd', {}, el('code', { text: String(packetId) })),
      el('dt', { text: 'Size' }),
      el('dd', { text: packet.raw_bytes_length == null ? 'unknown' : `${packet.raw_bytes_length} bytes` }),
      el('dt', { text: 'Priority' }),
      el('dd', { text: packet.priority == null ? 'default' : String(packet.priority) })));
}

/*
 * Everything the API returned for this packet, as it came, behind a
 * disclosure. The views above are the reading; this is for the person
 * who wants the fields themselves.
 */
/* The JSON starts open: closed, it read as an empty panel. It is still
 * a `details`, so it can be folded away, and it is still the last thing
 * on the page. */
function rawPanel(data) {
  return el('details', { class: 'panel span-2 raw-data', open: true },
    el('summary', {}, 'Raw data'),
    el('pre', { text: JSON.stringify({
      packet: data.packet,
      gateway_count: data.gateway_count,
      observations: data.observations,
    }, null, 2) }));
}

PAGES.packet = async (page) => {
  if (!currentPacket) {
    return replace($('[data-packet-body]', page),
      empty('Open a packet from a message, a node page, or the firehose. '
        + 'A packet is addressed by the node that sent it and the packet ID.'));
  }
  const [fromNode, packetId] = currentPacket;
  const body = $('[data-packet-body]', page);
  replace(body, el('p', { class: 'loading', text: 'Loading' }));
  const data = await get(
    `api/packets/${encodeURIComponent(fromNode)}/${encodeURIComponent(packetId)}`)
    .catch((error) => error);
  if (data instanceof Error) {
    const missing = /\(404\)/.test(data.message);
    return replace(body, missing
      ? empty(`No packet ${packetId} is stored for ${fromNode}. `
          + 'It may have aged out, or the sending node may be wrong.')
      : failure(data));
  }
  const packet = data.packet;
  const direct = data.observations.filter((row) => row.direct).length;
  /*
   * One gateway uploads the same packet more than once, so the number
   * of rows is not the number of gateways. The heading counted rows and
   * called them gateways, which overstated the reach of every packet.
   */
  const gateways = data.gateway_count == null
    ? new Set(data.observations.map((row) => row.gateway)).size
    : data.gateway_count;
  const uploads = data.observations.length;

  replace($('[data-packet-title]', page),
    el('h2', { title: String(packet.portnum), text: `${portnumLabel(packet.portnum)} from ${packet.from_name}` }),
    el('p', { class: 'sub packet-sentence' },
      packetSentence(packet, packet.decoded), ' ',
      el('span', { class: 'muted',
        text: `${count(gateways)} gateways uploaded it, `
          + (direct ? `${count(direct)} heard it direct.` : 'none heard it direct.') })));

  /*
   * Who heard it comes first. It is the one thing on this page that no
   * other page shows for a single packet, and it was at the bottom.
   */
  const panels = [
    el('div', { class: 'panel span-2' },
      el('h3', {}, 'Who heard it',
        el('span', { class: 'muted',
          text: `${count(gateways)} gateways, ${count(uploads)} uploads, ${count(direct)} direct` })),
      el('p', { class: 'notice' },
        'This is which MQTT gateways uploaded a copy of this packet. It is not '
        + 'which nodes could hear the sender: a node that is not a gateway hears '
        + 'plenty and reports none of it. A gateway that used a hop received the '
        + 'packet from a relay, so only a direct row measures the sender’s own '
        + 'link. A sender that gateways its own traffic uploads what it just sent, '
        + 'which is not a radio link at all.'),
      el('div', { class: 'table-wrap' }, table([
        { label: 'Gateway', cell: (row) => nodeChip({ node_id: row.gateway, display_name: row.gateway_name }) },
        {
          label: 'Path',
          cell: (row) => (row.self_reported
            ? el('span', { class: 'muted', text: 'its own upload' })
            : row.direct ? 'direct' : row.hops_taken == null ? 'unknown' : `${row.hops_taken} hops`),
        },
        { label: 'SNR', num: true, cell: (row) => (row.direct ? snrCell(row.rx_snr) : el('span', { class: 'muted', text: '-' })) },
        { label: 'RSSI', num: true, cell: (row) => (row.direct && row.rx_rssi != null ? `${row.rx_rssi} dBm` : '-') },
        { label: 'When', cell: (row) => clock(row.seen_at) },
        { label: 'Topic', wrap: true, cell: (row) => row.mqtt_topic },
      ], data.observations, 'No gateway observation stored.'))),
  ];

  panels.push(...[decodedPanels(packet)].flat());
  panels.push(envelopePanel(packet, packetId, data.observations));
  panels.push(rawPanel(data));
  replace(body, el('div', { class: 'grid two' }, panels));

  const mapHolder = $('[data-position-map]', body);
  if (mapHolder && packet.decoded) positionMap(mapHolder, packet.decoded.values);

  // A traceroute packet carries a path. Show it and the drawing here.
  if (packet.portnum === 'TRACEROUTE_APP') {
    const trace = await get(
      `api/traceroutes/by-packet/${encodeURIComponent(fromNode)}/${encodeURIComponent(packetId)}`)
      .catch(() => null);
    if (trace) {
      $('.grid', body).append(
        el('div', { class: 'panel' },
          el('h3', {}, 'Path this packet took',
            el('a', { class: 'linky', href: `#traceroute/${trace.id}`, text: 'full page' })),
          traceroutePath(trace.hops)),
        el('div', { class: 'panel' },
          el('h3', {}, 'mesh-graph drawing'),
          meshGraphTrace(trace)));
    }
  }
};

/* ---------------------------------------------------------------- 5 */

/* Pages that refresh on a timer while the Live button is pressed. */
const LIVE_INTERVAL_MS = 15000;
let liveTimer = null;
let currentPage = 'dashboard';
let loading = false;

function livePage(name) {
  const page = $(`[data-page="${name}"]`);
  const button = page && $('[data-live]', page);
  return Boolean(button && button.getAttribute('aria-pressed') === 'true');
}

function scheduleLive() {
  clearInterval(liveTimer);
  liveTimer = setInterval(() => {
    if (document.hidden || !livePage(currentPage)) return;
    /*
     * The chat reading view is updated, not redrawn (§6.1).
     *
     * `render` rebuilds the page, which throws away the scroll position
     * and every message paged in above it -- so a reader scrolled back
     * through yesterday would be thrown to the newest message every
     * fifteen seconds, and the older pages they had loaded would have to
     * be loaded again. `chatAppendNew` adds only what arrived and leaves
     * the view where it was unless the reader was already at the bottom.
     */
    if (currentPage === 'chat' && currentChatChannel && chatView === 'chat') {
      chatAppendNew();
      return;
    }
    render(currentPage);
  }, LIVE_INTERVAL_MS);
}

async function setStatus(state, message) {
  const dot = $('[data-status] .dot');
  dot.className = `dot ${state}`;
  $('[data-status-text]').textContent = message;
  // The visible copy is inside the menu, which is `hidden` when a phone
  // closes it; this one is `.sr-only`, always in the tree, and is the
  // only thing that announces (#175).
  const live = $('[data-status-live]');
  if (live) live.textContent = message;
}

/*
 * A table that scrolls sideways has to be reachable from a keyboard.
 *
 * `.table-wrap` has always scrolled, and the CSS now draws a shadow on
 * whichever side has more to show. That covers a pointer. A keyboard has
 * no way into a scrolling box that holds no focusable element, so the
 * coverage gaps table simply ended at "Best measured link" for anybody
 * not using a mouse, and the nodes table ended at the node ID on a
 * phone. A scrollable region needs `tabindex` and a name.
 *
 * Only when it actually overflows: a tab stop that scrolls nowhere is a
 * stop for nothing. The name comes from the panel heading above it when
 * there is one, so a screen reader says which table it has landed in.
 */
function markScrollableTables(root = document) {
  for (const wrap of $$('.table-wrap', root)) {
    const scrolls = wrap.scrollWidth > wrap.clientWidth + 1;
    if (!scrolls) {
      wrap.removeAttribute('tabindex');
      wrap.removeAttribute('role');
      wrap.removeAttribute('aria-label');
      continue;
    }
    // The panel heading names it. A few panels carry no heading of their
    // own — the nodes table is the whole page — so the page heading does.
    const heading = wrap.closest('.panel')?.querySelector('h3')
      || wrap.closest('.page')?.querySelector('h2');
    const name = (heading?.textContent || 'Table').trim();
    wrap.setAttribute('tabindex', '0');
    wrap.setAttribute('role', 'region');
    wrap.setAttribute('aria-label', `${name}, scrolls sideways`);
  }
}

/*
 * Write every hover-only sentence out where a finger can reach it.
 *
 * The dashboard explained itself entirely through the `title`
 * attribute: a column hint on `th`, a tile hint on `.stat .label`, and
 * the exact protocol value behind every role and packet type. A
 * `title` tooltip needs a pointer to hover, so on a phone none of it
 * existed — and the hints are written for the reader who does not know
 * the word yet, who is the reader least likely to be at a desk. The
 * HTML Living Standard names that failure directly: relying on `title`
 * "excludes keyboard-only users and touch-only users, such as anyone
 * with a modern phone or tablet".
 * https://html.spec.whatwg.org/multipage/dom.html#the-title-attribute
 *
 * The first answer was a disclosure under the table, "What these
 * columns mean". It worked, and it repeated every heading a second
 * time on a page that is already long (#99). The sentence now sits on
 * the heading it explains, behind a button.
 *
 * A button, and not a hover tooltip, for the same reason as before. A
 * hover tooltip must satisfy WCAG 2.2 SC 1.4.13 Content on Hover or
 * Focus (Level AA) — dismissible, hoverable, persistent — and a `title`
 * cannot be reached by a finger or a keyboard at all. A button that
 * opens on click, tap and Enter or Space has none of those problems:
 * nothing opens by accident, so nothing has to be kept open while the
 * pointer travels to it.
 *
 * The panel is a popover, which is what keeps it out of
 * `.table-wrap`'s sideways scroll. A popover draws in the browser's
 * top layer, so no ancestor's `overflow` can clip it, while staying
 * where it is in the document for a screen reader. It also brings
 * Escape and tap-outside-to-close with it, both of which SC 1.4.13
 * asks for. Where `popover` is not supported the same element is shown
 * with `hidden` and `position: fixed` — fixed positioning escapes a
 * plain `overflow` ancestor as well — and this file closes it on
 * Escape and on a tap outside.
 *
 * The exact wire values come with it, on the column that holds them. A
 * role column shows "Client mute" because `CLIENT_MUTE` truncates into
 * a lie, and the exact value had nowhere else to live on a phone.
 *
 * Nothing here changes a value, a label or a unit.
 */

/* Whether the browser has the popover API. Chrome 114, Safari 17 and
 * Firefox 125 have it; older ones take the `hidden` path below. */
const POPOVER = 'popover' in HTMLElement.prototype;

/* The panel that is open now, so a second one closes the first. */
let openHint = null;
let hintSeq = 0;

function revealHints(root = document) {
  for (const wrap of $$('.table-wrap', root)) {
    const table = $('table', wrap);
    for (const th of table ? $$('th', table) : []) {
      const hint = th.dataset.hint;
      const exact = exactValues(table, th);
      if (!hint && !exact.length) continue;
      fitHint(th, 'column', th.dataset.label || th.textContent.trim(), hint, exact);
    }
  }
  /*
   * The same for the summary tiles. Four numbers on the dashboard, each
   * with a sentence saying what it counts, and AGENTS.md 9.5.1 is the
   * reason those sentences matter: "Uploads" is not a count of gateways
   * and the tile that says so was readable only on hover.
   */
  // Any labelled figure, not only the dashboard's `.stat` blocks: the
  // node page's route tiles carry the same shape (#191).
  for (const label of $$('.label[data-hint]', root)) {
    fitHint(label, 'figure', label.dataset.label || label.textContent.trim(),
      label.dataset.hint, []);
  }
  /*
   * And panel headings (#191).
   *
   * Explanatory prose under a heading is useful once and clutter every
   * time after. #99 moved the column explanations of two tables behind
   * these buttons and did not reach panel-level prose, so it was still
   * printed in full on every visit.
   *
   * `data-hint` on the `h3` is all a panel needs; the button lands on
   * the heading beside its text. What must NOT move is listed in #191
   * and is worth repeating here, because the temptation is to sweep
   * every paragraph: an empty state stays visible, and so does any
   * sentence that changes what a number means -- if the reason a figure
   * is missing is behind a button, the figure reads as a fact.
   */
  for (const heading of $$('h3[data-hint]', root)) {
    fitHint(heading, 'panel', heading.dataset.label || heading.firstChild?.textContent?.trim()
      || heading.textContent.trim(), heading.dataset.hint, []);
  }
}

/** Every distinct exact value one column holds, in the order first seen. */
function exactValues(table, th) {
  const row = th.parentElement;
  const index = [...row.children].indexOf(th);
  const out = [];
  const seen = new Set();
  for (const body of $$('tbody tr', table)) {
    const cell = body.children[index];
    const marked = cell && $('[data-exact]', cell);
    if (!marked) continue;
    const exact = marked.dataset.exact;
    const text = marked.textContent.trim();
    // Nothing to explain when the cell already prints the wire value.
    if (!exact || exact === text || seen.has(exact)) continue;
    seen.add(exact);
    out.push({ text, exact });
  }
  return out;
}

/** The sentence and the exact values, as the panel's contents. */
function hintBody(label, hint, exact) {
  return [
    el('p', { class: 'hint-name', text: label }),
    hint ? el('p', { text: hint }) : null,
    exact.length
      ? el('p', { class: 'hint-exact' },
        el('span', { class: 'muted', text: 'Exact values here: ' }),
        exact.map((value, index) =>
          el('span', { text: `${index ? ', ' : ''}${value.text} = ${value.exact}` })))
      : null,
  ];
}

/**
 * Give one heading or tile label its hint button, once.
 *
 * A live page renders every 15 s and most renders say the same thing.
 * Rebuilding the button anyway would take the focus out of it each
 * time, and shut a panel somebody was reading, so the contents are
 * compared first and only a real change is written.
 */
function fitHint(host, noun, label, hint, exact) {
  /*
   * The name carries the heading, because a page holds a dozen of
   * these and "What this column means" a dozen times names nothing to
   * somebody tabbing through. The heading goes last rather than first
   * — "What Uploads means" reads well until the column is called "What
   * it said", and then it reads "What What it said means".
   */
  const name = `What this ${noun} means: ${label}`;
  const key = [label, hint, ...exact.map((value) => `${value.text}=${value.exact}`)].join(' ');
  const found = $('.hint-open', host);
  if (found) {
    const panel = document.getElementById(found.getAttribute('aria-controls'));
    if (panel && panel.dataset.key !== key) {
      replace(panel, hintBody(label, hint, exact));
      panel.dataset.key = key;
      found.setAttribute('aria-label', name);
    }
    return;
  }
  const id = `hint-${++hintSeq}`;
  const panel = el('div', { class: 'hint-pop', id, 'data-key': key, hidden: !POPOVER },
    hintBody(label, hint, exact));
  if (POPOVER) panel.setAttribute('popover', 'auto');
  const button = el('button', {
    type: 'button', class: 'hint-open',
    'aria-label': name,
    'aria-expanded': 'false',
    'aria-controls': id,
  }, el('span', { class: 'hint-mark', 'aria-hidden': 'true', text: 'i' }));
  /*
   * The browser drives it where it can. `popovertarget` toggles the
   * panel, closes it on Escape and on a tap outside, and — the part a
   * click handler of ours would get wrong — closes it when the button
   * that opened it is pressed again, rather than closing and reopening
   * it in the same gesture.
   */
  if (POPOVER) {
    button.setAttribute('popovertarget', id);
    /*
     * An auto popover closes any other one as it opens, so nothing here
     * has to track which panel is up. `toggle` is the first moment the
     * panel has a size to measure, so that is where it is placed.
     */
    panel.addEventListener('toggle', (event) => {
      const open = event.newState === 'open';
      button.setAttribute('aria-expanded', String(open));
      if (open) placeHint(button, panel);
    });
  } else {
    button.addEventListener('click', () => {
      const wasOpen = openHint && openHint.panel === panel;
      closeHint();
      if (wasOpen) return;
      panel.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      openHint = { button, panel };
      placeHint(button, panel);
    });
  }
  host.append(button, panel);
}

/**
 * Put the panel under its button, and never off the side of the screen.
 *
 * A heading near the right edge of a wide table would otherwise open a
 * panel that runs past the viewport, and the panel is in the top layer
 * so nothing scrolls to reach it. Below the button unless there is no
 * room below, and then above it.
 */
function placeHint(button, panel) {
  const gutter = 8;
  const rect = button.getBoundingClientRect();
  const wide = document.documentElement.clientWidth;
  const tall = document.documentElement.clientHeight;
  const left = Math.max(gutter,
    Math.min(rect.left + rect.width / 2 - panel.offsetWidth / 2, wide - panel.offsetWidth - gutter));
  const below = rect.bottom + 6;
  const top = below + panel.offsetHeight > tall - gutter
    ? Math.max(gutter, rect.top - panel.offsetHeight - 6) : below;
  panel.style.left = `${Math.round(left)}px`;
  panel.style.top = `${Math.round(top)}px`;
}

/* Only the fallback path has a panel to close by hand. */
function closeHint() {
  if (!openHint) return;
  const { button, panel } = openHint;
  openHint = null;
  button.setAttribute('aria-expanded', 'false');
  panel.hidden = true;
}

/*
 * Escape and a tap outside, for the browsers with no popover API.
 * Where there is one the browser does both, and these listeners are
 * not installed at all rather than racing it.
 */
if (!POPOVER) {
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeHint();
  });
  document.addEventListener('pointerdown', (event) => {
    if (openHint && !event.target.closest('.hint-pop, .hint-open')) closeHint();
  });
}

/*
 * Which pages the global preset actually applies to (#232, Tyler's second
 * point: "dim filters that are not applicable to the page you're on").
 *
 * DECLARED, never inferred, and that is the whole point of this list.
 *
 * Three ways of working it out automatically were tried and each got a
 * page wrong:
 *
 * - **Diffing the API requests** between the two presets said `coverage`
 *   ignores it. Coverage obeys it completely -- `state.preset` drives the
 *   tile URL, the node overlay, the legend and the summary -- and it only
 *   measured as inert because that instance had no published coverage run,
 *   so none of the path executed. The log was describing the data, not the
 *   code.
 * - **Grepping each page function** for the store said `stats` ignores it.
 *   The leaderboards read it from a separate function.
 * - **Looking for which modules mention the store** says `chat` ignores it.
 *   Chat filters its channel sections client-side through `channelsFor`,
 *   so the request never names a preset.
 *
 * A note that says "not used here" is a CLAIM about what the reader is
 * looking at. Getting it wrong on coverage would tell somebody the switch
 * is doing nothing while it silently decides which mesh their map shows,
 * which is worse than saying nothing at all. So each page says, and
 * `test_preset_scope.py` fails if a page is added without saying.
 */
const PRESET_PAGES = new Set([
  'dashboard', 'nodes', 'chat', 'map', 'graph', 'coverage', 'planner',
  'gaps', 'firehose', 'stats',
]);

/*
 * Pages the preset does not reach. Listed rather than derived, so that the
 * two lists together must account for every page in `PAGES` -- a new page
 * belongs in exactly one and the test says which is missing.
 *
 * The four single-subject pages are here because they show one node, one
 * packet, one link or one traceroute: the thing is already chosen, and the
 * preset has nothing left to narrow.
 */
const PRESET_FREE_PAGES = new Set([
  'traceroutes', 'meshnet', 'rf', 'config', 'settings',
  'node', 'packet', 'link', 'traceroute',
]);

/** True when the menu's preset changes what this page shows. */
function presetAppliesTo(name) {
  return PRESET_PAGES.has(name);
}

/*
 * Say so, next to the switch, when the page in view ignores it.
 *
 * A NOTE and not a dimmed control, which is what the issue suggested. A
 * disabled-looking radio group says "you cannot change this", and that is
 * false: the reader can change it here and it takes effect everywhere it
 * applies, including the page they go to next. The switch is global, so it
 * is never inoperable -- it is only irrelevant to what is currently on
 * screen, and those are different sentences. Trivially swapped for dimming
 * if Tyler would rather have that.
 */
function drawPresetScope(name) {
  const note = $('[data-preset-scope]');
  if (!note) return;
  const applies = presetAppliesTo(name);
  note.hidden = applies;
  note.textContent = applies ? '' : 'Not used on this page.';
}

async function render(name) {
  const page = $(`[data-page="${name}"]`);
  if (!page || loading) return;
  drawPresetScope(name);
  loading = true;
  try {
    await PAGES[name](page);
    setStatus('', `Updated ${clock(new Date())}`);
  } catch (error) {
    console.error(error);
    setStatus('down', 'Update failed');
  } finally {
    loading = false;
    markScrollableTables(page);
    revealHints(page);
  }
}

/*
 * Set when watch mode writes its own state into the fragment.
 *
 * Switching a tab or changing a panel height changes what is tabulated,
 * not what is fetched, so it must not cost a request. The fragment is
 * still where the state lives — it survives a reload, it is shareable,
 * and a `Referer` never carries it (AGENTS.md 9.9.1) — but the router has
 * to be told that this particular change is not a navigation.
 */
let watchFragmentWrite = false;

async function route() {
  /*
   * A page may carry settings after a `?`.
   *
   * The planner's share link is `#planner?v=1&lat=33.45&…`. Without
   * this split the page name is the whole string, `PAGES` does not have
   * `planner?v=1&lat=33.45&…` in it, and every shared link falls back
   * to the dashboard — the same failure AGENTS.md 9.14 describes for a
   * reload on `#planner`, and just as quiet. The page reads its own
   * settings straight off `location.hash`.
   */
  const fragment = (location.hash.slice(1) || 'dashboard').split('?')[0];
  const parts = (fragment || 'dashboard').split('/');
  const [name, nodeId] = parts;

  const known = Object.hasOwn(PAGES, name) ? name : 'dashboard';

  if (watchFragmentWrite && known === currentPage) {
    watchFragmentWrite = false;
    return;
  }
  watchFragmentWrite = false;

  /*
   * A pair is only a pair when both halves arrived.
   *
   * These used to be built unconditionally, so `#packet` with nothing
   * after it produced ['', ''] — an array, and so truthy. The `if
   * (!currentPacket) return` guard in the page never fired, and the page
   * asked the API for `packets//`. The link page did the same and took a
   * 422; the packet page got an answer with no observations in it and
   * threw on reading .filter of undefined, which leaves the panel blank
   * with no clue why.
   */
  const pair = (one, two) => (one && two ? [one, two] : null);
  if (known === 'packet') {
    currentPacket = pair(decodeURIComponent(parts[1] || ''), parts[2] || '');
  }
  if (known === 'link') {
    currentLink = pair(decodeURIComponent(parts[1] || ''), decodeURIComponent(parts[2] || ''));
  }
  if (known === 'traceroute') currentTrace = decodeURIComponent(parts[1] || '') || null;
  /*
   * `#firehose?type=POSITION_APP&hours=24` (§5.1, for §7.1).
   *
   * Read here rather than in the page so there is one place that turns
   * an address into state, and so an absent parameter clears the filter
   * instead of leaving the last one in force -- `#firehose` on its own
   * must mean "everything", or the Back button out of a filtered view
   * would land on the same filtered view.
   */
  if (known === 'firehose') {
    const query = new URLSearchParams(location.hash.split('?')[1] || '');
    firehoseFilter.type = (query.get('type') || '').trim();
    const hours = Number(query.get('hours'));
    // A window has to be a positive number of hours. Anything else is
    // not a smaller window, it is no window, and `new Date(NaN)` would
    // put `since=Invalid Date` in the query and take a 422.
    firehoseFilter.hours = Number.isFinite(hours) && hours > 0 ? String(hours) : '';
  }
  if (known === 'chat') {
    const channel = decodeURIComponent(parts[1] || '') || null;
    /*
     * A different channel starts again from its newest page. This used to
     * reset a `chatLimit`; `chatChannelPage` now compares the channel and
     * the range against the key `chatRows` was filled for, so the reset
     * lives with the rows rather than here. Left as a comment because the
     * line that was here referenced two constants that no longer exist,
     * and `node --check` does not notice that.
     */
    currentChatChannel = channel;
    chatView = parts[2] === 'table' ? 'table' : 'chat';
  }
  /*
   * `#map/node/<id>` opens the live map on one node (#193.6).
   *
   * Two traps, both named in the issue:
   *
   * - **Preset.** The map shows one preset at a time (AGENTS.md 9.7)
   *   and since #177 it opens on the deployment's own. A node on a
   *   different preset is simply not drawn, so the link would land on
   *   empty ground. The node page knows the node's channel and puts it
   *   in the fragment, and the map selects it before fetching.
   * - **Rounded positions.** The focus must not zoom so far that a
   *   coarse position looks exact (#96), so `MAP_FOCUS_ZOOM` is a long
   *   way short of street level.
   *
   * `watch` is already a word after `map`, so this reads `parts[1]`
   * and only claims the fragment when it says `node`.
   */
  if (known === 'map' && parts[1] === 'node' && parts[2]) {
    mapFocus = {
      nodeId: decodeURIComponent(parts[2]),
      preset: new URLSearchParams(location.hash.split('?')[1] || '').get('preset') || null,
    };
  } else if (known !== 'map') {
    mapFocus = null;
    // The mark belongs to one visit, not to the page for ever.
    mapState.focusNodeId = null;
  }
  currentNodeId = known === 'node' ? decodeURIComponent(nodeId || '') : currentNodeId;
  const leavingMap = currentPage === 'map' && known !== 'map';
  currentPage = known;

  /*
   * Leaving the map stops the animation dead.
   *
   * There was no page-exit hook at all, so the old fades went on running
   * over a page nobody was looking at. One loop makes this one call, and
   * the target is no CPU at all when the map is not the subject.
   */
  if (leavingMap && mapState.live) mapState.live.setPageActive(false);
  if (known === 'map' && mapState.live) mapState.live.setPageActive(true);
  if (leavingMap) {
    clearInterval(mapState.tickerTimer);
    mapState.tickerTimer = null;
  }

  for (const page of $$('[data-page]')) page.classList.toggle('active', page.dataset.page === known);
  for (const link of $$('[data-nav]')) {
    const here = link.dataset.nav === known;
    link.classList.toggle('current', here);
    // `aria-current` as well as the class. The class is how the page
    // LOOKS current; this is how it SAYS so. Without it a screen
    // reader cannot tell which of fifteen pages it is on, because the
    // only signal was a colour (WCAG 1.3.1).
    if (here) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  markNavHere(known);
  await render(known);
  // A link straight to `#map/watch/traffic/expanded` opens in watch mode.
  if (known === 'map') SonoranWatch.restore();
}

/**
 * The theme control (#50).
 *
 * Charts and map layers read the palette once, when the page loads, so
 * a change of theme reloads the page rather than chase every colour
 * that was already drawn. The address keeps its fragment, so the reader
 * lands back on the page they were on.
 *
 * With "follow the system", a change in the system setting is followed
 * the same way.
 */
/*
 * The global preset selector in the menu footer.
 *
 * Builds one radio button per preset on offer and re-renders the page in
 * view when the choice changes. The pages themselves do not subscribe:
 * they read `SonoranPreset.current()` (most of them through
 * `SonoranLabels.preferredPreset`) while they draw, so re-drawing is all
 * that is needed and there is no second copy of the choice to keep in
 * step.
 *
 * A radio group rather than a `<select>`: two options, one word each, and
 * a select costs a tap to open before the tap that chooses.
 */
/*
 * The settings page.
 *
 * One radio group per setting, built from `SonoranSettings.options` so the
 * page cannot offer a value the store would refuse. The words shown are
 * here rather than in the store, because the store is about validity and
 * this is about reading.
 */
const SETTING_WORDS = {
  units: { imperial: 'Miles and feet', metric: 'Kilometres and metres' },
  temperature: { fahrenheit: 'Fahrenheit', celsius: 'Celsius' },
  theme: { system: 'Follow my device', light: 'Light', dark: 'Dark' },
};

PAGES.settings = async (page) => {
  for (const group of $$('[data-setting]', page)) {
    drawSettingChoice(group);
  }
};

function drawSettingChoice(group) {
  const name = group.dataset.setting;
  const words = SETTING_WORDS[name] || {};
  const current = SonoranSettings.get(name);
  replace(group, SonoranSettings.options(name).map((value) => el('button', {
    type: 'button',
    role: 'radio',
    class: `settings-option${value === current ? ' active' : ''}`,
    'aria-checked': String(value === current),
    // Only the chosen option takes a tab stop; the arrows move between
    // them. That is how a radio group behaves, and a row of buttons each
    // taking a stop is the usual way this control is got wrong.
    tabindex: value === current ? '0' : '-1',
    text: words[value] || value,
    onclick: () => applySetting(name, value, group),
    onkeydown: (event) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      if (!step) return;
      event.preventDefault();
      const list = SonoranSettings.options(name);
      const next = list[(list.indexOf(current) + step + list.length) % list.length];
      applySetting(name, next, group);
      const moved = $('.settings-option.active', group);
      if (moved) moved.focus();
    },
  })));
}

/*
 * Apply a setting, and show the result.
 *
 * The theme is the one that cannot just re-render: the colours come from
 * an attribute on `<html>` that a script sets before paint, and the
 * `system` option has to start following the device again. Setting the
 * attribute here rather than reloading keeps the choice instant, and the
 * page the reader is on.
 */
function applySetting(name, value, group) {
  if (!SonoranSettings.set(name, value)) return;
  drawSettingChoice(group);
  if (name === 'theme') applyTheme(value);
  // Everything else is a formatting change, so redrawing the page the
  // reader came from is enough -- and the settings page itself shows no
  // distances, so this is for when they navigate back.
  else render(currentPage);
}

function applyTheme(mode) {
  const root = document.documentElement;
  root.setAttribute('data-theme-mode', mode);
  if (mode === 'system') {
    const light = window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches;
    root.setAttribute('data-theme', light ? 'light' : 'dark');
  } else {
    root.setAttribute('data-theme', mode);
  }
}

function wirePresetSwitch() {
  const holder = $('[data-preset-switch]');
  if (!holder || !window.SonoranPreset) return;

  const draw = () => {
    const current = SonoranPreset.current();
    const options = SonoranPreset.options();
    /*
     * The thumb's size and position, for the CSS (§3.5).
     *
     * CSS cannot count its own children or say which one has a class, so
     * the two numbers it needs are published here. The index is clamped at
     * 0: `indexOf` answers -1 for a preset that is no longer on offer,
     * and -1 would park the thumb one whole position off the left of the
     * track -- visible, wrong, and pointing at nothing.
     */
    holder.style.setProperty('--preset-count', String(Math.max(1, options.length)));
    holder.style.setProperty('--preset-index', String(Math.max(0, options.indexOf(current))));
    replace(holder, options.map((name) => el('button', {
      type: 'button',
      role: 'radio',
      class: `preset-choice${name === current ? ' active' : ''}`,
      'aria-checked': String(name === current),
      /*
       * Only the chosen button is reachable by Tab, and the arrow keys
       * move between them. That is how a radio group behaves, and a row
       * of buttons that each take a tab stop is the usual way this
       * control is got wrong.
       */
      tabindex: name === current ? '0' : '-1',
      text: SonoranLabels.presetLabel(name),
      onclick: () => { if (SonoranPreset.set(name)) draw(); },
      onkeydown: (event) => {
        const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
        const step = keys[event.key];
        if (!step) return;
        event.preventDefault();
        const list = options;
        const next = list[(list.indexOf(current) + step + list.length) % list.length];
        if (SonoranPreset.set(next)) draw();
        const moved = $(`[data-preset-switch] .preset-choice.active`);
        if (moved) moved.focus();
      },
    })));
  };

  draw();
  // A change from anywhere -- another tab's storage, or the available
  // list narrowing -- redraws the control and the page under it.
  SonoranPreset.onChange(() => {
    draw();
    render(currentPage);
  });

  /*
   * A setting changed in ANOTHER tab. `applySetting` already redraws for
   * the control on this page; this is the other tab's half.
   *
   * The theme is excluded because it needs no redraw -- `applyTheme` sets
   * an attribute on <html> and the CSS follows -- and redrawing on it
   * would throw away a table's scroll position for a colour change.
   */
  if (window.SonoranSettings) {
    SonoranSettings.onChange((name) => {
      if (name === 'theme') return;
      render(currentPage);
    });
  }
}

/*
 * The theme control moved to the settings page (Will, 2026-09-26).
 *
 * `wireTheme` wired a three-state cycle button in the menu footer. It is
 * gone, and so is this function's body: `$('[data-theme-choice]')` would
 * now return null and the next line would throw, which is the fourth time
 * this session a removed control has left a live reference behind.
 *
 * What the old button did that is still needed, and now lives in
 * `applySetting`: `system` has to keep following the device, so choosing
 * it re-reads `prefers-color-scheme` rather than freezing whatever was on
 * screen. The pre-paint script in `index.html` still does the same on
 * load, which is why there is no flash.
 *
 * The system-change listener stays here, because it belongs to the page
 * rather than to any control: with `system` chosen, the device switching
 * from light to dark has to be followed.
 */
function wireTheme() {
  const mode = document.documentElement.getAttribute('data-theme-mode') || 'system';
  if (mode === 'system' && window.matchMedia) {
    matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => location.reload());
  }
}

function wire() {
  wirePresetSwitch();
  wireTheme();
  wireFamilyFilter();
  for (const button of $$('[data-chat-view-choice]')) {
    button.addEventListener('click', () => {
      if (currentChatChannel) location.hash = chatHref(currentChatChannel, button.dataset.chatViewChoice).slice(1);
    });
  }
  for (const button of $$('.toggle')) {
    // A toggle that changes only how the page is drawn carries
    // `data-no-refresh` and wires itself. The Motion toggle is one: it
    // changes the animation, not the data, and a refetch for it would be
    // a request nobody asked for.
    if (button.hasAttribute('data-no-refresh')) continue;
    button.addEventListener('click', () => {
      const pressed = button.getAttribute('aria-pressed') === 'true';
      button.setAttribute('aria-pressed', String(!pressed));
      render(currentPage);
    });
  }
  for (const control of $$('select[data-traffic-minutes], select[data-graph-hours], select[data-node-hours], select[data-meshnet-weeks], select[data-node-active], select[data-node-role], select[data-graph-view], select[data-graph-layout]')) {
    control.addEventListener('change', () => render(currentPage));
  }

  /*
   * The chat range (§6.1).
   *
   * `change`, not `input`. A `datetime-local` fires `input` on every
   * keystroke, so paging the whole conversation would start again after
   * each digit of a year.
   *
   * The range goes into the address first and the page is drawn from the
   * address, so there is exactly one place the range lives. A control that
   * kept its own copy could disagree with a shared link, which is how the
   * gaps page's preset used to get lost on reload (#177).
   */
  for (const box of $$('[data-chat-from], [data-chat-to]')) {
    box.addEventListener('change', () => {
      const page = $('[data-page="chat"]');
      const from = $('[data-chat-from]', page).value;
      const to = $('[data-chat-to]', page).value;
      /*
       * An empty box is not a date, and the two ends mean different
       * things when empty: no `from` falls back to the default span, no
       * `to` means "up to now" and lets live keep filling.
       */
      chatWriteRange(from ? new Date(from) : null, to ? new Date(to) : null);
      render('chat');
    });
  }
  /*
   * The date boxes' disclosure (§6.1, phone widths).
   *
   * Only the class is toggled; the fields are in the DOM either way, so
   * `chatDrawRange` keeps filling them and a range arriving from the
   * address is never lost because the reader had not opened the panel.
   */
  for (const toggle of $$('[data-chat-custom-toggle]')) {
    toggle.addEventListener('click', () => {
      const range = toggle.closest('[data-chat-range]');
      if (!range) return;
      const open = range.classList.toggle('show-custom');
      toggle.setAttribute('aria-expanded', String(open));
      if (open) {
        const first = $('[data-chat-from]', range);
        if (first) first.focus();
      }
    });
  }
  for (const button of $$('[data-chat-quick]')) {
    button.addEventListener('click', () => {
      const hours = Number(button.dataset.chatQuick);
      if (!Number.isFinite(hours) || hours <= 0) return;
      // An open end, so the quick ranges stay live. "Last 24 h" that
      // stopped at the moment it was pressed would silently go stale.
      chatWriteRange(new Date(Date.now() - hours * 3600000), null);
      render('chat');
    });
  }
  // Put every node back where the layout wants it, undoing the dragging.
  $('[data-graph-reset]').addEventListener('click', () => {
    graphPinned.clear();
    render('graph');
  });
  /*
   * The Search button is gone (Will, 2026-09-26). Its handler went with
   * it: `$('[data-node-apply]')` would return null and the next call
   * would throw, which is the fifth time in this session a removed
   * control has left a live reference behind.
   *
   * Enter in the search box is wired separately, below, and the box
   * debounces on input -- so nothing was lost but the second ask.
   */
  /* The nodes list pages on as the reader scrolls. */
  wireNodeScroll();

  /* The filter panel. */
  const filterPanel = $('[data-node-filters]');
  const filterToggle = $('[data-node-filter-open]');
  filterToggle.addEventListener('click', () => {
    const open = filterPanel.hidden;
    filterPanel.hidden = !open;
    filterToggle.setAttribute('aria-expanded', String(open));
    if (open) drawNodeFilters($('[data-page="nodes"]'), nodeFacets);
  });
  $('[data-node-filter-apply]').addEventListener('click', () => {
    filterPanel.hidden = true;
    filterToggle.setAttribute('aria-expanded', 'false');
    render('nodes');
  });
  $('[data-node-filter-clear]').addEventListener('click', () => {
    nodeFilters.clear();
    drawNodeFilters($('[data-page="nodes"]'), nodeFacets);
    render('nodes');
  });

  /*
   * The starting points. Each one sets a whole query, because the
   * question somebody arrives with is "which routers have gone quiet",
   * not "role equals ROUTER and last heard is over seven days".
   */
  const NODE_STARTS = {
    'silent-routers': { role: 'ROUTER', active: '', sort: { key: 'last_heard', order: 'asc' } },
    'no-position': { position: 'none', sort: { key: 'last_heard', order: 'desc' } },
    gateways: { gateway: true, sort: { key: 'last_heard', order: 'desc' } },
    newest: { sort: { key: 'first_seen', order: 'desc' } },
    clear: {},
  };
  for (const chip of $$('[data-node-start]')) {
    chip.addEventListener('click', () => {
      const page = $('[data-page="nodes"]');
      const start = NODE_STARTS[chip.dataset.nodeStart] || {};
      // Every chip starts from nothing, so two clicks never compose
      // into a query nobody asked for.
      $('[data-node-search]', page).value = '';
      $('[data-node-role]', page).value = start.role || '';
      $('[data-node-active]', page).value = start.active === undefined ? '24' : start.active;
      // A starting point is a whole query, so it clears the panel too
      // rather than composing with whatever was left in it.
      nodeFilters.clear();
      if (start.position) nodeFilters.set('position', start.position);
      $('[data-node-gateway]', page).setAttribute('aria-pressed', start.gateway ? 'true' : 'false');
      nodeSort = start.sort || { key: 'last_heard', order: 'desc' };
      render('nodes');
    });
  }
  /*
   * Both search boxes look the same, so both behave the same.
   *
   * The graph box filtered as it was typed and the nodes box waited for
   * Enter or for the button beside it, with nothing on either one to
   * say so. The graph filters a list the browser already holds; the
   * nodes box asks the server, and that list is in the thousands, so it
   * waits for a pause in the typing rather than firing per keystroke.
   *
   * This paragraph used to end "the button stays for the people who look
   * for a button". It does not: Will had it removed on 2026-09-26, and
   * the comment outlived the control by a commit. Enter is handled below
   * because the button was its affordance.
   */
  const NODE_SEARCH_PAUSE_MS = 350;
  let nodeSearchTimer = null;
  $('[data-node-search]').addEventListener('input', () => {
    clearTimeout(nodeSearchTimer);
    nodeSearchTimer = setTimeout(() => render('nodes'), NODE_SEARCH_PAUSE_MS);
  });
  $('[data-node-search]').addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    clearTimeout(nodeSearchTimer);
    render('nodes');
  });
  $('[data-graph-search]').addEventListener('input', () => render('graph'));
  $('[data-meshnet-apply]').addEventListener('click', () => render('meshnet'));
  /*
   * The firehose controls write the address; the address draws the page.
   *
   * Not `render('firehose')`. The filter is in the fragment so it can be
   * linked to (§5.1), and a control that re-rendered directly would move
   * the page without moving the URL -- the reader's address bar would
   * then describe the view they had before they touched anything.
   *
   * `goFirehose` exists because assigning a hash that is already there
   * fires no `hashchange`, so pressing Filter twice would do nothing the
   * second time. That is a one-line trap that reads as "the button is
   * broken".
   */
  const goFirehose = () => {
    const page = $('[data-page="firehose"]');
    const typed = $('[data-firehose-portnum]', page).value.trim();
    const hours = $('[data-firehose-hours]', page).value;
    const href = firehoseHref(portnumWire(typed), hours);
    if (location.hash === href) render('firehose');
    else location.hash = href.slice(1);
  };
  $('[data-firehose-apply]').addEventListener('click', goFirehose);
  $('[data-firehose-hours]').addEventListener('change', goFirehose);
  // Enter in the filter box, because a box beside a button is still a
  // box somebody types into and presses Enter in.
  $('[data-firehose-portnum]').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') goFirehose();
  });

  // Show the brand mark only when the image file exists. Until then the
  // text wordmark stays, so the sidebar never shows a broken image.
  // A cached image can finish loading before this runs, so check
  // `complete` as well as listening for the event.
  const mark = $('[data-brand-mark]');
  if (mark) {
    const reveal = () => {
      mark.style.display = 'block';
      const text = $('[data-brand-text]');
      // Off the screen, not out of the tree. `hidden` here took the only
      // h1 on the page away and left an image in its place, so on every
      // deployment that ships a logo the document had no heading at all.
      if (text) text.classList.add('sr-only');
    };
    if (mark.complete && mark.naturalWidth > 0) reveal();
    else mark.addEventListener('load', reveal);
  }

  /*
   * The "Open mesh-graph" link was wired here and is gone (Will,
   * 2026-09-26).
   *
   * That was the LAST use of `CONFIG.graphBaseUrl` in the browser --
   * checked, because the first version of this comment claimed the value
   * was still needed for an embedded frame and there is no frame: the
   * graph page draws its own ECharts, and the node page's "Open in
   * mesh-graph" link uses `detail.graph.node_graph`, a URL the server
   * builds.
   *
   * The SETTING is still live and must not be removed with the link:
   * `mesh_graph_base_url` feeds the CSP's frame-src and img-src in
   * `api/app.py`, and the server builds that node link from it.
   * `graphBaseUrl` in the config JSON is now unread by this file, which
   * is worth knowing before anybody prunes it.
   */

  wireNav();
}

/*
 * The fourteen nav links, behind a button on a phone.
 *
 * Stacked at phone width the nav wrapped to seven rows, and with the
 * wordmark and the status line above and below it that was about
 * 1230 CSS px of navigation before the page heading — on every page.
 * The firehose filter and the first packet were both below the fold
 * before anything had been read.
 *
 * The button is `hidden` in the markup and unhidden here, so a browser
 * that never runs this script keeps every link on the page rather than
 * losing the navigation behind a control that cannot open. The
 * breakpoint is the 60rem one the shell already restacks at, read
 * through `matchMedia` so the CSS and the script cannot drift.
 */
function wireNav() {
  const toggle = $('[data-nav-toggle]');
  const nav = $('#site-nav');
  // The menu holds the nav, the status and the theme switch (#175), so
  // the button opens all three rather than the links alone.
  const menu = $('#site-menu') || nav;
  if (!toggle || !nav) return;
  const narrow = matchMedia('(max-width: 60rem)');

  const setOpen = (open) => {
    toggle.setAttribute('aria-expanded', String(open));
    menu.hidden = !open;
    $('use', toggle).setAttribute('href', open ? '#i-menu-close' : '#i-menu');
  };

  const apply = () => {
    // Wide: no button, and the nav is always there. Narrow: the button
    // appears and the nav starts closed.
    toggle.hidden = !narrow.matches;
    setOpen(!narrow.matches);
  };

  toggle.addEventListener('click', () => {
    setOpen(toggle.getAttribute('aria-expanded') !== 'true');
  });
  /*
   * Choosing a page is the end of the menu's job.
   *
   * On the MENU, not on the nav. It was on the nav, which worked for as
   * long as every route out of the menu was a nav entry. It stopped the
   * day Settings became a footer link and its nav entry was removed:
   * tapping it on a phone routed to the page and left the menu standing
   * open on top of it, so the reader saw the same list they had just
   * chosen from and the page they asked for was a full screen below.
   * Measured before the fix -- aria-expanded stayed "true" at 320 px.
   *
   * `#site-menu` holds the nav AND the footer, so any link in either
   * closes it. The preset switch is buttons rather than links and the
   * status line has no anchor, so nothing else in here can match.
   */
  menu.addEventListener('click', (event) => {
    if (narrow.matches && event.target.closest('a')) setOpen(false);
  });
  /*
   * Escape closes it and gives the focus back to the control that
   * opened it, so a keyboard is never left in a list that has gone.
   *
   * The listener goes on the pair rather than on the nav. Opening the
   * menu leaves the focus on the button, which is not inside the nav,
   * so a listener on the nav alone never saw the key — Escape did
   * nothing at all until the first Tab. `.sidebar` holds both.
   */
  const region = toggle.closest('.sidebar') || document;
  region.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !narrow.matches) return;
    if (toggle.getAttribute('aria-expanded') !== 'true') return;
    setOpen(false);
    toggle.focus();
  });
  narrow.addEventListener('change', apply);
  apply();
}

/* The page the nav button says you are on, so the answer does not need
   the menu opened for it. */
function markNavHere(known) {
  const here = $('[data-nav-here]');
  if (!here) return;
  const link = $(`[data-nav="${known}"]`);
  here.textContent = link ? link.textContent.trim() : '';
}

addEventListener('hashchange', route);
wire();
scheduleLive();
route();
