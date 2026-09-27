/*
 * A node's summary in a sheet at the foot of the screen, on a phone (#281).
 *
 * On a map, a tap on a node opened a Leaflet bubble: 188 x 137 px, over
 * the dots around the one tapped, with a 24 px close button. Below 40rem
 * the same summary opens here instead, in a sheet anchored to the bottom
 * of the screen, and the bubble is left for a mouse.
 *
 * NON-MODAL, which is the point (Material 3 "standard" sheet). There is
 * no backdrop and nothing is blocked: the map above the sheet still pans
 * and zooms, and another dot can be tapped while it is open, which puts
 * that node in the same sheet.
 *
 * Two heights. Peek shows the first three lines of the summary (the
 * name, when it was heard, the role) and its action, "Open node detail".
 * Half shows all of it, and scrolls inside itself past half the screen.
 * The grabber at the top switches between them; it is a button, so it
 * works without a swipe, which is also the gesture a map claims.
 *
 * Back closes it. Opening adds one history entry with the same address,
 * so Back takes the sheet away and leaves the reader on the map, which
 * is what a phone reader expects of anything that covers part of the
 * screen (NN/g, "Bottom sheets"). The close button is 44 px.
 *
 * The sheet is outside the map, so a live refresh that redraws the map
 * cannot take it away. The live map closes it when the node itself goes
 * (`closeIf`), as it does its bubble.
 */
(function nodeSheet() {
  const PHONE = '(max-width: 40rem)';
  // How many lines of the summary the peek height shows, before the action.
  const PEEK_LINES = 3;
  const state = { sheet: null, key: null, pushed: false };

  const wanted = () => Boolean(window.matchMedia && window.matchMedia(PHONE).matches);

  function make() {
    if (state.sheet) return state.sheet;
    const sheet = document.createElement('section');
    sheet.className = 'node-sheet';
    sheet.hidden = true;
    sheet.setAttribute('aria-label', 'Node summary');
    sheet.dataset.state = 'peek';
    const node = (tag, className, attributes = {}) => {
      const made = document.createElement(tag);
      made.className = className;
      for (const [name, value] of Object.entries(attributes)) made.setAttribute(name, value);
      return made;
    };
    const grab = node('button', 'node-sheet-grab', { type: 'button', 'aria-expanded': 'false', 'aria-label': 'Show more' });
    grab.append(node('span', 'node-sheet-grabber', { 'aria-hidden': 'true' }));
    grab.addEventListener('click', () => setHeight(sheet.dataset.state === 'peek' ? 'half' : 'peek'));
    const shut = node('button', 'node-sheet-close', { type: 'button', 'aria-label': 'Close' });
    shut.textContent = '×';
    shut.addEventListener('click', () => close());
    const bar = node('div', 'node-sheet-bar');
    bar.append(grab, shut);
    sheet.append(bar, node('div', 'node-sheet-body'));
    document.body.append(sheet);
    state.sheet = sheet;
    return sheet;
  }

  function setHeight(height) {
    const sheet = state.sheet;
    sheet.dataset.state = height;
    const grab = sheet.querySelector('.node-sheet-grab');
    grab.setAttribute('aria-expanded', String(height === 'half'));
    grab.setAttribute('aria-label', height === 'half' ? 'Show less' : 'Show more');
  }

  /** Put `content` in the sheet, at peek height. `key` names the node. */
  function open(content, key) {
    const sheet = make();
    const body = sheet.querySelector('.node-sheet-body');
    body.replaceChildren(content);
    // The lines past the peek, marked so the CSS can fold them. The
    // action is never folded, wherever it sits.
    const lines = [...(content.children || [])];
    let shown = 0;
    for (const line of lines) {
      const action = line.matches('button, a');
      line.classList.toggle('node-sheet-more', !action && ++shown > PEEK_LINES);
    }
    sheet.querySelector('.node-sheet-grab').hidden = !body.querySelector('.node-sheet-more');
    setHeight('peek');
    sheet.hidden = false;
    state.key = key == null ? null : String(key);
    if (!state.pushed) {
      history.pushState({ sonoranSheet: true }, '');
      state.pushed = true;
    }
  }

  /*
   * Close it. From the close button or Escape this also takes back the
   * history entry that opening added, so Back does not then do nothing.
   * From Back it is already gone, and from a new address it is under the
   * new page's entry, so `popstate` below steps over it later.
   */
  function close({ fromHistory = false } = {}) {
    if (!state.sheet || state.sheet.hidden) return;
    state.sheet.hidden = true;
    state.key = null;
    const pushed = state.pushed;
    state.pushed = false;
    if (pushed && !fromHistory && history.state && history.state.sonoranSheet) history.back();
  }

  window.addEventListener('popstate', (event) => {
    if (state.sheet && !state.sheet.hidden) {
      close({ fromHistory: true });
      return;
    }
    // Back into a sheet's entry after the reader left the map: the sheet
    // is gone, so step over the entry rather than make Back do nothing.
    if (event.state && event.state.sonoranSheet) history.back();
  });
  window.addEventListener('hashchange', () => close({ fromHistory: true }));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close();
  });

  /*
   * Give a Leaflet marker its summary: a bubble for a mouse, the sheet on
   * a phone. `build` makes the summary when it is opened, as the bubble's
   * content always has been (see `test_popups_are_built_on_open.py`).
   *
   * Leaflet 1.9.4's `bindPopup` opens the bubble from the marker's
   * `_openPopup` on click. That one listener is swapped for one that
   * asks first, so `openPopup()` and everything else about the bubble is
   * untouched on a desktop.
   */
  function bind(marker, build, key) {
    marker.bindPopup(build);
    if (typeof marker._openPopup !== 'function') return marker;
    marker.off('click', marker._openPopup, marker);
    marker.on('click', (event) => {
      if (!wanted()) {
        marker._openPopup(event);
        return;
      }
      // The map's own click would close the sheet it just opened.
      L.DomEvent.stopPropagation(event);
      open(build(), key);
      const map = marker._map;
      if (map && !map.__sonoranSheet) {
        map.__sonoranSheet = true;
        // A tap on the map itself, away from any dot, puts the sheet away,
        // as it does a bubble.
        map.on('click', () => close());
      }
    });
    return marker;
  }

  window.SonoranSheet = {
    bind,
    open,
    close,
    /** Close it if it shows this node. */
    closeIf(key) {
      if (state.key != null && state.key === String(key)) close();
    },
    /** The node it shows, or null. */
    current: () => (state.sheet && !state.sheet.hidden ? state.key : null),
  };
})();
