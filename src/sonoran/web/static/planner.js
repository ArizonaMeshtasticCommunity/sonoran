/*
 * Coverage planner.
 *
 * This page predicts where a radio at one place would be heard, and
 * draws the answer over the nodes this mesh already has. That last part
 * is the point of it: the standalone site planner knows the terrain but
 * knows nothing about our mesh.
 *
 * How a run works:
 *
 *   1. The form becomes engine parameters (planner-params.js).
 *   2. One worker is asked which elevation pages the run needs.
 *   3. Each page is read from /api/terrain/page/{tile} and cached.
 *   4. The radials are split between workers, which return rasters.
 *   5. The rasters are merged, coloured, and put on the map.
 *   6. Every node is tested against the result.
 *
 * The engine and the worker are described in planner.worker.js. This
 * file loads before app.js, so it uses the helpers from app.js only
 * inside functions, which run long after both files have loaded.
 */

'use strict';

/* ---------------------------------------------------------------- */
/* Terrain                                                           */

/** Cells in one page, and the size of one page in bytes. */
const PAGE_SIZE = 1200;

/** Pages already read, by tile name. Kept for the life of the tab. */
const terrainMemory = new Map();

/**
 * Signed floor longitude of a page.
 * The engine counts longitude west-positive from 0 to 359.
 */
function pageSignedFloorLon(minWest) {
  return minWest < 180 ? -(minWest + 1) : 359 - minWest;
}

/** The SRTM tile name for one engine page. */
function tileNameForPage(ref) {
  const lon = pageSignedFloorLon(ref.minWest);
  const ns = ref.minNorth >= 0 ? 'N' : 'S';
  const ew = lon >= 0 ? 'E' : 'W';
  const lat = String(Math.abs(ref.minNorth)).padStart(2, '0');
  const lonText = String(Math.abs(lon)).padStart(3, '0');
  return `${ns}${lat}${ew}${lonText}`;
}

/**
 * Read one elevation page.
 *
 * A 404 means the service holds no terrain there. That is not an error:
 * the engine reads a page it was never given as sea level. Returning
 * null here says exactly that.
 *
 * Pages never change, so the browser cache keeps them. The endpoint
 * marks them immutable, so a second run in the same area asks for
 * nothing at all.
 */
async function fetchTerrainPage(tile) {
  if (terrainMemory.has(tile)) return terrainMemory.get(tile);
  let page = null;
  try {
    const response = await fetch(api(`api/terrain/page/${tile}`));
    if (response.status === 404) {
      page = null;
    } else if (!response.ok) {
      throw new Error(`terrain ${tile} failed (${response.status})`);
    } else {
      const buffer = await response.arrayBuffer();
      const cells = PAGE_SIZE * PAGE_SIZE;
      if (buffer.byteLength !== cells * 2) {
        throw new Error(`terrain ${tile} has ${buffer.byteLength} bytes`);
      }
      page = new Int16Array(buffer);
    }
  } catch (error) {
    console.warn('terrain page unavailable', tile, error);
    page = null;
  }
  terrainMemory.set(tile, page);
  return page;
}

/* ---------------------------------------------------------------- */
/* Workers                                                           */

const WORKER_COUNT = Math.max(1, Math.min(navigator.hardwareConcurrency || 2, 4));

const pool = [];
let nextRunId = 1;

function workerUrl() {
  return new URL('static/planner.worker.js', document.baseURI).toString();
}

function ensurePool() {
  while (pool.length < WORKER_COUNT) {
    // A module worker, because the vendored engine loader is an ES
    // module. The Content-Security-Policy must allow worker-src 'self'.
    pool.push(new Worker(workerUrl(), { type: 'module' }));
  }
  return pool;
}

/**
 * Send one message to one worker and wait for its reply.
 *
 * `onProgress` is called for every progress message on the way. The
 * promise settles on the first reply that is not progress.
 */
