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

async function get(path) {
  const response = await fetch(api(path));
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

/**
 * Run several requests together.
 * A failed request becomes null. A null path stays null and makes no
 * request, so a caller can skip one item of a set.
 */
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
  gateway: colour('role-gateway', '#ff8c42'),
  router: colour('role-router', '#8cb369'),
  client: colour('role-client', '#edc04b'),
  stale: colour('role-stale', '#7d6857'),
};

/** Return the colour for a signal quality, or the accent when unknown. */
function snrColour(snr) {
  if (snr == null) return PALETTE.accent;
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

const CELSIUS = (value) => (value == null ? null : `${round(value, 1)} C`);

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

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function replace(target, ...children) {
  if (!target) return;
  target.replaceChildren(...children.flat().filter((child) => child != null));
}

const empty = (message) => el('p', { class: 'empty', text: message });
const failure = (error) => el('p', { class: 'error', text: error.message || String(error) });

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

/** Build a table from column definitions and rows. */
function table(columns, rows, emptyMessage = 'No data.') {
  if (!rows || !rows.length) return empty(emptyMessage);
  const head = el('tr', {}, columns.map((column) =>
    el('th', { class: column.num ? 'num' : null, text: column.label })));
  const body = rows.map((row) =>
    el('tr', {}, columns.map((column) => {
      const value = column.cell(row);
      return el('td', { class: [column.num ? 'num' : '', column.wrap ? 'wrap' : ''].join(' ').trim() || null },
        value && value.nodeType ? value : el('span', { text: value == null ? '-' : String(value) }));
    })));
  return el('table', {}, el('thead', {}, head), el('tbody', {}, body));
}

function statTile(label, value, delta) {
  return el('div', { class: 'panel' },
    el('div', { class: 'stat' },
      el('span', { class: 'value', text: value }),
      el('span', { class: 'label', text: label }),
      delta ? el('span', { class: 'delta', text: delta }) : null));
}

/** Render an SNR value with its quality colour. */
const snrCell = (snr) =>
  snr == null
    ? el('span', { class: 'muted', text: '-' })
    : el('span', { class: `snr ${snrClass(snr)}`, text: `${round(snr, 1)} dB` });

/** Split a message body so hashtags are highlighted. */
function messageBody(text) {
  const node = el('span', { class: 'body' });
  for (const part of String(text ?? '').split(/(#[A-Za-z0-9_]+)/g)) {
    if (!part) continue;
    node.append(part.startsWith('#') ? el('span', { class: 'hash', text: part }) : part);
  }
  return node;
}

/**
 * Render the tapback reactions on one message.
 * The phone apps send a tapback as a text message carrying the emoji,
 * so the API groups them and the page shows one chip per emoji.
 */
function reactionChips(reactions) {
  if (!reactions || !reactions.length) return null;
  return el('div', { class: 'reactions' }, reactions.map((reaction) =>
    el('span', { class: 'reaction' },
      el('span', { class: 'glyph', text: reaction.emoji }),
      // Name everyone who sent this emoji. Each name opens the node,
      // and the tapback's own packet can be opened beside it.
      el('span', { class: 'who' }, (reaction.senders || []).flatMap((sender, index) => [
        index ? el('span', { class: 'sep', text: ',' }) : null,
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
              text: '\u2197',
            }),
      ])))));
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
function messageItem(message, options = {}) {
  const direct = message.to_node && message.to_node !== '^all';
  return el('li', { class: direct ? 'dm' : null },
    replyQuote(message.reply_to),
    el('div', { class: 'who' },
      el('button', {
        class: 'linky name', type: 'button', title: message.from_node,
        onclick: () => openNode(message.from_node),
        text: message.from_name || message.from_node,
      }),
      options.showChannel && message.channel
        ? el('span', { class: 'tag', text: message.channel }) : null,
      message.packet_id == null
        ? el('time', { datetime: message.seen_at || '', title: stamp(message.seen_at),
            text: `${ago(message.seen_at)} ago` })
        : el('a', {
            class: 'linky', title: `Open packet ${message.packet_id}`,
            href: `#packet/${encodeURIComponent(message.from_node)}/${message.packet_id}`,
            text: `${ago(message.seen_at)} ago`,
          })),
    messageBody(message.body),
    reactionChips(message.reactions));
}

/* ECharts instances are kept so a redraw does not leak canvases. */
const charts = new Map();

function chart(target, option) {
  if (!target) return null;
  let instance = charts.get(target);
  if (!instance || instance.isDisposed()) {
    instance = echarts.init(target, null, { renderer: 'canvas' });
    charts.set(target, instance);
  }
  instance.setOption(option, true);
  return instance;
}

const CHART_BASE = {
  backgroundColor: 'transparent',
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
  for (const instance of charts.values()) {
    if (!instance.isDisposed()) instance.resize();
  }
});

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
  replace(target,
    statTile('Nodes', count(stats.node_count), delta('node_count')),
    statTile('Packets', count(stats.packet_count), delta('packet_count')),
    statTile('Observations', count(stats.observation_count), delta('observation_count')),
    statTile('Gateways', count(stats.gateway_count), delta('gateway_count')));
}

async function loadTopTalkers(page) {
  const target = $('[data-top-talkers]', page);
  if (!target) return;
  const rows = await get('api/stats/top?hours=24&limit=15').catch(() => null);
  if (!rows) return replace(target, failure(new Error('Cannot load the busiest nodes.')));
  replace(target, table([
    { label: 'Node', cell: (row) => nodeChip(row) },
    { label: 'Packets', num: true, cell: (row) => count(row.packet_count) },
  ], rows, 'No packets in the window.'));
}

const PAGES = {};

