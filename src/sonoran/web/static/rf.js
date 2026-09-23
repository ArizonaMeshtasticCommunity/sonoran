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

  /*
   * Every source the RF map is designed for (docs/design/rf-map.md 1.1).
   * Whether each is stored today comes from `/api/rf/kinds`, never from
   * here, so the page cannot show a source as working before it does.
   * `spectrum` is not an observation kind; it has its own view (design
   * 7.4) and is listed so the page says what is coming.
   */
  const SOURCES = [
    { key: 'aircraft', label: 'Aircraft', kinds: ['adsb', 'uat'], band: '1090 and 978 MHz' },
    { key: 'aprs', label: 'APRS', kinds: ['aprs'], band: '144.39 MHz' },
    { key: 'sonde', label: 'Radiosondes', kinds: ['sonde'], band: '400 to 406 MHz' },
    { key: 'ism', label: 'Weather sensors', kinds: ['ism'], band: '433 and 915 MHz' },
    { key: 'spectrum', label: '900 MHz band', kinds: ['spectrum'], band: '902 to 928 MHz' },
  ];
  const sourceOf = (kind) => SOURCES.find((source) => source.kinds.includes(kind));

  /* How each kind is drawn. Shape and colour both differ, so a mark
     reads without colour. Aircraft take their colour from altitude. */
  const KIND_STYLE = {
    aprs: { colour: '#a48fd0', radius: 6, label: 'APRS station' },
    sonde: { colour: '#f6ece2', radius: 5, label: 'Radiosonde' },
    ism: { colour: '#8fd0a4', radius: 4, label: 'Weather sensor' },
  };

  const state = {
    map: null,
    aircraft: null,
    stations: null,
    heard: null,
    track: null,
    selectedStation: null,
    selectedThing: null,
    kinds: null,
    // Which layers are shown, by source key, plus `stations`.
    shown: { stations: true },
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

  /* Any other kind: what it is, its id, and the plain fields it sent. */
  function otherTooltip(row) {
    const style = KIND_STYLE[row.kind] || { label: row.kind };
    const meta = row.meta || {};
    const extras = Object.entries(meta).slice(0, 4)
      .map(([key, value]) => el('div', { text: `${key.replaceAll('_', ' ')}: ${String(value).slice(0, 40)}` }));
    return el('div', { class: 'rf-tip' },
      el('strong', { text: row.id }),
      el('div', { text: style.label }),
      row.alt_m == null ? null : el('div', { text: `${Math.round(row.alt_m).toLocaleString()} m` }),
      extras,
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
      row.spectrum_last ? el('div', { text: `sweeps the 900 MHz band, newest minute ${ago(row.spectrum_last)}` }) : null,
      el('div', { class: 'muted', text: 'Click to show where it hears aircraft.' }));
  }

  function isAircraft(kind) {
    return kind === 'adsb' || kind === 'uat';
  }

  function drawThings(rows) {
    state.aircraft.clearLayers();
    for (const row of rows) {
      const source = sourceOf(row.kind);
      if (!source || !state.shown[source.key]) continue;
      const aircraft = isAircraft(row.kind);
      const style = aircraft ? null : KIND_STYLE[row.kind] || { colour: '#b59c88', radius: 4 };
      const colour = aircraft ? altitudeColour(row.alt_m) : style.colour;
      const marker = L.circleMarker([row.lat, row.lon], {
        radius: aircraft ? 5 : style.radius,
        color: colour,
        fillColor: colour,
        // Hollow for anything that is not an aircraft, so the two read
        // apart without colour.
        fillOpacity: aircraft ? 0.9 : 0.15,
        weight: aircraft ? 1 : 2,
        /* Built on hover, not on draw. Leaflet calls this when the
           tooltip opens, so a busy sky no longer builds six elements
           per aircraft on every poll for tooltips nobody hovered. */
      }).bindTooltip(() => (aircraft ? aircraftTooltip(row) : otherTooltip(row)), { direction: 'top' });
      marker.on('click', () => selectThing(row));
      state.aircraft.addLayer(marker);
      if (aircraft && row.track_deg != null) {
        state.aircraft.addLayer(L.polyline([[row.lat, row.lon], ahead(row.lat, row.lon, row.track_deg, 4)], {
          color: colour, weight: 2, opacity: 0.9, interactive: false,
        }));
      }
    }
  }

  function drawStations(rows) {
    state.stations.clearLayers();
    if (!state.shown.stations) return;
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
        .bindTooltip(() => stationTooltip(row), { direction: 'top' });
      marker.on('click', () => selectStation(row.station));
      state.stations.addLayer(marker);
    }
  }

  async function selectThing(row) {
    state.selectedThing = row;
    state.track.clearLayers();
    const colour = isAircraft(row.kind) ? altitudeColour(row.alt_m) : (KIND_STYLE[row.kind] || {}).colour;
    const { body } = await getJson(`api/rf/track/${row.kind}/${encodeURIComponent(row.id)}?hours=1`)
      .catch(() => ({ body: { points: [] } }));
    const points = body.points.map((p) => [p.lat, p.lon]);
    if (points.length > 1) {
      state.track.addLayer(L.polyline(points, {
        color: colour, weight: 2, opacity: 0.8, dashArray: '2 6',
      }));
    }
    const note = $('[data-rf-selected]');
    if (note) {
      note.textContent = points.length > 1
        ? `Track of ${(row.meta && row.meta.callsign) || row.id}: ${points.length} points in the last hour.`
        : `Only one point heard for ${row.id} in the last hour.`;
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
    if (!target) return;
    target.replaceChildren();
    if (state.shown.aircraft) {
      target.append(...ALTITUDE_BANDS.map((band) =>
        el('span', { class: 'legend-note' },
          el('span', { class: 'swatch', style: `background:${band.colour}` }), `aircraft ${band.label}`)));
    }
    for (const [kind, style] of Object.entries(KIND_STYLE)) {
      const source = sourceOf(kind);
      if (!source || !state.shown[source.key]) continue;
      target.append(el('span', { class: 'legend-note' },
        el('span', { class: 'swatch ring', style: `border-color:${style.colour}` }), style.label));
    }
    if (state.shown.stations) {
      target.append(el('span', { class: 'legend-note' },
        el('span', { class: 'swatch', style: 'background:#f6ece2' }), 'our receiver (dashed: position rounded)'));
    }
  }

  /* One toggle per stored source, then the receivers. Built once. */
  function drawLayerToggles(page, stored) {
    const target = $('[data-rf-layers]', page);
    if (!target || target.childElementCount) return;
    const layers = SOURCES.filter((source) => source.kinds.some((kind) => stored.has(kind)))
      .map((source) => ({ key: source.key, label: source.label }))
      .concat([{ key: 'stations', label: 'Receivers' }]);
    for (const layer of layers) {
      if (!(layer.key in state.shown)) state.shown[layer.key] = true;
      const button = el('button', {
        type: 'button', class: 'toggle', 'aria-pressed': String(state.shown[layer.key]), text: layer.label,
      });
      button.addEventListener('click', () => {
        state.shown[layer.key] = !state.shown[layer.key];
        button.setAttribute('aria-pressed', String(state.shown[layer.key]));
        show(page);
      });
      target.append(button);
    }
  }

  /*
   * The sources strip: every source the RF map is designed for, with
   * its honest state. Live: stored, with how many were heard. Sent but
   * not stored: a station offers it and the ingest does not keep it
   * yet. Not collected yet: nobody sends it.
   */
  function drawSources(page, stored, stations, counts) {
    const target = $('[data-rf-sources]', page);
    if (!target) return;
    const offering = (source) => stations.filter((station) =>
      (station.kinds || []).some((kind) => source.kinds.includes(kind))).length;
    // A sweeper is known by what it sends, not by the kinds a heartbeat
    // lists, so a station sweeps when it sent a minute of the band lately.
    const sweeping = stations.filter((station) => station.spectrum_last
      && Date.now() - Date.parse(station.spectrum_last) < BAND_FRESH_MS).length;
    const views = new Set((state.kinds && state.kinds.views) || []);
    target.replaceChildren(...SOURCES.map((source) => {
      if (source.key === 'spectrum') {
        const ready = views.has('spectrum');
        const [status, tone] = ready && sweeping
          ? [`live, ${sweeping} station${sweeping === 1 ? '' : 's'} sweeping`, 'live']
          : ready ? ['ready, no station sweeps yet', 'ready'] : ['not collected yet', 'off'];
        return el('li', { class: `rf-source ${tone}` },
          el('strong', { text: source.label }),
          el('span', { class: 'muted', text: source.band }),
          el('span', { class: 'rf-status', text: status }));
      }
      const isStored = source.kinds.some((kind) => stored.has(kind));
      const senders = offering(source);
      let status;
      let tone;
      if (isStored && senders) {
        status = `live, ${(counts[source.key] || 0).toLocaleString()} heard`;
        tone = 'live';
      } else if (isStored) {
        status = 'ready, no station sends it yet';
        tone = 'ready';
      } else if (senders) {
        status = `sent by ${senders} station${senders === 1 ? '' : 's'}, not stored yet`;
        tone = 'waiting';
      } else {
        status = 'not collected yet';
        tone = 'off';
      }
      return el('li', { class: `rf-source ${tone}` },
        el('strong', { text: source.label }),
        el('span', { class: 'muted', text: source.band }),
        el('span', { class: 'rf-status', text: status }));
    }));
  }


  /* --- The 900 MHz band (design 7.4) ----------------------------- */

  /* A station counts as sweeping when its newest minute is this fresh. */
  const BAND_FRESH_MS = 10 * 60 * 1000;
  /* The band view is redrawn at most this often by the Live refresh. */
  const BAND_REFRESH_MS = 60 * 1000;
  /*
   * The waterfall's colour ramp, quiet to loud. It is data, not chrome,
   * so it does not change with the theme (see docs/design/palette.md).
   * It runs dark to bright so it reads in greyscale too.
   */
  const BAND_RAMP = ['#0b0d2b', '#2a1b6b', '#6a1f7a', '#b1325f', '#e8603c', '#f9a53f', '#fcf3a8'];
  /* The presets drawn on the busy chart before a reader picks others. */
  const BAND_DEFAULT_CHANNELS = new Set(['LongFast', 'MediumFast']);

  const band = { station: null, hours: '6', view: 'p50', data: null, channels: null, drawnAt: 0, wired: false, where: null };

  function rampColour(fraction) {
    const f = Math.max(0, Math.min(1, fraction));
    const at = f * (BAND_RAMP.length - 1);
    const low = Math.floor(at);
    const high = Math.min(BAND_RAMP.length - 1, low + 1);
    const mix = at - low;
    const parse = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    const a = parse(BAND_RAMP[low]);
    const b = parse(BAND_RAMP[high]);
    return a.map((value, i) => Math.round(value + (b[i] - value) * mix));
  }

  /* The level a fraction of the way through the sorted values. */
  function quantile(sorted, q) {
    if (!sorted.length) return 0;
    return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  }

  const mhz = (hz) => `${(hz / 1e6).toFixed(hz % 1e6 ? 3 : 0)} MHz`;

  /** The bins a channel covers, clamped to the sweep. */
  function channelBins(channel, data) {
    const first = Math.floor((channel.low_hz - data.f_start_hz) / data.bin_hz);
    const last = Math.ceil((channel.high_hz - data.f_start_hz) / data.bin_hz) - 1;
    return [Math.max(0, first), Math.min(data.bins - 1, last)];
  }

  function drawWaterfall(page) {
    const data = band.data;
    const canvas = $('[data-rf-band-canvas]', page);
    const marks = $('[data-rf-band-marks]', page);
    const axis = $('[data-rf-band-axis]', page);
    const scale = $('[data-rf-band-scale]', page);
    const rows = data.rows.slice().reverse(); // newest at the top
    canvas.width = data.bins;
    canvas.height = Math.max(1, rows.length);
    const ctx = canvas.getContext('2d');
    const image = ctx.createImageData(canvas.width, canvas.height);
    // Scale to this station's own spread: its units are its dongle's,
    // so only its own quiet and loud ends mean anything.
    const values = rows.flatMap((row) => row[band.view]).filter((v) => v != null).sort((a, b) => a - b);
    const low = quantile(values, 0.02);
    const high = quantile(values, 0.995);
    const span = Math.max(1, high - low);
    rows.forEach((row, y) => {
      row[band.view].forEach((value, x) => {
        const at = (y * canvas.width + x) * 4;
        if (value == null) {
          image.data.set([40, 40, 40, 255], at); // no sweep reached this bin
          return;
        }
        const [r, g, b] = rampColour((value - low) / span);
        image.data.set([r, g, b, 255], at);
      });
    });
    ctx.putImageData(image, 0, 0);

    // Our channels, drawn from the firmware's own arithmetic.
    const width = data.bins * data.bin_hz;
    const left = (hz) => `${((hz - data.f_start_hz) / width) * 100}%`;
    const inSweep = (band.channels || []).filter((c) => c.high_hz > data.f_start_hz && c.low_hz < data.f_start_hz + width);
    marks.replaceChildren(...inSweep.map((c) => el('span', {
      class: 'rf-mark', title: `${c.label}: ${mhz(c.centre_hz)}, ${c.bandwidth_hz / 1000} kHz`,
      style: `left:${left(c.low_hz)};width:calc(${left(c.high_hz)} - ${left(c.low_hz)})`,
    })));
    // Neighbouring presets sit a few hundred kHz apart, so the names go
    // on three rows, in turn from low to high, and do not overlap. The
    // band's edges are written under the waterfall instead.
    axis.replaceChildren(...inSweep.map((c, index) => el('span', {
      class: `rf-tick channel row-${index % 3}`, style: `left:${left(c.centre_hz)}`, text: c.name,
    })));
    scale.replaceChildren(
      el('span', { class: 'rf-edges' },
        el('span', { text: mhz(data.f_start_hz) }),
        el('span', { text: mhz(data.f_start_hz + width) })),
      el('span', { text: 'quiet' }),
      el('span', { class: 'rf-ramp', style: `background:linear-gradient(to right, ${BAND_RAMP.join(', ')})` }),
      el('span', { text: 'loud, for this station' }),
      el('span', { class: 'muted', text: ` · newest at the top · each row ${data.bucket_minutes} min · grey: not swept` }));
  }

  function drawBusy(page) {
    const data = band.data;
    const target = $('[data-rf-band-busy]', page);
    if (!window.echarts || !target) return;
    const inSweep = (band.channels || []).filter((c) => c.high_hz > data.f_start_hz
      && c.low_hz < data.f_start_hz + data.bins * data.bin_hz);
    const covered = new Set();
    const series = inSweep.map((channel) => {
      const [first, last] = channelBins(channel, data);
      for (let i = first; i <= last; i += 1) covered.add(i);
      return {
        name: `${channel.name} (ours)`,
        type: 'line', showSymbol: false,
        data: data.rows.map((row) => {
          const values = row.busy.slice(first, last + 1).filter((v) => v != null);
          return [Date.parse(row.t), values.length ? values.reduce((a, b) => a + b, 0) / values.length : null];
        }),
      };
    });
    // Everything outside our channels: this is the interference number.
    series.unshift({
      name: 'Outside our channels', type: 'line', showSymbol: false, lineStyle: { width: 2.5 },
      data: data.rows.map((row) => {
        const values = row.busy.filter((v, i) => v != null && !covered.has(i));
        return [Date.parse(row.t), values.length ? values.reduce((a, b) => a + b, 0) / values.length : null];
      }),
    });
    const selected = Object.fromEntries(series.map((item) => [item.name,
      item.name === 'Outside our channels' || BAND_DEFAULT_CHANNELS.has(item.name.replace(' (ours)', ''))]));
    let chart = window.echarts.getInstanceByDom(target);
    if (!chart) chart = window.echarts.init(target, null, { renderer: 'canvas' });
    const css = getComputedStyle(document.documentElement);
    const token = (name, fallback) => (css.getPropertyValue(name) || '').trim() || fallback;
    chart.setOption({
      backgroundColor: 'transparent',
      textStyle: { color: token('--muted', '#b59c88') },
      tooltip: { trigger: 'axis', valueFormatter: (v) => (v == null ? '-' : `${v.toFixed(1)} %`) },
      legend: { top: 0, type: 'scroll', selected, textStyle: { color: token('--muted', '#b59c88') } },
      grid: { left: 40, right: 16, top: 36, bottom: 28, containLabel: true },
      xAxis: { type: 'time' },
      yAxis: { type: 'value', min: 0, axisLabel: { formatter: '{value} %' } },
      series,
    }, true);
  }

  function explain(page) {
    const text = band.view === 'p50'
      ? 'The median of each minute’s sweeps: the noise floor. A mesh packet is a short burst, so it does not move the median. A bright column here is something on the air most of the time.'
      : 'The 95th percentile of each minute’s sweeps: the bursts. Our own packets show here, inside the marked channels. A burst outside every mark is something else.';
    $('[data-rf-band-explain]', page).textContent = text
      + ' Levels are relative to this station’s own receiver and never compare two stations.';
  }

  /* A distance in words: "1 km", "500 m". */
  const metres = (value) => (value >= 1000 ? `${Math.round(value / 100) / 10} km` : `${value} m`);

  /**
   * Say where the waterfall was measured.
   *
   * The position is the station's own, rounded by its agent before it
   * was sent, so it is given with its rounding and never as a point. A
   * station that shared no position is said to have none, because a
   * waterfall with no place is noise with no address.
   */
  function drawWhere(page, row) {
    const target = $('[data-rf-band-where]', page);
    if (!target) return;
    if (!row || row.lat == null || row.lon == null) {
      target.className = 'rf-where unknown';
      target.replaceChildren(
        el('strong', { text: 'Where: not shared. ' }),
        `${band.station} has not shared its position, so where these samples were taken is unknown. `
        + 'Its operator can set STATION_LAT and STATION_LON on the agent; it is rounded before it is sent.');
      return;
    }
    const around = row.precision_m ? `within about ${metres(row.precision_m)} of ` : 'at ';
    const button = el('button', { type: 'button', class: 'linky', text: 'Show on map' });
    button.addEventListener('click', () => {
      const map = ensureMap();
      if (band.where) band.where.remove();
      band.where = L.circle([row.lat, row.lon], {
        radius: Math.max(row.precision_m || 0, 300), color: '#f9a53f', weight: 2, fill: false,
        interactive: false,
      }).addTo(map);
      map.setView([row.lat, row.lon], row.precision_m > 3000 ? 10 : 12);
      $('#rf-map').scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    target.className = 'rf-where';
    target.replaceChildren(
      el('strong', { text: 'Where: ' }),
      `measured at ${band.station}, ${around}${row.lat.toFixed(3)}, ${row.lon.toFixed(3)}`
      + (row.precision_m ? ' (the operator rounded it). ' : '. '),
      button);
  }

  async function drawBand(page, stations, force) {
    const panel = $('[data-rf-band]', page);
    if (!panel) return;
    const sweepers = stations.filter((station) => station.spectrum_last);
    panel.hidden = !sweepers.length;
    if (!sweepers.length) return;
    if (!force && band.data && Date.now() - band.drawnAt < BAND_REFRESH_MS) return;

    const picker = $('[data-rf-band-station]', page);
    if (!band.station || !sweepers.some((s) => s.station === band.station)) band.station = sweepers[0].station;
    picker.replaceChildren(...sweepers.map((s) => el('option', { value: s.station, text: s.station })));
    picker.value = band.station;
    if (!band.wired) {
      band.wired = true;
      picker.addEventListener('change', () => { band.station = picker.value; drawBand(page, stations, true); });
      $('[data-rf-band-hours]', page).addEventListener('change', (event) => { band.hours = event.target.value; drawBand(page, stations, true); });
      for (const button of page.querySelectorAll('[data-rf-band-view]')) {
        button.addEventListener('click', () => {
          band.view = button.dataset.rfBandView;
          for (const other of page.querySelectorAll('[data-rf-band-view]')) {
            other.setAttribute('aria-pressed', String(other === button));
          }
          explain(page);
          if (band.data && band.data.rows.length) drawWaterfall(page);
        });
      }
    }
    explain(page);
    drawWhere(page, stations.find((row) => row.station === band.station));
    try {
      if (!band.channels) band.channels = (await getJson('api/rf/channels')).body.channels;
      band.data = (await getJson(`api/rf/spectrum/${encodeURIComponent(band.station)}?hours=${band.hours}`)).body;
    } catch (error) {
      $('[data-rf-band-note]', page).textContent = `could not be loaded: ${error.message}`;
      return;
    }
    band.drawnAt = Date.now();
    const note = $('[data-rf-band-note]', page);
    if (!band.data.rows.length) {
      note.textContent = `${band.station} sent no minute of the band in the last ${band.hours} h`;
      return;
    }
    note.textContent = `${band.station}, ${mhz(band.data.f_start_hz)} to `
      + `${mhz(band.data.f_start_hz + band.data.bins * band.data.bin_hz)}, `
      + `${band.data.bin_hz / 1000} kHz bins, gain ${Number(band.data.gain_db).toFixed(1)} dB, newest ${ago(band.data.newest)}`;
    drawWaterfall(page);
    drawBusy(page);
  }

  async function show(page) {
    const map = ensureMap();
    setTimeout(() => map.invalidateSize(), 0);
    const minutes = $('[data-rf-minutes]', page).value || '5';
    const summary = $('[data-rf-summary]', page);
    let stations;
    let latest;
    try {
      if (!state.kinds) state.kinds = (await getJson('api/rf/kinds')).body;
      [stations, latest] = await Promise.all([
        getJson('api/rf/stations'),
        getJson(`api/rf/latest?minutes=${minutes}&limit=5000`),
      ]);
    } catch (error) {
      summary.textContent = `The RF data could not be loaded: ${error.message}.`;
      return;
    }
    const stored = new Set(state.kinds.stored);
    drawLayerToggles(page, stored);
    const counts = {};
    for (const row of latest.body) {
      const source = sourceOf(row.kind);
      if (source) counts[source.key] = (counts[source.key] || 0) + 1;
    }
    drawSources(page, stored, stations.body, counts);
    drawLegend(page);
    drawStations(stations.body);
    drawThings(latest.body);
    drawBand(page, stations.body, false);
    if (!stations.body.length) {
      summary.textContent = 'No RF station has reported yet. A station runs rf-agent beside its SDR.';
      return;
    }
    const online = stations.body.filter((station) => station.online).length;
    const total = Number(latest.total || latest.body.length);
    const heard = SOURCES.filter((source) => counts[source.key])
      .map((source) => `${counts[source.key].toLocaleString()} ${source.label.toLowerCase()}`);
    summary.textContent =
      `In the last ${minutes} min: ${heard.length ? heard.join(', ') : 'nothing'} heard by `
      + `${stations.body.length} station${stations.body.length === 1 ? '' : 's'} `
      + `(${online} reporting now).`
      + (total > latest.body.length ? ` The newest ${latest.body.length.toLocaleString()} of ${total.toLocaleString()} are drawn.` : '');
    if (state.selectedStation) selectStation(state.selectedStation);
  }

  window.SonoranRf = { show, state, altitudeColour };
})();
