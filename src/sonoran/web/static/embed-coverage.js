/*
 * The public coverage embed.
 *
 * It draws one layer: the weaker of the two directions, which is the
 * only honest answer to "can I use the mesh here". The dashboard offers
 * the other two, because the people who run the mesh have a use for
 * them and a visitor does not.
 *
 * It reads /api/embed/* and nothing else. That surface is sanitised on
 * the server, so this file cannot leak anything by mistake.
 */

'use strict';

(function () {
  const CONFIG = window.SONORAN_EMBED || {};
  const DOCUMENT_BASE = new URL('../', document.baseURI);
  const API = (path) =>
    new URL(String(path).replace(/^\//, ''), CONFIG.apiBase || DOCUMENT_BASE).toString();

  // The layer a visitor sees. Not a choice: the other two need
  // explaining and this one does not.
  const LAYER = 'usable';

  // The ramp in coverage/render.py spans this above the limit.

  const state = { map: null, tiles: null, summary: null, preset: null };

  const $ = (selector) => document.querySelector(selector);

  function note(text) {
    const host = $('[data-note]');
    if (host) host.textContent = text;
  }

  function ensureMap() {
    if (state.map) return state.map;
    // The zoom control sits at the top right, because the title card
    // takes the top left and an embed is often narrow.
    const map = L.map('map', {
      preferCanvas: true,
      attributionControl: false,
      zoomControl: false,
    }).setView(
      CONFIG.mapCenter || [34.0, -111.5],
      CONFIG.mapZoom || 7,
    );
    if (CONFIG.tileUrl) {
      L.tileLayer(CONFIG.tileUrl, {
        className: 'basemap-tiles',
        attribution: '',
        maxZoom: 19,
      }).addTo(map);
    }
    L.control.zoom({ position: 'topright' }).addTo(map);
    state.map = map;
    return map;
  }

  function drawTiles() {
    const map = ensureMap();
    if (state.tiles) {
      map.removeLayer(state.tiles);
      state.tiles = null;
    }
    const summary = state.summary;
    if (!summary || !summary.available || !state.preset) return;

    // The placeholders must not go through `new URL`, which percent
    // encodes the braces and asks for a tile named `%7Bz%7D`.
    const base = API(
      `/api/coverage/tiles/${summary.stamp}/${state.preset}/${LAYER}/`,
    );
    state.tiles = L.tileLayer(`${base}{z}/{x}/{y}.png`, {
      minNativeZoom: summary.min_zoom,
      maxNativeZoom: summary.max_zoom,
      maxZoom: 19,
      bounds: L.latLngBounds(
        [summary.bounds[0], summary.bounds[1]],
        [summary.bounds[2], summary.bounds[3]],
      ),
      errorTileUrl:
        'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
    }).addTo(map);
  }

  function drawLegend() {
    const legend = $('[data-legend]');
    const preset = (state.summary.presets || []).find((item) => item.preset === state.preset);
    if (!legend || !preset) return;
    legend.hidden = false;
    $('[data-floor]').textContent = `${preset.sensitivity_dbm} dBm`;
    // The span comes from the run. See coverage/render.py.
    const span = Number(state.summary.ramp_span_db) || 0;
    $('[data-ceiling]').textContent = `${preset.sensitivity_dbm + span} dBm`;
  }

  async function drawSites() {
    let nodes = [];
    try {
      const response = await fetch(API('/api/embed/nodes'));
      if (response.ok) nodes = await response.json();
    } catch (error) {
      console.warn('sites unavailable', error);
      return;
    }
    const map = ensureMap();
    for (const node of nodes) {
      L.circleMarker([node.lat, node.lon], {
        radius: node.is_gateway ? 5 : 4,
        color: '#f6ece2',
        weight: node.is_gateway ? 2 : 1,
        fillColor: '#8cb369',
        fillOpacity: 0.9,
      })
        .bindTooltip(node.short_name || node.role, { direction: 'top' })
        .addTo(map);
    }
  }

  function fit(summary) {
    const preset = (summary.presets || []).find((item) => item.preset === state.preset);
    const bounds = (preset && preset.data_bounds) || summary.data_bounds || summary.bounds;
    if (Array.isArray(bounds) && bounds.length === 4) {
      ensureMap().fitBounds(
        L.latLngBounds([bounds[0], bounds[1]], [bounds[2], bounds[3]]),
        { padding: [20, 20] },
      );
    }
  }

  async function start() {
    ensureMap();
    let summary = null;
    try {
      const response = await fetch(API('/api/embed/coverage'));
      if (!response.ok) throw new Error(String(response.status));
      summary = await response.json();
    } catch (error) {
      note('The coverage map could not be read.');
      return;
    }

    state.summary = summary;
    if (!summary.available || !(summary.presets || []).length) {
      note('No coverage map has been made yet.');
      return;
    }

    state.preset = summary.presets[0].preset;
    const picker = $('[data-preset]');
    if (picker && summary.presets.length > 1) {
      picker.hidden = false;
      picker.replaceChildren(
        ...summary.presets.map((item) => {
          const option = document.createElement('option');
          option.value = item.preset;
          option.textContent = item.label;
          return option;
        }),
      );
      picker.addEventListener('change', () => {
        state.preset = picker.value;
        drawTiles();
        drawLegend();
        fit(summary);
      });
    }

    note(
      'Predicted from the nodes the mesh hears, over terrain. It assumes a handheld radio at '
        + `${summary.rx_height_m} m above the ground. A real radio does worse.`,
    );
    const credit = $('[data-credit]');
    if (credit) {
      credit.textContent = CONFIG.tileAttribution || '';
    }

    drawTiles();
    drawLegend();
    fit(summary);
    drawSites();
  }

  start();
}());