function ask(worker, message, onProgress) {
  return new Promise((resolve, reject) => {
    const handle = (event) => {
      const reply = event.data;
      if (reply.runId !== message.runId) return;
      if (reply.type === 'progress') {
        if (onProgress) onProgress(reply.radialsDone);
        return;
      }
      worker.removeEventListener('message', handle);
      if (reply.type === 'error') reject(new Error(`${reply.code}: ${reply.message}`));
      else resolve(reply);
    };
    worker.addEventListener('message', handle);
    worker.postMessage(message);
  });
}

/** Contiguous radial slices, one for each worker. */
function sliceRadials(total, workers) {
  const count = Math.max(1, Math.min(workers, total));
  const per = Math.ceil(total / count);
  const slices = [];
  for (let start = 0; start < total; start += per) {
    slices.push({ start, end: Math.min(start + per, total) });
  }
  return slices;
}

/**
 * Merge the rasters the workers returned.
 *
 * SPLAT! computes each point at the FIRST radial that reaches it, and
 * skips it afterwards. The workers take the radials in order, so
 * merging in that same order with "the first worker to set a cell wins"
 * gives the same answer a single thread would have given.
 *
 * The low three bits of a mask byte are not a coverage flag, which is
 * why the test is against 248 and not against zero.
 */
function mergeFirstTouch(parts, cells) {
  const signal = new Uint8Array(cells);
  const mask = new Uint8Array(cells);
  for (const part of parts) {
    for (let i = 0; i < cells; i += 1) {
      if ((mask[i] & 248) === 0 && (part.mask[i] & 248) !== 0) {
        mask[i] = part.mask[i];
        signal[i] = part.signal[i];
      }
    }
  }
  return { signal, mask };
}

/* ---------------------------------------------------------------- */
/* Colour                                                            */

/*
 * The coverage ramp, from weakest to strongest.
 *
 * The weak end is the colour that matters most: it is the edge of the
 * usable area. It is kept bright enough to read over a dark basemap.
 */
const RAMP = [
  [0.0, [69, 12, 108]],
  [0.25, [141, 41, 122]],
  [0.5, [216, 87, 86]],
  [0.75, [251, 158, 63]],
  [1.0, [252, 254, 164]],
];

function rampColour(fraction) {
  const t = Math.max(0, Math.min(1, fraction));
  for (let i = 1; i < RAMP.length; i += 1) {
    if (t <= RAMP[i][0]) {
      const [t0, c0] = RAMP[i - 1];
      const [t1, c1] = RAMP[i];
      const k = (t - t0) / (t1 - t0);
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * k),
        Math.round(c0[1] + (c1[1] - c0[1]) * k),
        Math.round(c0[2] + (c1[2] - c0[2]) * k),
      ];
    }
  }
  return RAMP[RAMP.length - 1][1];
}

/* ---------------------------------------------------------------- */
/* Drawing                                                           */

/** Web Mercator, latitude in degrees to a linear y. */
function mercatorY(latitude) {
  const phi = (latitude * Math.PI) / 180;
  return Math.log(Math.tan(Math.PI / 4 + phi / 2));
}

/**
 * Paint the coverage grid onto a canvas.
 *
 * The engine grid is even in latitude. Leaflet stretches an image
 * overlay evenly in Web Mercator. Drawing the grid straight across
 * would therefore put the coverage in the wrong place, by a few pixels
 * near the middle of the picture and more the further north it goes.
 * Each output row is read from the source row at the same mercator
 * position, which puts it back where it belongs.
 */
