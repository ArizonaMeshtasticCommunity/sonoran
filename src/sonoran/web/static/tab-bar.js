/*
 * The bottom navigation bar on a phone (#282).
 *
 * Will chose the set on 2026-10-08: Map, Nodes, Chat and Dashboard, then
 * More, which opens the menu that already exists. The four are named in
 * the markup (`data-tabs`) and nowhere else.
 *
 * ONE LIST OF PAGES. The bar has no page links in the markup. `build`
 * copies the four from `#site-nav`, with their address, icon and word,
 * so a page that is renamed, moved or given a new icon changes in one
 * place and reaches both. A hand-kept second list is the drift this
 * project keeps paying for.
 *
 * WHEN. A phone, which is three things at once: a narrow screen, held
 * upright, and a finger. `QUERY` is the same words as the CSS block
 * that draws the bar, and
 * `test_the_css_and_the_script_ask_the_same_question` holds them
 * together.
 *
 * - 40rem is the phone width the review used (item 17) and the width of
 *   the node sheet (#281). An iPad is 52rem in portrait and keeps the
 *   bar at the top with its menu button.
 * - Upright, because an iPhone SE on its side is 568 px wide, under
 *   40rem, and only 320 px tall. The top bar and this one would take a
 *   third of that screen. Larger phones on their side are wider than
 *   40rem anyway.
 * - `(pointer: coarse)` is how #267 asks for a finger. A narrow desktop
 *   window with a mouse has no thumb to reach with, and keeps its
 *   vertical room.
 *
 * The menu button in the top bar (#271) stays. More is a second way to
 * open the SAME menu, not a second menu. It stays because the iOS 26
 * Safari toolbar floats at the bottom of the screen, and community
 * reports say it can cover a fixed bottom bar (review section 4.1). If
 * it does, the reader still has a way to every page. That is checked
 * on a real device, not here.
 */
(function tabBar() {
  const QUERY = '(max-width: 40rem) and (orientation: portrait) and (pointer: coarse)';

  /*
   * The tab a page belongs to when it is not a tab itself.
   *
   * Only a node page has one: it is what the Nodes list opens. A packet
   * is opened from the firehose and the dashboard, a link and a
   * traceroute from the traceroutes and the graph, and none of those is
   * a tab. A wrong light is worse than none, so those light nothing.
   */
  const PARENT = { node: 'nodes' };

  /**
   * Which tab to light for a page, and whether it is that tab's own page.
   * @param {string} page the router's page name
   * @param {string[]} tabs the pages in the bar
   * @returns {{tab: string, exact: boolean} | null}
   */
  function tabOf(page, tabs) {
    if (tabs.includes(page)) return { tab: page, exact: true };
    const parent = Object.hasOwn(PARENT, page) ? PARENT[page] : null;
    return parent && tabs.includes(parent) ? { tab: parent, exact: false } : null;
  }

  const bar = () => document.querySelector('[data-tab-bar]');
  const names = (node) => (node.dataset.tabs || '').split(/\s+/).filter(Boolean);

  /*
   * Copy the four links out of the page list, in the bar's order, before
   * the More button. The copy loses `data-nav` and `id`s, so the router
   * and `markNavHere`, which read `[data-nav]`, still see one menu.
   */
  function build() {
    const node = bar();
    const nav = document.getElementById('site-nav');
    if (!node || !nav) return null;
    const more = node.querySelector('[data-tab-more]');
    for (const name of names(node)) {
      const source = nav.querySelector(`a[data-nav="${name}"]`);
      if (!source) continue;
      const link = source.cloneNode(true);
      link.removeAttribute('data-nav');
      link.removeAttribute('aria-current');
      link.removeAttribute('class');
      link.dataset.tab = name;
      for (const label of link.querySelectorAll('.nav-label')) label.className = 'tab-label';
      node.insertBefore(link, more);
    }
    return node;
  }

  /*
   * Light the tab for the page in view.
   *
   * Its own page: `aria-current="page"`, the same as the menu entry.
   * A page that belongs to it (a node, under Nodes): `aria-current="true"`,
   * which says "the current item in this set" and not "this page".
   * Telling a screen reader it is on the Nodes page while it reads one
   * node would be false.
   */
  function mark(page) {
    const node = bar();
    if (!node) return;
    const links = [...node.querySelectorAll('a[data-tab]')];
    const found = tabOf(page, links.map((link) => link.dataset.tab));
    for (const link of links) {
      const here = Boolean(found) && link.dataset.tab === found.tab;
      link.classList.toggle('current', here);
      if (here) link.setAttribute('aria-current', found.exact ? 'page' : 'true');
      else link.removeAttribute('aria-current');
    }
  }

  window.SonoranTabBar = { QUERY, tabOf, build, mark };
})();
