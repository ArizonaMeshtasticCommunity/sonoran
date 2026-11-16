/*
 * Behaviour cases for the two new maps (beta-sonoran#412).
 *
 * Run by `tests/unit/test_where_heard_maps.py`, which shells out to node.
 *
 * The packet page map shows the sender and every gateway that uploaded
 * the packet, as Meshview does. The node page map shows a line to each
 * neighbor the node reports. What must hold, from the issue:
 *
 *   1. A line from the sender goes only to a gateway that heard it
 *      DIRECT. A relayed packet's path is unknown (AGENTS.md 9.20), so a
 *      relayed gateway gets its hop count and no line.
 *   2. The sender uploading its own packet is not a gateway that heard
 *      it (AGENTS.md 9.5.1). It is the sender mark, and nothing else.
 *   3. One gateway that uploaded twice is one mark (AGENTS.md 9.5.1),
 *      with the fewest hops it was reached in.
 *   4. A node with no position is not drawn, and is counted, so the
 *      page can say how many it left off.
 *   5. With no sender position there is nowhere to draw a line from.
 *   6. A neighbor line goes to each neighbor that has a position.
 *
 * The functions are extracted from the shipped `app.js` by name, as
 * `neighbour_names_cases.mjs` does.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
// The mutation controls point this at a copy, never at the shipped file.
const source = readFileSync(
  process.env.SONORAN_APP_JS || join(here, '../../../src/sonoran/web/static/app.js'), 'utf8');

function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found in app.js`);
  const end = source.indexOf('\n}', start);
  if (end < 0) throw new Error(`${name} has no closing brace`);
  return source.slice(start, end + 2);
}

/*
 * Stand-ins for the browser. `el` records what was built, and `text`
 * reads it back as the reader would. `fakeLeaflet` records every layer
 * the drawing code adds, so a case can count lines and read marks.
 */
const el = (tag, attrs = {}, ...kids) => ({ tag, attrs, kids: kids.flat(Infinity) });
const text = (node) => (node == null ? '' : typeof node === 'string' ? node
  : `${node.attrs && node.attrs.text ? node.attrs.text : ''}${(node.kids || []).map(text).join('')}`);
const fakeDocument = { createTextNode: (value) => ({ textNode: value }) };
function fakeLeaflet() {
  const log = { polylines: [], markers: [], circles: [] };
  const layer = (kind, args) => {
    const made = {
      ...args,
      addTo() { return made; },
      bindPopup(content) { made.popup = content; return made; },
      bindTooltip(content) { made.tooltip = content; return made; },
      getElement() { made.element = made.element || { textContent: '' }; return made.element; },
    };
    log[kind].push(made);
    return made;
  };
  // Leaflet's map methods return the map, so calls can chain.
  const map = {
    on() { return map; }, fitBounds() { return map; }, setView() { return map; },
    invalidateSize() {}, remove() {},
    scrollWheelZoom: { enable() {} },
    dragging: { enabled: () => true, enable() {} },
  };
  const L = {
    map: () => map,
    tileLayer: () => ({ addTo() {} }),
    polyline: (points, options) => layer('polylines', { points, options }),
    marker: (point, options) => layer('markers', { point, options }),
    circleMarker: (point, options) => layer('circles', { point, options }),
    divIcon: (options) => options,
    Browser: { mobile: false },
  };
  return { L, log };
}
const PALETTE = { accent: 'accent', good: 'good', link: 'link' };
const round = (value, digits = 1) => Number(value.toFixed(digits));
const count = (value) => String(value);

const api = new Function('el', 'round', 'count', 'PALETTE', 'CONFIG', 'document', [
  'const packetMaps = new Map();',
  'const nodeMaps = new Map();',
  'let L;',
  extract('packetMapMarks'),
  extract('neighborMapMarks'),
  extract('wherePanel'),
  extract('whereHeardPopup'),
  extract('drawWhereHeard'),
  extract('neighborKey'),
  extract('drawNodeMap'),
  'return { packetMapMarks, neighborMapMarks, wherePanel, neighborKey,',
  '  drawWhereHeard: (leaflet, ...a) => { L = leaflet; return drawWhereHeard(...a); },',
  '  drawNodeMap: (leaflet, ...a) => { L = leaflet; return drawNodeMap(...a); } };',
].join('\n'))(el, round, count, PALETTE, {}, fakeDocument);
const target = () => ({ isConnected: true });