function paintCoverage(result, floorDbm, ceilingDbm) {
  const { width, height, dbm, bounds } = result;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const image = new ImageData(width, height);
  const pixels = image.data;

  const yNorth = mercatorY(bounds.north);
  const ySouth = mercatorY(bounds.south);
  const span = Math.max(1e-12, ceilingDbm - floorDbm);

  for (let row = 0; row < height; row += 1) {
    // The latitude this output row stands for, in mercator.
    const y = yNorth + ((ySouth - yNorth) * (row + 0.5)) / height;
    const latitude = ((2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180) / Math.PI;
    let source = Math.floor(((bounds.north - latitude) / (bounds.north - bounds.south)) * height);
    if (source < 0) source = 0;
    if (source >= height) source = height - 1;

    const from = source * width;
    const to = row * width;
    for (let column = 0; column < width; column += 1) {
      const value = dbm[from + column];
      const at = (to + column) * 4;
      if (Number.isNaN(value) || value < floorDbm) {
        // Below the receiver, or never computed. Leave it clear so the
        // map shows through.
        pixels[at + 3] = 0;
        continue;
      }
      const [r, g, b] = rampColour((value - floorDbm) / span);
      pixels[at] = r;
      pixels[at + 1] = g;
      pixels[at + 2] = b;
      pixels[at + 3] = 205;
    }
  }

  canvas.getContext('2d').putImageData(image, 0, 0);
  return canvas;
}

/* ---------------------------------------------------------------- */
/* Reading the result                                                */

/** The predicted level at one position, or null when it was not computed. */
function sampleDbm(result, latitude, longitude) {
  const { bounds, width, height, dbm } = result;
  if (
    latitude > bounds.north ||
    latitude < bounds.south ||
    longitude < bounds.west ||
    longitude > bounds.east
  ) {
    return null;
  }
  const row = Math.floor(((bounds.north - latitude) / (bounds.north - bounds.south)) * height);
  const column = Math.floor(((longitude - bounds.west) / (bounds.east - bounds.west)) * width);
  if (row < 0 || row >= height || column < 0 || column >= width) return null;
  const value = dbm[row * width + column];
  return Number.isNaN(value) ? null : value;
}

const EARTH_RADIUS_M = 6371000;

function distanceKm(lat1, lon1, lat2, lon2) {
  const rad = (d) => (d * Math.PI) / 180;
  const dLat = rad(lat2 - lat1);
  const dLon = rad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2;
  return (2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)))) / 1000;
}

/** How much ground the prediction covers, in square kilometres. */
function coveredAreaKm2(result, threshold) {
  const { width, height, dbm, bounds } = result;
  const degreesPerRow = (bounds.north - bounds.south) / height;
  const metresPerDegree = 111320;
  const cellHeight = degreesPerRow * metresPerDegree;
  let area = 0;
  for (let row = 0; row < height; row += 1) {
    const latitude = bounds.north - (row + 0.5) * degreesPerRow;
    const cell = cellHeight * cellHeight * Math.cos((latitude * Math.PI) / 180);
    const base = row * width;
    for (let column = 0; column < width; column += 1) {
      const value = dbm[base + column];
      if (!Number.isNaN(value) && value >= threshold) area += cell;
    }
  }
  return area / 1e6;
}

/* ---------------------------------------------------------------- */
/* State                                                             */

const state = {
  map: null,
  nodeLayer: null,
  coverageLayer: null,
  siteMarker: null,
  linkLayer: null,
  nodes: [],
  result: null,
  request: null,
  running: false,
  cancelRunId: null,
};

/* ---------------------------------------------------------------- */
/* The form                                                          */

const FIELDS = [
  'site_name',
  'lat',
  'lon',
  'tx_height',
  'tx_power',
  'tx_gain',
  'frequency_mhz',
  'rx_height',
  'rx_gain',
  'system_loss',
  'sensitivity',
  'clutter_height',
  'ground_dielectric',
  'ground_conductivity',
  'atmosphere_bending',
  'radio_climate',
  'polarization',
  'radius',
  'situation_fraction',
  'time_fraction',
];

const NUMERIC = new Set(FIELDS.filter((name) => name !== 'site_name' && name !== 'radio_climate' && name !== 'polarization'));

function field(name) {
  return document.querySelector(`[data-planner="${name}"]`);
}

