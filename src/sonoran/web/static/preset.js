/*
 * The preset the whole site is looking at.
 *
 * A node on LongFast cannot hear a node on MediumFast (`AGENTS.md` 9.7),
 * so every page that draws links, coverage, gaps or a chat channel has
 * to pick ONE preset. Which messages and packets belong to a preset is
 * the server's answer, from the preset ingest tagged each packet with
 * (#313); this module only holds the reader's choice. Each page used to ask separately: the map had a
 * picker for its link layer, coverage had one, gaps had one, the graph
 * had a tab strip. A reader who had chosen MediumFast on the gaps page
 * then found the map on LongFast, and nothing on the site agreed with
 * anything else.
 *
 * This holds that choice once. `#177` already made the *default* a
 * deployment setting (`SONORAN.defaultPreset`, MediumFast here); this
 * adds the reader's own override on top of it, and keeps it.
 *
 * Deliberately NOT in the address. A preset is a standing preference
 * like the theme, not a property of the page you are linking somebody
 * to -- putting it in every URL would make two people's links differ for
 * a reason neither of them chose. The planner is the exception and keeps
 * its own preset in its share link, because there the preset is an input
 * to a prediction rather than a view of what already happened.
 */
window.SonoranPreset = (function build() {
  const KEY = 'sonoran.preset';

  /*
   * The two this mesh runs, in the order the menu shows them.
   *
   * A starting point, not a limit: `setAvailable` replaces this once the
   * channel list arrives, so a deployment running something else is not
   * stuck with our two. It exists at all because the menu has to be
   * usable before any request finishes.
   */
  const FALLBACK = ['MediumFast', 'LongFast'];

  let available = [...FALLBACK];
  let chosen = null;
  const listeners = new Set();

  /** The deployment's default, which the reader's choice overrides. */
  function fallbackPreset() {
    const configured = (window.SONORAN && window.SONORAN.defaultPreset) || '';
    return configured || FALLBACK[0];
  }

  /*
   * Storage that cannot break the page.
   *
   * Every read and write is wrapped: in a private window, with site data
   * blocked, or during a thumbnail capture, both the accessor and the
   * assignment can throw. A preset preference is a convenience, so
   * losing it has to cost nothing.
   */
  function stored() {
    try {
      return window.localStorage.getItem(KEY);
    } catch {
      return null;
    }
  }

  function remember(value) {
    try {
      window.localStorage.setItem(KEY, value);
    } catch {
      /* A reader whose browser forbids this still gets the choice for
         this visit; it simply does not survive a reload. */
    }
  }

  /**
   * The preset in force.
   *
   * A stored value is only honoured when it is still one of the presets
   * on offer. Otherwise a name that was valid once -- a deployment that
   * stopped running ShortTurbo, or a hand-edited value -- would pin the
   * whole site to a preset with nothing in it, and the reader would have
   * no way to tell why every page was empty.
   */
  function current() {
    if (chosen && available.includes(chosen)) return chosen;
    const saved = stored();
    if (saved && available.includes(saved)) {
      chosen = saved;
      return chosen;
    }
    const preferred = fallbackPreset();
    return available.includes(preferred) ? preferred : available[0];
  }

  /** The presets to offer, newest list wins. */
  function options() {
    return [...available];
  }

  /**
   * Replace the list of presets on offer.
   *
   * Called once the channel list is known. Keeps the order it is given,
   * because that order comes from the server and already puts the
   * deployment's own preset first.
   */
  function setAvailable(list) {
    const names = [...new Set((list || []).filter((name) => typeof name === 'string' && name))];
    if (!names.length) return false;
    const before = current();
    available = names;
    const after = current();
    // Announce only a real change: the reader's preset can move here if
    // the one they had chosen is no longer on offer.
    if (after !== before) announce(after);
    return after !== before;
  }

  /** Choose a preset. Returns true when it actually changed. */
  function set(name) {
    if (typeof name !== 'string' || !available.includes(name)) return false;
    if (name === current()) return false;
    chosen = name;
    remember(name);
    announce(name);
    return true;
  }

  function announce(name) {
    for (const listener of [...listeners]) {
      /*
       * One bad listener must not stop the others. Half the site
       * following the new preset while the other half keeps the old one
       * is the exact inconsistency this module exists to remove, so a
       * throw is swallowed here rather than allowed to break the loop.
       */
      try {
        listener(name);
      } catch (error) {
        if (window.console) window.console.warn('preset listener failed', error);
      }
    }
  }

  /*
   * Another tab chose a different preset.
   *
   * `storage` fires only in the OTHER tabs, so this is what makes two
   * open tabs agree. It matters more here than for a formatting setting:
   * the preset decides WHICH nodes and which messages a page shows, so
   * two tabs left disagreeing show different data with both switches
   * looking right.
   *
   * `chosen` is set directly rather than through `set`, because `set`
   * would write storage again -- harmless but pointless -- and because a
   * value that is no longer available must not be adopted: `current()`
   * already falls back, and adopting it would strand the reader on a
   * preset no control offers.
   */
  if (window.addEventListener) {
    window.addEventListener('storage', (event) => {
      if (event.key !== null && event.key !== KEY) return;
      const before = current();
      chosen = stored();
      const after = current();
      if (after !== before) announce(after);
    });
  }

  /** Run `fn` whenever the preset changes. Returns an unsubscribe. */
  function onChange(fn) {
    if (typeof fn !== 'function') return () => {};
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  /**
   * True when `name` is the preset in force.
   *
   * A helper rather than `=== current()` at the call sites, because
   * channel names arrive in several spellings and a comparison that
   * misses reads as "hide everything".
   */
  function matches(name) {
    return String(name ?? '') === current();
  }

  return { current, options, setAvailable, set, onChange, matches, FALLBACK };
}());