let failed = 0;
function ok(name, condition, detail) {
  if (!condition) {
    failed += 1;
    console.error(`FAIL ${name}: ${detail}`);
  }
}
function eq(name, actual, expected) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  ok(name, a === b, `got ${a}, wanted ${b}`);
}

// --- The packet page ----------------------------------------------

const SENDER = '!00000001';
const place = (lat, lon, confidence = 'exact') => ({ lat, lon, confidence });
const upload = (gateway, extra) => ({
  gateway, gateway_name: `GW ${gateway.slice(-2)}`,
  hops_taken: 0, direct: false, self_reported: false, rx_snr: null, ...extra,
});

const data = {
  packet: { from_node: SENDER, from_name: 'Sender' },
  places: {
    [SENDER]: place(33.4, -111.9),
    '!00000002': place(33.45, -111.95),
    '!00000003': place(33.5, -112.0, 'coarse'),
    // !00000004 has no position.
    '!00000007': place(33.3, -111.8),
    '!00000008': place(33.35, -111.7),
  },
  observations: [
    // The sender gatewaying itself.
    upload(SENDER, { self_reported: true, hops_taken: 0 }),
    // Heard direct, and uploaded twice. The best reading comes first, so
    // "the last reading wins" would be caught.
    upload('!00000002', { direct: true, hops_taken: 0, rx_snr: 6.25 }),
    upload('!00000002', { direct: true, hops_taken: 0, rx_snr: 4.5 }),
    // Relayed: one hop on one upload, two on another.
    upload('!00000003', { hops_taken: 2 }),
    upload('!00000003', { hops_taken: 1 }),
    upload('!00000004', { hops_taken: 1 }),
    // Direct, from a row that recorded no hop count.
    upload('!00000007', { direct: true, hops_taken: null, rx_snr: 2 }),
    // Relayed on one upload and direct on another: it heard it direct.
    upload('!00000008', { hops_taken: 2 }),
    upload('!00000008', { direct: true, hops_taken: 0, rx_snr: -1 }),
  ],
};

const marks = api.packetMapMarks(data);
const ids = marks.gateways.map((g) => g.node_id);
const byId = Object.fromEntries(marks.gateways.map((g) => [g.node_id, g]));

eq('the sender is placed', marks.sender && [marks.sender.lat, marks.sender.lon], [33.4, -111.9]);
eq('the sender is named', marks.sender && marks.sender.name, 'Sender');
ok('the sender gatewaying itself is not a gateway mark', !ids.includes(SENDER),
  `gateways were ${JSON.stringify(ids)}`);
eq('one mark for each placed gateway', [...ids].sort(),
  ['!00000002', '!00000003', '!00000007', '!00000008']);
eq('a direct gateway with no hop count is still zero hops', byId['!00000007'].hops, 0);
eq('a gateway heard direct once is direct', [byId['!00000008'].direct, byId['!00000008'].line, byId['!00000008'].hops],
  [true, true, 0]);
eq('a gateway that heard it direct gets a line', byId['!00000002'].line, true);
eq('a relayed gateway gets no line (AGENTS.md 9.20)', byId['!00000003'].line, false);
eq('a relayed gateway shows the fewest hops it was reached in', byId['!00000003'].hops, 1);
eq('a direct gateway is zero hops', byId['!00000002'].hops, 0);
eq('the direct line carries the best reading', byId['!00000002'].snr, 6.25);
eq('a relayed gateway carries no reading', byId['!00000003'].snr, null);
eq('a rounded gateway says so', byId['!00000003'].confidence, 'coarse');
eq('the gateway with no position is counted, not drawn', marks.unplaced, 1);

const noSender = api.packetMapMarks({ ...data, places: { ...data.places, [SENDER]: undefined } });
eq('with no sender position there is no sender mark', noSender.sender, null);
ok('with no sender position no line is drawn', noSender.gateways.every((g) => !g.line),
  JSON.stringify(noSender.gateways));
eq('the gateways are still drawn without the sender', noSender.gateways.length, 4);

const nothing = api.packetMapMarks({ packet: { from_node: SENDER }, observations: [] });
eq('an old answer with no places draws nothing and does not throw',
  [nothing.sender, nothing.gateways.length, nothing.unplaced], [null, 0, 0]);