/** Read the form. Returns null and marks the problem when it is not usable. */
function readForm() {
  const request = {};
  // The site is checked first. Without it the message would be "lat
  // needs a number", which does not tell anybody what to do.
  if (!field('lat').value.trim() || !field('lon').value.trim()) {
    setNotice('Choose a site: click the map, or click one of your nodes', 'bad');
    return null;
  }
  for (const name of FIELDS) {
    const input = field(name);
    if (!input) continue;
    const raw = input.value;
    if (!NUMERIC.has(name)) {
      request[name] = raw;
      continue;
    }
    const value = Number(raw);
    if (raw === '' || Number.isNaN(value)) {
      setNotice(`${name.replace(/_/g, ' ')} needs a number`, 'bad');
      input.focus();
      return null;
    }
    request[name] = value;
  }
  // The radius is asked for in kilometres and used in metres.
  request.radius = request.radius * 1000;
  return request;
}

function fillForm(values) {
  for (const name of FIELDS) {
    const input = field(name);
    if (input && values[name] != null) input.value = values[name];
  }
}

function setNotice(text, kind) {
  const notice = document.querySelector('[data-planner-notice]');
  if (!notice) return;
  notice.textContent = text || '';
  notice.hidden = !text;
  notice.className = `notice${kind ? ` ${kind}` : ''}`;
}

function setProgress(text) {
  const line = document.querySelector('[data-planner-progress]');
  if (line) line.textContent = text || '';
}

/* ---------------------------------------------------------------- */
/* The map                                                           */

function ensurePlannerMap() {
  if (state.map) return state.map;
  const map = L.map('planner-map', { preferCanvas: true })
    .setView(CONFIG.mapCenter || [34.0, -111.5], CONFIG.mapZoom || 7);
  if (CONFIG.tileUrl) {
    L.tileLayer(CONFIG.tileUrl, {
      className: 'basemap-tiles',
      attribution: CONFIG.tileAttribution || '',
      maxZoom: 19,
    }).addTo(map);
  }
  state.coverageLayer = L.layerGroup().addTo(map);
  state.linkLayer = L.layerGroup().addTo(map);
  state.nodeLayer = L.layerGroup().addTo(map);
  map.on('click', (event) => setSite(event.latlng.lat, event.latlng.lng, ''));
  state.map = map;
  return map;
}

/** Put the transmitter somewhere and show it. */
function setSite(latitude, longitude, name, altitude) {
  fillForm({ lat: latitude.toFixed(5), lon: longitude.toFixed(5) });
  if (name != null) fillForm({ site_name: name });
  if (altitude != null && Number.isFinite(altitude)) {
    // A node reports the height of its ground, not of its antenna. Keep
    // the antenna height the user chose and do not overwrite it.
    setNotice(`Site set from ${name || 'the map'}. Ground is about ${Math.round(altitude)} m.`, '');
  } else {
    setNotice('', '');
  }
  markSite(latitude, longitude, name);
}

/** Put the one transmitter pin on the map, replacing any earlier one. */
function markSite(latitude, longitude, name) {
  if (state.siteMarker) state.map.removeLayer(state.siteMarker);
  state.siteMarker = L.marker([latitude, longitude], { title: name || 'Transmitter site' });
  state.siteMarker.addTo(state.map);
}

/**
 * Draw the nodes.
 *
 * When a run has finished, each node is coloured by whether the
 * prediction reaches it. Before that they keep their usual role colour.
 *
 * That colour is `nodeColour` from app.js, the one the map and the
 * mesh graph draw with. This page used to sort every node into
 * gateway, router, or client of its own, so a client mute and a client
 * base were one colour here and two colours on every other page.
 */
