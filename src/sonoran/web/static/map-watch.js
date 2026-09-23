/*
 * Watch mode: the map, fullscreen, with one tabbed overlay.
 *
 * "Basically create a full screen view where someone can sit and watch
 * the mesh as it's happening." The animation is the subject and this file
 * is only the frame around it, so it does as little as it can: it moves
 * existing DOM, it does not build a second copy of it.
 *
 * Two decisions in here are worth the words.
 *
 * The Fullscreen API first, a CSS class second. The API hides the
 * browser's own chrome, which is the whole point of sitting and
 * watching, and CSS cannot. It also gives one place to sync state, so a
 * viewer who leaves fullscreen by a route the page did not initiate is
 * still handled. The fallback is mandatory because iOS Safari does not
 * grant `requestFullscreen` on an arbitrary element. Both paths end with
 * the same class on the same element, so there is one set of CSS rules.
 *
 * Tabs, not two panels. A traceroute arrives about 1.25 times a minute,
 * so a permanently visible traceroute panel is empty most of the time and
 * a region of the screen that is usually empty trains the eye to stop
 * looking at it. A badge on the inactive tab does the opposite, and it
 * costs a tenth of the screen.
 *
 * Watch mode is not a page. It is a state of the map, kept in the URL
 * fragment, which is where this dashboard keeps state on purpose: a
 * `Referer` never carries a fragment, so the state persists across a
 * reload and is shareable and leaks nothing. See AGENTS.md 9.9.1.
 */

'use strict';

