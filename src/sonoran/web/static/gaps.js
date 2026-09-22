/*
 * The coverage gaps page.
 *
 * It draws what the gaps job already measured. It computes nothing and
 * it predicts nothing: the endpoint reads one written file, and this
 * file turns it into sentences.
 *
 * The file is separate from app.js for the same reason coverage.js and
 * planner.js are: its own Leaflet map, its own state, and app.js is
 * large enough. **It loads before app.js**, because app.js runs the
 * router as its last act and the router needs `window.SonoranGaps` to
 * exist by then. Without that, a reload straight onto #gaps quietly
 * shows the dashboard. See AGENTS.md 9.14.2.
 *
 * Three rules hold this page together, and each one is the difference
 * between a measurement and an accusation:
 *
 * 1. Three states, everywhere. `unknown` has its own colour, its own
 *    count, and its own section. It never renders as zero, as green, or
 *    as an empty cell that reads like "fine".
 * 2. No score. A row's colour comes from `worst_state`. There is no 0 to
 *    100 number on this page and no averaged amber.
 * 3. The words are the endpoint's words. Every sentence in the evidence
 *    panel comes from the API's `sentence` field, which the signals
 *    module wrote. This file does not paraphrase a finding, because
 *    "none of the 31 gateways active this week heard it" and "it is
 *    isolated" are not the same claim.
 *
 * Nothing on this page draws a line between two nodes. No signal here
 * names two ends of one link, so there is nothing a line could mean.
 */

'use strict';