function drawNodes() {
  state.nodeLayer.clearLayers();
  const threshold = state.request ? Number(state.request.sensitivity) : null;
  for (const node of state.nodes) {
    if (node.lat == null || node.lon == null) continue;
    let colour = nodeColour(node);
    let reached = null;
    let level = null;
    if (state.result && threshold != null) {
      level = sampleDbm(state.result, node.lat, node.lon);
      if (level != null) {
        level = SonoranPlannerParams.receivedDbm(level, state.request);
        reached = level >= threshold;
      } else {
        reached = false;
      }
      colour = reached ? PALETTE.good : PALETTE.stale;
    }
    /*
     * A gateway wears a bright ring rather than a colour of its own,
     * because uploading to MQTT is not a role and must not hide the
     * one the node is actually running. The map draws it the same way.
     *
     * A node not heard in a day fades, again as on the map, but only
     * until a run has answered. After that the fading belongs to what
     * the prediction reaches, and two meanings on one channel would
     * say neither clearly.
     */
    const faded = reached == null && isStale(node);
    const marker = L.circleMarker([node.lat, node.lon], {
      radius: node.is_mqtt_gateway ? 7 : 5,
      color: node.is_mqtt_gateway ? PALETTE.text : colour,
      weight: node.is_mqtt_gateway ? 2.5 : 1.5,
      fillColor: colour,
      fillOpacity: reached === false ? 0.2 : faded ? 0.15 : 0.6,
      opacity: faded ? 0.35 : 1,
    });
    const lines = [
      el('div', { style: 'font-weight:650' }, node.display_name || node.node_id),
      el('div', { class: 'muted', style: 'font-size:.8rem' }, node.node_id),
      // The colour on the map means nothing without the word for it,
      // and it is the same word the other pages use.
      el('div', { class: 'muted', style: 'font-size:.8rem' },
        roleLabel(node.role) + (node.is_mqtt_gateway ? ', gateway' : '')),
    ];
    if (reached != null) {
      lines.push(
        el('div', { style: `font-size:.85rem;color:${reached ? PALETTE.good : PALETTE.muted}` },
          reached ? `Reached, about ${level.toFixed(1)} dBm` : 'Not reached'),
      );
    }
    // The buttons sit in their own row. Two `.linky` buttons side by
    // side have no space between them and read as one run-on phrase.
    lines.push(
      el('div', { class: 'popup-actions' },
        el('button', {
          class: 'linky',
          type: 'button',
          text: 'Use as the site',
          onclick: () => setSite(node.lat, node.lon, node.display_name || node.node_id, node.altitude),
        }),
        state.result
          ? el('button', {
              class: 'linky',
              type: 'button',
              text: 'Check this link',
              onclick: () => runLink(node),
            })
          : null),
    );
    marker.bindPopup(el('div', {}, ...lines));
    marker.addTo(state.nodeLayer);
  }
}

/* ---------------------------------------------------------------- */
/* A run                                                             */

async function runCoverage() {
  if (state.running) return;
  const request = readForm();
  if (!request) return;

  const params = SonoranPlannerParams.toEngineParams(request);
  const runId = nextRunId;
  nextRunId += 1;

  // Show the site. The coordinates may have been typed rather than
  // clicked, in which case nothing has marked the spot yet.
  markSite(request.lat, request.lon, request.site_name);

  state.running = true;
  state.cancelRunId = runId;
  setRunning(true);
  setNotice('', '');

  try {
    const workers = ensurePool();

    setProgress('Asking the engine which terrain it needs');
    const plan = await ask(workers[0], { type: 'pages', runId, params });

    setProgress(`Reading terrain: ${plan.pages.length} tile(s)`);
    const tiles = plan.pages.map(tileNameForPage);
    const pages = [];
    let missing = 0;
    for (let i = 0; i < tiles.length; i += 1) {
      setProgress(`Reading terrain ${i + 1} of ${tiles.length}: ${tiles[i]}`);
      const page = await fetchTerrainPage(tiles[i]);
      if (page === null) missing += 1;
      pages.push(page);
    }
    if (missing === tiles.length) {
      throw new Error(
        'No terrain is held for this area. The planner covers Arizona only, ' +
          'and the prediction would be over flat ground.',
      );
    }
    if (missing > 0) {
      setNotice(
        `${missing} of ${tiles.length} terrain tiles are missing. ` +
          'Coverage over those parts is drawn as if the ground were flat.',
        'warn',
      );
    }

    const slices = sliceRadials(plan.radials, workers.length);
    const done = new Array(slices.length).fill(0);
    const total = plan.radials;
    const report = () => {
      const complete = done.reduce((sum, value) => sum + value, 0);
      setProgress(`Computing: ${Math.round((complete / total) * 100)}%`);
    };
    report();

    const replies = await Promise.all(
      slices.map((slice, index) =>
        ask(
          workers[index],
          {
            type: 'run',
            runId,
            params,
            // Each worker needs its own copy of the terrain. The arrays
            // are not transferred, because a transfer would empty them
            // for every other worker.
            pages: pages.map((page) => (page ? page.slice() : null)),
            start: slice.start,
            end: slice.end,
            chunk: 16,
          },
          (radialsDone) => {
            done[index] = radialsDone;
            report();
          },
        ),
      ),
    );

    setProgress('Merging and drawing');
    const region = replies[0].region;
    const cells = region.width * region.height;
    const merged = mergeFirstTouch(replies.map((reply) => ({ signal: reply.signal, mask: reply.mask })), cells);

    // The engine reports the field strength as a byte with a 200 dB
    // offset. A cell the sweep never reached has no value at all.
    const dbm = new Float32Array(cells);
    for (let i = 0; i < cells; i += 1) {
      dbm[i] = (merged.mask[i] & 248) !== 0 ? merged.signal[i] - 200 : NaN;
    }

    state.result = {
      width: region.width,
      height: region.height,
      dbm,
      bounds: {
        north: region.north,
        south: region.south,
        east: region.east,
        west: region.west,
      },
    };
    state.request = request;
    showResult();
    setProgress('');
  } catch (error) {
    console.error(error);
    setNotice(String(error && error.message ? error.message : error), 'bad');
    setProgress('');
  } finally {
    state.running = false;
    state.cancelRunId = null;
    setRunning(false);
  }
}