PAGES.dashboard = async (page) => {
  await Promise.all([loadSummary(page), loadTopTalkers(page)]);
  const [nodes, messages, portnums] = await getAll([
    'api/nodes?limit=15&active_hours=24',
    'api/chat?limit=12',
    'api/stats/portnums',
  ]);

  replace($('[data-recent-nodes]', page), nodes
    ? table([
        { label: 'Node', cell: (row) => nodeChip(row) },
        { label: 'Role', cell: (row) => row.role || '-' },
        { label: 'Heard', num: true, cell: (row) => `${ago(row.last_heard)} ago` },
      ], nodes, 'No nodes heard yet.')
    : failure(new Error('Cannot load nodes.')));

  replace($('[data-recent-chat]', page), messages
    ? (messages.length
        ? messages.map((message) => messageItem(message, { showChannel: true }))
        : [empty('No messages stored.')])
    : [failure(new Error('Cannot load messages.'))]);

  if (portnums && portnums.length) {
    const top = [...portnums].sort((a, b) => b.count - a.count).slice(0, 10).reverse();
    chart($('[data-portnum-chart]', page), {
      ...CHART_BASE,
      tooltip: { ...CHART_BASE.tooltip, trigger: 'item' },
      xAxis: { type: 'value', ...AXIS },
      yAxis: { type: 'category', data: top.map((row) => row.name || String(row.portnum)), ...AXIS },
      series: [{ type: 'bar', data: top.map((row) => row.count), itemStyle: { color: PALETTE.accent, borderRadius: [0, 3, 3, 0] } }],
    });
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
 * Every device role the firmware knows, in the order the legend shows
 * them: the routing roles first, then the clients, then the rest.
 *
 * The colours live in app.css so the stylesheet stays the one source of
 * the palette. A role that is not in this list still draws, in the
 * muted colour, so a new firmware role never leaves an invisible node.
 */
const ROLES = [
  { key: 'ROUTER', label: 'Router' },
  { key: 'ROUTER_LATE', label: 'Router late' },
  { key: 'ROUTER_CLIENT', label: 'Router client' },
  { key: 'REPEATER', label: 'Repeater' },
  { key: 'CLIENT', label: 'Client' },
  { key: 'CLIENT_MUTE', label: 'Client mute' },
  { key: 'CLIENT_BASE', label: 'Client base' },
  { key: 'CLIENT_HIDDEN', label: 'Client hidden' },
  { key: 'CLIENT_TAK', label: 'Client TAK' },
  { key: 'TAK_TRACKER', label: 'TAK tracker' },
  { key: 'TAK_PLUGIN', label: 'TAK plugin' },
  { key: 'ATAK_PLUGIN', label: 'ATAK plugin' },
  { key: 'TRACKER', label: 'Tracker' },
  { key: 'SENSOR', label: 'Sensor' },
  { key: 'LOST_AND_FOUND', label: 'Lost and found' },
];

const ROLE_LABELS = new Map(ROLES.map((role) => [role.key, role.label]));
const roleColour = (role) => colour(`role-${role}`, PALETTE.muted);

/** The label for a role, or a readable form of an unknown one. */
function roleLabel(role) {
  if (!role) return 'No role reported';
  return ROLE_LABELS.get(role) || role.replace(/_/g, ' ').toLowerCase();
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
function nodeStyle(node) {
  const fill = nodeColour(node);
  const stale = isStale(node);
  return {
    radius: node.is_mqtt_gateway ? 7 : 5,
    // A gateway wears a bright ring. Everything else outlines in its
    // own colour, so the role stays the thing the eye picks up.
    color: node.is_mqtt_gateway ? PALETTE.text : fill,
    weight: node.is_mqtt_gateway ? 2.5 : 1.5,
    fillColor: fill,
    fillOpacity: stale ? 0.15 : 0.6,
    opacity: stale ? 0.35 : 1,
  };
}

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
    el('span', { class: 'legend-note' }, el('span', { class: 'line neighbour' }), 'Neighbour link'),
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

function ensureMap() {
  if (mapState.map) return mapState.map;
  const map = L.map('map', { preferCanvas: true, worldCopyJump: true })
    .setView(CONFIG.mapCenter || [34.0, -111.5], CONFIG.mapZoom || 7);
  if (CONFIG.tileUrl) {
    L.tileLayer(CONFIG.tileUrl, {
      attribution: CONFIG.tileAttribution || '',
      maxZoom: 19,
    }).addTo(map);
  }
  mapState.nodes = L.layerGroup().addTo(map);
  mapState.traffic = L.layerGroup().addTo(map);
  mapState.traces = L.layerGroup().addTo(map);
  mapState.links = L.layerGroup();
  mapState.map = map;
  return map;
}

function drawMapNodes(rows) {
  mapState.nodes.clearLayers();
  const bounds = [];
  for (const row of rows) {
    if (row.lat == null || row.lon == null) continue;
    if (!passesRoleFilter(row)) continue;
    bounds.push([row.lat, row.lon]);
    const marker = L.circleMarker([row.lat, row.lon], nodeStyle(row));
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

/** A port number as a short label, without the shouting. */
function portnumLabel(portnum) {
  if (!portnum) return 'packet';
  return String(portnum).replace(/_APP$/, '').replace(/_/g, ' ').toLowerCase();
}

/*
 * The live traffic layer.
 *
 * An observation is drawn as it arrives and then goes away again. The
 * layer used to redraw the whole window on every refresh, which built a
 * standing mat of hundreds of lines and said nothing about what was
 * happening now.
 *
 * A direct observation is a real radio link: the sender and the gateway
 * heard each other with no hop between them. It draws as a solid line
 * in its signal colour.
 *
 * A relayed observation is not a link. The packet reached the gateway
 * through other nodes, so the straight line crosses ground the signal
 * never took. It draws dashed with an arrow head, which says "this
 * packet ended up here" rather than "these two can hear each other".
 * Most observations are relayed. See AGENTS.md 9.5.
 */
const TRAFFIC_VISIBLE_MS = 7000;
const TRAFFIC_FADE_MS = 2500;
const DIRECT_OPACITY = 0.95;
const RELAYED_OPACITY = 0.7;

const trafficSeen = new Set();

/**
 * Build an arrow head partway along a line, pointing at its end.
 *
 * Leaflet draws no arrows, so this is two short segments in a V. The
 * shape is worked out in screen pixels and put back into coordinates,
 * because a chevron built in degrees would lean over as latitude
 * changes. It is sized for the zoom it was drawn at, and these lines
 * live only a few seconds, so a zoom during one leaves it a little off.
 */
function arrowHead(map, from, to, options) {
  const start = map.latLngToLayerPoint(from);
  const end = map.latLngToLayerPoint(to);
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const length = Math.hypot(dx, dy);
  if (length < 12) return null;

  // Two thirds along, so it does not sit under either node marker.
  const tip = L.point(start.x + dx * 0.66, start.y + dy * 0.66);
  const angle = Math.atan2(dy, dx);
  const size = 9;
  const spread = 0.45;
  const wing = (turn) =>
    map.layerPointToLatLng(
      L.point(
        tip.x - size * Math.cos(angle + turn),
        tip.y - size * Math.sin(angle + turn),
      ),
    );
  return L.polyline([wing(spread), map.layerPointToLatLng(tip), wing(-spread)], options);
}

/** Draw one observation, hold it, then fade it off the map. */
function flashTraffic(event) {
  const direct = event.direct === true;
  const from = L.latLng(event.from.lat, event.from.lon);
  const to = L.latLng(event.gateway.lat, event.gateway.lon);
  const style = {
    color: direct ? snrColour(event.snr) : PALETTE.relayed,
    weight: direct ? 2.5 : 1.8,
    opacity: direct ? DIRECT_OPACITY : RELAYED_OPACITY,
    dashArray: direct ? null : '6 5',
  };

  const parts = [L.polyline([from, to], style)];
  if (!direct) {
    // The arrow marks the direction the packet travelled, and marks the
    // line as a path rather than a link.
    const head = arrowHead(mapState.map, from, to, { ...style, dashArray: null, weight: 2 });
    if (head) parts.push(head);
  }
  for (const part of parts) part.addTo(mapState.traffic);

  parts[0].bindTooltip(
    `${portnumLabel(event.portnum)} from ${event.from.display_name}, ` +
    `heard by ${event.gateway.display_name}` +
    (direct
      ? `, direct${event.snr == null ? '' : `, ${round(event.snr, 1)} dB`}`
      : ', relayed, so this is a path and not a radio link') +
    '. Click for the packet.',
  );
  for (const part of parts) {
    part.on('click', () => { location.hash = packetHref(event).slice(1); });
  }

  const steps = 12;
  const start = direct ? DIRECT_OPACITY : RELAYED_OPACITY;
  for (let step = 1; step <= steps; step += 1) {
    mapLater(() => {
      for (const part of parts) {
        if (step === steps) mapState.traffic.removeLayer(part);
        else part.setStyle({ opacity: start * (1 - step / steps) });
      }
    }, TRAFFIC_VISIBLE_MS + (step * TRAFFIC_FADE_MS) / steps);
  }
}

/**
 * Flash every observation that has not been shown yet.
 *
 * The first pass only records what is already in the window, so opening
 * the page does not fire fifteen minutes of traffic at once.
 */
function flashNewTraffic(events, firstPass) {
  let started = 0;
  for (const event of events) {
    const key = `${event.packet_id}-${event.gateway.node_id}-${event.time}`;
    const known = trafficSeen.has(key);
    trafficSeen.add(key);
    if (known || !event.has_line || firstPass) continue;
    flashTraffic(event);
    started += 1;
  }
  // The set would otherwise grow for as long as the tab is open.
  if (trafficSeen.size > 4000) {
    for (const key of [...trafficSeen].slice(0, 2000)) trafficSeen.delete(key);
  }
  return started;
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
    L.polyline([a, b], {
      color: PALETTE.link,
      weight: 1.2,
      opacity: 0.38,
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
const traceSeen = new Set();
const mapTimers = new Set();

/** Run something later, and remember the timer so it can be cancelled. */
function mapLater(action, delay) {
  const timer = setTimeout(() => {
    mapTimers.delete(timer);
    action();
  }, delay);
  mapTimers.add(timer);
}

/**
 * Cancel every pending fade and clear both live layers.
 *
 * The traffic and traceroute layers share the timer set, so a timer
 * left running would try to restyle a line that has been removed.
 */
function stopMapAnimations() {
  for (const timer of mapTimers) clearTimeout(timer);
  mapTimers.clear();
  if (mapState.traces) mapState.traces.clearLayers();
  if (mapState.traffic) mapState.traffic.clearLayers();
}

/** Draw one hop, hold it, then fade it out and remove it. */
function animateHop(hop, trace, delay) {
  mapLater(() => {
    const line = L.polyline(
      [[hop.from.lat, hop.from.lon], [hop.to.lat, hop.to.lon]],
      { color: snrColour(hop.snr), weight: 3, opacity: 0.95 },
    ).addTo(mapState.traces);
    line.bindTooltip(
      `${hop.from.display_name} to ${hop.to.display_name}` +
      (hop.snr == null ? ', signal not measured' : `, ${round(hop.snr, 1)} dB`) +
      '. Click for the whole traceroute.',
    );
    // Clickable while it is on the map. The same trace stays in the
    // side list afterwards, which is the part that does not expire.
    if (trace && trace.id != null) line.on('click', () => openTraceroute(trace.id));

    // Fade, then take it off the map. Leaving it would slowly turn the
    // live layer into the same standing mat of old lines this replaced.
    const steps = 24;
    for (let step = 1; step <= steps; step += 1) {
      mapLater(() => {
        if (step === steps) mapState.traces.removeLayer(line);
        else line.setStyle({ opacity: 0.95 * (1 - step / steps) });
      }, TRACE_HOLD_MS + (step * TRACE_FADE_MS) / steps);
    }
  }, delay);
}

const TRACE_STEP_MS = 220;
/* A hop is held, then fades. Together these keep a path on the map
 * for about eight seconds, and the longest paths for about ten. */
const TRACE_HOLD_MS = 3000;
const TRACE_FADE_MS = 5000;

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
function drawTraceroutes(traces, firstPass) {
  let started = 0;
  let seeded = 0;
  for (const trace of traces) {
    const key = trace.trace_id || `${trace.time}-${trace.from.node_id}`;
    const known = traceSeen.has(key);
    traceSeen.add(key);
    if (known) continue;

    const drawable = trace.hops.filter((hop) => hop.has_line);
    if (!drawable.length) continue;

    if (firstPass) {
      if (seeded >= TRACE_SEED) continue;
      // Stagger the seeded ones so they read as separate paths.
      drawable.forEach((hop, index) =>
        animateHop(hop, trace, seeded * 900 + index * TRACE_STEP_MS));
      seeded += 1;
      continue;
    }
    drawable.forEach((hop, index) => animateHop(hop, trace, index * TRACE_STEP_MS));
    started += 1;
  }
  started += seeded;
  // The set would otherwise grow for as long as the tab is open.
  if (traceSeen.size > 2000) {
    for (const key of [...traceSeen].slice(0, 1000)) traceSeen.delete(key);
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
async function linkChannelOptions(page) {
  const wrap = $('[data-link-channel-wrap]', page);
  const select = $('[data-link-channel]', page);
  const list = await get('api/graph/channels?hours=24').catch(() => null);
  const channels = (list && list.channels) || [];
  if (!channels.length) {
    wrap.hidden = true;
    return null;
  }
  if (!channels.some((item) => item.channel === linkChannel)) {
    linkChannel = channels[0].channel;
  }
  const wanted = channels.map((item) => `${item.channel}:${item.tier}`).join('|');
  if (select.dataset.filled !== wanted) {
    /*
     * Core first, extra second.
     *
     * Core is the mesh proper: the modem presets and the channels this
     * deployment claims as its own. Extra is everything running beside
     * it, such as the weather and trivia channels. Without the split
     * the mesh is buried among them.
     */
    const option = (item) =>
      el('option', {
        value: item.channel,
        // Packets, not link reports. The busiest layer on this page is
        // the traffic one, and mixing the two units in one list makes a
        // quiet channel look busier than a loud one.
        text: `${item.label} (${count(item.packet_count || 0)})`,
      });
    const tier = (name, items) =>
      items.length ? el('optgroup', { label: name }, items.map(option)) : null;
    replace(select, [
      tier('Core', channels.filter((item) => item.tier === 'core')),
      tier('Extra', channels.filter((item) => item.tier !== 'core')),
    ]);
    select.dataset.filled = wanted;
  }
  select.value = linkChannel;
  wrap.hidden = false;
  return linkChannel;
}

PAGES.map = async (page) => {
  const map = ensureMap();
  setTimeout(() => map.invalidateSize(), 0);

  const minutes = $('[data-traffic-minutes]', page).value || '15';
  const showTraffic = $('[data-show-traffic]', page).getAttribute('aria-pressed') === 'true';
  const showLinks = $('[data-show-links]', page).getAttribute('aria-pressed') === 'true';
  const showTraces = $('[data-show-traces]', page).getAttribute('aria-pressed') === 'true';

  const channel = await linkChannelOptions(page);

  const nodes = await get('api/map/nodes').catch(() => null);
  if (!nodes) return;
  const [traffic, edges, traces] = await getAll([
    showTraffic
      ? `api/map/traffic?minutes=${minutes}&limit=400` +
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

  // Held so the legend filter can redraw without another request.
  mapState.lastNodes = nodes;
  const bounds = drawMapNodes(nodes);
  drawMapLegend($('[data-map-legend]', page), nodes);
  if (bounds.length && !mapState.fitted) {
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 11 });
    mapState.fitted = true;
  }

  const positions = new Map(
    nodes.filter((row) => row.lat != null && row.lon != null)
      .map((row) => [row.node_id, [row.lat, row.lon]]));

  if (showTraffic && traffic) {
    if (!map.hasLayer(mapState.traffic)) map.addLayer(mapState.traffic);
    const flashed = flashNewTraffic(traffic.events, !mapState.trafficPrimed);
    mapState.trafficPrimed = true;
    const direct = traffic.direct_count || 0;
    $('[data-traffic-summary]', page).textContent =
      `${count(traffic.event_count)} observations in ${traffic.window_minutes} min, ` +
      `${count(direct)} direct.` + (flashed ? ` ${count(flashed)} drawing.` : '');
    replace($('[data-traffic-feed]', page),
      traffic.events.length
        ? traffic.events.slice(0, 40).map((event) => el('li', {},
            el('div', {}, nodeChip(event.from)),
            el('div', { class: 'meta' },
              el('span', { text: `via ${event.gateway.display_name}` }),
              event.snr != null ? snrCell(event.snr) : null,
              // A relayed observation is not evidence of a radio link.
              el('span', { class: event.direct ? 'tag router' : 'tag',
                text: event.direct ? 'direct' : 'relayed' }),
              // The packet itself, so the whole record is one click away.
              el('a', {
                class: 'linky',
                href: packetHref(event),
                text: portnumLabel(event.portnum),
              }),
              el('span', { text: clock(event.time) }))))
        : [empty('No traffic in the window.')]);
  } else {
    map.removeLayer(mapState.traffic);
    mapState.trafficPrimed = false;
    $('[data-traffic-summary]', page).textContent = 'The traffic layer is off.';
    replace($('[data-traffic-feed]', page));
  }

  if (showLinks && edges) {
    const drawn = drawLinks(edges, positions);
    if (!map.hasLayer(mapState.links)) map.addLayer(mapState.links);
    $('[data-link-summary]', page).textContent =
      `${count(drawn)} neighbour links over ${LINK_HOURS} h.`;
  } else {
    if (map.hasLayer(mapState.links)) map.removeLayer(mapState.links);
    $('[data-link-summary]', page).textContent = '';
  }

  if (showTraces && traces) {
    if (!map.hasLayer(mapState.traces)) map.addLayer(mapState.traces);
    const started = drawTraceroutes(traces.traces, !mapState.tracesPrimed);
    mapState.tracesPrimed = true;
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
    stopMapAnimations();
    if (map.hasLayer(mapState.traces)) map.removeLayer(mapState.traces);
    mapState.tracesPrimed = false;
    $('[data-trace-summary]', page).textContent = 'The traceroute layer is off.';
    replace($('[data-trace-feed]', page));
  }
};

/* --- Mesh graph ------------------------------------------------ */

const ROLE_CATEGORIES = [
  { name: 'Gateway', colour: PALETTE.gateway },
  { name: 'Router', colour: PALETTE.router },
  { name: 'Client', colour: PALETTE.client },
  { name: 'Not heard', colour: PALETTE.stale },
];

function graphCategory(node) {
  if (!node.known || ageHours(node.last_heard) > 72) return 3;
  if (node.is_mqtt_gateway) return 0;
  if (node.role && /ROUTER|REPEATER/i.test(node.role)) return 1;
  return 2;
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
function focusNode(data, query) {
  if (query) {
    const found = data.nodes.find((node) =>
      node.display_name.toLowerCase().includes(query)
      || node.node_id.toLowerCase().includes(query));
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

/* The channel the graph page shows. Empty means "not chosen yet". */
let graphChannel = '';

/*
 * The window the graph page last drew. The link page has to ask about
 * the same window, or a click on a link found over seven days goes to a
 * page that only looks at the last day and reports no evidence at all.
 */
let graphHours = '24';

/**
 * Draw one tab for each channel that has mesh links.
 *
 * The channel list also carries channels that only have traffic, so the
 * map can point its live layer at them. Those have no links and would
 * open an empty graph, so this page leaves them out.
 */
function graphTabs(page, all) {
  const target = $('[data-graph-tabs]', page);
  const channels = all.filter((item) => item.link_report_count > 0);
  if (!channels.length) return replace(target);
  if (!channels.some((item) => item.channel === graphChannel)) {
    graphChannel = channels[0].channel;
  }
  replace(target, channels.map((item) =>
    el('button', {
      type: 'button',
      role: 'tab',
      'aria-selected': String(item.channel === graphChannel),
      onclick: () => {
        if (graphChannel === item.channel) return;
        graphChannel = item.channel;
        render('graph');
      },
    },
      el('span', { text: item.label }),
      item.group && item.group !== 'Presets'
        ? el('span', { class: 'group', text: item.group }) : null,
      el('span', { class: 'n', text: count(item.link_report_count) }))));
}

/*
 * The coverage planner lives in planner.js, which loads before this
 * file. It has its own map, its own workers and a vendored WebAssembly
 * engine, so it is kept out of this file.
 */
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
  const allLinks = data.links;
  const confirmed = allLinks.filter((link) => link.snr != null);
  const unconfirmed = allLinks.length - confirmed.length;
  /*
   * A link is confirmed only when the mesh reported a signal reading
   * for it. A traceroute hop with no reading is not proof of a working
   * radio link, so it is hidden by default. The toggle brings those
   * back for anyone who wants to see the raw path data.
   *
   * Nodes left with no visible link are dropped too, so the graph does
   * not show a crowd of unconnected dots.
   */
  data.links = showUnconfirmed ? allLinks : confirmed;

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
  const query = ($('[data-graph-search]', page).value || '').trim().toLowerCase();
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
    + (showUnconfirmed ? '' : unconfirmed ? `, ${count(unconfirmed)} unconfirmed hidden` : '');
  // Links stored before channel tracking mix every preset together, so
  // this one graph does show links that cannot exist. Say so plainly.
  const dotted = $('[data-legend-unconfirmed]', page);
  if (dotted) dotted.hidden = !showUnconfirmed;

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
   * How crowded this graph is, from 0 for a handful of nodes to 1 for a
   * few hundred. `lerp` reads the setting for a small graph and the one
   * for a large graph, and gives the value in between. Every force
   * setting moves together, so the layout keeps one character over the
   * whole range instead of changing at a threshold.
   */
  const crowding = Math.min(1, Math.max(0, (data.nodes.length - 40) / 260));
  const lerp = (small, large) => small + (large - small) * crowding;

  chart(target, {
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: PALETTE.panel, borderColor: PALETTE.line, textStyle: { color: PALETTE.text },
      formatter: (item) => {
        if (item.dataType === 'edge') {
          const snr = item.data.snr == null ? 'no SNR' : `${round(item.data.snr, 1)} dB`;
          return `${item.data.kind} link<br/>${snr}, seen ${item.data.count} times`;
        }
        const node = item.data.raw;
        return [
          `<b>${node.display_name}</b>`,
          node.node_id,
          node.role || 'role unknown',
          node.hw_model || '',
          `${count(node.packet_count)} packets`,
          `heard ${ago(node.last_heard)} ago`,
        ].filter(Boolean).join('<br/>');
      },
    },
    legend: [{ data: ROLE_CATEGORIES.map((category) => category.name), textStyle: { color: PALETTE.muted }, top: 0 }],
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      categories: ROLE_CATEGORIES.map((category) => ({ name: category.name, itemStyle: { color: category.colour } })),
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
        show: data.nodes.length <= 90,
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
        const match = query && node.display_name.toLowerCase().includes(query);
        return {
          id: node.node_id,
          name: node.display_name,
          raw: node,
          category: graphCategory(node),
          symbolSize: (data.nodes.length > 120 ? 3 : 6)
            + (data.nodes.length > 120 ? 9 : 18) * Math.sqrt((node.packet_count || 0) / busiest),
          itemStyle: match ? { borderColor: PALETTE.text, borderWidth: 2 } : undefined,
          label: match ? { show: true } : undefined,
        };
      }),
      // A link with no SNR is still a real link: a packet crossed it.
      // The mesh just did not report a reading for that hop. Draw those
      // faint and dotted so a measured link is never confused with one
      // that was only inferred from a traceroute path.
      links: data.links.map((link) => ({
        source: link.source,
        target: link.target,
        kind: link.kind,
        snr: link.snr,
        count: link.count,
        lineStyle:
          link.snr == null
            ? { width: 0.7, type: 'dotted', opacity: 0.18, color: PALETTE.stale }
            : {
                width: link.kind === 'neighbor' ? 1.8 : 1.1,
                type: link.kind === 'neighbor' ? 'solid' : 'dashed',
                opacity: link.kind === 'neighbor' ? 0.6 : 0.42,
              },
      })),
    }],
  });

  const instance = charts.get(target);
  if (instance && !instance.__wired) {
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

function nodeQuery(page) {
  const params = new URLSearchParams({ limit: '300' });
  const search = $('[data-node-search]', page).value.trim();
  const active = $('[data-node-active]', page).value;
  const role = $('[data-node-role]', page).value;
  const gateway = $('[data-node-gateway]', page).getAttribute('aria-pressed') === 'true';
  if (search) params.set('q', search);
  if (active) params.set('active_hours', active);
  if (role) params.set('role', role);
  if (gateway) params.set('gateway', 'true');
  return `api/nodes?${params}`;
}

PAGES.nodes = async (page) => {
  const target = $('[data-node-table]', page);
  replace(target, el('p', { class: 'loading', text: 'Loading' }));
  const rows = await get(nodeQuery(page)).catch((error) => error);
  if (rows instanceof Error) return replace(target, failure(rows));

  const roleSelect = $('[data-node-role]', page);
  if (roleSelect.options.length <= 1) {
    for (const role of [...new Set(rows.map((row) => row.role).filter(Boolean))].sort()) {
      roleSelect.append(el('option', { value: role, text: role }));
    }
  }

  $('[data-node-count]', page).textContent = `${count(rows.length)} nodes match.`;
  replace(target, table([
    { label: 'Node', cell: (row) => nodeChip(row) },
    { label: 'ID', cell: (row) => el('code', { text: row.node_id }) },
    { label: 'Hardware', cell: (row) => row.hw_model || '-' },
    { label: 'Role', cell: (row) => row.role || '-' },
    {
      label: 'Flags',
      cell: (row) => el('span', {},
        row.is_mqtt_gateway ? el('span', { class: 'tag gateway', text: 'gateway' }) : null,
        row.has_position ? el('span', { class: 'tag', text: 'position' }) : null),
    },
    { label: 'Last heard', num: true, cell: (row) => `${ago(row.last_heard)} ago` },
  ], rows, 'No nodes match the filters.'));
};

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
    el('h3', {}, 'Neighbours',
      el('span', { class: 'muted',
        text: `${count(neighbors.length)} in ${windowHours} h` })),
    el('div', { class: 'table-wrap' }, table([
      { label: 'Node', cell: (row) => nodeChip(row) },
      { label: 'SNR', num: true, cell: (row) => snrCell(row.snr) },
      { label: 'Last RX', num: true, cell: (row) => `${ago(row.last_rx_time || row.time)} ago` },
    ], neighbors, 'This node reports no neighbors.')));
}

function heardByPanel(gateways) {
  return el('div', { class: 'panel' },
    el('h3', {}, 'Heard by',
      el('span', { class: 'muted', text: `${count(gateways.length)} gateways` })),
    el('p', { class: 'notice' },
      'A gateway usually receives a packet after other nodes relayed it. '
      + 'Signal figures below come only from packets that arrived direct, '
      + 'with no hop used.'),
    el('div', { class: 'table-wrap' }, table([
      { label: 'Gateway', cell: (row) => nodeChip(row) },
      { label: 'Relayed', num: true, cell: (row) => count(row.relayed_count) },
      { label: 'Direct', num: true, cell: (row) => count(row.direct_count) },
      { label: 'Avg SNR', num: true, cell: (row) => snrCell(row.avg_snr) },
      { label: 'Best SNR', num: true, cell: (row) => snrCell(row.best_snr) },
      { label: 'Last', num: true, cell: (row) => `${ago(row.last_heard)} ago` },
    ], gateways, 'No gateway heard this node in the window.')));
}

function weatherPanel(detail) {
  const list = definitionList(detail.weather, WEATHER_LABELS);
  return el('div', { class: 'panel' },
    el('h3', {}, 'Weather',
      detail.weather_time ? el('span', { class: 'muted', text: `${ago(detail.weather_time)} ago` }) : null),
    list || empty('This node sends no environment telemetry.'));
}

function devicePanel(detail) {
  const list = definitionList(detail.device, DEVICE_LABELS);
  return el('div', { class: 'panel' },
    el('h3', {}, 'Device',
      detail.device && detail.device.time
        ? el('span', { class: 'muted', text: `${ago(detail.device.time)} ago` }) : null),
    list || empty('This node sends no device telemetry.'));
}

function messagesPanel(detail) {
  const messages = detail.messages.recent || [];
  return el('div', { class: 'panel' },
    el('h3', {}, 'Messages sent',
      el('span', { class: 'muted', text: `${count(detail.messages.count)} in ${detail.window_hours} h` })),
    messages.length
      ? el('ul', { class: 'messages' }, messages.map((message) => messageItem(message, { showChannel: true })))
      : empty('This node sent no stored messages in the window.'));
}

function identityPanel(node) {
  const rows = [
    ['Node ID', node.node_id],
    ['Long name', node.long_name || 'not reported'],
    ['Short name', node.short_name || 'not reported'],
    ['Hardware', node.hw_model || 'unknown'],
    ['Role', node.role || 'unknown'],
    ['Licensed', node.is_licensed ? 'yes' : 'no'],
    ['MQTT gateway', node.is_mqtt_gateway ? 'yes' : 'no'],
    ['Channel', node.last_channel || 'unknown'],
    ['First seen', stamp(node.first_seen)],
    ['Last heard', node.last_heard ? `${stamp(node.last_heard)} (${ago(node.last_heard)} ago)` : 'never'],
  ];
  if (node.position) {
    rows.push(['Position', `${round(node.position.lat, 5)}, ${round(node.position.lon, 5)}`]);
    rows.push(['Altitude', node.position.altitude == null ? 'unknown' : `${node.position.altitude} m`]);
  }
  return el('div', { class: 'panel' },
    el('h3', {}, 'Identity'),
    el('dl', { class: 'kv' }, rows.flatMap(([label, value]) =>
      [el('dt', { text: label }), el('dd', { text: value })])));
}

function activityPanel(detail) {
  return el('div', { class: 'panel' },
    el('h3', {}, 'Activity',
      el('span', { class: 'muted', text: `${count(detail.activity.packet_count)} packets in ${detail.window_hours} h` })),
    el('div', { class: 'table-wrap' }, table([
      { label: 'Packet type', cell: (row) => row.portnum },
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
    target.replaceWith(empty('This node reports no neighbours, so no direct link was measured.'));
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

async function loadNodeDetail(nodeId) {
  const page = $('[data-page="node"]');
  const hours = $('[data-node-hours]', page).value || '24';
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
      el('span', { class: 'muted', text: 'from neighbour reports' })),
    el('div', { class: 'chart', 'data-signal-chart': '' }));

  replace(body, el('div', { class: 'grid two' },
    identityPanel(node),
    weatherPanel(detail),
    devicePanel(detail),
    activityPanel(detail),
    neighborPanel(detail.neighbors, detail.window_hours),
    heardByPanel(detail.heard_by),
    messagesPanel(detail),
    signalPanel));

  await drawSignalChart($('[data-signal-chart]', body), nodeId, hours);
}

PAGES.node = async () => {
  if (currentNodeId) await loadNodeDetail(currentNodeId);
};

/* --- Chat ------------------------------------------------------ */

function channelSection(section) {
  return el('div', { class: 'panel' },
    el('h3', { class: 'channel-head' },
      el('span', { class: 'title', text: section.label }),
      el('span', { class: 'muted', text: `${count(section.count)} messages - last ${ago(section.last_seen)} ago` })),
    section.messages.length
      ? el('ul', { class: 'messages' }, section.messages.map((message) => messageItem(message)))
      : empty('No messages in the window.'));
}

PAGES.chat = async (page) => {
  const hours = $('[data-chat-hours]', page).value || '168';
  const body = $('[data-chat-body]', page);
  const data = await get(`api/chat/overview?hours=${hours}`).catch((error) => error);
  if (data instanceof Error) return replace(body, failure(data));
  if (!data.sections.length) {
    return replace(body, empty('No channels have stored messages. Text storage may be off.'));
  }

  const groups = new Map();
  for (const section of data.sections) {
    if (!groups.has(section.group)) groups.set(section.group, []);
    groups.get(section.group).push(section);
  }
  replace(body, [...groups.entries()].map(([group, sections]) =>
    el('div', { class: 'channel-group' },
      el('h3', { text: `${group} (${sections.length})` }),
      el('div', { class: 'grid two' }, sections.map(channelSection)))));
};

/* --- Weekly check-in ------------------------------------------- */

PAGES.meshnet = async (page) => {
  const tag = ($('[data-meshnet-tag]', page).value || 'meshnet').replace(/^#/, '');
  const weeks = $('[data-meshnet-weeks]', page).value || '8';
  const body = $('[data-meshnet-body]', page);
  const data = await get(`api/chat/tagged?tag=${encodeURIComponent(tag)}&weeks=${weeks}`)
    .catch((error) => error);
  if (data instanceof Error) return replace(body, failure(data));
  if (!data.weeks.length) {
    return replace(body, empty(`No message carries ${data.tag} in the window.`));
  }
  replace(body, data.weeks.map((week, index) =>
    el('details', { class: 'week', open: index === 0 },
      el('summary', {},
        el('span', { class: 'range', text: `${DATE.format(new Date(week.week_start))} - ${DATE.format(new Date(new Date(week.week_end).getTime() - 1))}` }),
        el('span', { class: 'count', text: `${count(week.check_in_count)} nodes checked in, ${count(week.message_count)} messages` })),
      el('div', {},
        el('ul', { class: 'messages', style: 'max-height:none' },
          week.messages.map((message) => messageItem(message, { showChannel: true })))))));
};

/* --- Firehose --------------------------------------------------- */

PAGES.firehose = async (page) => {
  const portnum = $('[data-firehose-portnum]', page).value.trim();
  const params = new URLSearchParams({ limit: '150' });
  if (portnum) params.set('portnum', portnum);
  const target = $('[data-firehose-table]', page);
  const rows = await get(`api/packets?${params}`).catch((error) => error);
  if (rows instanceof Error) return replace(target, failure(rows));
  replace(target, table([
    {
      label: 'Time',
      cell: (row) => el('a', {
        class: 'linky',
        href: `#packet/${encodeURIComponent(row.from_node)}/${row.packet_key.split(':')[1]}`,
        text: clock(row.first_seen_at),
      }),
    },
    { label: 'From', cell: (row) => nodeChip({ node_id: row.from_node, display_name: row.from_name }) },
    { label: 'To', cell: (row) => (row.to_node === '^all' ? 'everyone' : row.to_name || row.to_node) },
    { label: 'Type', cell: (row) => row.portnum },
    { label: 'Channel', cell: (row) => row.channel || '-' },
    { label: 'Hops', num: true, cell: (row) => (row.hop_start == null ? '-' : `${row.hop_start - (row.hop_limit ?? row.hop_start)}`) },
    { label: 'Gateways', num: true, cell: (row) => count(row.seen_count) },
  ], rows, 'No packets match the filter.'));
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
    { label: 'Path', wrap: true, cell: (row) => (row.route_names || []).join(' -> ') || 'direct' },
    { label: 'Hops', num: true, cell: (row) => (row.hops || []).length },
    {
      label: 'Measured',
      num: true,
      cell: (row) =>
        `${(row.hops || []).filter((hop) => hop.snr != null).length} of ${(row.hops || []).length}`,
    },
    {
      label: 'Packet',
      cell: (row) => (row.packet_id == null
        ? el('span', { class: 'muted', text: 'not recorded' })
        : el('a', {
            class: 'linky',
            href: `#packet/${encodeURIComponent(row.packet_from_node)}/${row.packet_id}`,
            text: String(row.packet_id),
          })),
    },
    {
      label: 'mesh-graph',
      cell: (row) => (row.graph_url == null
        ? el('span', { class: 'muted', text: '-' })
        : el('a', {
            class: 'linky', href: row.graph_url, target: '_blank', rel: 'noopener',
            title: 'This traceroute, drawn by mesh-graph',
            text: 'trace',
          })),
    },
  ], rows, 'No traceroutes recorded.'));
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

/** The short name of a packet family, without the shouting. */
const familyLabel = (name) =>
  String(name).replace(/_APP$/, '').replace(/_/g, ' ').toLowerCase();

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
        text: mains ? 'on mains' : `${Math.round(h.battery_level)}%`,
      }));
    }
    if (h.uptime_seconds != null) {
      parts.push(el('span', { class: 'muted', text: `up ${everySeconds(h.uptime_seconds)}` }));
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
          text: `${familyLabel(name)} ${rate.ratio}x`,
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
  if (!data || !data.families || !data.families.length) return;
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

  chart($('[data-activity-chart]', page), {
    ...CHART_BASE,
    legend: {
      data: bands.map((band) => familyLabel(band.name)),
      textStyle: { color: PALETTE.muted },
      top: 0,
    },
    xAxis: { type: 'category', data: data.hours.map((hour) => clock(hour)), ...AXIS },
    yAxis: { type: 'value', ...AXIS },
    series: bands.map((band, index) => ({
      name: familyLabel(band.name),
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
  await Promise.all([loadSummary(page), loadTopTalkers(page)]);
  const [daily, hardware, activity, broadcast] = await getAll([
    'api/stats/snapshots/daily?days=30',
    'api/stats/hardware',
    'api/stats/activity?hours=24',
    'api/stats/broadcast?hours=24&limit=40',
  ]);
  drawActivityChart(page, activity);
  drawBroadcastTable(page, broadcast);

  if (daily && daily.length) {
    const rows = [...daily].reverse();
    chart($('[data-daily-chart]', page), {
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

  if (hardware && hardware.length) {
    const top = hardware.slice(0, 12).reverse();
    chart($('[data-hardware-chart]', page), {
      ...CHART_BASE,
      tooltip: { ...CHART_BASE.tooltip, trigger: 'item' },
      xAxis: { type: 'value', ...AXIS },
      yAxis: { type: 'category', data: top.map((row) => row.hw_model || 'unknown'), ...AXIS },
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
function meshGraphTrace(url) {
  if (!url) return empty('This traceroute has no packet ID, so it cannot be linked.');
  const drawing = el('img', {
    src: url,
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
  if (!currentLink) return;
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
  if (!currentTrace) return;
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
      meshGraphTrace(trace.graph_url)),
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
  altitude: ['Altitude', (v) => `${v} m`],
  ground_speed: ['Ground speed', (v) => `${v} m/s`],
  ground_track: ['Ground track', (v) => `${round(v, 0)} deg`],
  sats_in_view: ['Satellites', (v) => String(v)],
  precision_bits: ['Precision bits', (v) => String(v)],
  body: ['Message', (v) => v],
  channel: ['Channel', (v) => v],
  snr: ['SNR', (v) => `${round(v, 2)} dB`],
  neighbor_node_num: ['Neighbour', (v) => `!${(v >>> 0).toString(16).padStart(8, '0')}`],
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
    L.tileLayer(CONFIG.tileUrl, { attribution: CONFIG.tileAttribution || '', maxZoom: 19 })
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

/** Build the panels that show what a packet carried. */
function decodedPanels(decoded) {
  if (!decoded || !decoded.values || !decoded.values.length) {
    return el('div', { class: 'panel span-2' },
      el('h3', {}, 'Payload'),
      empty('No decoded value is stored for this packet.'));
  }
  const panels = [
    el('div', { class: 'panel' },
      el('h3', {}, 'Payload', el('span', { class: 'muted', text: decoded.kind })),
      el('div', {}, decoded.values.map((row) => decodedValues(row)))),
  ];
  if (decoded.kind === 'position') {
    const holder = el('div', { class: 'chart tall', 'data-position-map': '' });
    panels.push(el('div', { class: 'panel' },
      el('h3', {}, 'Reported position'), holder));
  }
  return panels;
}

PAGES.packet = async (page) => {
  if (!currentPacket) return;
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

  replace($('[data-packet-title]', page),
    el('h2', { text: `${packet.portnum} from ${packet.from_name}` }),
    el('p', { class: 'sub',
      text: `Packet ${packetId}, heard by ${data.observations.length} gateways, `
        + `${direct} of them direct` }));

  const panels = [
    el('div', { class: 'panel' },
      el('h3', {}, 'Packet'),
      el('dl', { class: 'kv' },
        el('dt', { text: 'Packet ID' }), el('dd', {}, el('code', { text: String(packetId) })),
        el('dt', { text: 'From' }), el('dd', {}, nodeChip({ node_id: packet.from_node, display_name: packet.from_name })),
        el('dt', { text: 'To' }), el('dd', { text: packet.to_name || packet.to_node }),
        el('dt', { text: 'Type' }), el('dd', { text: packet.portnum }),
        el('dt', { text: 'Channel' }), el('dd', { text: packet.channel || 'unknown' }),
        el('dt', { text: 'Hop start' }), el('dd', { text: packet.hop_start == null ? 'unknown' : String(packet.hop_start) }),
        el('dt', { text: 'Hop limit' }), el('dd', { text: packet.hop_limit == null ? 'unknown' : String(packet.hop_limit) }),
        el('dt', { text: 'Wants ack' }), el('dd', { text: packet.want_ack ? 'yes' : 'no' }),
        el('dt', { text: 'Priority' }), el('dd', { text: packet.priority == null ? 'default' : String(packet.priority) }),
        el('dt', { text: 'Size' }), el('dd', { text: packet.raw_bytes_length == null ? 'unknown' : `${packet.raw_bytes_length} bytes` }),
        el('dt', { text: 'First seen' }), el('dd', { text: stamp(packet.first_seen_at) }))),
    el('div', { class: 'panel span-2' },
      el('h3', {}, 'Heard by',
        el('span', { class: 'muted',
          text: `${count(data.observations.length)} gateways, ${count(direct)} direct` })),
      el('p', { class: 'notice' },
        'A gateway that used a hop received this packet from a relay, not from '
        + 'the sender. Only a direct observation measures the sender\u2019s own link.'),
      el('div', { class: 'table-wrap' }, table([
        { label: 'Gateway', cell: (row) => nodeChip({ node_id: row.gateway, display_name: row.gateway_name }) },
        { label: 'Path', cell: (row) => (row.direct ? 'direct' : row.hops_taken == null ? 'unknown' : `${row.hops_taken} hops`) },
        { label: 'SNR', num: true, cell: (row) => (row.direct ? snrCell(row.rx_snr) : el('span', { class: 'muted', text: '-' })) },
        { label: 'RSSI', num: true, cell: (row) => (row.direct && row.rx_rssi != null ? `${row.rx_rssi} dBm` : '-') },
        { label: 'When', cell: (row) => clock(row.seen_at) },
        { label: 'Topic', wrap: true, cell: (row) => row.mqtt_topic },
      ], data.observations, 'No gateway observation stored.'))),
  ];

  panels.push(...[decodedPanels(packet.decoded)].flat());
  if (packet.payload_json) {
    panels.push(el('div', { class: 'panel span-2' },
      el('h3', {}, 'Raw payload'),
      el('pre', { text: JSON.stringify(packet.payload_json, null, 2) })));
  }
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
          meshGraphTrace(trace.graph_url)));
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
    if (!document.hidden && livePage(currentPage)) render(currentPage);
  }, LIVE_INTERVAL_MS);
}

async function setStatus(state, message) {
  const dot = $('[data-status] .dot');
  dot.className = `dot ${state}`;
  $('[data-status-text]').textContent = message;
}

async function render(name) {
  const page = $(`[data-page="${name}"]`);
  if (!page || loading) return;
  loading = true;
  try {
    await PAGES[name](page);
    setStatus('', `Updated ${clock(new Date())}`);
  } catch (error) {
    console.error(error);
    setStatus('down', 'Update failed');
  } finally {
    loading = false;
  }
}

async function route() {
  const parts = (location.hash.slice(1) || 'dashboard').split('/');
  const [name, nodeId] = parts;

  const known = Object.hasOwn(PAGES, name) ? name : 'dashboard';
  if (known === 'packet') currentPacket = [decodeURIComponent(parts[1] || ''), parts[2] || ''];
  if (known === 'link') currentLink = [decodeURIComponent(parts[1] || ''), decodeURIComponent(parts[2] || '')];
  if (known === 'traceroute') currentTrace = decodeURIComponent(parts[1] || '');
  currentNodeId = known === 'node' ? decodeURIComponent(nodeId || '') : currentNodeId;
  currentPage = known;

  for (const page of $$('[data-page]')) page.classList.toggle('active', page.dataset.page === known);
  for (const link of $$('[data-nav]')) link.classList.toggle('current', link.dataset.nav === known);
  await render(known);
}

function wire() {
  for (const button of $$('.toggle')) {
    button.addEventListener('click', () => {
      const pressed = button.getAttribute('aria-pressed') === 'true';
      button.setAttribute('aria-pressed', String(!pressed));
      render(currentPage);
    });
  }
  for (const control of $$('select[data-traffic-minutes], select[data-graph-hours], select[data-chat-hours], select[data-node-hours], select[data-meshnet-weeks], select[data-node-active], select[data-node-role], select[data-graph-view]')) {
    control.addEventListener('change', () => render(currentPage));
  }
  $('[data-link-channel]').addEventListener('change', (event) => {
    linkChannel = event.target.value;
    render('map');
  });
  $('[data-node-apply]').addEventListener('click', () => render('nodes'));
  $('[data-node-search]').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') render('nodes');
  });
  $('[data-graph-search]').addEventListener('input', () => render('graph'));
  $('[data-meshnet-apply]').addEventListener('click', () => render('meshnet'));
  $('[data-firehose-apply]').addEventListener('click', () => render('firehose'));

  // Show the brand mark only when the image file exists. Until then the
  // text wordmark stays, so the sidebar never shows a broken image.
  // A cached image can finish loading before this runs, so check
  // `complete` as well as listening for the event.
  const mark = $('[data-brand-mark]');
  if (mark) {
    const reveal = () => {
      mark.style.display = 'block';
      const text = $('[data-brand-text]');
      if (text) text.hidden = true;
    };
    if (mark.complete && mark.naturalWidth > 0) reveal();
    else mark.addEventListener('load', reveal);
  }

  const external = $('[data-graph-external]');
  if (CONFIG.graphBaseUrl) external.href = CONFIG.graphBaseUrl;
  else external.hidden = true;
}

addEventListener('hashchange', route);
wire();
scheduleLive();
route();