const SonoranWatch = (() => {
  /* Three discrete heights, in this order. No free drag: it is fiddly
   * with a mouse, hostile with a finger, and creates a persistence
   * question that three words in the fragment answer instead. */
  const HEIGHTS = ['peek', 'normal', 'expanded'];
  const TABS = ['traffic', 'traces'];

  let ctx = null;
  let on = false;
  let height = 'normal';
  let tab = 'traffic';
  let legendOpen = false;
  let control = null;
  let watchButton = null;
  let fallback = false;
  const unread = { traffic: 0, traces: 0 };
  /* Where each moved element came from, so exit puts it back exactly. */
  const homes = new Map();

  const $ = (selector, root = document) => root.querySelector(selector);

  /** Remember where an element lives, then move it somewhere else. */
  function moveInto(element, target) {
    if (!element || !target) return;
    if (!homes.has(element)) {
      const anchor = document.createComment('watch-mode placeholder');
      element.parentNode.insertBefore(anchor, element);
      homes.set(element, anchor);
    }
    target.append(element);
  }

  /** Put an element back where it was before watch mode moved it. */
  function moveHome(element) {
    const anchor = homes.get(element);
    if (!anchor || !anchor.parentNode) return;
    anchor.parentNode.insertBefore(element, anchor);
    anchor.remove();
    homes.delete(element);
  }

  /* --- Fragment ------------------------------------------------- */

  /*
   * `#map/watch/<tab>/<height>`. Read loosely, because a hand-edited or
   * older link must not break the page: an unknown word is ignored and
   * the default stands.
   */
  function readFragment() {
    const parts = (location.hash.slice(1) || '').split('/');
    if (parts[0] !== 'map') return null;
    const wanted = { watch: parts[1] === 'watch', tab: null, height: null };
    for (const part of parts.slice(2)) {
      if (TABS.includes(part)) wanted.tab = part;
      if (HEIGHTS.includes(part)) wanted.height = part;
    }
    return wanted;
  }

  function writeFragment() {
    const parts = on ? ['map', 'watch', tab, height] : ['map'];
    const next = parts.join('/');
    if (location.hash.slice(1) === next) return;
    if (ctx && ctx.writeFragment) ctx.writeFragment(next);
    else location.hash = next;
  }

  /* --- Entry and exit ------------------------------------------- */

  function syncControl() {
    if (!control) return;
    const button = control.getContainer().firstChild;
    button.setAttribute('aria-pressed', String(on));
    /*
     * The accessible name has to move with the title.
     *
     * `aria-label` is set once when the control is built and was never
     * updated here, so in watch mode the tooltip read "Leave watch
     * mode" while a screen reader still said "Watch mode" — and
     * `aria-label` wins, so the spoken name was the wrong one in the
     * state where getting out matters. The keystroke stays out of the
     * name: "(F)" is of no use to a finger and a screen reader reads it
     * aloud on every pass.
     */
    const label = on ? 'Leave watch mode' : 'Watch mode';
    button.title = `${label} (F)`;
    button.setAttribute('aria-label', label);
    $('use', button).setAttribute('href', on ? '#i-fullscreen-exit' : '#i-fullscreen');
  }

  /**
   * Show the chrome and move the shared DOM into it.
   *
   * The controls row and the two feed panels are moved rather than
   * copied. A copy would mean two preset pickers and two feed renderers,
   * and the day they disagree is the day a viewer reads the wrong mesh.
   */
  function dress() {
    const { shell, page } = ctx;
    for (const name of ['bar', 'panel']) {
      $(`[data-watch-${name}]`, shell).hidden = false;
    }
    moveInto($('.controls', page), $('[data-watch-bar]', shell));
    for (const name of TABS) {
      moveInto($(`[data-map-panel="${name}"]`, page), $(`[data-watch-pane="${name}"]`, shell));
    }
    /*
     * Leaflet's zoom buttons move to the right.
     *
     * The panel is a left-hand overlay at every height, and at the
     * expanded height it reaches the top of the map, so a top-left zoom
     * control ends up sitting on the panel's own tab strip.
     */
    if (ctx.map.zoomControl) ctx.map.zoomControl.setPosition('topright');
    shell.classList.add('watch');
    applyTab();
    applyHeight();
    measureBar();
  }

  function undress() {
    const { shell, page } = ctx;
    for (const name of ['bar', 'panel', 'legend']) {
      $(`[data-watch-${name}]`, shell).hidden = true;
    }
    legendOpen = false;
    for (const name of TABS) moveHome($(`[data-map-panel="${name}"]`, page));
    moveHome($('.controls', page));
    if (ctx.map.zoomControl) ctx.map.zoomControl.setPosition('topleft');
    shell.classList.remove('watch');
    document.body.classList.remove('watch-mode');
    measureBar();
    for (const name of TABS) {
      const panel = $(`[data-map-panel="${name}"]`, page);
      if (panel) panel.hidden = false;
    }
  }

  /** Resize Leaflet after the shell has changed size, not before. */
  function settle() {
    if (ctx && ctx.onResize) ctx.onResize();
  }

  /*
   * Publish the top strip's real height as a custom property.
   *
   * The strip holds the status and the whole controls row, so it wraps to
   * two lines on a narrow window and to one on a wide one. Anything that
   * must sit below it — Leaflet's own zoom control, and the expanded
   * panel — needs the measured height rather than a guess, or the guess
   * is wrong at exactly the widths where the screen is tightest.
   */
  function measureBar() {
    if (!ctx) return;
    const bar = $('[data-watch-bar]', ctx.shell);
    const pixels = on && !bar.hidden ? bar.offsetHeight : 0;
    ctx.shell.style.setProperty('--watch-bar-h', `${pixels}px`);
  }

  async function enter() {
    if (on) return;
    on = true;
    dress();
    /*
     * A button click is a user gesture, so the permission model costs
     * nothing here. The element is fullscreened in place: re-parenting a
     * Leaflet container forces a resize dance, and there is no reason to.
     */
    fallback = false;
    const shell = ctx.shell;
    try {
      if (shell.requestFullscreen) await shell.requestFullscreen({ navigationUI: 'hide' });
      else if (shell.webkitRequestFullscreen) shell.webkitRequestFullscreen();
      else throw new Error('no fullscreen');
    } catch {
      // iOS Safari, and anything that refuses. The class does
      // `position: fixed; inset: 0` on the same element, so every other
      // rule in app.css applies unchanged.
      fallback = true;
      document.body.classList.add('watch-mode');
    }
    syncControl();
    writeFragment();
    settle();
    // The fallback grows the shell over a transition, so one more resize
    // after it lands. Fullscreen fires `fullscreenchange`, which does
    // the same thing by its own route.
    setTimeout(settle, 260);
  }

  async function leave() {
    if (!on) return;
    on = false;
    /*
     * Space is a watch-mode key, so a viewer who paused and then left
     * would have no way to start the world again and a map that had
     * stopped for no reason they could see. Leaving resumes.
     */
    if (ctx && ctx.onLeavePaused) ctx.onLeavePaused();
    if (!fallback && document.fullscreenElement) {
      try {
        await document.exitFullscreen();
      } catch {
        /* Already out, by Escape or by the browser. Nothing to undo. */
      }
    }
    undress();
    syncControl();
    writeFragment();
    settle();
    setTimeout(settle, 260);
    /*
     * Put focus back on the control that started this.
     *
     * Exiting used to leave it on the map div, which is not
     * interactive: a keyboard user pressed F, watch mode ended, and
     * their focus was somewhere they could not act from (WCAG 2.4.3).
     * `undress()` moves elements back to where they came from, so this
     * runs after it, and after the settle that follows.
     */
    if (watchButton && watchButton.isConnected) watchButton.focus();
  }

  const toggle = () => (on ? leave() : enter());

  /* --- Tabs and heights ---------------------------------------- */

  function applyTab() {
    const shell = ctx.shell;
    for (const name of TABS) {
      const selected = name === tab;
      const button = $(`[data-watch-tab="${name}"]`, shell);
      button.setAttribute('aria-selected', String(selected));
      $(`[data-watch-pane="${name}"]`, shell).hidden = !selected;
      if (selected) {
        unread[name] = 0;
        const badge = $(`[data-watch-badge="${name}"]`, shell);
        badge.hidden = true;
        badge.textContent = '';
      }
    }
    if (ctx.onTabChange) ctx.onTabChange(tab);
  }

  function applyHeight() {
    $('[data-watch-panel]', ctx.shell).dataset.height = height;
    if (ctx.onHeightChange) ctx.onHeightChange(height);
  }

  function setTab(name) {
    if (!TABS.includes(name) || name === tab) return;
    tab = name;
    applyTab();
    writeFragment();
  }

  function setHeight(name) {
    if (!HEIGHTS.includes(name) || name === height) return;
    height = name;
    applyHeight();
    writeFragment();
  }

  function stepHeight() {
    setHeight(HEIGHTS[(HEIGHTS.indexOf(height) + 1) % HEIGHTS.length]);
  }

  /**
   * Count something that arrived on the tab nobody is looking at.
   *
   * The badge is what side by side was actually trying to buy. It goes
   * away when the tab is opened, never on a timer, so nothing is missed
   * by looking away.
   */
  function bump(name, howMany) {
    if (!on || !howMany || name === tab || !TABS.includes(name)) return;
    unread[name] += howMany;
    const badge = $(`[data-watch-badge="${name}"]`, ctx.shell);
    badge.hidden = false;
    badge.textContent = String(unread[name] > 99 ? '99+' : unread[name]);
  }

  /* --- The status line ------------------------------------------ */

  /**
   * Write the four things that may never leave the screen.
   *
   * `preset` and `scope` say which mesh this is: one preset per picture,
   * and in fullscreen there is no page head to say which (AGENTS.md 9.7).
   * `counter` is the honesty count. `lag` says the replay runs behind
   * live, because presenting a replay as instantaneous would be the one
   * lie this whole feature could tell without being caught.
   */
  function status(fields) {
    if (!ctx) return;
    const shell = ctx.shell;
    for (const [key, value] of Object.entries(fields)) {
      const target = $(`[data-watch-${key}]`, shell);
      if (target) target.textContent = value == null ? '' : value;
    }
  }

  function ticker(text) {
    if (!ctx) return;
    const target = $('[data-watch-ticker]', ctx.shell);
    if (target) target.textContent = text || '';
  }

  /* --- The legend ---------------------------------------------- */

  function toggleLegend(force) {
    if (!ctx) return;
    const target = $('[data-watch-legend]', ctx.shell);
    legendOpen = force == null ? !legendOpen : force;
    target.hidden = !(on && legendOpen);
    if (target.hidden || target.childElementCount) return;
    if (ctx.legend) ctx.legend(target);
  }

  /* --- Wiring -------------------------------------------------- */

  function wireGrip(shell) {
    /*
     * The drag handle snaps. It is the third way into the height, after
     * the button and the E key, because this is the control the owner
     * named: "It'd be cool if we could expand those boxes as well."
     * Dragging picks the nearest snap on release, so there is nothing
     * in between to store or to restore after a resize.
     */
    const grip = $('[data-watch-grip]', shell);
    let startY = null;
    let startIndex = 0;
    grip.addEventListener('pointerdown', (event) => {
      startY = event.clientY;
      startIndex = HEIGHTS.indexOf(height);
      grip.setPointerCapture(event.pointerId);
    });
    grip.addEventListener('pointermove', (event) => {
      if (startY == null) return;
      // Up is taller. One snap per 70 px of travel.
      const steps = Math.round((startY - event.clientY) / 70);
      const wanted = Math.max(0, Math.min(HEIGHTS.length - 1, startIndex + steps));
      setHeight(HEIGHTS[wanted]);
    });
    const done = (event) => {
      if (startY == null) return;
      startY = null;
      if (grip.hasPointerCapture(event.pointerId)) grip.releasePointerCapture(event.pointerId);
    };
    grip.addEventListener('pointerup', done);
    grip.addEventListener('pointercancel', done);
  }

  /**
   * Install the control and the handlers.
   *
   * `ctx.writeFragment` lets the caller change the hash without a
   * refetch: a tab switch must not cost a request.
   */
  function install(context) {
    ctx = context;
    const { map, shell } = ctx;

    /*
     * Bottom right, which is where the owner asked for it, and inside the
     * map rather than in the page chrome that watch mode hides.
     */
    const Watch = L.Control.extend({
      options: { position: 'bottomright' },
      onAdd() {
        const wrap = L.DomUtil.create('div', 'leaflet-bar watch-control');
        /*
         * A real button, not an anchor wearing `role="button"`.
         *
         * An element with that role must respond to Space as well as
         * Enter (WCAG 4.1.2), and a native `<a href>` never does.
         * Measured before this change: Enter toggled watch mode, Space
         * did nothing at all. A `<button>` gets both keys, the right
         * role and the disabled semantics for free, and none of it can
         * drift.
         */
        const button = L.DomUtil.create('button', '', wrap);
        button.type = 'button';
        button.setAttribute('aria-pressed', 'false');
        button.title = 'Watch mode (F)';
        button.setAttribute('aria-label', 'Watch mode');
        const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        icon.setAttribute('class', 'icon');
        icon.setAttribute('aria-hidden', 'true');
        const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        use.setAttribute('href', '#i-fullscreen');
        icon.append(use);
        button.append(icon);
        L.DomEvent.disableClickPropagation(wrap);
        L.DomEvent.on(button, 'click', (event) => {
          L.DomEvent.preventDefault(event);
          toggle();
        });
        // Where focus goes when watch mode ends. Leaving it on the map
        // div strands a keyboard user somewhere they cannot act from
        // (WCAG 2.4.3); `app.js` already does this for the nav toggle.
        watchButton = button;
        return wrap;
      },
    });
    control = new Watch();
    control.addTo(map);

    for (const name of TABS) {
      $(`[data-watch-tab="${name}"]`, shell).addEventListener('click', () => setTab(name));
    }
    $('[data-watch-step]', shell).addEventListener('click', stepHeight);
    wireGrip(shell);
    // The strip wraps with the window, so its height is watched rather
    // than measured once. A ResizeObserver costs no timer.
    if (window.ResizeObserver) {
      new ResizeObserver(measureBar).observe($('[data-watch-bar]', shell));
    }

    /*
     * One place to learn that fullscreen ended, including Escape and
     * every route the page did not initiate. Without this the chrome
     * would stay dressed over a map that is no longer fullscreen.
     */
    document.addEventListener('fullscreenchange', () => {
      if (!document.fullscreenElement && on && !fallback) leave();
      settle();
    });

    /*
     * Active only on the map page, and never while a control has focus,
     * so typing a node name into a search box does not toggle fullscreen.
     */
    document.addEventListener('keydown', (event) => {
      if (!ctx.isMapActive()) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const node = document.activeElement;
      const tagName = node && node.tagName;
      if (tagName === 'INPUT' || tagName === 'SELECT' || tagName === 'TEXTAREA') return;
      const key = event.key;
      if (key === 'f' || key === 'F') { event.preventDefault(); toggle(); return; }
      if (!on) return;
      if (key === 'Escape' && fallback) { event.preventDefault(); leave(); return; }
      if (key === 't' || key === 'T') { event.preventDefault(); setTab(tab === 'traffic' ? 'traces' : 'traffic'); return; }
      if (key === '1') { event.preventDefault(); setTab('traffic'); return; }
      if (key === '2') { event.preventDefault(); setTab('traces'); return; }
      if (key === 'e' || key === 'E') { event.preventDefault(); stepHeight(); return; }
      /*
       * Space is worth more than it looks. A viewer watching a burst
       * wants to stop it and read what just happened, and the panel
       * beside the map is where the exact numbers are. Pausing holds the
       * replay buffer and keeps accumulating, so nothing that arrives
       * while somebody is reading is lost.
       *
       * It only binds inside watch mode. On the ordinary page Space
       * scrolls, and taking that away from a viewer who is reading the
       * feed below the map would be a worse trade than the key is worth.
       */
      if (key === ' ' || key === 'Spacebar') {
        event.preventDefault();
        if (ctx.onPause) ctx.onPause();
        return;
      }
      /*
       * The other half of the choice. Resuming replays from the pause
       * point, which is what a viewer who paused to read something
       * wants; L gives up the backlog and rejoins live, which is what a
       * viewer who paused and walked away wants. Both are offered in
       * words on the status line rather than one being chosen for them.
       */
      if (key === 'l' || key === 'L') {
        event.preventDefault();
        if (ctx.onSkipToLive) ctx.onSkipToLive();
        return;
      }
      if (key === '?') { event.preventDefault(); toggleLegend(); }
    });

    $('[data-watch-legend]', shell).addEventListener('click', () => toggleLegend(false));

    /* A link straight to `#map/watch/...` opens in watch mode. */
    restore();
  }

  /** Bring the state in the fragment into effect. */
  function restore() {
    const wanted = readFragment();
    if (!wanted) return;
    if (wanted.tab) tab = wanted.tab;
    if (wanted.height) height = wanted.height;
    if (wanted.watch && !on) enter();
    else if (!wanted.watch && on) leave();
    else if (on) { applyTab(); applyHeight(); }
  }

  return {
    install,
    restore,
    toggle,
    enter,
    leave,
    bump,
    status,
    ticker,
    setTab,
    setHeight,
    toggleLegend,
    isOn: () => on,
    tab: () => tab,
    height: () => height,
    HEIGHTS,
    TABS,
  };
})();

window.SonoranWatch = SonoranWatch;