function cancelRun() {
  if (!state.running || state.cancelRunId == null) return;
  for (const worker of pool) worker.postMessage({ type: 'cancel', runId: state.cancelRunId });
  setProgress('Stopping');
}

function setRunning(running) {
  const run = document.querySelector('[data-planner-run]');
  const stop = document.querySelector('[data-planner-cancel]');
  if (run) run.disabled = running;
  if (stop) stop.hidden = !running;
}

/** Put the finished prediction on the map and write up what it means. */
function showResult() {
  const request = state.request;
  const threshold = Number(request.sensitivity);
  // The colour scale runs from the receiver's limit to a strong signal.
  const floor = threshold - Number(request.rx_gain) + Number(request.system_loss);
  const canvas = paintCoverage(state.result, floor, floor + 60);

  state.coverageLayer.clearLayers();
  const bounds = [
    [state.result.bounds.south, state.result.bounds.west],
    [state.result.bounds.north, state.result.bounds.east],
  ];
  L.imageOverlay(canvas.toDataURL('image/png'), bounds, { opacity: 1, interactive: false })
    .addTo(state.coverageLayer);

  // Frame the range that was asked for, not the whole engine region.
  // The engine works in whole degrees, so its region is far larger than
  // the run and fitting to it leaves the coverage a speck in the middle.
  const reach = (Number(request.radius) / 1000 / 111.32) * 1.15;
  const spread = reach / Math.max(0.2, Math.cos((request.lat * Math.PI) / 180));
  state.map.fitBounds(
    [
      [request.lat - reach, request.lon - spread],
      [request.lat + reach, request.lon + spread],
    ],
    { padding: [20, 20] },
  );

  drawNodes();
  writeSummary(threshold);
}