// --- The packet map as drawn --------------------------------------

{
  const { L, log } = fakeLeaflet();
  api.drawWhereHeard(L, target(), marks);
  const lineEnds = log.polylines.map((line) => JSON.stringify(line.points[1])).sort();
  const directEnds = marks.gateways.filter((g) => g.direct)
    .map((g) => JSON.stringify([g.lat, g.lon])).sort();
  eq('the map draws a line to each direct gateway and no other', lineEnds, directEnds);
  ok('every line starts at the sender',
    log.polylines.every((line) => JSON.stringify(line.points[0]) === '[33.4,-111.9]'),
    JSON.stringify(log.polylines.map((line) => line.points[0])));
  const markAt = (id) => log.markers.find((m) => m.options.title === byId[id].name);
  ok('a rounded gateway is drawn hollow', /where-mark-coarse/.test(markAt('!00000003').options.icon.className),
    markAt('!00000003').options.icon.className);
  ok('an exact gateway is not drawn hollow', !/where-mark-coarse/.test(markAt('!00000002').options.icon.className),
    markAt('!00000002').options.icon.className);
  eq('a relayed gateway shows its hop count on the map', markAt('!00000003').element.textContent, '1');
}
{
  const exact = fakeLeaflet();
  api.drawWhereHeard(exact.L, target(), marks);
  const coarse = fakeLeaflet();
  api.drawWhereHeard(coarse.L, target(), { ...marks, sender: { ...marks.sender, confidence: 'coarse' } });
  ok('a rounded sender is drawn hollow',
    coarse.log.circles[0].options.fillOpacity < exact.log.circles[0].options.fillOpacity,
    `${coarse.log.circles[0].options.fillOpacity} against ${exact.log.circles[0].options.fillOpacity}`);
}
ok('the panel says how many gateways it left off', /1 more gateway shares no position/.test(text(api.wherePanel(marks))),
  text(api.wherePanel(marks)));
ok('the panel says when the sender has no position',
  /sender shares no position/.test(text(api.wherePanel(noSender))), text(api.wherePanel(noSender)));

// --- The node page ------------------------------------------------

const neighbors = [
  { node_id: '!0000000a', display_name: 'Near', snr: 7.5, position: place(33.41, -111.91) },
  { node_id: '!0000000b', display_name: 'Far', snr: -9, position: place(33.6, -112.2, 'coarse') },
  { node_id: '!0000000c', display_name: 'Hidden', snr: 1, position: null },
  { node_id: '!0000000d', display_name: 'Old answer', snr: 1 },
];
const near = api.neighborMapMarks(neighbors);
eq('each placed neighbor is drawn', near.marks.map((m) => m.node_id), ['!0000000a', '!0000000b']);
eq('a neighbor carries its name and SNR', [near.marks[0].name, near.marks[0].snr], ['Near', 7.5]);
eq('a rounded neighbor says so', near.marks[1].confidence, 'coarse');
eq('unplaced neighbors are counted', near.unplaced, 2);
eq('no neighbors, nothing drawn', api.neighborMapMarks([]).marks.length, 0);
{
  const { L, log } = fakeLeaflet();
  api.drawNodeMap(L, target(), { lat: 33.4, lon: -111.9 }, 'exact', neighbors);
  eq('a line goes to each placed neighbor', log.polylines.map((line) => line.points[1]),
    [[33.41, -111.91], [33.6, -112.2]]);
  eq('each line starts at the node', log.polylines.map((line) => line.points[0]),
    [[33.4, -111.9], [33.4, -111.9]]);
  eq('a neighbor line carries the SNR it reported', log.polylines[0].tooltip, { textNode: 'SNR 7.5 dB' });
  const dots = log.circles.slice(1);
  ok('a rounded neighbor is drawn hollow', dots[1].options.fillOpacity < dots[0].options.fillOpacity,
    `${dots[1].options.fillOpacity} against ${dots[0].options.fillOpacity}`);
}
const key = text(api.neighborKey(near));
ok('the key says what a line means', /2 neighbors/.test(key) && /does not say the other node hears this one/.test(key), key);
ok('the key says how many neighbors it left off', /2 more share no position/.test(key), key);
eq('no neighbors, no key', api.neighborKey(api.neighborMapMarks([])), null);

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('where heard cases: all passed');
