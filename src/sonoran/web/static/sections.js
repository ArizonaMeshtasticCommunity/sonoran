/*
 * Parts of the site this deployment keeps out of view (HIDDEN_SECTIONS).
 *
 * Logan asked for this for the test roll-out to main: an operator hides
 * an unfinished part of the site with a setting, not a code change. The
 * ids and what each one hides are in `api/sections.py` and
 * docs/OPERATIONS.md 2.1.
 *
 * THE LIST comes from the server, in `window.SONORAN.hiddenSections`,
 * which `api/app.py` writes into the page. No request of its own, so the
 * page knows before it draws anything. With an empty list this script
 * changes nothing at all.
 *
 * What a hidden section loses here:
 *
 * - its menu entry. Removed before `tab-bar.js` copies the menu into the
 *   phone bar, so the bar and More never offer it either;
 * - every element marked `data-section="<id>"` (a dashboard card, a
 *   panel). An element marked `data-section-absent="<id>"` shows instead,
 *   for a sentence that must read differently without it;
 * - every link to its address (`#<id>`, `#<id>/...`, `#<id>?...`), now
 *   and in whatever a page draws later;
 * - its address. The router asks `pageFor`, and a hidden page shows the
 *   "not available" page instead.
 *
 * The server closes its API routes as well (`api/sections.py`), so this
 * is not the only thing between a reader and a hidden feature.
 */
(function sections() {
  const config = window.SONORAN || {};
  const list = Array.isArray(config.hiddenSections) ? config.hiddenSections : [];
  const hidden = new Set(list.map((name) => String(name)));
  const UNAVAILABLE = 'unavailable';

  /** True when this deployment hides the section. */
  function isHidden(name) {
    return hidden.has(name);
  }

  /**
   * The page a `#` address opens: the part before a `/` or a `?`.
   * @param {string | null} href
   * @returns {string | null}
   */
  function pageOf(href) {
    const text = String(href || '');
    if (!text.startsWith('#')) return null;
    return text.slice(1).split('?')[0].split('/')[0] || null;
  }

  /** The page to show for a page name: itself, or "not available". */
  function pageFor(name) {
    return hidden.has(name) ? UNAVAILABLE : name;
  }

  /** True when a link leads to a hidden page. */
  function linkIsHidden(href) {
    const page = pageOf(href);
    return Boolean(page) && hidden.has(page);
  }

  /* Hide every link to a hidden page in this part of the document. */
  function hideLinks(root) {
    if (!root || root.nodeType !== 1) return;
    const links = root.matches('a[href^="#"]') ? [root] : [];
    links.push(...root.querySelectorAll('a[href^="#"]'));
    for (const link of links) {
      if (linkIsHidden(link.getAttribute('href'))) link.hidden = true;
    }
  }

  function apply(doc) {
    if (!hidden.size) return;
    for (const name of hidden) {
      for (const link of doc.querySelectorAll(`#site-nav a[data-nav="${name}"]`)) link.remove();
      for (const node of doc.querySelectorAll(`[data-section="${name}"]`)) node.hidden = true;
      for (const node of doc.querySelectorAll(`[data-section-absent="${name}"]`)) node.hidden = false;
    }
    hideLinks(doc.body);
    /*
     * Pages draw their links long after this runs, and some fill in a
     * panel after their own render has finished (the node page's links,
     * for one). So every element added later is checked as it arrives.
     * Only when something is hidden: the default page has no observer.
     */
    new MutationObserver((changes) => {
      for (const change of changes) {
        if (change.type === 'attributes') hideLinks(change.target);
        for (const node of change.addedNodes) hideLinks(node);
      }
    }).observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['href'] });
  }

  window.SonoranSections = { UNAVAILABLE, isHidden, pageOf, pageFor, linkIsHidden };
  if (typeof document !== 'undefined') apply(document);
})();