function writeSummary(threshold) {
  const body = document.querySelector('[data-planner-summary]');
  if (!body) return;
  const request = state.request;

  const withPosition = state.nodes.filter((node) => node.lat != null && node.lon != null);
  const reached = [];
  const missed = [];
  for (const node of withPosition) {
    const raw = sampleDbm(state.result, node.lat, node.lon);
    if (raw == null) {
      missed.push({ node, level: null });
      continue;
    }
    const level = SonoranPlannerParams.receivedDbm(raw, request);
    if (level >= threshold) reached.push({ node, level });
    else missed.push({ node, level });
  }
  reached.sort((a, b) => b.level - a.level);

  const floor = threshold - Number(request.rx_gain) + Number(request.system_loss);
  const area = coveredAreaKm2(state.result, floor);
  const furthest = reached.reduce(
    (best, item) => Math.max(best, distanceKm(request.lat, request.lon, item.node.lat, item.node.lon)),
    0,
  );

  replace(body, [
    el('div', { class: 'grid' },
      statTile('Nodes reached', `${reached.length} of ${withPosition.length}`),
      statTile('Ground covered', `${area.toFixed(0)} km2`),
      statTile('Furthest node', furthest ? `${furthest.toFixed(1)} km` : 'none'),
      statTile('Receiver threshold', `${threshold} dBm`)),
    el('p', { class: 'muted', style: 'margin:.75rem 0 .25rem;font-size:.82rem' },
      'A prediction, not a promise. It assumes clear ground and the ' +
      'receiver figures in the form. Real radios do worse.'),
    el('div', { class: 'panel', style: 'margin-top:1rem' },
      el('h3', { text: 'Nodes this site would reach' }),
      el('div', { class: 'table-wrap' },
        table(
          [
            { label: 'Node', cell: (row) => nodeChip(row.node) },
            { label: 'Predicted', num: true, cell: (row) => `${row.level.toFixed(1)} dBm` },
            { label: 'Distance', num: true, cell: (row) => `${row.range.toFixed(1)} km` },
          ],
          reached.slice(0, 40).map((item) => ({
            node: item.node,
            level: item.level,
            range: distanceKm(request.lat, request.lon, item.node.lat, item.node.lon),
          })),
          'This site reaches none of the known nodes.',
        ))),
  ]);
}

/* ---------------------------------------------------------------- */
/* One link                                                          */

async function runLink(node) {
  const request = state.request || readForm();
  if (!request) return;
  const params = SonoranPlannerParams.toEngineParams(request);
  const runId = nextRunId;
  nextRunId += 1;

  try {
    setProgress(`Checking the link to ${node.display_name || node.node_id}`);
    const workers = ensurePool();
    const plan = await ask(workers[0], { type: 'pages', runId, params });
    const pages = [];
    for (const ref of plan.pages) pages.push(await fetchTerrainPage(tileNameForPage(ref)));

    const reply = await ask(workers[0], {
      type: 'link',
      runId,
      params,
      pages,
      target: {
        lat: node.lat,
        lon: node.lon,
        altFeet: Number(request.rx_height) / SonoranPlannerParams.METRES_PER_FOOT,
      },
    });
    showLink(node, reply.result, request);
    setProgress('');
  } catch (error) {
    console.error(error);
    setNotice(String(error && error.message ? error.message : error), 'bad');
    setProgress('');
  }
}

/** Draw the terrain between the site and one node, and say if it works. */
function showLink(node, result, request) {
  const panel = document.querySelector('[data-planner-link]');
  if (!panel) return;
  const level = SonoranPlannerParams.receivedDbm(result.dbm, request);
  const threshold = Number(request.sensitivity);
  const margin = level - threshold;

  state.linkLayer.clearLayers();
  L.polyline([[request.lat, request.lon], [node.lat, node.lon]], {
    color: margin >= 0 ? PALETTE.good : PALETTE.bad,
    weight: 2,
    dashArray: '5 4',
  }).addTo(state.linkLayer);

  const chart = el('div', { class: 'chart' });
  replace(panel, [
    el('h3', { text: `Link to ${node.display_name || node.node_id}` }),
    el('p', {
      style: `font-weight:650;color:${margin >= 0 ? PALETTE.good : PALETTE.bad}`,
      text:
        margin >= 0
          ? `Workable, ${margin.toFixed(1)} dB above the receiver`
          : `Too weak, ${Math.abs(margin).toFixed(1)} dB short`,
    }),
    el('p', { class: 'muted', style: 'font-size:.82rem' },
      `${result.distanceKm.toFixed(1)} km on a bearing of ${result.azimuthDeg.toFixed(0)} degrees. ` +
      `Path loss ${result.lossDb.toFixed(1)} dB, predicted ${level.toFixed(1)} dBm.`),
    result.itmErrno > 0
      ? el('p', { class: 'notice warn' },
          'The model reported a warning for this path, so treat the number with care.')
      : null,
    chart,
  ]);

  if (!result.profile.length) return;
  // The ground between the two ends. A hill that touches the straight
  // line is the usual reason a link does not work.
  const instance = echarts.init(chart);
  instance.setOption({
    grid: { left: 48, right: 16, top: 20, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: result.profile.map((point) => point.distanceKm.toFixed(1)),
      axisLabel: { color: PALETTE.muted },
      name: 'km',
    },
    yAxis: { type: 'value', axisLabel: { color: PALETTE.muted }, name: 'm' },
    series: [
      {
        name: 'Ground',
        type: 'line',
        areaStyle: { opacity: 0.35 },
        showSymbol: false,
        data: result.profile.map((point) => Math.round(point.groundM)),
        itemStyle: { color: PALETTE.accent },
      },
    ],
  });
}

