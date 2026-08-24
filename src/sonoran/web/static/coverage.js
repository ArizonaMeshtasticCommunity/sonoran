/*
 * The coverage map page.
 *
 * This page draws what the coverage job already computed. It predicts
 * nothing itself. The tiles are plain images and the browser caches
 * them, so the map opens at once the second time somebody looks at it.
 *
 * The planner page is the other half of this pair. It answers "if a
 * radio stood here" for one hypothetical mast, in the browser. This
 * page answers "where does the mesh reach today" for every real node.
 * Both run the same engine. See docs/PLANNER.md 2.
 *
 * The file is separate from app.js for the same reason planner.js is:
 * its own Leaflet map and its own state, and app.js is large enough.
 */

'use strict';

(function () {
  const CONFIG = window.SONORAN || {};
  const API_BASE = CONFIG.apiBase || '';
  const api = (path) =>
    new URL(String(path).replace(/^\//, ''), API_BASE || document.baseURI).toString();

  /*
   * The layer a reader sees first.
   *
   * `usable` is the weaker of the two directions, so it answers "can I
   * use the mesh from here", which is the question somebody looking at
   * a coverage map is actually asking. A carrier map shows the downlink
   * because that is what sells telephones. Showing only the downlink
   * here would promise reach that a handheld cannot return.
   */
  const DEFAULT_LAYER = 'usable';

  // How see-through the signal layer is drawn, 0 to 1. This is the
  // viewer's own choice, not the deployment's: it restyles the tiles
  // already in their browser and touches nothing on the server and no
  // other viewer. Kept in localStorage so their choice survives a
  // reload; a viewer who has never touched it opens fully opaque. See
  // `recallOpacity`.
  const OPACITY_KEY = 'sonoran.coverage.signalOpacity';

  function recallOpacity() {
    try {
      const saved = Number(localStorage.getItem(OPACITY_KEY));
      // Honour a saved level only when it is a real fraction the map is
      // still visible at. Nothing saved, a zero, or junk all mean "open
      // fully opaque": a first visit should show all of the signal, and
      // a saved zero would reopen to a blank map that looks broken.
      // Hiding the signal outright is the "Signal strength" toggle's
      // job, not a persisted opacity of nothing.
      if (Number.isFinite(saved) && saved > 0 && saved <= 1) return saved;
    } catch {
      // Storage off or unreadable. The default stands.
    }
    return 1;
  }

  const state = {
    map: null,
    baseTiles: null,
    tiles: null,
    nodes: null,
    nodeRows: new Map(),
    nodeRequest: 0,
    summary: null,
    preset: null,
    siteSet: null,
    layer: DEFAULT_LAYER,
    showMap: true,
    showNodes: true,
    showSignal: true,
    // First visit opens fully opaque; after that, whatever the viewer
    // last set. See `recallOpacity`.
    signalOpacity: recallOpacity(),
    loaded: false,
  };

  window.SonoranCoverageState = state;

  /* ---------------------------------------------------------- helpers */

  const $ = (selector, root) => (root || document).querySelector(selector);

  function el(tag, attributes, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes || {})) {
      if (value == null) continue;
      if (key === 'text') node.textContent = value;
      else if (key === 'class') node.className = value;
      else if (key.startsWith('on') && typeof value === 'function') {
        node.addEventListener(key.slice(2), value);
      } else node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child == null) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function replace(target, ...children) {
    if (!target) return;
    target.replaceChildren(...children.flat().filter((child) => child != null));
  }

  function number(value, digits) {
    if (value == null || Number.isNaN(Number(value))) return '—';
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0,
    });
  }

  function when(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '—';
    const minutes = Math.round((Date.now() - date.getTime()) / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 48) return `${hours} h ago`;
    return `${Math.round(hours / 24)} d ago`;
  }

  /* A run publishes the infrastructure map, and the wider map that
     includes the nodes which repeat, when the deployment turns that on.
     `summary.presets` is always the infrastructure one, so a reader who
     never touches the picker gets the narrow answer. */
  function siteSets(summary) {
    const sets = (summary && summary.site_sets) || [];
    return Array.isArray(sets) ? sets : [];
  }

  function siteSetOf(summary, key) {
    const sets = siteSets(summary);
    if (!sets.length) return null;
    return sets.find((item) => item.key === key) || sets[0];
  }

  /* The presets of the site set on show. Falls back to the top level,
     which is the infrastructure map, for a run made before site sets
     existed. */
  function presetsOf(summary) {
    const set = siteSetOf(summary, state.siteSet);
    if (set && Array.isArray(set.presets)) return set.presets;
    return (summary && summary.presets) || [];
  }

  function presetOf(summary, name) {
    return presetsOf(summary).find((item) => item.preset === name) || null;
  }

  /* The preset to open on: the one this mesh actually runs.

     The manifest lists presets in name order, so taking the first gave
     "Long fast" on a mesh whose backbone is all on Medium fast, and the
     reader saw a nearly empty map of a preset nobody uses. A mesh
     agrees one preset and puts its infrastructure there, so the busiest
     one is the answer.

     Sites first, because that is what the map is drawn from. Candidates
     break a tie, so a preset with nodes and no usable sites still beats
     one with nothing at all, and the name breaks the last tie so the
     choice is stable between redraws. */
  function busiestPreset(summary) {
    const presets = presetsOf(summary).slice();
    if (!presets.length) return null;
    presets.sort((a, b) =>
      (b.site_count || 0) - (a.site_count || 0)
      || (b.candidate_count || 0) - (a.candidate_count || 0)
      || String(a.preset).localeCompare(String(b.preset)));
    return presets[0].preset;
  }

  /* The site set the tiles come from. The infrastructure map is the
     answer whenever nothing else has been chosen, so a run with one
     site set, or a reader who never touched the picker, gets it. */
  function currentSiteSet() {
    const set = siteSetOf(state.summary, state.siteSet);
    return (set && set.key) || 'infrastructure';
  }

  /* ------------------------------------------------------------- map */

  function ensureMap() {
    if (state.map) return state.map;
    const map = L.map('coverage-map', { preferCanvas: true }).setView(
      CONFIG.mapCenter || [34.0, -111.5],
      CONFIG.mapZoom || 7,
    );
    if (CONFIG.tileUrl) {
      state.baseTiles = L.tileLayer(CONFIG.tileUrl, {
        className: 'basemap-tiles',
        attribution: CONFIG.tileAttribution || '',
        maxZoom: 19,
      }).addTo(map);
    }
    state.nodes = L.layerGroup().addTo(map);
    state.map = map;
    return map;
  }

  function drawBaseMap() {
    const map = ensureMap();
    if (!state.baseTiles) return;
    if (state.showMap && !map.hasLayer(state.baseTiles)) state.baseTiles.addTo(map);
    if (!state.showMap && map.hasLayer(state.baseTiles)) map.removeLayer(state.baseTiles);
  }

  function drawTiles() {
    const map = ensureMap();
    if (state.tiles) {
      map.removeLayer(state.tiles);
      state.tiles = null;
    }
    if (!state.showSignal || !state.summary || !state.summary.available || !state.preset) return;

    const summary = state.summary;
    /*
     * `maxNativeZoom` is what makes this cheap. The job writes tiles up
     * to the zoom the 90 m terrain can support. Past that Leaflet
     * stretches the last real tile rather than asking for one that was
     * never written, so zooming in costs no requests at all.
     */
    /*
     * The placeholders must not go through `new URL`. It percent
     * encodes the braces, and Leaflet then asks for a tile literally
     * named `%7Bz%7D`. Resolve the part before them, then append.
     */
    const base = api(
      `api/coverage/tiles/${summary.stamp}/${state.preset}/${currentSiteSet()}/${state.layer}/`,
    );
    state.tiles = L.tileLayer(
      `${base}{z}/{x}/{y}.png`,
      {
        minZoom: 0,
        maxZoom: 19,
        minNativeZoom: summary.min_zoom,
        maxNativeZoom: summary.max_zoom,
        bounds: L.latLngBounds(
          [summary.bounds[0], summary.bounds[1]],
          [summary.bounds[2], summary.bounds[3]],
        ),
        opacity: state.signalOpacity,
        // A tile that was never written is ground no node reaches. That
        // is a 404 and it must not log an error for every empty square.
        errorTileUrl:
          'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
        className: 'coverage-tiles',
      },
    ).addTo(map);
  }

  function cssColour(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim()
      || fallback;
  }

  function nodeColour(node) {
    return node.role ? cssColour(`role-${node.role}`, '#f6ece2') : cssColour('muted', '#b59c88');
  }

  function nodeStyle(node) {
    const fill = nodeColour(node);
    const heard = Date.parse(node.last_heard || '');
    const stale = Number.isFinite(heard) && Date.now() - heard > 24 * 60 * 60 * 1000;
    return {
      radius: node.is_mqtt_gateway ? 7 : 5,
      color: node.is_mqtt_gateway ? cssColour('text', '#f6ece2') : '#17100b',
      weight: node.is_mqtt_gateway ? 3 : 2,
      fillColor: fill,
      fillOpacity: stale ? 0.45 : 0.95,
      opacity: stale ? 0.65 : 1,
    };
  }

  function nodePopup(node) {
    const role = node.role ? node.role.replace(/_/g, ' ').toLowerCase() : 'no role reported';
    return el(
      'div',
      {},
      el('div', { style: 'font-weight:650', text: node.display_name || node.node_id }),
      el('div', { class: 'muted', style: 'font-size:.8rem', text: node.node_id }),
      el('div', { style: `font-size:.8rem;color:${nodeColour(node)}`, text: role }),
      el('button', {
        class: 'linky',
        type: 'button',
        text: 'Open node detail',
        onclick: () => {
          location.hash = `node/${node.node_id}`;
        },
      }),
    );
  }

  async function drawNodes() {
    const map = ensureMap();
    state.nodes.clearLayers();
    if (!state.showNodes || !state.summary || !state.preset) return;

    const preset = state.preset;
    const request = ++state.nodeRequest;
    let rows = state.nodeRows.get(preset);
    if (!rows) {
      const hours = Number(state.summary.active_hours) || 168;
      try {
        const response = await fetch(
          api(`api/map/nodes?channel=${encodeURIComponent(preset)}&hours=${hours}&active_hours=${hours}`),
        );
        if (!response.ok) throw new Error(`Request failed (${response.status})`);
        rows = await response.json();
        state.nodeRows.set(preset, rows);
      } catch (error) {
        console.warn('coverage nodes unavailable', error);
        return;
      }
    }
    if (request !== state.nodeRequest || preset !== state.preset || !state.showNodes) return;

    /* Draw only the nodes the map on show was predicted from, so the
       dots agree with the banner and the site set. The infrastructure
       view draws routers and repeaters; the extended view adds the
       nodes that repeat. A CLIENT_MUTE, a tracker or an unintroduced
       (roleless) node the prediction left out is left off the map too,
       instead of sitting on a footprint it did not contribute to.

       A deployment-wide diagnostic run names every role (EVERY_ROLE,
       "ALL"), and then nothing is filtered and every node is drawn. */
    const roles = shownRoles();
    const allowed = new Set(roles);
    /* Fail open. An empty set means the roles could not be read at all
       (an old manifest with no site_roles, say), and hiding every node
       then is the wrong failure: the overlay is there to be read, so an
       unknown role set draws everything rather than nothing. */
    const shown = (!allowed.size || allowed.has('ALL'))
      ? rows
      : rows.filter((node) => node.role && allowed.has(node.role));

    for (const node of shown) {
      if (node.lat == null || node.lon == null) continue;
      L.circleMarker([node.lat, node.lon], nodeStyle(node))
        .bindPopup(nodePopup(node))
        .addTo(state.nodes);
    }
    if (!map.hasLayer(state.nodes)) state.nodes.addTo(map);
  }

  /* ---------------------------------------------------------- panels */

  function drawLayers(page) {
    const host = $('[data-coverage-layers]', page);
    if (!host || !state.summary) return;
    replace(
      host,
      (state.summary.layers || []).map((layer) =>
        el('button', {
          type: 'button',
          'aria-pressed': String(layer.key === state.layer),
          text: layer.label,
          title: layer.key === 'usable' ? 'The weaker of the two directions' : null,
          onclick: () => {
            state.layer = layer.key;
            drawLayers(page);
            drawTiles();
            drawLegend(page);
          },
        }),
      ),
    );
  }

  function drawViews(page) {
    const host = $('[data-coverage-views]', page);
    if (!host) return;
    const choices = [
      ['showMap', 'Map'],
      ['showNodes', 'Nodes'],
      ['showSignal', 'Signal strength'],
    ];
    replace(
      host,
      choices.map(([key, label]) =>
        el('button', {
          type: 'button',
          'aria-pressed': String(state[key]),
          text: label,
          onclick: () => {
            state[key] = !state[key];
            drawViews(page);
            if (key === 'showMap') drawBaseMap();
            if (key === 'showNodes') drawNodes();
            if (key === 'showSignal') {
              drawTiles();
              drawLegend(page);
              drawOpacity(page);
            }
          },
        }),
      ),
    );
  }

  /* Keep the opacity slider in step with the state, and dim it when
     the signal layer is off, because it has nothing to act on then.
     The slider is the viewer's control: it never leaves the browser. */
  function drawOpacity(page) {
    const input = $('[data-coverage-opacity]', page);
    if (!input) return;
    const pct = Math.round(state.signalOpacity * 100);
    input.value = String(pct);
    input.disabled = !state.showSignal;
    const out = $('[data-coverage-opacity-value]', page);
    if (out) out.textContent = `${pct}%`;
  }

  function drawSiteSets(page) {
    const wrap = $('[data-coverage-siteset-wrap]', page);
    const picker = $('[data-coverage-siteset]', page);
    if (!wrap || !picker || !state.summary) return;
    const sets = siteSets(state.summary);
    /* One set is not a choice. The picker stays hidden rather than
       offering a control that cannot change anything. */
    if (sets.length < 2) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    replace(
      picker,
      sets.map((item) => el('option', { value: item.key, text: item.label })),
    );
    picker.value = currentSiteSet();
  }

  function drawPresets(page) {
    const picker = $('[data-coverage-preset]', page);
    if (!picker || !state.summary) return;
    const presets = presetsOf(state.summary);
    replace(
      picker,
      presets.map((item) =>
        el('option', { value: item.preset, text: `${item.label} (${item.node_count})` }),
      ),
    );
    if (state.preset) picker.value = state.preset;
  }

  function drawLegend(page) {
    const legend = $('[data-coverage-legend]', page);
    if (!legend) return;
    const preset = state.summary && presetOf(state.summary, state.preset);
    if (!preset || !state.showSignal) {
      legend.hidden = true;
      return;
    }
    legend.hidden = false;
    const floor = preset.sensitivity_dbm;
    const layer = (state.summary.layers || []).find((item) => item.key === state.layer);
    $('[data-coverage-legend-title]', legend).textContent = layer ? layer.label : 'Signal';
    $('[data-coverage-floor]', legend).textContent = `${floor} dBm`;
    // The span comes from the run, so the legend cannot drift from
    // the tiles it describes. See coverage/render.py.
    const span = Number(state.summary.ramp_span_db) || 0;
    $('[data-coverage-ceiling]', legend).textContent = `${floor + span} dBm`;
  }

  function statTile(value, label, delta) {
    return el(
      'div',
      { class: 'panel stat' },
      el('span', { class: 'value', text: value }),
      el('span', { class: 'label', text: label }),
      delta ? el('span', { class: 'delta', text: delta }) : null,
    );
  }

  function drawStats(page) {
    const host = $('[data-coverage-stats]', page);
    if (!host) return;
    const summary = state.summary;
    const preset = summary && presetOf(summary, state.preset);
    if (!preset) {
      replace(host);
      return;
    }
    replace(
      host,
      statTile(number(preset.site_count), 'Sites predicted from',
        preset.skipped_count ? `${preset.skipped_count} over the cap` : null),
      statTile(number(preset.usable_area_km2), 'Usable km²', 'Both directions'),
      statTile(number(preset.downlink_area_km2), 'Heard km²', 'One direction only'),
      statTile(when(summary.generated_at), 'Last run', `${number(summary.seconds, 0)} s`),
    );
  }

  function flag(good, text) {
    return el('span', { class: `coverage-flag ${good ? 'good' : 'warn'}`, text });
  }

  /*
   * What the run left out, and why.
   *
   * A coverage map is only about nodes that stay where they are, so
   * most of a mesh is not on it. A page that shows a site count and
   * nothing else invites a reader to think it drew everything.
   */
  function excluded() {
    const preset = state.summary && presetOf(state.summary, state.preset);
    const counts = (preset && preset.excluded_by_role) || {};
    const names = Object.keys(counts);
    if (!names.length) return null;
    const total = names.reduce((sum, name) => sum + counts[name], 0);
    const label = (name) =>
      name === 'NULL'
        ? 'no role reported'
        : name === 'coarse-position'
          ? 'position too coarse'
          : name.replace(/_/g, ' ').toLowerCase();
    return el(
      'p',
      { class: 'muted', style: 'font-size:.84rem' },
      `${total} of ${number(preset.candidate_count)} positioned nodes were left out: `,
      names
        .sort((a, b) => counts[b] - counts[a])
        .map((name) => `${counts[name]} ${label(name)}`)
        .join(', '),
        `. This run selected ${(state.summary.site_roles || []).join(', ') || 'no roles'}.`,
      counts['coarse-position']
        ? el(
            'span',
            {},
            ' ',
            el('strong', { text: `${counts['coarse-position']} of those` }),
            // "routers" is right for an ordinary run, because nothing
            // else reaches the position test. A diagnostic run tests
            // every role, so there it has to be the wider word.
            state.summary.is_diagnostic
              ? ' are nodes whose position the broker rounded off too far to predict '
                + 'from. Give each one a latitude and longitude in config/nodes.yaml '
                + 'and it becomes a site again.'
              : ' are routers whose position the broker rounded off too far to predict '
                + 'from. Give each one a latitude and longitude in config/nodes.yaml '
                + 'and it becomes a site again.',
          )
        : null,
    );
  }

  /*
   * A run that predicted from every node is a useful thing to look at
   * and is not a coverage map: a handheld that crossed town once draws
   * a permanent footprint. Neither the heading nor the panel may let
   * the two be mistaken for each other, because the tiles look
   * identical.
   */
  /* Whether the map on show is a diagnostic one.

     Two ways it can be. The whole run is diagnostic when a deployment
     set COVERAGE_SITE_ROLES wide, and then every map is. Or the reader
     picked the wider site set, and that one is. The page must say so
     either way: a map drawn from client nodes that says it was drawn
     from routers is the one thing worse than no map. */
  function shownIsDiagnostic() {
    const summary = state.summary;
    if (!summary) return false;
    if (summary.is_diagnostic) return true;
    const set = siteSetOf(summary, state.siteSet);
    return Boolean(set && set.is_diagnostic);
  }

  /* The roles the map on show was predicted from. */
  function shownRoles() {
    const summary = state.summary;
    const set = siteSetOf(summary, state.siteSet);
    const roles = (set && set.site_roles) || (summary && summary.site_roles) || [];
    return Array.isArray(roles) ? roles : [];
  }

  function drawDiagnosticBanner(page) {
    const sub = $('[data-coverage-sub]', page);
    const summary = state.summary;
    if (!sub || !summary || !summary.available) return;
    sub.textContent = shownIsDiagnostic()
      ? `Diagnostic view: predicted from ${shownRoles().join(', ') || 'every role'}.`
      : 'Where the mesh reaches, predicted from the routers and repeaters that carry it.';
  }

  function diagnosticNotice() {
    if (!shownIsDiagnostic()) return null;
    const roles = shownRoles().join(', ') || 'roles outside the infrastructure set';
    /* A run made diagnostic by the deployment cannot be fixed from the
       page, so it names the setting. A view the reader chose can be
       changed by choosing again, so it says that instead. */
    const remedy = state.summary.is_diagnostic
      ? 'Set COVERAGE_SITE_ROLES back to infrastructure roles for a map to publish.'
      : 'Pick "Routers and repeaters" above for the map this mesh publishes.';
    return el(
      'p',
      { class: 'notice warn', style: 'font-weight:600' },
      `This is a diagnostic view. It predicted from ${roles}. `
        + 'It can include personal or mobile nodes, so it shows where a radio could '
        + `reach on the day and not where the mesh reaches. ${remedy}`,
    );
  }

  function drawAssumes(page) {
    const host = $('[data-coverage-assumes]', page);
    if (!host) return;
    const summary = state.summary;
    if (!summary || !summary.available) {
      replace(host, el('p', { text: 'No coverage run has been made yet.' }));
      return;
    }
    const missing = (summary.missing_terrain_tiles || []).length;
    replace(
      host,
      diagnosticNotice(),
      el(
        'p',
        {},
        'The prediction is not a promise. It assumes a handheld radio at ',
        el('strong', { text: `${summary.rx_height_m} m` }),
        ' above the ground, with a ',
        el('strong', { text: `${summary.rx_gain_dbi} dBi` }),
        ' antenna, transmitting at ',
        el('strong', { text: `${summary.handheld_tx_power_dbm} dBm` }),
        '. A real radio in a pocket, indoors, or against a body does worse.',
      ),
      el(
        'p',
        {},
        'Each node is predicted out to ',
        el('strong', { text: `${summary.radius_km} km` }),
        '. Terrain is about 90 m across. Coverage that follows ridge lines and stops at ',
        'them is the model working. A smooth circle means the terrain did not load.',
      ),
      el(
        'p',
        { style: 'display:flex;flex-wrap:wrap;gap:.4rem;align-items:center' },
        flag(summary.has_terrain, summary.has_terrain ? 'Terrain loaded' : 'No terrain: flat ground'),
        flag(
          summary.has_landcover,
          summary.has_landcover ? 'Buildings and trees accounted for' : 'No clutter data',
        ),
        missing ? flag(false, `${missing} terrain tiles missing`) : null,
      ),
      excluded(),
    );
  }

  async function drawCalibration(page) {
    const host = $('[data-coverage-calibration]', page);
    if (!host) return;

    let report = null;
    try {
      const response = await fetch(api('api/coverage/calibration'));
      if (response.ok) report = await response.json();
    } catch (error) {
      console.warn('calibration unavailable', error);
    }

    if (!report || !report.available) {
      replace(
        host,
        el('p', {
          class: 'muted',
          text: 'The mesh has not been measured against the model yet. The job runs daily '
            + 'and reads the neighbour reports that nodes publish.',
        }),
      );
      return;
    }

    const summary = report.summary || {};
    const trusted = report.applied_count > 0;
    const head = el(
      'p',
      { style: 'display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin:0 0 .7rem' },
      flag(trusted, trusted
        ? `${report.applied_count} nodes corrected`
        : 'No node corrected'),
      el('span', {
        class: 'coverage-flag',
        text: `${Math.round(summary.count || 0)} links, ${Math.round(summary.censored || 0)} silent`,
      }),
      el('span', {
        class: 'coverage-flag',
        text: `scatter ${report.residual_spread_db} dB`,
      }),
      el('span', {
        class: 'coverage-flag',
        text: `model bias ${report.model_bias_db} dB`,
      }),
    );

    const rows = (report.nodes || [])
      .slice()
      .sort((a, b) => Number(b.applied) - Number(a.applied)
        || Math.abs(b.offset_db || 0) - Math.abs(a.offset_db || 0))
      .slice(0, 40)
      .map((node) =>
        el(
          'tr',
          {},
          el(
            'td',
            {},
            el('button', {
              class: 'linky',
              type: 'button',
              text: node.node_id,
              onclick: () => {
                location.hash = `node/${node.node_id}`;
              },
            }),
          ),
          el('td', {
            class: 'num',
            text: node.applied
              ? `${node.offset_db > 0 ? '+' : ''}${node.offset_db} dB`
              : '—',
          }),
          el('td', { class: 'num', text: String(node.reported) }),
          el('td', { class: 'num', text: String(node.censored) }),
          el('td', { class: 'num', text: String(node.counterparties) }),
          el('td', { class: 'num', text: `${node.residual_spread_db} dB` }),
          el('td', { text: node.applied ? 'applied' : 'not enough' }),
        ),
      );

    replace(
      host,
      head,
      el(
        'p',
        { class: 'muted', style: 'font-size:.82rem;margin:0 0 .7rem' },
        'A silent link is one the model expected and no node reported. Counting only the '
          + 'links that worked would say every node is better than it is.',
      ),
      el(
        'div',
        { class: 'table-wrap' },
        el(
          'table',
          {},
          el(
            'thead',
            {},
            el(
              'tr',
              {},
              el('th', { text: 'Node' }),
              el('th', { class: 'num', text: 'Measured' }),
              el('th', { class: 'num', text: 'Heard' }),
              el('th', { class: 'num', text: 'Silent' }),
              el('th', { class: 'num', text: 'Peers' }),
              el('th', { class: 'num', text: 'Scatter' }),
              el('th', { text: 'State' }),
            ),
          ),
          el('tbody', {}, rows),
        ),
      ),
    );
  }

  /*
   * The nodes a run could not use because the broker rounded their
   * position off, as a block to paste into config/nodes.yaml.
   *
   * The assumptions panel gives the count. A count is not an
   * instruction: "give each one a latitude and longitude" is only
   * followable if the page says which ones, and the rounded position
   * is what there is to start from. Coarsest first, because the node
   * that is 23 km out is the one moving the map most.
   */
  function coarseYaml(sites) {
    const lines = ['nodes:'];
    for (const site of sites) {
      const off = site.deviation_m ? `${number(Math.round(site.deviation_m))} m out` : 'rounded';
      lines.push(`  # ${site.display_name} (${site.role}, ${off})`);
      lines.push(`  "${site.node_id}":`);
      lines.push(`    latitude: ${site.rounded_lat}`);
      lines.push(`    longitude: ${site.rounded_lon}`);
    }
    return lines.join('\n');
  }

  function drawCoarse(page) {
    const panel = $('[data-coverage-coarse-panel]', page);
    const host = $('[data-coverage-coarse]', page);
    if (!panel || !host) return;
    const sites = (state.summary && state.summary.coarse_sites) || [];
    panel.hidden = !sites.length;
    if (!sites.length) return;

    const text = coarseYaml(sites);
    // `.panel pre` and a plain button are already styled. Nothing new
    // is needed in the stylesheet for this panel.
    const copy = el('button', {
      type: 'button',
      text: 'Copy',
      onclick: () => {
        // The clipboard is not always there: an insecure origin has no
        // navigator.clipboard at all. Say so rather than doing nothing.
        const done = (ok) => {
          copy.textContent = ok ? 'Copied' : 'Select and copy';
          setTimeout(() => {
            copy.textContent = 'Copy';
          }, 2000);
        };
        if (!navigator.clipboard) {
          done(false);
          return;
        }
        navigator.clipboard.writeText(text).then(() => done(true), () => done(false));
      },
    });
    replace(
      host,
      el(
        'p',
        { class: 'muted', style: 'font-size:.84rem' },
        `${sites.length} named here, coarsest first. The position shown is the `
          + 'rounded one, so it names the area and not the mast. Replace each with '
          + 'the real one.',
      ),
      el('div', { style: 'margin:0 0 .5rem' }, copy),
      el('pre', { text }),
    );
  }

  function drawSites(page) {
    const host = $('[data-coverage-sites]', page);
    if (!host) return;
    const preset = state.summary && presetOf(state.summary, state.preset);
    const nodes = (preset && preset.nodes) || [];
    if (!nodes.length) {
      replace(host, el('p', { class: 'muted', text: 'No sites in this run.' }));
      return;
    }
    const used = nodes.filter((node) => node.used);
    const rows = used.slice(0, 100).map((node) =>
      el(
        'tr',
        {},
        el(
          'td',
          {},
          el('button', {
            class: 'linky',
            type: 'button',
            text: node.display_name || node.node_id,
            onclick: () => {
              location.hash = `node/${node.node_id}`;
            },
          }),
        ),
        el('td', { class: 'num', text: `${node.eirp_dbm} dBm` }),
        el('td', { class: 'num', text: `${node.antenna_height_m} m` }),
        el('td', { class: 'num', text: node.clutter_height_m ? `${node.clutter_height_m} m` : '—' }),
        el('td', { text: node.calibrated ? 'measured' : 'nameplate' }),
      ),
    );
    replace(
      host,
      el(
        'table',
        {},
        el(
          'thead',
          {},
          el(
            'tr',
            {},
            el('th', { text: 'Node' }),
            el('th', { class: 'num', text: 'Radiated' }),
            el('th', { class: 'num', text: 'Antenna' }),
            el('th', { class: 'num', text: 'Clutter' }),
            el('th', { text: 'Power from' }),
          ),
        ),
        el('tbody', {}, rows),
      ),
    );
  }

  function notice(page, message, kind) {
    const host = $('[data-coverage-notice]', page);
    if (!host) return;
    host.hidden = !message;
    host.textContent = message || '';
    host.className = `notice${kind ? ` ${kind}` : ''}`;
  }

  function drawAll(page) {
    drawSiteSets(page);
    drawPresets(page);
    drawLayers(page);
    drawViews(page);
    drawOpacity(page);
    drawLegend(page);
    drawStats(page);
    drawDiagnosticBanner(page);
    drawAssumes(page);
    drawCoarse(page);
    drawSites(page);
    drawBaseMap();
    drawTiles();
    drawNodes();
    drawCalibration(page);
  }

  /* ------------------------------------------------------------ show */

  async function show(page) {
    const map = ensureMap();
    setTimeout(() => map.invalidateSize(), 0);
    // Read current positions each time this page opens. A node list
    // kept for the whole browser session becomes stale.
    state.nodeRows.clear();

    let summary = null;
    try {
      const response = await fetch(api('api/coverage'));
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      summary = await response.json();
    } catch (error) {
      console.warn('coverage summary failed', error);
      notice(page, 'The coverage map could not be read.', 'error');
      return;
    }

    state.summary = summary;
    if (!summary.available || !(summary.presets || []).length) {
      notice(
        page,
        'No coverage map has been made yet. The job runs on a timer and writes one for '
          + 'each modem preset the mesh is using.',
        '',
      );
      drawDiagnosticBanner(page);
    drawAssumes(page);
    drawCoarse(page);
      return;
    }
    notice(page, '');

    if (!state.siteSet || !siteSetOf(summary, state.siteSet)) {
      const sets = siteSets(summary);
      state.siteSet = sets.length ? sets[0].key : 'infrastructure';
    }
    if (!state.preset || !presetOf(summary, state.preset)) {
      state.preset = busiestPreset(summary);
    }
    if (!state.preset) {
      notice(page, 'This run predicted from no node on any modem preset.');
      return;
    }
    if (!state.loaded) {
      const picker = $('[data-coverage-preset]', page);
      if (picker) {
        picker.addEventListener('change', () => {
          state.preset = picker.value;
          drawAll(page);
        });
      }
      const opacity = $('[data-coverage-opacity]', page);
      if (opacity) {
        opacity.addEventListener('input', () => {
          const pct = Number(opacity.value);
          state.signalOpacity = Number.isFinite(pct) ? pct / 100 : 1;
          const out = $('[data-coverage-opacity-value]', page);
          if (out) out.textContent = `${Math.round(state.signalOpacity * 100)}%`;
          /* setOpacity restyles the tiles already on the map, so
             dragging refetches nothing. drawTiles is not called. */
          if (state.tiles) state.tiles.setOpacity(state.signalOpacity);
          try {
            // Remember a level the map is visible at; a zero is not a
            // preference to keep, so it clears back to the default.
            if (state.signalOpacity > 0) {
              localStorage.setItem(OPACITY_KEY, String(state.signalOpacity));
            } else {
              localStorage.removeItem(OPACITY_KEY);
            }
          } catch {
            // Storage off. The slider still works for this visit.
          }
        });
      }
      const setPicker = $('[data-coverage-siteset]', page);
      if (setPicker) {
        setPicker.addEventListener('change', () => {
          state.siteSet = setPicker.value;
          /* The two sets need not carry the same presets: a preset
             whose only nodes are clients exists in one and not the
             other. If the chosen preset is not in the new set, land on
             the busiest one there, never on nothing, or the map goes
             blank with a preset still named in the picker. */
          if (!presetOf(summary, state.preset)) state.preset = busiestPreset(summary);
          /* The node rows are keyed on preset, not on the site set, so
             they survive a set switch. Only the role filter in
             drawNodes changes, and it runs again from the cache. */
          drawAll(page);
        });
      }
      state.loaded = true;
      /*
       * Open on the coverage, not on the region. The region covers
       * every degree the terrain service serves, which is far more
       * ground than any mesh reaches, and the coverage would be a speck
       * in the middle of it.
       */
      const preset = presetOf(summary, state.preset);
      const bounds = (preset && preset.data_bounds) || summary.data_bounds || summary.bounds;
      if (Array.isArray(bounds) && bounds.length === 4) {
        map.fitBounds(L.latLngBounds([bounds[0], bounds[1]], [bounds[2], bounds[3]]), {
          padding: [24, 24],
        });
      }
    }

    drawAll(page);
  }

  window.SonoranCoverage = { show, state };
}());
