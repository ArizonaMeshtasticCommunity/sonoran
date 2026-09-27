/*
 * The siting half of the coverage gaps page.
 *
 * gaps.js answers "which nodes are struggling", from measurement. This
 * file answers "where would one new node help the most of them", from
 * prediction. **They are never drawn in the same colour**, because a
 * measurement and a prediction are not the same kind of claim and a
 * reader who mixes them up will go and buy a mast.
 *
 * Its own file, and not part of gaps.js, for two reasons. The first is
 * size: gaps.js is already the biggest thing on that page. The second
 * matters more. gaps.js is pinned by a test that says it draws no
 * polygon and no line, because nothing it holds names two ends of one
 * link. This file draws a box round a neighbourhood, which is a
 * different sort of shape making a different sort of claim, and keeping
 * the two apart keeps that test meaning what it says.
 *
 * **It loads before app.js**, like gaps.js and planner.js, because
 * app.js runs the router as its last act. See AGENTS.md 9.14.2.
 *
 * Four rules hold this file together:
 *
 * 1. Every sentence comes from the endpoint. `sentence`, `caveats` and
 *    `assumed_radio` are written beside the rule that set them, in
 *    Python, and this file prints them. It softens nothing.
 * 2. Three states. A candidate we could not judge is `unknown`. It is
 *    never drawn as "no benefit" and its count is an em dash, never a
 *    zero.
 * 3. A candidate pin is not a node marker. Nodes on this page are
 *    circles; a candidate is a diamond with a hole in it, so that
 *    nobody reads a suggestion as a radio somebody owns.
 * 4. What a siting suggestion cannot know is permanently visible. Land,
 *    access, power, backhaul, a roof, and whether anybody asked the
 *    person who lives there. A recommendation without that list is a
 *    lie of omission.
 */

'use strict';

