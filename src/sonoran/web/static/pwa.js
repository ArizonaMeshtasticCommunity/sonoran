/*
 * The installed-app half of the page (#322).
 *
 * 1. Register the service worker (`sw.js`, served from the app root).
 * 2. When a deploy has installed a new worker, say that Sonoran was
 *    updated, and reload only when the reader chooses. A page is never
 *    swapped in the middle of a session.
 * 3. When the device loses its connection, say so, and mark the page as
 *    not live. Every figure on the page stopped at that moment, and a
 *    figure that looks live and is not is the one thing this dashboard
 *    must not show.
 * 4. In an installed app, give the four detail pages a Back button.
 *
 * Loaded after app.js, so `clock` (the mesh's timezone), `setStatus`,
 * `api`, `apiFetch`, `abortRequests` and `route` exist.
 */
(function () {
  'use strict';

  const root = document.documentElement;
  const tray = document.createElement('div');
  tray.className = 'app-notices';
  document.body.append(tray);

  // One notice: a sentence, and an optional button.
  function notice(text, action) {
    const box = document.createElement('div');
    box.className = 'app-notice';
    box.setAttribute('role', 'status');
    const words = document.createElement('p');
    words.textContent = text;
    box.append(words);
    if (action) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'primary';
      button.textContent = action.label;
      button.addEventListener('click', action.run);
      box.append(button);
    }
    tray.append(box);
    return { box, words };
  }

  /* ---- Offline ------------------------------------------------------ */

  let offline = null;

  function wentOffline() {
    root.setAttribute('data-offline', '');
    // A request in flight as the network goes can hang for ever, and the
    // page drawing waits on it (see `apiFetch` in app.js). End them: the
    // page then says it could not load, which is true.
    abortRequests();
    if (offline) return;
    const at = clock(new Date());
    // The status line in the menu and the phone bar, which otherwise
    // keeps its green "Updated" dot. The next refresh after the
    // connection comes back sets it again.
    setStatus('down', `Offline since ${at}`);
    offline = notice(
      `You are offline. This page stopped updating at ${at}. What it shows is not live.`,
    );
  }

  /*
   * The device says it is online a moment before a request can get
   * through: on an iPhone the event comes as the radio returns, ahead of
   * a working route. Drawing the page at that moment failed, and a page
   * that does not refresh by itself (Traceroutes, the weekly check-in)
   * stayed on "Failed to fetch". Measured in Chromium with the network
   * held back for 3 s after the event.
   *
   * So the page is drawn again when the API answers, asked at once and
   * then after 0.5, 1, 1.5, 2, then every 3 s, for up to about two
   * minutes. `api/version` is the smallest answer the API has.
   */
  const RETRY_MS = [500, 1000, 1500, 2000, 3000];
  const RETRY_LIMIT = 45;
  let reconnecting = null;

  async function whenReachable() {
    for (let attempt = 0; attempt < RETRY_LIMIT; attempt += 1) {
      if (navigator.onLine === false) return false;
      try {
        const response = await apiFetch(api('api/version'));
        if (response.ok) return true;
      } catch (error) {
        // Not yet. Ask again below.
      }
      const wait = RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)];
      await new Promise((resolve) => setTimeout(resolve, wait));
    }
    return false;
  }

  function cameOnline() {
    root.removeAttribute('data-offline');
    // Anything still in flight started while there was no network, so
    // end it; otherwise the new drawing would queue behind it.
    abortRequests();
    if (offline) {
      offline.box.remove();
      offline = null;
    }
    if (reconnecting) return;
    setStatus('stale', 'Reconnecting');
    reconnecting = whenReachable().then((reached) => {
      reconnecting = null;
      // Drawn either way: a page that still cannot load says so, which
      // is better than the stale "Failed to fetch" from before.
      if (navigator.onLine !== false) route();
      return reached;
    });
  }

  window.addEventListener('offline', wentOffline);
  window.addEventListener('online', cameOnline);
  if (navigator.onLine === false) wentOffline();

  /* ---- Back, in an installed app ------------------------------------ */

  /*
   * An installed app has no browser back button, and iOS gives a
   * home-screen app no back gesture either. The four detail pages are
   * reached from a list, and the menu goes to the list's top, not to
   * the place the reader was. So each one gets a Back button, in the
   * installed app only.
   *
   * The pages this app visited are kept here, not in `history.state`:
   * app.js calls `replaceState(null, ...)`, which would wipe it. When
   * there is no earlier page in this app (a shortcut or a link opened
   * the page), Back goes to the page's list instead.
   */
  const PARENT = { node: 'nodes', link: 'graph', traceroute: 'traceroutes', packet: 'firehose' };
  const standalone = (window.matchMedia && matchMedia('(display-mode: standalone)').matches)
    || navigator.standalone === true;

  if (standalone) {
    const page = (hash) => (hash.slice(1) || 'dashboard').split('?')[0];
    const visited = [page(location.hash)];
    window.addEventListener('hashchange', () => {
      const now = page(location.hash);
      if (visited.length > 1 && visited[visited.length - 2] === now) visited.pop();
      else if (visited[visited.length - 1] !== now) visited.push(now);
    });
    for (const [name, parent] of Object.entries(PARENT)) {
      const head = document.querySelector(`[data-page="${name}"] .page-head`);
      if (!head) continue;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'app-back';
      button.textContent = '← Back';
      button.addEventListener('click', () => {
        if (visited.length > 1) history.back();
        else location.hash = `#${parent}`;
      });
      head.before(button);
    }
  }

  /* ---- Service worker ----------------------------------------------- */

  // A service worker needs a secure context. Over plain HTTP (the bare
  // port on the dev box) the browser hides the API, and there is
  // nothing to do.
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;

  let updateShown = false;
  let reloading = false;

  /*
   * The words say that the page changed, not that a release came out
   * (#382). The worker changes when any static file changes, which is
   * most deploys, and a release is tagged later, if at all. "A new
   * version" read like a release. The server knows no release tag, so
   * the notice names none.
   */
  function offerUpdate(worker) {
    if (updateShown) return;
    updateShown = true;
    notice('Sonoran was updated. Reload to get the new page.', {
      label: 'Reload',
      run: () => {
        reloading = true;
        worker.postMessage('sonoran:activate');
      },
    });
  }

  // The new worker took over because the reader asked for it. Reload
  // once, so the page and its scripts are the updated ones too.
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) window.location.reload();
  });

  function watch(registration) {
    // A worker that was already waiting when this page opened.
    if (registration.waiting && navigator.serviceWorker.controller) {
      offerUpdate(registration.waiting);
    }
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing;
      if (!worker) return;
      worker.addEventListener('statechange', () => {
        // With no controller this is the first install, not an update.
        if (worker.state === 'installed' && navigator.serviceWorker.controller) {
          offerUpdate(worker);
        }
      });
    });
    // An installed app can stay open for days. Ask for a new worker when
    // the reader comes back to it, and at most once a minute.
    let asked = Date.now();
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible' || Date.now() - asked < 60000) return;
      asked = Date.now();
      registration.update().catch(() => {});
    });
  }

  // Relative to the document, so a deployment under WEB_BASE_PATH works.
  // A failure is not the reader's problem: the page works without a
  // worker, and only the offline page and the update notice are lost.
  navigator.serviceWorker
    .register('sw.js', { scope: './' })
    .then(watch)
    .catch((error) => console.warn('Sonoran: no service worker', error));
}());
