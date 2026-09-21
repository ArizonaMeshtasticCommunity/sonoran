/*
 * The RF page: what the community's own receivers hear beyond Meshtastic.
 *
 * Aircraft first. Every mark is something one of our stations heard,
 * sent by `rf-agent` and stored by `sonoran-rf-ingest`. Nothing is
 * fetched from anywhere else, so an aircraft that is not here was not
 * heard by us. See docs/design/rf-map.md.
 *
 * Its own file and its own Leaflet map, like coverage.js. It loads
 * before app.js so the router finds it on a reload straight to #rf.
 *
 * Text that came off the air (a callsign, a station name) is only ever
 * set as text, never as HTML: a tooltip is a DOM node, not a string.
 */

'use strict';

(function () {
  const CONFIG = window.SONORAN || {};
  const API_BASE = CONFIG.apiBase || '';
  const api = (path) =>
    new URL(String(path).replace(/^\//, ''), API_BASE || document.baseURI).toString();
  const $ = (selector, root = document) => root.querySelector(selector);

  /*
   * Altitude bands, low to high. Colour carries altitude and nothing
   * else: never anything that could read as risk. The same bands are
   * drawn in the legend, from this one list.
   */
  const ALTITUDE_BANDS = [
    { below: 1500, colour: '#f4703f', label: 'under 1,500 m' },
    { below: 5000, colour: '#e0b64a', label: '1,500 to 5,000 m' },
    { below: 9000, colour: '#b6d94c', label: '5,000 to 9,000 m' },
    { below: Infinity, colour: '#46b3e6', label: 'above 9,000 m' },
  ];
  const UNKNOWN_ALTITUDE = '#b59c88';
  // A station's heard cells, from quiet to loud. Relative to that one
  // station: receivers read in their own units, not comparable dBm.
  const HEARD_RAMP = ['#3a2a20', '#6b3f22', '#a8592a', '#e0793a', '#f6b35a'];

  const state = {
    map: null,
    aircraft: null,
    stations: null,
    heard: null,
    track: null,
    selectedStation: null,
    selectedAircraft: null,
  };

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value == null) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child != null) node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function altitudeColour(alt) {
    if (alt == null) return UNKNOWN_ALTITUDE;
    return ALTITUDE_BANDS.find((band) => alt < band.below).colour;
  }

  const ago = (iso) => {
    const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
    if (seconds < 90) return `${seconds} s ago`;
    if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
    return `${Math.round(seconds / 3600)} h ago`;
  };

  /* A point this far along a heading, for the short direction tick. */
  function ahead(lat, lon, degrees, km) {
    const rad = (degrees * Math.PI) / 180;
    const dLat = (km / 111.32) * Math.cos(rad);
    const dLon = (km / (111.32 * Math.cos((lat * Math.PI) / 180))) * Math.sin(rad);
    return [lat + dLat, lon + dLon];
  }

  function ensureMap() {
    if (state.map) return state.map;
    const map = L.map('rf-map', { preferCanvas: true }).setView(
      CONFIG.mapCenter || [34.0, -111.5],
      CONFIG.mapZoom || 7,
    );
    if (CONFIG.tileUrl) {
      L.tileLayer(CONFIG.tileUrl, {
        className: 'basemap-tiles',
        attribution: CONFIG.tileAttribution || '',
        maxZoom: 19,
      }).addTo(map);
    }
    state.heard = L.layerGroup().addTo(map);
    state.track = L.layerGroup().addTo(map);
    state.stations = L.layerGroup().addTo(map);
    state.aircraft = L.layerGroup().addTo(map);
    state.map = map;
    return map;
  }

  async function getJson(path) {
    const response = await fetch(api(path));
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return { body: await response.json(), total: response.headers.get('X-Total-Count') };
  }

  function aircraftTooltip(row) {
    const meta = row.meta || {};
    const name = meta.callsign || meta.flight || row.id.toUpperCase();
    return el('div', { class: 'rf-tip' },
      el('strong', { text: name }),
      el('div', { text: `ICAO ${row.id.toUpperCase()} · ${row.kind === 'uat' ? 'UAT' : 'ADS-B'}` }),
      el('div', { text: row.alt_m == null ? 'altitude not reported' : `${Math.round(row.alt_m).toLocaleString()} m${row.alt_ref === 'geom' ? ' (GNSS)' : ''}` }),
      row.gs_kn == null ? null : el('div', { text: `${Math.round(row.gs_kn)} kn` }),
      el('div', { class: 'muted', text: `heard ${ago(row.t)} by ${row.station}` }));
  }

  function stationTooltip(row) {
    const counts = row.counts || {};
    return el('div', { class: 'rf-tip' },
      el('strong', { text: row.station }),
      el('div', { text: row.online ? 'reporting' : `silent since ${ago(row.last_seen)}` }),
      el('div', { text: (row.kinds || []).join(', ') || 'no kinds reported' }),
      counts.heard == null ? null
        : el('div', { text: `last minute: heard ${counts.heard}, sent ${counts.sent}, thinned ${counts.dropped}` }),
      row.precision_m ? el('div', { class: 'muted', text: `position rounded to ${row.precision_m} m` }) : null,
      el('div', { class: 'muted', text: 'Click to show where it hears aircraft.' }));
  }

  function drawAircraft(rows, show) {
    state.aircraft.clearLayers();
    if (!show) return;
    for (const row of rows) {
      const colour = altitudeColour(row.alt_m);
      const marker = L.circleMarker([row.lat, row.lon], {
        radius: 5, color: colour, fillColor: colour, fillOpacity: 0.9, weight: 1,
      }).bindTooltip(aircraftTooltip(row), { direction: 'top' });
      marker.on('click', () => selectAircraft(row));
      state.aircraft.addLayer(marker);
      if (row.track_deg != null) {
        state.aircraft.addLayer(L.polyline([[row.lat, row.lon], ahead(row.lat, row.lon, row.track_deg, 4)], {
          color: colour, weight: 2, opacity: 0.9, interactive: false,
        }));
      }
    }
  }

  function drawStations(rows, show) {
    state.stations.clearLayers();
    if (!show) return;
    for (const row of rows) {
      if (row.lat == null || row.lon == null) continue;
      const style = row.online
        ? { color: '#f6ece2', fillColor: '#f6ece2', fillOpacity: 0.9 }
        : { color: '#7d6857', fillColor: '#7d6857', fillOpacity: 0.5 };
      // The position was rounded by the agent; draw how much, honestly.
      if (row.precision_m) {
        state.stations.addLayer(L.circle([row.lat, row.lon], {
          radius: row.precision_m, color: style.color, weight: 1, dashArray: '4 4',
          fill: false, interactive: false,
        }));
      }
      const marker = L.circleMarker([row.lat, row.lon], { radius: 7, weight: 2, ...style })
        .bindTooltip(stationTooltip(row), { direction: 'top' });
      marker.on('click', () => selectStation(row.station));
      state.stations.addLayer(marker);
    }
  }

  async function selectAircraft(row) {
    state.selectedAircraft = row;
    state.track.clearLayers();
    const { body } = await getJson(`api/rf/track/${row.kind}/${encodeURIComponent(row.id)}?hours=1`)
      .catch(() => ({ body: { points: [] } }));
    const points = body.points.map((p) => [p.lat, p.lon]);
    if (points.length > 1) {
      state.track.addLayer(L.polyline(points, {
        color: altitudeColour(row.alt_m), weight: 2, opacity: 0.8, dashArray: '2 6',
      }));
    }
    const note = $('[data-rf-selected]');
    if (note) {
      note.textContent = points.length > 1
        ? `Track of ${(row.meta && row.meta.callsign) || row.id.toUpperCase()}: ${points.length} points in the last hour.`
        : `Only one point heard for ${row.id.toUpperCase()} in the last hour.`;
    }
  }

  async function selectStation(station) {
    state.selectedStation = station;
    state.heard.clearLayers();
    const { body } = await getJson(`api/rf/heard/${encodeURIComponent(station)}?kind=adsb&hours=24`)
      .catch(() => ({ body: { cells: [], cell_deg: 0.02 } }));
    const levels = body.cells.map((c) => c.best_rssi_db).filter((v) => v != null);
    const low = levels.length ? Math.min(...levels) : 0;
    const high = levels.length ? Math.max(...levels) : 0;
    const half = body.cell_deg / 2;
    for (const cell of body.cells) {
      const share = high > low && cell.best_rssi_db != null ? (cell.best_rssi_db - low) / (high - low) : 0.5;
      const colour = HEARD_RAMP[Math.min(HEARD_RAMP.length - 1, Math.floor(share * HEARD_RAMP.length))];
      state.heard.addLayer(L.rectangle(
        [[cell.lat - half, cell.lon - half], [cell.lat + half, cell.lon + half]],
        { color: colour, weight: 0, fillColor: colour, fillOpacity: 0.55, interactive: false },
      ));
    }
    const note = $('[data-rf-selected]');
    if (note) {
      note.textContent = body.cells.length
        ? `${station} heard aircraft in ${body.cells.length} places of about 2 km in the last 24 h. Brighter is louder, relative to this station only.`
        : `${station} has heard no aircraft in the last 24 h.`;
    }
  }

  function drawLegend(page) {
    const target = $('[data-rf-legend]', page);
    if (!target || target.childElementCount) return;
    target.append(...ALTITUDE_BANDS.map((band) =>
      el('span', { class: 'legend-note' },
        el('span', { class: 'swatch', style: `background:${band.colour}` }), band.label)),
    el('span', { class: 'legend-note' },
      el('span', { class: 'swatch', style: `background:${UNKNOWN_ALTITUDE}` }), 'altitude not reported'));
  }

  function pressed(page, name) {
    const button = $(`[data-rf-layer="${name}"]`, page);
    return !button || button.getAttribute('aria-pressed') === 'true';
  }

  async function show(page) {
    const map = ensureMap();
    setTimeout(() => map.invalidateSize(), 0);
    drawLegend(page);
    const minutes = $('[data-rf-minutes]', page).value || '5';
    const summary = $('[data-rf-summary]', page);
    let stations;
    let latest;
    try {
      [stations, latest] = await Promise.all([
        getJson('api/rf/stations'),
        getJson(`api/rf/latest?minutes=${minutes}&limit=5000`),
      ]);
    } catch (error) {
      summary.textContent = `The RF data could not be loaded: ${error.message}.`;
      return;
    }
    const online = stations.body.filter((s) => s.online).length;
    drawStations(stations.body, pressed(page, 'stations'));
    drawAircraft(latest.body, pressed(page, 'aircraft'));
    const total = Number(latest.total || latest.body.length);
    if (!stations.body.length) {
      summary.textContent = 'No RF station has reported yet. A station runs rf-agent beside its SDR.';
      return;
    }
    summary.textContent =
      `${total.toLocaleString()} aircraft heard in the last ${minutes} min by `
      + `${stations.body.length} station${stations.body.length === 1 ? '' : 's'} `
      + `(${online} reporting now).`
      + (total > latest.body.length ? ` The newest ${latest.body.length.toLocaleString()} are drawn.` : '');
    if (state.selectedStation) selectStation(state.selectedStation);
  }

  window.SonoranRf = { show, state, altitudeColour };
})();
