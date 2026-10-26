/*
 * The rules of the coverage settings panel (#334).
 *
 * This file holds no page code. It holds the defaults, the count of
 * changed settings, the address, the storage and the node filter, so
 * that `tests/unit/js/coverage_settings_cases.mjs` can run each rule
 * under node. `coverage.js` draws the panel and calls these.
 *
 * Two kinds of setting live here, and they are kept in two places.
 *
 * 1. The map choices: which nodes the map is predicted from, whether
 *    rounded positions are included, the layer, and the signal floor.
 *    They change what the map IS. They go in the address
 *    (`#coverage?set=…&approx=1&layer=…&floor=…`), so a link shows the
 *    same map to the next reader. They
 *    are not stored. A plain `#coverage` link must always be the map
 *    Logan and Tyler asked for. If a stored choice could turn it into
 *    the approximate map, one link would show two different maps to
 *    two people, and the approximate one could be read as the precise.
 * 2. The display filters: node markers by role, last heard, moving
 *    nodes, uncertainty circles and signal opacity. They change only
 *    what this browser draws over the map. They are stored for this
 *    viewer and never reach the address or the server.
 */

'use strict';

window.SonoranCoverageSettings = (function build() {
  const STORE_KEY = 'sonoran.coverage.settings';
  // The key the opacity slider used before this panel existed. It is
  // read, so a viewer keeps the level they chose, and it is cleared on
  // every save, so a reset cannot bring the old level back.
  const OLD_OPACITY_KEY = 'sonoran.coverage.signalOpacity';

  const DEFAULT_BASE = 'infrastructure';
  const APPROXIMATE_SUFFIX = '_approximate';
  const LAYERS = ['uplink', 'empirical_heatmap_position'];

  /*
   * The signal floors the panel offers, in dB above what the radio
   * needs (#334). Zero is the whole usable map, which is the map the
   * page has always drawn.
   */
  const FLOORS = [0, 5, 10, 20];
  // The margin tile encoding this page can read. See coverage/render.py.
  const MARGIN_ENCODING = 'margin_db_plus_one';

  // Last heard: the key, and the window in hours. `any` sets no window.
  const HEARD = { any: null, '24h': 24, '7d': 168 };

  /*
   * The roles that stand for "a node that moves".
   *
   * The page has no measure of movement. It has the role, and
   * `sonoran/roles.py` leaves these two out of every map for the same
   * reason: config.proto describes both as worn or carried. A node of
   * another role can move too, and this filter cannot see it.
   */
  const MOVING_ROLES = ['TRACKER', 'TAK_TRACKER'];

  // A role key as the API writes one, or `NULL` for no role reported.
  const ROLE_KEY = /^[A-Z0-9_]{1,40}$/;
  // A site set name as the tile route accepts one.
  const SET_KEY = /^[a-z_]{1,32}$/;

  function defaults() {
    return {
      base: DEFAULT_BASE,
      approximate: false,
      layer: 'uplink',
      floor: 0,
      showMap: true,
      showNodes: true,
      showSignal: true,
      hiddenRoles: [],
      heard: 'any',
      hideMoving: false,
      circles: false,
      opacity: 1,
    };
  }

  /** Every setting back to its default. The same as `defaults`, named
      for the button. */
  function reset() {
    return defaults();
  }

  /*
   * How many settings differ from their default.
   *
   * Settings, not controls. Three hidden roles are one filter in force,
   * and a badge that said 3 would make one choice look like three.
   *
   * `defaultBase` is the run's own first map. A diagnostic run has no
   * `infrastructure` map, and landing on its first map is not a change
   * the reader made.
   */
  function changedCount(settings, { defaultBase = DEFAULT_BASE } = {}) {
    const d = defaults();
    let count = 0;
    if (settings.base !== defaultBase) count += 1;
    for (const key of ['approximate', 'layer', 'floor', 'showMap', 'showNodes', 'showSignal',
      'heard', 'hideMoving', 'circles', 'opacity']) {
      if (settings[key] !== d[key]) count += 1;
    }
    if ((settings.hiddenRoles || []).length) count += 1;
    return count;
  }

  /* ----------------------------------------------------- site sets */

  function isApproximate(set) {
    if (!set) return false;
    if (typeof set.approximate === 'boolean') return set.approximate;
    // A run made before #315 has no flag. The name still says it.
    return String(set.key || '').endsWith(APPROXIMATE_SUFFIX);
  }

  /** The maps a reader can choose as a source: the precise ones. */
  function baseSets(sets) {
    return (Array.isArray(sets) ? sets : []).filter((set) => set && !isApproximate(set));
  }

  /*
   * The site set to draw, from the reader's two choices.
   *
   * The approximate toggle names the approximate map of the chosen
   * source. When the run did not compute that map, the answer is the
   * precise map and `approximateAvailable` is false, so the page can
   * say so. It never draws one map under the other's name.
   */
  function resolveSiteSet(sets, base, approximate) {
    const bases = baseSets(sets);
    if (!bases.length) {
      return { key: DEFAULT_BASE, base: DEFAULT_BASE, approximate: false, approximateAvailable: false };
    }
    const chosen = bases.find((set) => set.key === base) || bases[0];
    const wanted = `${chosen.key}${APPROXIMATE_SUFFIX}`;
    const available = sets.some((set) => set && set.key === wanted && isApproximate(set));
    const on = Boolean(approximate) && available;
    return {
      key: on ? wanted : chosen.key,
      base: chosen.key,
      approximate: on,
      approximateAvailable: available,
    };
  }

  /* ------------------------------------------------------- address */

  function query(hash) {
    return new URLSearchParams(String(hash || '').split('?')[1] || '');
  }

  /** True when the address names a map at all. */
  function hashNamesMap(hash) {
    return String(hash || '').includes('?');
  }

  /*
   * The map choices in an address. Anything missing or unknown is the
   * default, so `#coverage` is always the precise infrastructure map.
   */
  function fromHash(hash) {
    const q = query(hash);
    const set = q.get('set') || '';
    const layer = q.get('layer') || '';
    return {
      base: SET_KEY.test(set) && !set.endsWith(APPROXIMATE_SUFFIX) ? set : DEFAULT_BASE,
      approximate: q.get('approx') === '1',
      layer: LAYERS.includes(layer) ? layer : 'uplink',
      floor: floorOf(q.get('floor')),
    };
  }

  /** The address of the map choices. Only what differs is written. */
  function toHash(settings) {
    const q = new URLSearchParams();
    if (settings.base && settings.base !== DEFAULT_BASE) q.set('set', settings.base);
    if (settings.approximate) q.set('approx', '1');
    if (settings.layer && settings.layer !== 'uplink') q.set('layer', settings.layer);
    if (floorOf(settings.floor)) q.set('floor', String(floorOf(settings.floor)));
    const text = q.toString();
    return text ? `#coverage?${text}` : '#coverage';
  }

  /* -------------------------------------------------- signal floor */

  /** A floor the panel offers, or 0. A number typed into a link that
      the panel does not offer is not a floor anybody chose. */
  function floorOf(value) {
    const number = Number(value);
    return FLOORS.includes(number) ? number : 0;
  }

  /*
   * What this run says about its margin tiles, or null.
   *
   * A run made before the margin tiles existed has no `margin_tiles`,
   * and a run with an encoding this page does not know is read the same
   * way. Either one cannot draw a floor, and the page says so rather
   * than guessing at its bytes.
   */
  function marginSpec(summary) {
    const spec = summary && summary.margin_tiles;
    if (!spec || spec.encoding !== MARGIN_ENCODING) return null;
    const ramp = Array.isArray(spec.ramp) ? spec.ramp : [];
    const colours = ramp.length >= 2 && ramp.every((stop) => Array.isArray(stop)
      && stop.length === 3 && stop.every((value) => Number.isInteger(value) && value >= 0 && value <= 255));
    const alpha = Number(spec.alpha);
    const span = Number(summary.ramp_span_db);
    if (!colours || !Number.isInteger(alpha) || alpha < 1 || alpha > 255) return null;
    if (!Number.isFinite(span) || span <= 0) return null;
    return { ramp, alpha, span };
  }

  /*
   * Colour one margin tile above a floor.
   *
   * `pixels` is the RGBA of the grey tile as the canvas decoded it: the
   * byte is in each of red, green and blue. Byte 0 is no usable
   * coverage, and byte n is n - 1 dB above the sensitivity. A cell below
   * the floor is left clear, the same as a cell below the sensitivity.
   *
   * The colour is the ramp `coverage/render.py` draws. Each step uses
   * the precision that numpy uses for it, so at a floor of 0 dB a pixel
   * is the pixel of the colour tile. `coverage_floor_cases.mjs` pins it
   * against every margin as Python wrote it.
   */
  function colourMargins(pixels, floor, spec) {
    const out = new Uint8ClampedArray(pixels.length);
    const f = Math.fround;
    const last = spec.ramp.length - 1;
    const lowest = floorOf(floor);
    for (let i = 0; i < pixels.length; i += 4) {
      const byte = pixels[i];
      if (byte === 0) continue;
      const margin = byte - 1;
      if (margin < lowest) continue;
      const fraction = Math.min(Math.max(f(margin / spec.span), 0), 1);
      const position = f(fraction * last);
      const lower = Math.floor(position);
      const upper = Math.min(lower + 1, last);
      // numpy takes an int32 from a float32 here, which gives a
      // float64, so the mix is in double precision like plain JavaScript.
      const weight = position - lower;
      for (let c = 0; c < 3; c += 1) {
        const mixed = spec.ramp[lower][c] * (1 - weight) + spec.ramp[upper][c] * weight;
        out[i + c] = Math.trunc(mixed);
      }
      out[i + 3] = spec.alpha;
    }
    return out;
  }

  /** The words for a floor, or '' for none. */
  function floorWords(floor) {
    const value = floorOf(floor);
    return value ? `at least ${value} dB above what the radio needs` : '';
  }

  /* ------------------------------------------------------- storage */

  function opacityOf(value) {
    const number = Number(value);
    // Zero is not kept: a saved zero would reopen to a blank map that
    // looks broken. Hiding the signal is the Signal strength toggle.
    return Number.isFinite(number) && number > 0 && number <= 1 ? number : null;
  }

  function hiddenRolesOf(value) {
    if (!Array.isArray(value)) return [];
    return [...new Set(value.filter((role) => typeof role === 'string' && ROLE_KEY.test(role)))];
  }

  /*
   * The display filters this viewer saved, over the defaults.
   *
   * Each field is checked alone. A hand-edited or stale value lands on
   * its default and the other fields still apply. Every read is in a
   * try: in a private window, with site data blocked, or in a thumbnail
   * capture, the accessor itself throws.
   */
  function load(storage) {
    const out = defaults();
    if (!storage) return out;
    let saved = {};
    try {
      const parsed = JSON.parse(storage.getItem(STORE_KEY) || '{}');
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) saved = parsed;
    } catch {
      saved = {};
    }
    out.hiddenRoles = hiddenRolesOf(saved.hiddenRoles);
    if (Object.hasOwn(HEARD, saved.heard)) out.heard = saved.heard;
    if (typeof saved.hideMoving === 'boolean') out.hideMoving = saved.hideMoving;
    if (typeof saved.circles === 'boolean') out.circles = saved.circles;
    let opacity = opacityOf(saved.opacity);
    if (opacity == null && !Object.hasOwn(saved, 'opacity')) {
      try {
        const old = storage.getItem(OLD_OPACITY_KEY);
        opacity = old == null ? null : opacityOf(old);
      } catch {
        opacity = null;
      }
    }
    if (opacity != null) out.opacity = opacity;
    return out;
  }

  /** Keep the display filters. Returns false when storage refused. */
  function save(storage, settings) {
    if (!storage) return false;
    const kept = {
      hiddenRoles: hiddenRolesOf(settings.hiddenRoles),
      heard: Object.hasOwn(HEARD, settings.heard) ? settings.heard : 'any',
      hideMoving: Boolean(settings.hideMoving),
      circles: Boolean(settings.circles),
      opacity: opacityOf(settings.opacity) || 1,
    };
    try {
      storage.setItem(STORE_KEY, JSON.stringify(kept));
      storage.removeItem(OLD_OPACITY_KEY);
      return true;
    } catch {
      // The choice holds for this visit and is not remembered.
      return false;
    }
  }

  /* -------------------------------------------------- node filters */

  /** Whether a node marker is drawn under these filters. */
  function nodeShown(node, settings, now = Date.now()) {
    const role = (node && node.role) || 'NULL';
    if ((settings.hiddenRoles || []).includes(role)) return false;
    if (settings.hideMoving && MOVING_ROLES.includes(role)) return false;
    const hours = HEARD[settings.heard];
    if (hours) {
      // A node with no time heard was not heard inside the window.
      const heard = Date.parse((node && node.last_heard) || '');
      if (!Number.isFinite(heard)) return false;
      if (now - heard > hours * 3600 * 1000) return false;
    }
    return true;
  }

  /** The roles in a list of nodes, once each. No role reported last. */
  function rolesPresent(rows) {
    const roles = new Set((rows || []).map((row) => (row && row.role) || 'NULL'));
    const named = [...roles].filter((role) => role !== 'NULL').sort();
    return roles.has('NULL') ? [...named, 'NULL'] : named;
  }

  /*
   * One circle for each site the run predicted from a rounded position.
   *
   * The radius is `position_deviation_m` from the manifest. The centre
   * is the node's position from the map API, because the manifest does
   * not write positions. An operator position is exact, so it gets no
   * circle, and a site the run did not use draws nothing.
   */
  function uncertaintyCircles(sites, rows) {
    const where = new Map((rows || []).map((row) => [row.node_id, row]));
    const out = [];
    for (const site of sites || []) {
      if (!site || !site.used || site.position_source === 'operator') continue;
      const radius = Number(site.position_deviation_m);
      if (!Number.isFinite(radius) || radius <= 0) continue;
      const row = where.get(site.node_id);
      if (!row || row.lat == null || row.lon == null) continue;
      out.push({ node_id: site.node_id, lat: row.lat, lon: row.lon, radius });
    }
    return out;
  }

  /** The words that name the map on show, for the legend and stats. */
  function mapWords(label, approximate, floor = 0) {
    const words = `${label} · ${approximate ? 'rounded positions included' : 'precise positions only'}`;
    const value = floorOf(floor);
    return value ? `${words} · ${value} dB floor` : words;
  }

  return {
    LAYERS,
    FLOORS,
    HEARD,
    MOVING_ROLES,
    defaults,
    reset,
    changedCount,
    baseSets,
    resolveSiteSet,
    fromHash,
    toHash,
    hashNamesMap,
    load,
    save,
    nodeShown,
    rolesPresent,
    uncertaintyCircles,
    mapWords,
    floorOf,
    marginSpec,
    colourMargins,
    floorWords,
  };
}());