(function () {
  const CONFIG = window.SONORAN || {};
  const API_BASE = CONFIG.apiBase || '';
  const api = (path) =>
    new URL(String(path).replace(/^\//, ''), API_BASE || document.baseURI).toString();

  // The house convention for "not measured".
  const EM_DASH = '—';

  const state = {
    preset: null,
    summary: null,
    rows: [],
    loaded: false,
    map: null,
    markers: null,
    // Which rows the one table shows (#62). `measured` holds the nodes
    // with a finding, `unknown` the nodes we cannot judge. A tile click
    // sets `filter`, which looks across both.
    view: 'measured',
    filter: null,
    query: '',
    sort: null,
  };

  async function fetchJson(path) {
    const response = await fetch(api(path));
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
  }

  /* ----------------------------------------------------------- chips */

  /*
   * Each signal answers one yes-or-no question about a node, so the chip
   * says yes, no, or "we cannot tell". The full sentence rides along as
   * the tooltip, and the row opens to it.
   */
  function chip(signal) {
    if (!signal) return el('span', { class: 'gap-chip unknown', title: 'Not measured.' },
      el('span', { class: 'gap-word', text: EM_DASH }));
    const words = { bad: 'yes', ok: 'no', unknown: EM_DASH };
    const word = words[signal.state] || EM_DASH;
    const parts = [el('span', { class: 'gap-word', text: word })];
    if (signal.state !== 'unknown' && signal.value != null) {
      parts.push(el('span', { class: 'gap-value', text: String(signal.value) }));
    }
    return el('span', {
      class: `gap-chip ${signal.state}`,
      title: signal.sentence || signal.reason || '',
    }, parts);
  }

  /* ------------------------------------------------------- the lead */

  /*
   * One sentence for somebody who joined the mesh last week.
   *
   * It names the preset, because there is no whole-mesh answer, and it
   * ends on the unknown count, because that is usually the biggest
   * number on the page and the least likely to be read.
   */
  function leadSentence(summary) {
    const counts = summary.signals || {};
    const bad = (name) => (counts[name] && counts[name].bad) || 0;
    const label = summary.label || summary.preset;
    const clauses = [];

    /* One node is not "1 nodes". The headline is the sentence most
       people will read, so it is worth getting the grammar right. */
    const say = (n, one, many) => `${n} ${n === 1 ? 'node' : 'nodes'} ${n === 1 ? one : many}`;

    const asymmetric = bad('hears_but_is_not_heard');
    if (asymmetric) {
      clauses.push(say(asymmetric,
        'can hear the mesh and the mesh cannot hear it',
        'can hear the mesh and the mesh cannot hear them'));
    }
    /* A node with the asymmetry also satisfies radio_isolated, so it
       would otherwise be counted twice in one sentence. */
    const isolated = bad('radio_isolated') - asymmetric;
    if (isolated > 0) {
      clauses.push(say(isolated,
        'reaches us only through its own internet link',
        'reach us only through their own internet link'));
    }
    const flaky = bad('rf_intermittent');
    if (flaky) {
      clauses.push(say(flaky,
        'gets out over the air in fewer than half the hours it is awake',
        'get out over the air in fewer than half the hours they are awake'));
    }
    const thin = bad('weak_best_link');
    if (thin) {
      clauses.push(say(thin,
        'has little margin on its best measured link',
        'have little margin on their best measured link'));
    }

    const unmeasured = summary.not_enough_evidence_count || 0;
    const tail = unmeasured === 1
      ? 'For 1 node there is not enough evidence to say anything at all.'
      : `For ${unmeasured} nodes there is not enough evidence to say anything at all.`;
    const head = `On ${label} over the last ${summary.window_hours} hours, `;
    if (!clauses.length) {
      return `${head}no node shows a fault this can measure. ${tail}`;
    }
    const list = clauses.length === 1
      ? clauses[0]
      : `${clauses.slice(0, -1).join(', ')}, and ${clauses[clauses.length - 1]}`;
    return `${head}${list}. ${tail}`;
  }

  /* ------------------------------------------------------ stat tiles */

  /* One tile per signal, with `bad` and `unknown` side by side. The
     unknown number is never hidden: it is the honest half of the count. */
  function signalTile(name, label, counts, page) {
    /* Each half opens the nodes behind its number (#62). A tile that
       could not be opened left the reader with a count and no names. */
    const half = (kind, n, word) => {
      const active = state.filter && state.filter.signal === name && state.filter.state === kind;
      return el('button', {
        type: 'button',
        class: `gap-half ${kind}${active ? ' active' : ''}`,
        'aria-pressed': String(Boolean(active)),
        title: `Show the ${n} nodes where "${label || name}" is ${kind === 'bad' ? 'found' : 'not known'}`,
        onclick: () => {
          state.filter = active ? null : { signal: name, state: kind, label: label || name };
          drawCounts(page, state.summary);
          drawNodes(page);
          const table = $('[data-gaps-table]', page);
          if (table && !active) table.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        },
      },
      el('span', { class: 'gap-n', text: String(n) }),
      el('span', { class: 'gap-k', text: word }));
    };
    return el('div', { class: 'panel gap-tile' },
      el('div', { class: 'stat' },
        el('div', { class: 'gap-pair' },
          half('bad', counts.bad || 0, 'found'),
          half('unknown', counts.unknown || 0, 'cannot tell')),
        el('span', { class: 'gap-label', text: label || name })));
  }

  function drawCounts(page, summary) {
    const target = $('[data-gaps-counts]', page);
    if (!target) return;
    const order = summary.signal_order || [];
    const labels = summary.signal_labels || {};
    const counts = summary.signals || {};
    replace(target, order.map((name) =>
      signalTile(name, labels[name], counts[name] || {}, page)));
  }

  /* ---------------------------------------------------------- table */

  function evidencePanel(row, summary) {
    const order = summary.signal_order || [];
    const labels = summary.signal_labels || {};
    const findings = order.map((name) => {
      const signal = (row.signals || {})[name];
      if (!signal) return null;
      return el('div', { class: `gap-finding ${signal.state}` },
        el('span', { class: 'gap-name', text: labels[name] || name }),
        el('span', { class: 'gap-said', text: signal.sentence || signal.reason || '' }),
        el('span', {
          class: 'gap-counts',
          text: Object.entries(signal.evidence || {})
            .filter(([, value]) => value != null && value !== '')
            .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join('|') : value}`)
            .join('  '),
        }));
    });

    /* Where a reader goes next. The node page for the node itself; no
       link page, because no signal here names a link to open. */
    const links = el('div', { class: 'gap-links' },
      el('a', { class: 'linky', href: `#node/${row.node_id}`, text: 'Open this node and its potential issues' }),
      el('span', { class: 'muted', text: `${row.packets} packets over ${row.active_hours} hours` }),
      row.position_confidence === 'coarse'
        ? el('span', {
            class: 'muted',
            text: `position accurate to about ${Math.round(row.position_deviation_m)} m`,
          })
        : null,
      row.mobile
        ? el('span', {
            class: 'muted',
            text: `moves: positions spread ${row.position_spread_km} km`,
          })
        : null);

    return el('div', { class: 'gap-evidence' }, findings, links);
  }

  /*
   * The table, built with app.js's `table()` helper, then given the
   * ability to open a row in place. The rows arrive pre-sorted by the
   * endpoint, as every other table in this project does, so the ranking
   * rule lives in one place and this file holds no copy of it.
   */
  function drawTable(target, rows, summary, emptyMessage) {
    const order = summary.signal_order || [];
    const labels = summary.signal_labels || {};
    const sortState = state.sort || { key: null, order: null };
    const onSort = (key, order) => {
      state.sort = { key, order };
      drawNodes($('[data-page="gaps"]'));
    };
    const sortable = (key) => ({ sort: key, sortState, onSort });
    const columns = [
      {
        label: 'Evidence',
        /* A visible way in (#62). The row still opens on a click, but a
           bare click target is one nobody finds. */
        cell: () => el('button', {
          type: 'button', class: 'linky gap-open', 'aria-expanded': 'false', text: 'Open \u25b8',
        }),
      },
      {
        label: 'Node',
        ...sortable('name'),
        cell: (row) => el('span', {}, nodeChip(row)),
      },
      /*
       * `roleCell` is app.js's, and it prints the label with the wire
       * value on hover. This column printed the enum, so the same node
       * read "Client base" on the nodes page and `CLIENT_BASE` here.
       */
      { label: 'Role', ...sortable('role'), cell: (row) => roleCell(row.role) },
      ...order.map((name) => ({
        label: labels[name] || name,
        ...sortable(name),
        cell: (row) => chip((row.signals || {})[name]),
      })),
      { label: 'Packets', num: true, ...sortable('packets'), cell: (row) => row.packets },
    ];

    const built = table(columns, rows, emptyMessage);
    replace(target, built);
    if (!rows.length || built.tagName !== 'TABLE') return;

    const body = built.tBodies[0];
    if (!body) return;
    Array.from(body.rows).forEach((tr, index) => {
      const row = rows[index];
      if (!row) return;
      /* The row's colour comes from worst_state. Never from a number. */
      tr.classList.add('gap-row', row.worst_state);
      tr.tabIndex = 0;
      tr.setAttribute('role', 'button');
      tr.setAttribute('aria-expanded', 'false');
      tr.title = 'Open the evidence';
      const opener = tr.querySelector('.gap-open');
      const toggle = () => {
        const open = tr.getAttribute('aria-expanded') === 'true';
        if (opener) {
          opener.setAttribute('aria-expanded', String(!open));
          opener.textContent = open ? 'Open \u25b8' : 'Close \u25be';
        }
        if (open) {
          if (tr.nextElementSibling && tr.nextElementSibling.classList.contains('gap-detail')) {
            tr.nextElementSibling.remove();
          }
          tr.setAttribute('aria-expanded', 'false');
          tr.classList.remove('open');
          return;
        }
        const detail = el('tr', { class: 'gap-detail' },
          el('td', { colspan: String(columns.length) }, evidencePanel(row, summary)));
        tr.after(detail);
        tr.setAttribute('aria-expanded', 'true');
        tr.classList.add('open');
      };
      tr.addEventListener('click', (event) => {
        /* A click on the node chip opens the node page. Let it. */
        if (event.target.closest('.gap-open')) { toggle(); return; }
        if (event.target.closest('button, a')) return;
        toggle();
      });
      tr.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          toggle();
        }
      });
    });
  }

  /* ------------------------------------------------ the one table */

  /*
   * The two views, and the order a signal column sorts in.
   *
   * A node with a fault we can measure and a node we cannot measure at
   * all are different answers, so they stay two views, each with its
   * own count on its own button. `unknown` sorts between the two
   * others, never with `ok`: not measured is not fine.
   */
  const VIEWS = [
    ['measured', 'Something we can measure', (row) => row.bad_count > 0],
    ['unknown', 'Not enough evidence', (row) => row.bad_count === 0 && row.unknown_count > 0],
  ];
  const STATE_ORDER = { bad: 0, unknown: 1, ok: 2 };

  /*
   * Sorting in the browser is safe here, where it is not on the node
   * list, because this page holds every assessed row: the endpoint
   * returns up to 500 and says how many matched. If that ever stops
   * being every row, `drawNodes` says so rather than sort a sample.
   */
  function sortRows(rows) {
    if (!state.sort || !state.sort.key) return rows;
    const { key, order } = state.sort;
    const value = (row) => {
      if (key === 'name') return (row.display_name || row.node_id || '').toLowerCase();
      if (key === 'role') return row.role || '\uffff';
      if (key === 'packets') return row.packets || 0;
      const signal = (row.signals || {})[key];
      return signal ? STATE_ORDER[signal.state] ?? 3 : 3;
    };
    const sign = order === 'desc' ? -1 : 1;
    // The server's order breaks every tie, so equal rows keep it.
    const rank = new Map(rows.map((row, index) => [row, index]));
    return rows.slice().sort((a, b) => {
      const x = value(a);
      const y = value(b);
      if (x < y) return -sign;
      if (x > y) return sign;
      return rank.get(a) - rank.get(b);
    });
  }

  function drawNodes(page) {
    const summary = state.summary;
    if (!summary) return;
    const all = state.rows;
    const counts = Object.fromEntries(VIEWS.map(([key, , test]) => [key, all.filter(test).length]));

    replace($('[data-gaps-view]', page), VIEWS.map(([key, label]) => el('button', {
      type: 'button',
      class: 'toggle',
      'aria-pressed': String(!state.filter && state.view === key),
      text: `${label} (${counts[key]})`,
      onclick: () => {
        state.view = key;
        state.filter = null;
        drawCounts(page, summary);
        drawNodes(page);
      },
    })));

    let rows;
    let note;
    const filterChip = $('[data-gaps-filter]', page);
    if (state.filter) {
      const { signal, label } = state.filter;
      rows = all.filter((row) => {
        const found = (row.signals || {})[signal];
        return found && found.state === state.filter.state;
      });
      note = state.filter.state === 'bad'
        ? `Nodes where "${label}" is found.`
        : `Nodes where "${label}" cannot be told. That is not the same as fine.`;
      filterChip.hidden = false;
      replace(filterChip,
        el('span', { text: label }),
        el('button', {
          type: 'button', class: 'linky', text: 'Clear',
          onclick: () => { state.filter = null; drawCounts(page, summary); drawNodes(page); },
        }));
    } else {
      const [, , test] = VIEWS.find(([key]) => key === state.view) || VIEWS[0];
      rows = all.filter(test);
      note = state.view === 'unknown'
        ? 'No fault we can measure, and at least one thing we cannot judge. Not a clean bill of health.'
        : 'Worst first. Open a row for the evidence behind it.';
      filterChip.hidden = true;
      replace(filterChip);
    }
    if (state.query) {
      rows = rows.filter((row) =>
        (row.display_name || '').toLowerCase().includes(state.query)
        || (row.node_id || '').toLowerCase().includes(state.query));
    }
    if (state.matched > all.length) {
      note += ` Only the first ${all.length} of ${state.matched} assessed nodes are loaded, so sorting and finding cover those alone.`;
    }
    const heading = $('[data-gaps-table-heading]', page);
    if (heading) heading.textContent = `Nodes: ${rows.length}`;
    const viewNote = $('[data-gaps-view-note]', page);
    if (viewNote) viewNote.textContent = note;
    drawTable($('[data-gaps-table]', page), sortRows(rows), summary,
      state.query ? 'No node here matches that name.' : 'No node on this preset is in this view.');
  }

  /* ------------------------------------------------------------ map */

  function ensureMap() {
    if (state.map) return state.map;
    const holder = document.getElementById('gaps-map');
    if (!holder || typeof L === 'undefined') return null;
    const map = L.map(holder, { preferCanvas: true }).setView(
      CONFIG.mapCenter || [34.0, -111.5],
      CONFIG.mapZoom || 7,
    );
    /* The tile host comes from settings, and so does its attribution.
       A deployment with no tile URL gets the markers on a plain
       background rather than a request to somebody else's server. */
    if (CONFIG.tileUrl) {
      L.tileLayer(CONFIG.tileUrl, {
        className: 'basemap-tiles',
        attribution: CONFIG.tileAttribution || '',
        maxZoom: 19,
      }).addTo(map);
    }
    state.markers = L.layerGroup().addTo(map);
    state.map = map;
    return map;
  }

  /*
   * A tooltip as a DOM node, never as a string.
   *
   * Leaflet's `_updateContent` does `t.innerHTML = e` when the content
   * is a string, and a node's name is chosen by whoever owns the radio.
   * A name of `<img src=x onerror=...>` therefore ran on this origin,
   * which also holds Web Serial for the config page. Building the node
   * here means the name lands as text and markup in a name is shown,
   * not executed. See the security issue for the confirmed sink.
   *
   * Leaflet accepts an HTMLElement for exactly this reason.
   */
  function nameTooltip(name, verdict) {
    const wrap = document.createElement('span');
    wrap.textContent = `${name}: ${verdict}`;
    return wrap;
  }

  /*
   * Circles only, and only for a node whose position we can place.
   *
   * A node with a coarse or missing position is NOT drawn, because a
   * marker is a claim about where something is. It stays in the table,
   * where its position confidence is named.
   */
  function drawMap(rows) {
    const map = ensureMap();
    if (!map || !state.markers) return;
    state.markers.clearLayers();
    let drawn = 0;
    const points = [];
    for (const row of rows) {
      if (row.latitude == null || row.longitude == null) continue;
      if (row.position_confidence !== 'exact') continue;
      if (row.worst_state === 'ok') continue;
      const bad = row.worst_state === 'bad';
      L.circleMarker([row.latitude, row.longitude], {
        radius: bad ? 7 : 5,
        weight: 2,
        color: bad ? '#ef6f5c' : '#8fa6c4',
        fillColor: bad ? '#ef6f5c' : '#8fa6c4',
        fillOpacity: bad ? 0.75 : 0.35,
      })
        .bindTooltip(nameTooltip(
          row.display_name,
          bad ? 'a fault we can measure' : 'not enough evidence',
        ))
        .on('click', () => { location.hash = `#node/${row.node_id}`; })
        .addTo(state.markers);
      points.push([row.latitude, row.longitude]);
      drawn += 1;
    }
    setTimeout(() => map.invalidateSize(), 0);
    if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [28, 28], maxZoom: 11 });
    const note = $('[data-gaps-map-note]');
    if (note) {
      const hidden = rows.filter((row) =>
        row.worst_state !== 'ok' && row.position_confidence !== 'exact').length;
      note.textContent = hidden
        ? `${drawn} drawn. ${hidden} left off the map: their position is coarse or missing, ` +
          'and a marker would claim a place we do not know. They are in the table.'
        : `${drawn} drawn.`;
    }
  }

  /* --------------------------------------------------------- limits */

  function drawLimits(page, summary) {
    const target = $('[data-gaps-limits]', page);
    if (!target) return;
    replace(target, (summary.caveats || []).map((item) =>
      el('li', { text: item.text || item.key })));
  }

  /* ---------------------------------------------------------- notice */

  function notice(page, message, kind) {
    const holder = $('[data-gaps-notice]', page);
    if (!holder) return;
    holder.hidden = !message;
    holder.className = `notice${kind ? ` ${kind}` : ''}`;
    holder.textContent = message || '';
  }

  /* ----------------------------------------------------------- draw */

  function drawPresetPicker(page, summary) {
    const picker = $('[data-gaps-preset]', page);
    if (!picker) return;
    const listed = summary.presets || [];
    replace(picker, listed.map((item) =>
      el('option', {
        value: item.preset,
        selected: item.preset === summary.preset,
        text: `${item.label || item.preset} (${item.node_count ?? 0})`,
      })));
    /* One preset is not a choice. Two is. */
    const wrap = $('[data-gaps-preset-wrap]', page);
    if (wrap) wrap.hidden = listed.length < 2;
  }

  async function show(page) {
    let summary;
    try {
      summary = await fetchJson(
        state.preset ? `api/gaps?channel=${encodeURIComponent(state.preset)}` : 'api/gaps');
    } catch (error) {
      console.warn('gaps summary failed', error);
      notice(page, 'The coverage gap assessment could not be read.', 'bad');
      return;
    }

    state.summary = summary;

    if (!summary.available) {
      const why = summary.reason === 'not_a_preset'
        ? 'That channel does not name a modem radio preset. A channel such as Weather ' +
          'rides on top of one and does not name it, so there is no honest assessment ' +
          'to make for it.'
        : 'No gap assessment has been made yet. The job writes one every half hour, or ' +
          'run sonoran-gaps-once to make one now.';
      notice(page, why, '');
      replace($('[data-gaps-counts]', page));
      replace($('[data-gaps-view]', page));
      replace($('[data-gaps-table]', page), empty('Nothing measured yet.'));
      const lead = $('[data-gaps-lead]', page);
      if (lead) lead.textContent = '';
      const window_ = $('[data-gaps-window]', page);
      if (window_) window_.textContent = '';
      return;
    }

    notice(page, '');
    state.preset = summary.preset;
    drawPresetPicker(page, summary);

    const lead = $('[data-gaps-lead]', page);
    if (lead) lead.textContent = leadSentence(summary);

    const window_ = $('[data-gaps-window]', page);
    if (window_) {
      const coverage = summary.coverage || {};
      const predicted = coverage.available
        ? (coverage.is_diagnostic
            ? 'The published coverage run is a diagnostic, so the predicted signal is not read.'
            : `Predicted coverage read from run ${coverage.stamp}.`)
        : 'No coverage run is published, so the predicted signal reads "cannot tell".';
      window_.textContent =
        `${summary.assessed_count} nodes assessed against ${summary.gateways_active} ` +
        `active gateways, over ${summary.window_hours} hours. ${predicted} ` +
        `Generated ${summary.generated_at}.`;
    }

    drawCounts(page, summary);
    drawLimits(page, summary);

    let listing;
    try {
      listing = await fetchJson(
        `api/gaps/nodes?channel=${encodeURIComponent(summary.preset)}&limit=500`);
    } catch (error) {
      console.warn('gaps nodes failed', error);
      replace($('[data-gaps-table]', page), failure(error));
      return;
    }

    const rows = listing.nodes || [];
    state.rows = rows;
    state.matched = listing.matched_count ?? rows.length;
    drawNodes(page);
    drawMap(rows);

    /* The siting half, in its own file. It is handed this page's preset
       and this page's map, so the two halves always answer about one
       radio setting and share one picture. A siting answer for Long
       fast beside a node list for Medium fast would be two radios that
       cannot hear each other on one screen. */
    if (window.SonoranSiting) {
      window.SonoranSiting.show(page, summary.preset, state.map).catch((error) => {
        console.warn('gaps siting failed', error);
      });
    }

    if (!state.loaded) {
      const search = $('[data-gaps-search]', page);
      if (search) {
        search.addEventListener('input', () => {
          state.query = search.value.trim().toLowerCase();
          drawNodes(page);
        });
      }
      const picker = $('[data-gaps-preset]', page);
      if (picker) {
        picker.addEventListener('change', () => {
          state.preset = picker.value;
          state.filter = null;
          show(page);
        });
      }
      state.loaded = true;
    }
  }

  window.SonoranGaps = { show, state };
}());
