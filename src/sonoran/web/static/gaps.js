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
  function signalTile(name, label, counts) {
    return el('div', { class: 'panel gap-tile' },
      el('div', { class: 'stat' },
        el('div', { class: 'gap-pair' },
          el('div', { class: 'gap-half bad' },
            el('span', { class: 'gap-n', text: String(counts.bad || 0) }),
            el('span', { class: 'gap-k', text: 'found' })),
          el('div', { class: 'gap-half unknown' },
            el('span', { class: 'gap-n', text: String(counts.unknown || 0) }),
            el('span', { class: 'gap-k', text: 'cannot tell' }))),
        el('span', { class: 'gap-label', text: label || name })));
  }

  function drawCounts(page, summary) {
    const target = $('[data-gaps-counts]', page);
    if (!target) return;
    const order = summary.signal_order || [];
    const labels = summary.signal_labels || {};
    const counts = summary.signals || {};
    replace(target, order.map((name) =>
      signalTile(name, labels[name], counts[name] || {})));
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
      el('a', { class: 'linky', href: `#node/${row.node_id}`, text: 'Open this node' }),
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
    const columns = [
      {
        label: 'Node',
        cell: (row) => el('span', {}, nodeChip(row)),
      },
      { label: 'Role', cell: (row) => row.role },
      ...order.map((name) => ({
        label: labels[name] || name,
        cell: (row) => chip((row.signals || {})[name]),
      })),
      { label: 'Packets', num: true, cell: (row) => row.packets },
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
      const toggle = () => {
        const open = tr.getAttribute('aria-expanded') === 'true';
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
        .bindTooltip(`${row.display_name}: ${bad ? 'a fault we can measure' : 'not enough evidence'}`)
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
      replace($('[data-gaps-table]', page), empty('Nothing measured yet.'));
      replace($('[data-gaps-unknown-table]', page), empty('Nothing measured yet.'));
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

    /*
     * Two tables, on purpose.
     *
     * A node with a fault we can measure and a node we cannot measure at
     * all are different answers, and a single list sorted by severity
     * hides the second behind the first. The unknown bucket gets its own
     * section with its own count, not a filter a reader has to find.
     */
    const faulty = rows.filter((row) => row.bad_count > 0);
    const unmeasured = rows.filter((row) => row.bad_count === 0 && row.unknown_count > 0);

    const heading = $('[data-gaps-table-heading]', page);
    if (heading) {
      heading.textContent = `Nodes with something we can measure: ${faulty.length}`;
    }
    const unknownHeading = $('[data-gaps-unknown-heading]', page);
    if (unknownHeading) {
      unknownHeading.textContent = `Not enough evidence: ${unmeasured.length} nodes`;
    }

    drawTable($('[data-gaps-table]', page), faulty, summary,
      'No node on this preset shows a fault this can measure.');
    drawTable($('[data-gaps-unknown-table]', page), unmeasured, summary,
      'Every assessed node had enough evidence to judge.');

    drawMap(rows);

    if (!state.loaded) {
      const picker = $('[data-gaps-preset]', page);
      if (picker) {
        picker.addEventListener('change', () => {
          state.preset = picker.value;
          show(page);
        });
      }
      state.loaded = true;
    }
  }

  window.SonoranGaps = { show, state };
}());