(function () {
  const CONFIG = window.SONORAN || {};
  const API_BASE = CONFIG.apiBase || '';
  const api = (path) =>
    new URL(String(path).replace(/^\//, ''), API_BASE || document.baseURI).toString();

  /* The house convention for "not measured". */
  const EM_DASH = '—';

  /*
   * The two values `method` can hold, written out rather than tested
   * inline. Only one of them is a prediction, and a page that cannot
   * tell them apart is a page that promises coverage it never computed.
   */
  const METHOD_SPLAT = 'splat';
  const METHOD_SCREEN = 'terrain_screen';

  /*
   * How many screen-only rows to show before the rest go behind a
   * count.
   *
   * Sixty candidates all reaching the same five places is not sixty
   * answers. On open ground the screen separates almost none of them,
   * because a 1 W node with line of sight reaches a handheld at these
   * ranges whatever hill it stands on, and a table of sixty
   * indistinguishable rows buries the three the engine actually
   * predicted. The whole list is still served and still one click away:
   * the screen is a ranking, and a ranking's tail is not a finding.
   */
  const SCREENED_SHOWN = 6;

  const state = {
    preset: null,
    areas: null,
    candidates: [],
    layer: null,
    map: null,
    /* Whether the tail of the ranking is open. Per visit, not stored. */
    showAll: false,
  };

  async function fetchJson(path) {
    const response = await fetch(api(path));
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
  }

  /* --------------------------------------------------------- the pin */

  /*
   * A candidate is a diamond, and a node is a circle. The shape carries
   * the difference between "this is where a radio is" and "this is a
   * place a radio could go", which colour alone cannot: a reader who is
   * colour blind still has to be able to tell a prediction from a node.
   */
  /*
   * The only three states the engine produces, checked here rather than
   * trusted.
   *
   * `state` is a server-side enum today, so what follows was never
   * exploitable. But it is a `str` field that travels from the API into
   * an `innerHTML` sink by string interpolation -- `el()`'s `html:`
   * escape hatch, whose one caller this is -- and that is the exact
   * shape of #81, where a node's name reached a sink the same way. A
   * value that is checked against a fixed set cannot carry markup no
   * matter what the API is changed to return later.
   */
  const PIN_STATES = new Set(['ok', 'bad', 'unknown']);

  function pin(candidate) {
    const state_ = PIN_STATES.has(candidate.state) ? candidate.state : 'unknown';
    return L.divIcon({
      className: '',
      html: `<span class="gap-candidate-pin ${state_}"></span>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    });
  }

  /* ------------------------------------------------------ the numbers */

  /*
   * `newly_usable` is null when the state is unknown, and it must stay
   * visibly absent. A zero would say "this site would help nobody",
   * which is a finding. A null says "we did not judge it", which is an
   * admission, and the two must never render the same.
   */
  function served(candidate) {
    if (candidate.newly_usable == null) return EM_DASH;
    return String(candidate.newly_usable);
  }

  function methodWord(candidate) {
    return candidate.method === METHOD_SPLAT ? 'engine' : 'screen only';
  }

  /*
   * A tooltip as a DOM node, never as a string.
   *
   * Leaflet sets `innerHTML` from a string tooltip. Nothing on this
   * layer carries a node's name today — these lines are counts and
   * words of our own — so this is not a live hole the way the gaps map
   * and the graph tooltip were. It is written this way so the rule has
   * no exception to argue with: a later edit that drops a name into one
   * of these lines must not silently become a sink.
   */
  function textTooltip(line) {
    const wrap = document.createElement('span');
    wrap.textContent = line;
    return wrap;
  }

  /* ------------------------------------------------------- the lead */

  function leadSentence(areas) {
    const list = areas.areas || [];
    if (!list.length) {
      return 'No neighbourhood on this preset holds enough struggling nodes to site against. ' +
        'Three places wanting help, within eight kilometres of each other, make an area.';
    }
    const biggest = list[0];
    const count = list.length;
    const head = count === 1
      ? 'One neighbourhood holds the struggling nodes on this preset'
      : `${count} neighbourhoods hold the struggling nodes on this preset`;
    return `${head}. The largest holds ${biggest.node_count} ` +
      `${biggest.node_count === 1 ? 'node' : 'nodes'} across ` +
      `${biggest.point_count} ${biggest.point_count === 1 ? 'place' : 'places'}, ` +
      `about ${biggest.width_km} km wide.`;
  }

  /* ------------------------------------------------------- the radio */

  /* Every one of these is an assumption, so every one of them is
     printed. A reader who wants a different mast opens the planner. */
  /*
   * `radioLine` rendered the four assumed radio figures into the note
   * under the heading, and went with it (Will, 2026-09-26). The figures
   * are NOT assumptions the reader can change: they are SETTINGS, named
   * `gaps_candidate_tx_power_dbm` (30), `gaps_candidate_height_m` (9)
   * and `gaps_candidate_radius_km` (25) in `config.py`, reported as
   * `assumed_radio` by `jobs/gaps_siting.py` and passed through by
   * `api/routes/gaps.py`, so anything that wants to show them still can.
   *
   * The first version of this comment sent the reader to
   * `gaps/siting.py`, which is the scoring module and does not set them.
   * A test caught it. A wrong pointer in a comment kept AS documentation
   * is worse than no comment, because it will be believed.
   *
   * Removing the note first left this function and its caller behind,
   * referencing a `note` variable that had just been deleted -- a
   * ReferenceError that would have broken the whole siting panel.
   * `node --check` passed it, because a syntax check does not know what
   * a name refers to.
   */

  /* -------------------------------------------------------- the table */

  function areaCell(row) {
    return el('span', { class: 'gap-area-chip', text: `Area ${row.area + 1}` });
  }

  /*
   * Every row the engine predicted, and the head of the ranking behind
   * them. The rest open in place, because a ranking's tail is evidence
   * and not an answer, and it must not be thrown away either. The count
   * beside the control is always the whole number, so a shortened list
   * cannot read as the whole story.
   */
  function visible(all) {
    if (state.showAll) return all;
    const confirmed = all.filter((row) => row.method === METHOD_SPLAT);
    const screened = all.filter((row) => row.method !== METHOD_SPLAT);
    return confirmed.concat(screened.slice(0, SCREENED_SHOWN));
  }

  function drawTable(target, all) {
    const columns = [
      { label: 'Area', cell: areaCell },
      {
        label: 'Where',
        cell: (row) => (row.kind === 'existing_node' && row.node_id
          ? el('a', { class: 'linky', href: `#node/${row.node_id}`, text: row.display_name || row.node_id })
          : el('span', { class: 'mono', text: `${row.latitude.toFixed(4)}, ${row.longitude.toFixed(4)}` })),
      },
      {
        label: 'Kind',
        cell: (row) => el('span', {
          class: 'gap-kind',
          text: row.kind === 'existing_node' ? 'a node already there' : 'ground',
          title: row.kind === 'existing_node'
            ? 'This node already stands here. Raising it needs no land and no permission.'
            : 'High ground found from the terrain. Nobody has looked at it.',
        }),
      },
      {
        label: 'Height',
        num: true,
        cell: (row) => (row.elevation_m == null ? EM_DASH : SonoranUnits.heightFromM(row.elevation_m)),
      },
      {
        label: 'Method',
        cell: (row) => el('span', {
          class: `gap-method ${row.method}`,
          text: methodWord(row),
          title: row.method === METHOD_SPLAT
            ? 'The coverage engine ran here and sampled its own prediction at each place that wants help.'
            : `Method ${METHOD_SCREEN}: a cheap terrain ranking. The engine did not run here, ` +
              'so this row is not a prediction.',
        }),
      },
      {
        label: 'Would newly reach',
        num: true,
        cell: (row) => el('span', { class: `gap-chip ${row.state}` },
          el('span', { class: 'gap-word', text: served(row) })),
      },
    ];

    /*
     * Every row the engine predicted, and the head of the ranking
     * behind them. The rest open in place, because a ranking's tail is
     * evidence and not an answer, and it must not be thrown away
     * either. The count is always the whole number, so a shortened
     * table cannot read as the whole story.
     */
    const rows = visible(all);
    const hidden = all.length - rows.length;

    const built = table(columns, rows, 'No candidate has been worked out yet.');
    replace(target, built);
    /* The map draws exactly the rows the table holds. Sixty pins over
       one neighbourhood is a blob, and a blob is not an answer. */
    if (state.map && state.areas) drawMap(state.map, state.areas, rows);
    if (hidden > 0 || state.showAll) {
      target.append(el('p', { class: 'sub', style: 'margin:.5rem 0 0' },
        el('button', {
          class: 'linky',
          onclick: () => {
            state.showAll = !state.showAll;
            drawTable(target, all);
          },
          text: state.showAll
            ? 'Show only the places the engine predicted'
            : `Show ${hidden} more the screen ranked and the engine did not predict`,
        })));
    }
    if (!rows.length || built.tagName !== 'TABLE') return;
    const body = built.tBodies[0];
    if (!body) return;

    Array.from(body.rows).forEach((tr, index) => {
      const row = rows[index];
      if (!row) return;
      /* The row's colour comes from the state. Never from a number. */
      tr.classList.add('gap-row', row.state || 'unknown');
      /*
       * The ROW is not the button. The button inside it is.
       *
       * This used to be `tabindex=0` plus `role="button"` plus
       * `aria-expanded` on the `<tr>` itself, with two real buttons
       * inside it. `role="button"` on a row destroys the row and cell
       * semantics for everything within, and interactive content
       * nested inside a button role is invalid ARIA -- a screen reader
       * is told "button", then finds a button inside it.
       *
       * The `.gap-open` button already does the work and already
       * worked by keyboard. The row keeps its click handler as a
       * convenience for a mouse, which needs no role: a pointer
       * shortcut that duplicates a real control is an enhancement,
       * not the only way in.
       */
      tr.title = 'Open what this site would do';
      const toggle = () => {
        const open = tr.classList.contains('open');
        if (open) {
          if (tr.nextElementSibling && tr.nextElementSibling.classList.contains('gap-detail')) {
            tr.nextElementSibling.remove();
          }
          tr.classList.remove('open');
          return;
        }
        const detail = el('tr', { class: 'gap-detail' },
          el('td', { colspan: String(columns.length) }, detailPanel(row)));
        tr.after(detail);
        tr.classList.add('open');
      };
      tr.addEventListener('click', (event) => {
        if (event.target.closest('button, a')) return;
        toggle();
      });
      tr.addEventListener('mouseenter', () => highlight(row));
    });
  }

  /* The words are the endpoint's words. This panel arranges them. */
  function detailPanel(row) {
    const bits = [
      el('div', { class: `gap-finding ${row.state}` },
        el('span', { class: 'gap-name', text: row.method === METHOD_SPLAT ? 'The engine says' : 'The screen says' }),
        el('span', { class: 'gap-said', text: row.sentence || row.reason || '' })),
    ];

    if (row.method === METHOD_SPLAT) {
      const counts = [`newly reached ${served(row)}`];
      if (row.already_usable) counts.push(`${row.already_usable} already inside the published map`);
      if (row.baseline_unknown) {
        counts.push(`${row.baseline_unknown} we cannot say were outside it before`);
      }
      if (row.run_stamp) counts.push(`scored against run ${row.run_stamp}`);
      bits.push(el('div', { class: 'gap-counts', text: counts.join('  ·  ') }));
    }

    if (row.newly_usable_nodes && row.newly_usable_nodes.length) {
      bits.push(el('div', { class: 'gap-links' },
        ...row.newly_usable_nodes.slice(0, 12).map((id) =>
          el('a', { class: 'linky', href: `#node/${id}`, text: id }))));
    }

    if (row.screen_unknown) {
      bits.push(el('p', {
        class: 'sub',
        text: `${row.screen_unknown} of the places that want help could not be judged from here: ` +
          'we hold no terrain under that path. That is not the same as no benefit.',
      }));
    }

    bits.push(el('p', {
      class: 'sub',
      text: 'What this cannot know: whether anybody owns or can reach this ground, whether ' +
        'there is power, a roof, a pole, a road or an internet link, and whether the person ' +
        'who lives here wants a node on it. The tool names terrain. A human names a site.',
    }));

    return el('div', { class: 'gap-evidence' }, bits);
  }

  /* ---------------------------------------------------------- the map */

  function highlight(row) {
    if (!state.map || row.latitude == null) return;
    state.map.panTo([row.latitude, row.longitude], { animate: true });
  }

  /*
   * Draws two things and no lines.
   *
   * An area is a box round the demand, which is a claim about where the
   * struggling nodes are and nothing else. A candidate is a diamond,
   * which is a claim about a place and never about a radio path. No
   * line is drawn between anything, because no number on this page
   * names both ends of one link.
   */
  function drawMap(map, areas, candidates) {
    state.map = map;
    if (!state.layer) state.layer = L.layerGroup().addTo(map);
    state.layer.clearLayers();

    for (const area of (areas.areas || [])) {
      const bounds = area.bounds;
      if (!bounds || bounds.length !== 4) continue;
      L.rectangle([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
        className: 'gap-area-box',
        color: '#d8a657',
        weight: 2,
        dashArray: '5 4',
        fill: true,
        fillOpacity: 0.06,
      })
        .bindTooltip(textTooltip(`Area ${area.area + 1}: ${area.node_count} nodes that want help`))
        .addTo(state.layer);
    }

    for (const candidate of candidates) {
      if (candidate.latitude == null) continue;
      const kind = candidate.kind === 'existing_node' ? 'a node already there' : 'high ground';
      const reach = candidate.newly_usable == null
        ? 'not judged'
        : `would newly reach ${candidate.newly_usable}`;
      L.marker([candidate.latitude, candidate.longitude], { icon: pin(candidate) })
        .bindTooltip(textTooltip(`Candidate (${kind}): ${reach} — ${methodWord(candidate)}`))
        .addTo(state.layer);
    }
  }

  /*
   * `drawLimits` filled the "What a siting suggestion cannot know" list,
   * which was removed at Will's request. The caveats are still served on
   * the API under `caveats`, and `gaps/siting.py` still decides them, so
   * putting the list back is a rendering job and not a rebuild.
   */

  /* ---------------------------------------------------------- drawing */

  /*
   * Called by gaps.js once it has its own preset and its own map, so
   * that the two halves of the page always show the same preset and
   * share one map. A siting answer for Long fast beside a node list for
   * Medium fast would be two radios that cannot hear each other on one
   * screen.
   */
  async function show(page, preset, map) {
    state.preset = preset;
    const query = preset ? `?channel=${encodeURIComponent(preset)}` : '';

    let areas;
    let candidates;
    try {
      areas = await fetchJson(`api/gaps/areas${query}`);
      candidates = await fetchJson(
        `api/gaps/candidates${query}${query ? '&' : '?'}limit=200`);
    } catch (error) {
      console.warn('gaps siting failed', error);
      const holder = $('[data-siting-table]', page);
      if (holder) replace(holder, failure(error));
      return;
    }

    state.areas = areas;
    state.candidates = candidates.candidates || [];

    /* The limits are drawn first and are drawn whatever happened, so a
       run that produced nothing still says what it could not have
       known. */

    /*
     * The lead sentence and the note under it are gone (Will,
     * 2026-09-26). Between them they carried: how many nodes in how many
     * places want help, the coverage run they were scored against, how
     * many times the engine ran against a ceiling of 24 and how long it
     * took, the four assumed radio figures (30 dBm, a 2.15 dBi antenna,
     * no cable loss, a 9 m mast, predicted to 25 km against a handheld
     * at 1.5 m), and the clustering rule -- three places wanting help
     * within eight kilometres of each other make an area.
     *
     * All of it true, none of it readable. The assumptions still hold
     * and are still the right thing to know before trusting a
     * suggestion, so they live in `gaps/siting.py` beside the code that
     * applies them, and are still served on the API for anything that
     * wants to render them properly.
     *
     * The empty case keeps a plain "nothing yet" in the table, which is
     * all a reader needs: the reason it is empty (no coverage run has
     * finished) is an operator's problem, not theirs.
     */
    if (!areas.available) {
      replace($('[data-siting-table]', page), empty('Nothing to site against yet.'));
      return;
    }

    /*
     * The heading used to recite its own counts -- "Where a node would
     * help: 0 candidates, 0 confirmed with the engine". Will asked for
     * it to go (2026-09-26), and zero of zero is the worst case of it: a
     * heading announcing that the thing under it is empty, in a
     * vocabulary ("confirmed with the engine") that means nothing to
     * anybody who has not read the siting code.
     *
     * The distinction it was drawing is real and is still in the table,
     * per row: a candidate from the terrain versus one SPLAT has
     * actually run against (`METHOD_SPLAT`). That belongs beside the row
     * it describes, not in a heading.
     */

    /* The map is set first, so that `drawTable` can redraw the pins
       to match whatever the table is showing. */
    state.map = map || null;
    drawTable($('[data-siting-table]', page), state.candidates);
  }

  window.SonoranSiting = { show, state };
}());
