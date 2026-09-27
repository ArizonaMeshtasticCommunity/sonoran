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
    { below: 1500, colour: '#f4703f' },
    { below: 5000, colour: '#e0b64a' },
    { below: 9000, colour: '#b6d94c' },
    { below: Infinity, colour: '#46b3e6' },
  ];

  /*
   * A band's edge in the reader's units, for the legend.
   *
   * Feet are rounded to the nearest hundred: 1,500 m is 4,921 ft, and a
   * legend that says "under 4,900 ft" is read at a glance where "4,921"
   * asks to be checked. The colour still changes at the metre edge.
   */
  function bandEdge(metres) {
    if (!SonoranUnits.imperial()) return SonoranUnits.heightFromM(metres);
    const feet = Math.round((metres * SonoranUnits.FEET_PER_METRE) / 100) * 100;
    return `${feet.toLocaleString()} ${SonoranUnits.heightUnit()}`;
  }

  function bandLabel(index) {
    const band = ALTITUDE_BANDS[index];
    const lower = index ? ALTITUDE_BANDS[index - 1].below : 0;
    if (!lower) return `under ${bandEdge(band.below)}`;
    if (band.below === Infinity) return `above ${bandEdge(lower)}`;
    return `${bandEdge(lower).split(' ')[0]} to ${bandEdge(band.below)}`;
  }
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
     reads without colour. Aircraft take their colour from altitude.

     `heardHere` marks a kind that sends no position of its own. A weather
     sensor is drawn at the rounded position of the receiver that heard
     it, so the mark says where it was heard, never where it is. */
  const KIND_STYLE = {
    aprs: { colour: '#a48fd0', radius: 6, label: 'APRS station' },
    sonde: { colour: '#f6ece2', radius: 5, label: 'Radiosonde' },
    ism: { colour: '#8fd0a4', radius: 4, label: 'Weather sensor', heardHere: true },
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
      el('div', { text: `${CATEGORY_NAME[String(meta.category || '').toUpperCase()] || 'Aircraft'} · ICAO ${row.id.toUpperCase()} · ${row.kind === 'uat' ? 'UAT' : 'ADS-B'}` }),
      // In the reader's units. In imperial mode that is feet, which is
      // also how aviation states an altitude. Speed stays in knots in both
      // modes, as aviation reads it.
      el('div', { text: row.alt_m == null ? 'altitude not reported' : `${SonoranUnits.heightFromM(row.alt_m)}${row.alt_ref === 'geom' ? ' (GNSS)' : ''}` }),
      row.gs_kn == null ? null : el('div', { text: `${Math.round(row.gs_kn)} kn` }),
      el('div', { class: 'muted', text: `heard ${ago(row.t)} by ${row.station}` }));
  }

  /* Any other kind: what it is, its id, and the plain fields it sent. */
  /* How an APRS packet reached the receiver, in words (design 5.1). The
     ingest writes these keys into `meta` from the contract fields, so
     they are facts about the hearing, not something the sender said. */
  /* --- APRS and weather, in words ----------------------------------

     APRS carries most of what it says in codes: a two-character symbol,
     a destination that names the sending software, a path of callsigns.
     These turn each one into what a person would say. The names come
     from aprs.fi's lists (vendor/aprs/PROVENANCE.md); nothing here
     decodes a packet, it only names what the agent decoded. */
  const APRS_TABLES = window.SonoranAprsTables || { symbols: {}, tocalls: [] };

  /* What an overlay character means on the two symbols that use it to
     say what kind of station this is. Anything else is just a letter
     printed on the symbol. */
  const OVERLAYS = {
    '#': {
      1: 'WIDE1-1 fill-in digipeater',
      A: 'digipeater on an alternate input frequency',
      E: 'emergency-powered digipeater',
      I: 'digipeater with an I-gate',
      L: 'WIDEn-N digipeater with path trapping',
      S: 'state SSn-N digipeater',
      W: 'WIDEn-N digipeater',
      X: 'experimental digipeater',
    },
    '&': {
      I: 'I-gate',
      R: 'receive-only I-gate',
      T: 'I-gate that transmits one hop',
      2: 'I-gate that transmits two hops',
      W: 'Yaesu WIRES-X gateway',
    },
  };

  const call = (value) => String(value).toUpperCase();
  const round1 = (value) => Math.round(Number(value) * 10) / 10;

  /** Name a symbol: `/#` "Digipeater", `S#` "State SSn-N digipeater". */
  function symbolName(symbol) {
    if (typeof symbol !== 'string' || symbol.length !== 2) return null;
    let [table, code] = symbol;
    /* A compressed position writes the overlay digits 0 to 9 as the
       letters a to j, so `b#` is the `1#` fill-in digipeater. */
    if (table >= 'a' && table <= 'j') table = String(table.charCodeAt(0) - 97);
    if (table === '/' || table === '\\') return APRS_TABLES.symbols[symbol] || null;
    const special = OVERLAYS[code] && OVERLAYS[code][table];
    if (special) return special.charAt(0).toUpperCase() + special.slice(1);
    const base = APRS_TABLES.symbols[`\\${code}`];
    return base ? `${base}, marked ${table}` : null;
  }

  /** The software or radio a destination names, such as APMI06. */
  function deviceName(destination) {
    if (typeof destination !== 'string' || !destination) return null;
    const dest = destination.toUpperCase();
    for (const [pattern, name] of APRS_TABLES.tocalls) {
      if (pattern.length > dest.length && !pattern.includes('*')) continue;
      let ok = true;
      for (let i = 0; i < pattern.length && ok; i += 1) {
        const p = pattern[i];
        if (p === '*') return name;
        const d = dest[i];
        if (d === undefined) ok = false;
        else if (p === '?') ok = true;
        else if (p === 'n') ok = d >= '0' && d <= '9';
        else ok = p === d;
      }
      if (ok && pattern.length === dest.length) return name;
    }
    return null;
  }

  const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  const compass = (deg) => COMPASS[Math.round((((Number(deg) % 360) + 360) % 360) / 22.5) % 16];
  const speed = (knots) => SonoranUnits.speedFromKn(knots);
  // Rain and snow arrive in inches from APRS and in millimetres from
  // rtl_433. Both go through the formatter, so one tooltip has one unit.
  const inches = (value) => SonoranUnits.lengthFromMm(Number(value) * 25.4);

  /* The readings a weather station or sensor sends, with their units.
     The keys are the agent's, shared by APRS weather and rtl_433 where
     they overlap. Returns the lines and the keys it used. */
  const WEATHER_KEYS = ['wind_dir_deg', 'wind_kn', 'gust_kn', 'wind_avg_kmh', 'wind_max_kmh',
    'temperature_f', 'temperature_c', 'humidity', 'pressure_hpa', 'rain_1h_in', 'rain_24h_in',
    'rain_today_in', 'rain_mm', 'snow_24h_in', 'luminosity_wm2', 'battery_ok', 'wx_type'];

  function weatherLines(meta) {
    const lines = [];
    const has = (key) => meta[key] != null && meta[key] !== '';
    if (has('wind_kn') || has('wind_dir_deg') || has('gust_kn')) {
      let text = 'Wind';
      if (has('wind_dir_deg')) text += ` from ${compass(meta.wind_dir_deg)} (${Math.round(meta.wind_dir_deg)}°)`;
      if (has('wind_kn')) text += ` at ${speed(meta.wind_kn)}`;
      if (has('gust_kn')) text += `, gusts ${speed(meta.gust_kn)}`;
      lines.push(text);
    }
    if (has('wind_avg_kmh') || has('wind_max_kmh')) {
      const parts = [];
      if (has('wind_avg_kmh')) parts.push(SonoranUnits.speedFromKmh(meta.wind_avg_kmh));
      if (has('wind_max_kmh')) parts.push(`gusts ${SonoranUnits.speedFromKmh(meta.wind_max_kmh)}`);
      lines.push(`Wind ${parts.join(', ')}`);
    }
    // Only the unit the reader chose. A station that sends Fahrenheit is
    // read in whole degrees, because that is all it sent.
    if (has('temperature_f')) {
      lines.push(`Temperature ${SonoranUnits.temperatureFromC((Number(meta.temperature_f) - 32) * 5 / 9, { digits: 0 })}`);
    } else if (has('temperature_c')) {
      lines.push(`Temperature ${SonoranUnits.temperatureFromC(meta.temperature_c)}`);
    }
    if (has('humidity')) lines.push(`Humidity ${Math.round(meta.humidity)} %`);
    if (has('pressure_hpa')) lines.push(`Pressure ${SonoranUnits.pressureFromHpa(meta.pressure_hpa)}`);
    const rain = [];
    if (has('rain_1h_in')) rain.push(`${inches(meta.rain_1h_in)} in the last hour`);
    if (has('rain_24h_in')) rain.push(`${inches(meta.rain_24h_in)} in 24 hours`);
    if (has('rain_today_in')) rain.push(`${inches(meta.rain_today_in)} since midnight`);
    if (has('rain_mm')) rain.push(`${SonoranUnits.lengthFromMm(meta.rain_mm)} total`);
    if (rain.length) lines.push(`Rain ${rain.join(', ')}`);
    if (has('snow_24h_in')) lines.push(`Snow ${inches(meta.snow_24h_in)} in 24 hours`);
    if (has('luminosity_wm2')) lines.push(`Sunlight ${Math.round(meta.luminosity_wm2)} W/m²`);
    if (has('battery_ok')) lines.push(meta.battery_ok === false || meta.battery_ok === 0 ? 'Battery low' : 'Battery OK');
    if (has('wx_type')) lines.push(`Weather station type ${meta.wx_type}`);
    return lines;
  }

  /* How an APRS packet reached the receiver, in words (design 5.1). The
     ingest writes `direct`, `via` and `precision_m` into `meta` from the
     contract fields, so they are facts about the hearing, not something
     the sender said. */
  function hearingLines(meta) {
    const lines = [];
    if (meta.object) {
      lines.push(`${meta.object === 'item' ? 'An item' : 'An object'} placed by ${meta.owner ? call(meta.owner) : 'another station'}, not a transmitter`);
    }
    /* Every hop that repeated the packet, in order: the `*` ones that
       name a station. An alias such as WIDE2* names nobody. */
    const hops = String(meta.path || '').split(',').map((hop) => hop.trim())
      .filter((hop) => hop.endsWith('*')).map((hop) => hop.slice(0, -1))
      .filter((hop) => hop && !/^(WIDE|TRACE|RELAY|ECHO|GATE|TCPIP|TCPXX|NOGATE|RFONLY|Q[A-Z]{2})/i.test(hop));
    if (meta.third_party) {
      lines.push(`From the internet, put on the air by ${meta.via ? call(meta.via) : 'a gateway'}`);
    } else if (meta.direct === true && !meta.object) {
      lines.push('Heard directly, with no digipeater');
    } else if (hops.length) {
      lines.push(`Repeated by ${hops.map(call).join(', then ')}`);
    } else if (meta.direct === false) {
      lines.push(meta.via ? `Heard through ${call(meta.via)}` : 'Repeated by a digipeater that did not sign the path');
    }
    if (meta.precision_m) {
      const metres = Number(meta.precision_m);
      lines.push(`The sender blurred its own position to about ${SonoranUnits.distanceFromM(metres)}`);
    }
    return lines;
  }

  /* Keys the APRS tooltip turns into words. Anything else the agent
     sends is listed plainly, so a new field is never hidden. */
  const APRS_KEYS = ['direct', 'via', 'precision_m', 'owner', 'object', 'third_party', 'path',
    'symbol', 'destination', 'device', 'message', 'comment', ...WEATHER_KEYS];

  function aprsTooltip(row) {
    const meta = row.meta || {};
    const isObject = row.id.startsWith(';');
    const muted = (text) => el('div', { class: 'muted', text });
    const kind = symbolName(meta.symbol);
    const device = meta.device || deviceName(meta.destination);
    const motion = [];
    if (row.gs_kn != null && Number(row.gs_kn) > 0) {
      motion.push(`Moving ${speed(row.gs_kn)}`
        + (row.track_deg != null ? `, heading ${compass(row.track_deg)} (${Math.round(row.track_deg)}°)` : ''));
    } else if (row.track_deg != null) {
      motion.push(`Heading ${compass(row.track_deg)} (${Math.round(row.track_deg)}°)`);
    }
    if (row.alt_m != null) {
      motion.push(`Altitude ${SonoranUnits.heightFromM(row.alt_m)}`);
    }
    const others = Object.entries(meta)
      .filter(([key, value]) => !APRS_KEYS.includes(key) && value != null && value !== '')
      .slice(0, 6)
      .map(([key, value]) => el('div', { text: `${key.replaceAll('_', ' ')}: ${String(value).slice(0, 40)}` }));
    return el('div', { class: 'rf-tip' },
      el('strong', { text: isObject ? row.id.slice(1).toUpperCase() : call(row.id) }),
      el('div', { text: kind ? `${kind} · APRS` : 'APRS station' }),
      meta.message ? el('div', { text: `Status: ${meta.message}` }) : null,
      motion.map((text) => el('div', { text })),
      weatherLines(meta).map((text) => el('div', { text })),
      /* The comment is what a person typed. It is shown whole and
         wrapped, never cut to fit the tooltip. */
      meta.comment ? el('div', { class: 'rf-comment', text: String(meta.comment) }) : null,
      others,
      device ? muted(`Sent with ${device}`) : null,
      hearingLines(meta).map(muted),
      muted(`heard ${ago(row.t)} by ${row.station}`));
  }

  /* Any other kind: what it is, its id, and the plain fields it sent. */
  function otherTooltip(row) {
    if (row.kind === 'aprs') return aprsTooltip(row);
    const style = KIND_STYLE[row.kind] || { label: row.kind };
    const { comment, ...meta } = row.meta || {};
    const readings = weatherLines(meta);
    const extras = Object.entries(meta)
      .filter(([key]) => !WEATHER_KEYS.includes(key))
      .slice(0, 4)
      .map(([key, value]) => el('div', { text: `${key.replaceAll('_', ' ')}: ${String(value).slice(0, 40)}` }));
    return el('div', { class: 'rf-tip' },
      el('strong', { text: row.id }),
      el('div', { text: style.label }),
      row.alt_m == null ? null : el('div', { text: SonoranUnits.heightFromM(row.alt_m) }),
      readings.map((text) => el('div', { text })),
      extras,
      comment == null || comment === '' ? null : el('div', { class: 'rf-comment', text: String(comment) }),
      style.heardHere
        ? el('div', { class: 'muted', text: 'It sends no position. The mark is the receiver that heard it.' })
        : null,
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
      row.precision_m
        ? el('div', {
          class: 'muted',
          text: `position rounded to ${SonoranUnits.distanceFromM(row.precision_m)}`,
        })
        : null,
      row.spectrum_last ? el('div', { text: `sweeps the 900 MHz band, newest minute ${ago(row.spectrum_last)}` }) : null,
      el('div', { class: 'muted', text: 'Click to show where it hears aircraft.' }));
  }

  function isAircraft(kind) {
    return kind === 'adsb' || kind === 'uat';
  }

  /* --- Icons ---------------------------------------------------------

     An aircraft is drawn as what it is, from the ADS-B emitter category
     it broadcasts, pointing the way it is going and coloured by
     altitude. Shape carries the kind and colour the height, so each
     still reads without the other. The silhouettes are drawn here, in a
     24 unit box pointing north. */
  const AIRCRAFT_SHAPES = {
    plane: 'M12 2c.9 0 1.4 1 1.4 2.4V9l7.6 4.6v2l-7.6-2.3V18l2.4 1.8v1.6L12 20.4l-3.8 1V19.8L10.6 18v-4.7L3 15.6v-2L10.6 9V4.4C10.6 3 11.1 2 12 2z',
    jet: 'M12 1.5c.7 0 1.2 1.3 1.2 3v4.6L21 19v1.6l-7.8-4.1v3.6l2.1 1.6v1.2L12 22l-3.3 1V21.7l2.1-1.6v-3.6L3 20.6V19l7.8-9.9V4.5c0-1.7.5-3 1.2-3z',
    rotor: 'M12 6.2a3.3 3.3 0 0 1 3.3 3.3v2.8a3.3 3.3 0 0 1-2.4 3.2V21h2.2v1.4H8.9V21h2.2v-5.5a3.3 3.3 0 0 1-2.4-3.2V9.5A3.3 3.3 0 0 1 12 6.2zM2.5 8.2l.8-1.2L21.5 17l-.8 1.2zM3.3 18.2l-.8-1.2L20.7 7l.8 1.2z',
    glider: 'M12 3c.6 0 1 .9 1 2v5.4l10 1.2v1.6l-10-.4V19l2.4 1.4V22H8.6v-1.6L11 19v-6.2l-10 .4v-1.6l10-1.2V5c0-1.1.4-2 1-2z',
    balloon: 'M12 1.5a7 7 0 0 1 7 7c0 4.2-4 7.8-5.6 9.6h-2.8C9 16.3 5 12.7 5 8.5a7 7 0 0 1 7-7zM10.2 19.2h3.6V22h-3.6z',
    drone: 'M9.5 9.5h5v5h-5zM4 4l6 6M20 4l-6 6M4 20l6-6M20 20l-6-6M1.5 4a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M17.5 4a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M1.5 20a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M17.5 20a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0',
    vehicle: 'M7 4h10a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z',
  };

  /* Emitter category (DO-260B) to a shape and a size in pixels. The
     size grows with the class of aircraft, so a heavy reads as heavy. */
  const CATEGORY_ICON = {
    A1: ['plane', 18], A2: ['plane', 20], A3: ['plane', 22], A4: ['plane', 24],
    A5: ['plane', 26], A6: ['jet', 22], A7: ['rotor', 22],
    B1: ['glider', 22], B2: ['balloon', 20], B3: ['plane', 16], B4: ['plane', 16],
    B6: ['drone', 18], B7: ['jet', 22],
    C1: ['vehicle', 14], C2: ['vehicle', 14],
  };

  /** What an aircraft's category says it is, in words, for the tooltip. */
  const CATEGORY_NAME = {
    A1: 'Light aircraft', A2: 'Small aircraft', A3: 'Large aircraft', A4: 'Large aircraft (B757)',
    A5: 'Heavy aircraft', A6: 'High-performance aircraft', A7: 'Helicopter',
    B1: 'Glider', B2: 'Balloon or airship', B3: 'Parachutist', B4: 'Ultralight',
    B6: 'Drone', B7: 'Space vehicle', C1: 'Emergency vehicle', C2: 'Service vehicle',
  };

  /* A Leaflet icon that shows an element this file built node by node.
     Leaflet's div icon would take the same element through its `html` option;
     this keeps rf.js free of any markup path at all (see
     test_text_off_the_air_is_never_built_into_html). */
  const ElementIcon = L.Icon.extend({
    createIcon() {
      const node = this.options.element;
      /* `_setIconStyles` REPLACES className with Leaflet's own. The
         element's classes are what size and place an APRS symbol's two
         sprite layers, so without them the icon is an empty box and
         draws nothing. Put them back. */
      const own = node.className.split(/\s+/).filter(Boolean);
      this._setIconStyles(node, 'icon');
      node.classList.add(...own);
      return node;
    },
    createShadow() { return null; },
  });

  const SVG = 'http://www.w3.org/2000/svg';

  function aircraftIcon(row, colour) {
    const category = String((row.meta || {}).category || '').toUpperCase();
    const [shape, size] = CATEGORY_ICON[category] || ['plane', 20];
    /* A balloon, a drone and a vehicle have no nose to point with. */
    const turns = !['balloon', 'drone', 'vehicle'].includes(shape) && row.track_deg != null;
    const angle = turns ? Math.round(Number(row.track_deg)) : 0;
    const stroked = shape === 'drone';
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('aria-hidden', 'true');
    svg.style.transform = `rotate(${angle}deg)`;
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', AIRCRAFT_SHAPES[shape]);
    path.setAttribute('fill', stroked ? 'none' : colour);
    path.setAttribute('stroke', stroked ? colour : 'rgba(0,0,0,.75)');
    path.setAttribute('stroke-width', stroked ? 2 : 0.8);
    svg.append(path);
    const node = document.createElement('div');
    node.className = 'rf-plane';
    node.append(svg);
    return new ElementIcon({ element: node, className: 'rf-icon', iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
  }

  /* An APRS station is drawn as the symbol it chose, from the aprs.fi
     symbol set (vendor/aprs/PROVENANCE.md). A sheet is 16 symbols wide
     and six high, from `!` onwards. An overlay letter or digit is the
     alternate table's symbol with the character printed on top. */
  const APRS_SHEETS = ['static/vendor/aprs/aprs-symbols-24-0@2x.png',
    'static/vendor/aprs/aprs-symbols-24-1@2x.png', 'static/vendor/aprs/aprs-symbols-24-2@2x.png'];

  function spriteCell(sheet, char) {
    const index = char.charCodeAt(0) - 33;
    if (!(index >= 0 && index < 96)) return null;
    const span = document.createElement('span');
    span.style.backgroundImage = `url("${APRS_SHEETS[sheet]}")`;
    span.style.backgroundPosition = `-${(index % 16) * 24}px -${Math.floor(index / 16) * 24}px`;
    return span;
  }

  function aprsIcon(row) {
    const meta = row.meta || {};
    const symbol = meta.symbol;
    if (typeof symbol !== 'string' || symbol.length !== 2) return null;
    let [table, code] = symbol;
    if (table >= 'a' && table <= 'j') table = String(table.charCodeAt(0) - 97);
    const overlay = table !== '/' && table !== '\\' && /^[0-9A-Z]$/.test(table);
    if (table !== '/' && table !== '\\' && !overlay) return null;
    const base = spriteCell(table === '/' ? 0 : 1, code);
    if (!base) return null;
    const node = document.createElement('div');
    /* Relayed stations are drawn fainter: the map puts them where they
       say they are, but this receiver did not hear them there. */
    node.className = meta.direct === false ? 'rf-aprs relayed' : 'rf-aprs';
    node.append(base);
    const letter = overlay ? spriteCell(2, table) : null;
    if (letter) node.append(letter);
    return new ElementIcon({ element: node, className: 'rf-icon', iconSize: [24, 24], iconAnchor: [12, 12] });
  }

  function drawThings(rows) {
    state.aircraft.clearLayers();
    for (const row of rows) {
      const source = sourceOf(row.kind);
      if (!source || !state.shown[source.key]) continue;
      const aircraft = isAircraft(row.kind);
      const style = aircraft ? null : KIND_STYLE[row.kind] || { colour: '#b59c88', radius: 4 };
      const colour = aircraft ? altitudeColour(row.alt_m) : style.colour;
      const icon = aircraft ? aircraftIcon(row, colour) : row.kind === 'aprs' ? aprsIcon(row) : null;
      /* Anything without an icon keeps the hollow ring, so it still
         reads apart from an aircraft without colour. */
      const marker = (icon
        ? L.marker([row.lat, row.lon], { icon, keyboard: false })
        : L.circleMarker([row.lat, row.lon], {
          radius: style.radius, color: colour, fillColor: colour, fillOpacity: 0.15, weight: 2,
        })
      /* Built on hover, not on draw. Leaflet calls this when the
         tooltip opens, so a busy sky no longer builds six elements
         per aircraft on every poll for tooltips nobody hovered. */
      ).bindTooltip(() => (aircraft ? aircraftTooltip(row) : otherTooltip(row)), { direction: 'top' });
      marker.on('click', () => selectThing(row));
      state.aircraft.addLayer(marker);
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
        ? `${station} heard aircraft in ${body.cells.length} places of about ${SonoranUnits.distanceFromKm(2)} in the last 24 h. Brighter is louder, relative to this station only.`
        : `${station} has heard no aircraft in the last 24 h.`;
    }
  }

  function drawLegend(page) {
    const target = $('[data-rf-legend]', page);
    if (!target) return;
    target.replaceChildren();
    if (state.shown.aircraft) {
      target.append(...ALTITUDE_BANDS.map((band, index) =>
        el('span', { class: 'legend-note' },
          el('span', { class: 'swatch', style: `background:${band.colour}` }), `aircraft ${bandLabel(index)}`)));
    }
    for (const [kind, style] of Object.entries(KIND_STYLE)) {
      const source = sourceOf(kind);
      if (!source || !state.shown[source.key]) continue;
      target.append(el('span', { class: 'legend-note' },
        el('span', { class: 'swatch ring', style: `border-color:${style.colour}` }),
        style.heardHere ? `${style.label} (drawn where heard)` : style.label));
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

  /* A distance in words, in the reader's units: "1 mi", "500 ft". */
  const metres = (value) => SonoranUnits.distanceFromM(value);

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

  /* --- The table ----------------------------------------------------

     Everything on the map, as rows: the decoded fields in words, and
     beside them the raw frame the decoder gave the agent (`meta.raw`,
     contract field `raw`). The rows are the ones the map drew, so the
     table never disagrees with it. Text only, like the tooltips. */
  const RAW_NOTE = 'Not sent: this source gives the agent decoded data only';
  // A whole number in the reader's height unit, for a sortable column.
  const altitude = (metres) => (metres == null
    ? null
    : Math.round(Number(metres) * (SonoranUnits.imperial() ? SonoranUnits.FEET_PER_METRE : 1)));
  const altitudeColumn = {
    get label() { return `Altitude ${SonoranUnits.heightUnit()}`; },
    num: true,
    value: (row) => altitude(row.alt_m),
  };
  const heardAt = (row) => Date.parse(row.t) || 0;
  const aprsMotion = (row) => {
    if (row.gs_kn != null && Number(row.gs_kn) > 0) {
      return `${speed(row.gs_kn)}${row.track_deg != null ? ` ${compass(row.track_deg)}` : ''}`;
    }
    return '';
  };

  const TABLES = [
    {
      key: 'aircraft', label: 'Aircraft', kinds: ['adsb', 'uat'],
      columns: [
        { label: 'ICAO', value: (row) => row.id.toUpperCase() },
        { label: 'Callsign', value: (row) => (row.meta || {}).callsign || (row.meta || {}).flight || '' },
        { label: 'Type', value: (row) => CATEGORY_NAME[String((row.meta || {}).category || '').toUpperCase()] || '' },
        altitudeColumn,
        { label: 'Speed kn', num: true, value: (row) => (row.gs_kn == null ? null : Math.round(row.gs_kn)) },
        { label: 'Heading', num: true, value: (row) => (row.track_deg == null ? null : Math.round(row.track_deg)) },
        { label: 'Squawk', value: (row) => (row.meta || {}).squawk || '' },
        { label: 'Signal dB', num: true, value: (row) => (row.rssi_db == null ? null : round1(row.rssi_db)) },
      ],
    },
    {
      key: 'aprs', label: 'APRS', kinds: ['aprs'],
      columns: [
        { label: 'Callsign', value: (row) => (row.id.startsWith(';') ? row.id.slice(1) : row.id).toUpperCase() },
        { label: 'Symbol', value: (row) => symbolName((row.meta || {}).symbol) || (row.meta || {}).symbol || '' },
        { label: 'Status', value: (row) => (row.meta || {}).message || '' },
        { label: 'Moving', value: aprsMotion },
        altitudeColumn,
        { label: 'Weather', wrap: true, value: (row) => weatherLines(row.meta || {}).join(' · ') },
        { label: 'Comment', wrap: true, value: (row) => (row.meta || {}).comment || '' },
        { label: 'How heard', wrap: true, value: (row) => hearingLines(row.meta || {}).join(' · ') },
        { label: 'Sent with', value: (row) => (row.meta || {}).device || deviceName((row.meta || {}).destination) || '' },
      ],
    },
    {
      key: 'sonde', label: 'Radiosondes', kinds: ['sonde'],
      columns: [
        { label: 'Serial', value: (row) => row.id.toUpperCase() },
        altitudeColumn,
        { label: 'Speed kn', num: true, value: (row) => (row.gs_kn == null ? null : Math.round(row.gs_kn)) },
        { label: 'Heading', num: true, value: (row) => (row.track_deg == null ? null : Math.round(row.track_deg)) },
      ],
    },
    {
      key: 'ism', label: 'Weather sensors', kinds: ['ism'],
      columns: [
        { label: 'Sensor', value: (row) => row.id },
        { label: 'Readings', wrap: true, value: (row) => weatherLines(row.meta || {}).join(' · ') },
      ],
    },
  ];
  /* Every table ends with where and when, and the raw frame. */
  const TAIL_COLUMNS = [
    { label: 'Latitude', num: true, value: (row) => Number(row.lat).toFixed(4) },
    { label: 'Longitude', num: true, value: (row) => Number(row.lon).toFixed(4) },
    { label: 'Heard', value: heardAt, text: (row) => ago(row.t) },
    { label: 'Station', value: (row) => row.station || '' },
    { label: 'Raw', raw: true, wrap: true, value: (row) => (row.meta || {}).raw || '' },
  ];
  /* A busy sky is thousands of rows. The filter narrows it; the table
     draws this many and says so. */
  const TABLE_MAX_ROWS = 500;

  const tableState = { open: false, which: 'aircraft', sort: {}, filter: '' };

  function tableRows(table) {
    const kinds = new Set(table.kinds);
    return (state.lastRows || []).filter((row) => kinds.has(row.kind));
  }

  function cellText(column, row) {
    if (column.text) return column.text(row);
    const value = column.value(row);
    return value == null ? '' : String(value);
  }

  function drawTable(page) {
    const panel = $('[data-rf-table]', page);
    if (!panel) return;
    panel.hidden = !tableState.open;
    if (!tableState.open) return;
    const available = TABLES.filter((table) => tableRows(table).length);
    if (!available.some((table) => table.key === tableState.which) && available.length) {
      tableState.which = available[0].key;
    }
    const tabs = $('[data-rf-table-tabs]', page);
    tabs.replaceChildren(...TABLES.map((table) => {
      const count = tableRows(table).length;
      const button = el('button', {
        type: 'button', class: 'toggle', 'aria-pressed': String(table.key === tableState.which),
        text: `${table.label} (${count.toLocaleString()})`,
      });
      button.disabled = !count;
      button.addEventListener('click', () => { tableState.which = table.key; drawTable(page); });
      return button;
    }));
    const table = TABLES.find((item) => item.key === tableState.which) || TABLES[0];
    const columns = table.columns.concat(TAIL_COLUMNS);
    const sort = tableState.sort[table.key] || { index: columns.findIndex((c) => c.label === 'Heard'), order: 'desc' };
    const needle = tableState.filter.trim().toLowerCase();
    let rows = tableRows(table);
    if (needle) {
      rows = rows.filter((row) => columns.some((column) => cellText(column, row).toLowerCase().includes(needle)));
    }
    const key = columns[sort.index];
    rows = rows.slice().sort((a, b) => {
      const x = key.value(a);
      const y = key.value(b);
      if (x == null || x === '') return 1;
      if (y == null || y === '') return -1;
      const order = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
      return sort.order === 'asc' ? order : -order;
    });
    const shown = rows.slice(0, TABLE_MAX_ROWS);
    const head = el('tr', {}, columns.map((column, index) => {
      const active = index === sort.index;
      const button = el('button', { type: 'button', class: 'sort-button' },
        el('span', { text: column.label }),
        el('span', { class: 'sort-arrow', 'aria-hidden': 'true',
          text: active ? (sort.order === 'asc' ? '↑' : '↓') : '↕' }));
      button.addEventListener('click', () => {
        tableState.sort[table.key] = { index, order: active && sort.order === 'asc' ? 'desc' : 'asc' };
        drawTable(page);
      });
      return el('th', {
        scope: 'col',
        class: ['sortable', active ? 'sorted' : '', column.num ? 'num' : ''].join(' ').trim(),
        'aria-sort': active ? (sort.order === 'asc' ? 'ascending' : 'descending') : 'none',
      }, button);
    }));
    const body = shown.map((row) => el('tr', {}, columns.map((column) => {
      const text = cellText(column, row);
      const classes = [column.num ? 'num' : '', column.wrap ? 'wrap' : ''].join(' ').trim() || null;
      if (column.raw) {
        return el('td', { class: classes },
          text ? el('code', { class: 'rf-raw', text }) : el('span', { class: 'muted', title: RAW_NOTE, text: 'not sent' }));
      }
      return el('td', { class: classes, text });
    })));
    $('[data-rf-table-grid]', page).replaceChildren(
      el('table', { class: 'rf-table' }, el('thead', {}, head), el('tbody', {}, body)));
    const total = tableRows(table).length;
    $('[data-rf-table-note]', page).textContent = !total
      ? 'Nothing of this kind is on the map right now.'
      : `${shown.length.toLocaleString()} of ${rows.length.toLocaleString()} rows`
        + (needle ? ` matching "${tableState.filter.trim()}"` : '')
        + (rows.length > shown.length ? '; narrow the filter to see the rest.' : '.')
        + ' The same things the map shows, over the same window.';
  }

  function bindTable(page) {
    const button = $('[data-rf-table-toggle]', page);
    if (!button || button.dataset.bound) return;
    button.dataset.bound = '1';
    button.addEventListener('click', () => {
      tableState.open = !tableState.open;
      button.setAttribute('aria-pressed', String(tableState.open));
      drawTable(page);
    });
    $('[data-rf-table-filter]', page).addEventListener('input', (event) => {
      tableState.filter = event.target.value;
      drawTable(page);
    });
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
    state.lastRows = latest.body;
    bindTable(page);
    drawTable(page);
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
