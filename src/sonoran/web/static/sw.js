/*
 * The service worker (#322). It does two things and nothing more.
 *
 * 1. It shows a page that says "offline" when a page load cannot reach
 *    the server, so an installed app opens to a clear message and not
 *    to the browser's own error.
 * 2. It changes with every deploy, because the asset version below is
 *    written into it by the server. The browser compares the script
 *    byte for byte, so a deploy installs a new worker, and the new one
 *    takes over at once. It keeps nothing, so the swap changes nothing
 *    the reader can see, and there is no notice to show (#382).
 *
 * It keeps NOTHING in a cache, on purpose:
 *
 * - The data is live. An old answer from `/api/` would read as the
 *   mesh's real state, so the API is never touched here.
 * - A login proxy (Keycloak in production, Authelia on the dev box)
 *   stands in front of every request. A cached page could be a login
 *   page, and a page served from a cache never reaches the proxy, so an
 *   expired session would not be sent to log in again.
 * - The document and every asset already have the right HTTP caching:
 *   the document is `no-cache`, and each asset URL carries `?v=` with a
 *   hash of its bytes and is kept for a year. A second cache here could
 *   only disagree with that one.
 * - The map tiles come from a third party whose terms forbid bulk
 *   offline copies. Requests to another origin are never intercepted.
 *
 * Served from `/sw.js` (the app root) and not from `/static/`, because
 * a worker controls only the pages at or below its own path.
 */
'use strict';

const VERSION = '__SONORAN_ASSET_VERSION__';

self.addEventListener('install', () => {
  // A new worker takes over at once (#382). It holds no cache and
  // touches no request but a page load, so an open page goes on exactly
  // as before, and its next load comes from the network with the new
  // files. An update notice told the reader about a change that needed
  // nothing from them, after every deploy.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // A worker of an earlier design may have left caches. None of them
    // is wanted now.
    const names = await caches.keys();
    await Promise.all(names.map((name) => caches.delete(name)));
    // Start the page load request in parallel with the worker's start.
    if (self.registration.navigationPreload) {
      await self.registration.navigationPreload.enable();
    }
    // Take control of the open pages, on the first install so the
    // offline page works without a reload, and after an update so no
    // page keeps the old worker.
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  // Only page loads. Every other request, the API included, goes to the
  // network exactly as if no worker existed.
  if (event.request.mode !== 'navigate') return;
  event.respondWith(load(event));
});

/*
 * Load a page from the network, or say "offline".
 *
 * A redirect (the login proxy sending the reader to log in) comes back
 * as it is and the browser follows it. Only a request that could not
 * reach any server gets the offline page. An error status from the
 * server is not "offline", and it is shown as the server sent it.
 */
async function load(event) {
  try {
    const preloaded = await event.preloadResponse;
    if (preloaded) return preloaded;
    return await fetch(event.request);
  } catch (error) {
    return offlinePage();
  }
}

function offlinePage() {
  const home = self.registration.scope;
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#17100b">
<title>Sonoran: offline</title>
<style>
  /* The two themes' tokens from app.css. */
  :root { color-scheme: dark light; --bg: #17100b; --fg: #f6ece2; --muted: #b59c88; --accent: #f4703f; --on-accent: #1b1109; }
  @media (prefers-color-scheme: light) {
    :root { --bg: #f7f2ec; --fg: #25190f; --muted: #6b5646; --accent: #b8481f; --on-accent: #ffffff; }
  }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg); }
  body {
    display: grid; place-content: center; gap: 1rem; text-align: center;
    padding: calc(1.5rem + env(safe-area-inset-top, 0px)) 1.5rem calc(1.5rem + env(safe-area-inset-bottom, 0px));
    font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  h1 { margin: 0; font-size: 1.4rem; }
  p { margin: 0; color: var(--muted); max-width: 26rem; }
  a {
    justify-self: center; display: inline-block; min-height: 44px; min-width: 44px;
    padding: .65rem 1.4rem; border-radius: .5rem; box-sizing: border-box;
    background: var(--accent); color: var(--on-accent); font-weight: 600; text-decoration: none;
  }
</style>
</head>
<body>
<h1>Sonoran is offline</h1>
<p>This device cannot reach the server. Sonoran shows only live data, so there is nothing to show until the connection comes back.</p>
<a href="${escapeAttribute(home)}">Try again</a>
</body>
</html>`;
  return new Response(html, {
    status: 503,
    statusText: 'Offline',
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      // The page has no script and loads nothing.
      'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
      'X-Sonoran-Version': VERSION,
    },
  });
}

function escapeAttribute(text) {
  return String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}