/* ---------------------------------------------------------------- */
/* Wiring                                                            */

let wired = false;

function wirePlanner() {
  if (wired) return;
  wired = true;

  const climate = field('radio_climate');
  if (climate) {
    replace(climate, SonoranPlannerParams.CLIMATE_LABELS.map(([value, label]) =>
      el('option', { value, text: label })));
  }
  const preset = document.querySelector('[data-planner="preset"]');
  if (preset) {
    replace(preset, SonoranPlannerParams.PRESETS.map((item) =>
      el('option', { value: item.key, text: `${item.label} (${item.sensitivity} dBm)` })));
    preset.addEventListener('change', () => {
      const chosen = SonoranPlannerParams.PRESETS.find((item) => item.key === preset.value);
      if (chosen) fillForm({ sensitivity: chosen.sensitivity });
    });
  }

  const defaults = SonoranPlannerParams.DEFAULTS;
  fillForm({ ...defaults, radius: defaults.radius / 1000 });
  if (preset) preset.value = defaults.preset;

  const run = document.querySelector('[data-planner-run]');
  if (run) run.addEventListener('click', runCoverage);
  const stop = document.querySelector('[data-planner-cancel]');
  if (stop) stop.addEventListener('click', cancelRun);
  const clear = document.querySelector('[data-planner-clear]');
  if (clear) {
    clear.addEventListener('click', () => {
      state.result = null;
      state.request = null;
      state.coverageLayer.clearLayers();
      state.linkLayer.clearLayers();
      replace(document.querySelector('[data-planner-summary]'), []);
      replace(document.querySelector('[data-planner-link]'), []);
      drawNodes();
      setNotice('', '');
    });
  }
}

/** Called by the router when the Planner page is shown. */
async function show() {
  const map = ensurePlannerMap();
  wirePlanner();
  setTimeout(() => map.invalidateSize(), 0);

  // Read the node list on every visit, not only the first. A node
  // fades once it has not been heard for a day, and that age is worked
  // out from `last_heard`. Read once, the list would keep aging on the
  // page and fade nodes the mesh is still hearing. A failed read keeps
  // the list already held rather than blanking the map.
  const first = !state.nodes.length;
  const nodes = await get('api/map/nodes').catch(() => null);
  if (nodes) state.nodes = nodes;
  drawNodes();
  if (first && !state.result && state.nodes.length) {
    const points = state.nodes
      .filter((node) => node.lat != null && node.lon != null)
      .map((node) => [node.lat, node.lon]);
    if (points.length) map.fitBounds(points, { padding: [30, 30], maxZoom: 11 });
  }
}

/*
 * `state` is exposed to make this page answerable from the browser
 * console: what the last run produced, where the map is looking, and
 * which nodes were counted. Nothing here reads it back, so it can be
 * inspected freely but not usefully written to.
 */
window.SonoranPlanner = { show, state };
