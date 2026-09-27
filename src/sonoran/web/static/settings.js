/*
 * What the reader has chosen about how this site looks and reads.
 *
 * Units, temperature and appearance. `preset.js` holds which mesh they are
 * looking at, which is a different kind of choice -- it changes what the
 * data IS, not how it is written -- so the two stay apart.
 *
 * `localStorage`, not cookies (Will asked for cookies; decided against on
 * 2026-09-26, see docs/design/2026-09-26-ux-overhaul.md §2.3). A cookie is
 * sent on every request, including every map tile, and the server never
 * needs to read any of this: units are converted in the browser and the
 * API keeps its figures in SI. A cookie would be bytes on the wire
 * thousands of times a session for nothing.
 *
 * Every read and write is wrapped. In a private window, with site data
 * blocked, or during a thumbnail capture, both the accessor and the
 * assignment throw -- and a preference that cannot be stored must cost
 * nothing more than not being remembered.
 */
window.SonoranSettings = (function build() {
  const KEY = 'sonoran.settings';

  /*
   * The theme keeps its OWN key, and that is deliberate.
   *
   * `index.html` applies the theme in a tiny script BEFORE paint, reading
   * `localStorage.getItem('sonoran.theme')` directly, so the page does not
   * flash the wrong colours on every load. Two things follow:
   *
   * 1. moving the theme into this module's JSON blob would mean that boot
   *    script parsing JSON before paint, or the flash coming back;
   * 2. every reader who has already chosen light or dark has it stored
   *    under that key, and a move would silently reset all of them.
   *
   * So this module OWNS the theme as a setting -- the settings page reads
   * and writes it here -- while the value itself stays where the boot
   * script can find it. One value, one storage location, two readers.
   */
  const THEME_KEY = 'sonoran.theme';

  /*
   * Each setting, its allowed values, and its default.
   *
   * Declared as data rather than as three getters, because every rule
   * below -- validation, the defaults, what `set` accepts -- then has one
   * place to read. A stored value outside `values` is ignored, which is
   * what stops a hand-edited or stale entry putting the site in a state
   * no control can reach.
   *
   * `units` defaults to imperial: this mesh is in Arizona and Will asked
   * for miles and feet. It is a default, not an assumption about the
   * reader -- the control is two taps from every page.
   */
  const FIELDS = {
    units: { values: ['imperial', 'metric'], fallback: 'imperial' },
    temperature: { values: ['fahrenheit', 'celsius'], fallback: 'fahrenheit' },
    /*
     * `system` must stay reachable and stay the default. A reader who has
     * told their operating system they want light should not have to say
     * it again here, and a two-value toggle would lose that.
     */
    theme: { values: ['system', 'light', 'dark'], fallback: 'system' },
  };

  const listeners = new Set();
  let cache = null;

  function storedTheme() {
    try {
      return window.localStorage.getItem(THEME_KEY);
    } catch {
      return null;
    }
  }

  function rememberTheme(value) {
    try {
      window.localStorage.setItem(THEME_KEY, value);
      return true;
    } catch {
      return false;
    }
  }

  function stored() {
    try {
      const text = window.localStorage.getItem(KEY);
      if (!text) return {};
      const parsed = JSON.parse(text);
      // A stored value that is not an object at all -- `null`, a string, an
      // array -- would otherwise throw on property access below.
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch {
      /* Unreadable or unparseable. Defaults, rather than a broken page. */
      return {};
    }
  }

  function remember(all) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(all));
    } catch {
      /* The choice still holds for this visit; it will not survive a
         reload. That is the whole cost, and it is the right one. */
    }
  }

  /** Every setting, with anything invalid or missing replaced. */
  function all() {
    if (cache) return { ...cache };
    const saved = stored();
    const out = {};
    for (const [name, field] of Object.entries(FIELDS)) {
      const value = name === 'theme' ? storedTheme() : saved[name];
      out[name] = field.values.includes(value) ? value : field.fallback;
    }
    cache = out;
    return { ...out };
  }

  /** One setting. */
  function get(name) {
    return all()[name];
  }

  /**
   * Change one setting. Returns true when it actually changed.
   *
   * An unknown name or an unknown value is refused rather than stored.
   * Storing it would put the site in a state the controls cannot show and
   * the reader cannot undo.
   */
  function set(name, value) {
    const field = FIELDS[name];
    if (!field || !field.values.includes(value)) return false;
    const current = all();
    if (current[name] === value) return false;
    cache = { ...current, [name]: value };
    if (name === 'theme') {
      rememberTheme(value);
    } else {
      // The theme is excluded from the blob so the two cannot disagree
      // about one value.
      const { theme, ...rest } = cache;
      remember(rest);
    }
    announce(name, value);
    return true;
  }

  /** The values a setting accepts, in the order a control should show. */
  function options(name) {
    const field = FIELDS[name];
    return field ? [...field.values] : [];
  }

  function announce(name, value) {
    for (const listener of [...listeners]) {
      /*
       * One throwing listener must not stop the others. Half the page in
       * miles and half in kilometres is worse than either.
       */
      try {
        listener(name, value);
      } catch (error) {
        if (window.console) window.console.warn('settings listener failed', error);
      }
    }
  }

  /** Run `fn(name, value)` on every change. Returns an unsubscribe. */
  function onChange(fn) {
    if (typeof fn !== 'function') return () => {};
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  /*
   * Another tab changed a setting.
   *
   * `storage` fires in every OTHER tab on the same origin, never in the
   * one that wrote, so this is the only way two open tabs agree. Without
   * it, a reader who switches to miles in one tab and returns to another
   * finds kilometres, with no control on screen disagreeing with what
   * they see -- which reads as the setting not having worked.
   *
   * The cache is dropped rather than patched: `all()` re-reads and
   * re-validates, so a hand-edited or partly-written value lands on the
   * fallback here exactly as it would on a fresh load.
   */
  if (window.addEventListener) {
    window.addEventListener('storage', (event) => {
      // A null key is localStorage.clear(); both our keys matter.
      if (event.key !== null && event.key !== KEY && event.key !== THEME_KEY) return;
      const before = cache;
      cache = null;
      const after = all();
      if (!before) return;
      for (const name of Object.keys(FIELDS)) {
        if (before[name] !== after[name]) announce(name, after[name]);
      }
    });
  }

  /** True when distances should read in miles and feet. */
  function isImperial() {
    return get('units') === 'imperial';
  }

  return { all, get, set, options, onChange, isImperial, FIELDS };
}());
