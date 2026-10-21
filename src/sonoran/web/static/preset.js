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
 * Several at once (#383). A reader may choose more than one preset, in
 * the Settings page. The list pages (dashboard, nodes, chat, firehose,
 * the packet types on statistics) send every chosen name as one
 * `preset=MediumFast,LongFast`. A page that can only draw ONE preset --
 * the map and the graph, which draw links (AGENTS.md 9.7), coverage,
 * gaps, the planner and the leaderboards -- asks `single()` and says
 * under the switch which one it drew. `current()` gives that same one
 * preset, so a caller that only knows one name keeps working.
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

  /*
   * Every modem preset the firmware can run, so every one is a choice
   * even before the server has heard traffic on it (#383).
   *
   * The names are the channel names firmware gives each preset
   * (`DisplayFormatters::getModemPresetDisplayName`, firmware v2.8.1),
   * which are what the API matches. Note `LongMod`, not `LongModerate`.
   * The list and its order are those of `KNOWN` in
   * `sonoran/radio/presets.py`, shortest range first;
   * `tests/unit/test_preset_choices.py` keeps the two the same. The
   * enum is `Config.LoRaConfig.ModemPreset` in the protobufs.
   */
  const STANDARD = [
    'ShortTurbo', 'ShortFast', 'MediumTurbo', 'ShortSlow', 'MediumFast', 'NarrowFast',
    'LongTurbo', 'MediumSlow', 'LiteFast', 'NarrowSlow', 'LongFast', 'LiteSlow',
    'TinyFast', 'LongMod', 'TinySlow', 'LongSlow', 'VeryLongSlow',
  ];

  /* A preset name never holds a comma, so a choice of several is stored
     as one string with commas between the names. An old stored value,
     one name or '*', is read the same way and still loads. */
  const SEPARATOR = ',';

  /*
   * Every preset at once (Logan, 2026-10-12: "we are not unified quite
   * yet", so the whole state has to be visible in one view).
   *
   * Not a preset name: `menuPreset()` in app.js turns it into no filter
   * at all, and a page that can only draw one preset (coverage, gaps,
   * the planner, the leaderboards) asks `single()` instead and says so
   * under the switch. '*' cannot be a channel name the server sends.
   */
  const ALL = '*';

  /* The server's list first, in its order, then every other preset. */
  function withStandard(names) {
    return [...new Set([...names, ...STANDARD])];
  }

  let available = withStandard(FALLBACK);
  // null, or ALL, or a list of one or more names on offer.
  let chosen = null;
  const listeners = new Set();
  // Told when the list on offer changes, even when the chosen preset
  // does not. The menu's switch needs it; a page does not.
  const listListeners = new Set();

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

  /*
   * A stored or a passed value, as a choice: ALL, or the names in it
   * that are on offer, in the order of the list on offer. Null when
   * nothing in it is usable.
   */
  function parse(value) {
    if (value === ALL) return ALL;
    const names = Array.isArray(value) ? value : String(value ?? '').split(SEPARATOR);
    const wanted = new Set(names.map((name) => String(name ?? '').trim()).filter(Boolean));
    const usable = available.filter((name) => wanted.has(name));
    return usable.length ? usable : null;
  }

  /** The default choice: the deployment's preset, alone. */
  function defaultChoice() {
    const preferred = fallbackPreset();
    return [available.includes(preferred) ? preferred : available[0]];
  }

  /**
   * The choice in force: ALL, or a list of one or more names.
   *
   * A stored value is only honoured when it is still on offer. Otherwise
   * a hand-edited value would pin the whole site to a preset no control
   * offers, and the reader would have no way to tell why every page was
   * empty. Every firmware preset is always on offer (#383), so this now
   * refuses only names that are not presets at all.
   */
  function choice() {
    const held = chosen === null ? null : parse(chosen);
    if (held) return held;
    const saved = parse(stored());
    if (saved) {
      chosen = saved;
      return saved;
    }
    return defaultChoice();
  }

  /** Every preset chosen, in menu order, or [ALL]. */
  function selected() {
    const held = choice();
    return held === ALL ? [ALL] : [...held];
  }

  /** True when the reader asked for every preset at once. */
  function isAll() {
    return choice() === ALL;
  }

  /** True when the reader chose two or more presets, but not all. */
  function isSeveral() {
    const held = choice();
    return held !== ALL && held.length > 1;
  }

  /**
   * One real preset, for a page that cannot draw them all together.
   *
   * The choice in force when it is one preset. Under "All", or with
   * several chosen, the deployment's default when it is among them, and
   * otherwise the first chosen. So a coverage map, a gaps list or the
   * map's links never mix presets that cannot hear each other
   * (AGENTS.md 9.7).
   */
  function single() {
    const held = choice();
    const preferred = fallbackPreset();
    if (held === ALL) return available.includes(preferred) ? preferred : available[0];
    return held.includes(preferred) ? preferred : held[0];
  }

  /**
   * The preset in force, as one name: ALL, or a real preset.
   *
   * With several chosen it is `single()`, so a caller that knows one
   * name only draws one preset and never a mix.
   */
  function current() {
    return isAll() ? ALL : single();
  }

  /**
   * The value of `preset=` for the API: '' for every preset, otherwise
   * every chosen name with commas between them.
   */
  function query() {
    const held = choice();
    return held === ALL ? '' : held.join(SEPARATOR);
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
    const given = [...new Set((list || []).filter((name) => typeof name === 'string' && name))];
    if (!given.length) return false;
    const names = withStandard(given);
    const before = query();
    // Compared without order: the channel list sorts by traffic, so the
    // same presets often come back in a new order, and a redraw then
    // would take keyboard focus off the switch for nothing.
    const listed = [...available].sort().join('|') !== [...names].sort().join('|');
    available = names;
    const after = query();
    // Announce only a real change: the reader's preset can move here if
    // the one they had chosen is no longer on offer.
    if (after !== before) announce(current());
    // A longer list with the same choice redraws only the switch. Before
    // this, a third preset showed in the menu only after some later
    // change of preset happened to redraw it.
    else if (listed) {
      for (const listener of [...listListeners]) {
        try {
          listener(options());
        } catch (error) {
          if (window.console) window.console.warn('preset list listener failed', error);
        }
      }
    }
    return after !== before;
  }

  /** Choose one preset alone, or ALL. Returns true when it changed. */
  function set(name) {
    if (typeof name !== 'string' || (name !== ALL && !available.includes(name))) return false;
    return setMany(name === ALL ? ALL : [name]);
  }

  /**
   * Choose several presets at once, or ALL. Returns true when it changed.
   *
   * An empty list is refused: no preset at all is a site with nothing on
   * any page, which no reader means. A name not on offer is refused, and
   * so is the whole list with it, rather than kept in part.
   */
  function setMany(list) {
    let next;
    if (list === ALL) {
      next = ALL;
    } else {
      if (!Array.isArray(list) || !list.length) return false;
      if (list.some((name) => typeof name !== 'string' || !available.includes(name))) return false;
      next = parse(list);
    }
    const value = next === ALL ? ALL : next.join(SEPARATOR);
    if (value === (isAll() ? ALL : query())) return false;
    chosen = next;
    remember(value);
    announce(current());
    return true;
  }

  /**
   * Add a preset to the choice, or take it out. Returns true when it
   * changed. Taking out the last one is refused. Under "All", taking
   * one out leaves every other preset on offer.
   */
  function toggle(name) {
    if (!available.includes(name)) return false;
    const now = isAll() ? [...available] : selected();
    const next = now.includes(name) ? now.filter((item) => item !== name) : [...now, name];
    return setMany(next);
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
      const before = isAll() ? ALL : query();
      chosen = null;
      const after = isAll() ? ALL : query();
      if (after !== before) announce(current());
    });
  }

  /** Run `fn` whenever the preset changes. Returns an unsubscribe. */
  function onChange(fn) {
    if (typeof fn !== 'function') return () => {};
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  /** Run `fn` whenever the list on offer changes. Returns an unsubscribe. */
  function onOptionsChange(fn) {
    if (typeof fn !== 'function') return () => {};
    listListeners.add(fn);
    return () => listListeners.delete(fn);
  }

  /**
   * True when `name` is the preset in force.
   *
   * A helper rather than `=== current()` at the call sites, because
   * channel names arrive in several spellings and a comparison that
   * misses reads as "hide everything".
   */
  function matches(name) {
    return isAll() || selected().includes(String(name ?? ''));
  }

  return {
    current, options, setAvailable, set, setMany, toggle, onChange, onOptionsChange, matches,
    isAll, isSeveral, single, selected, query, ALL, FALLBACK, STANDARD,
  };
}());
