# APP.md — Sonoran as an installed app

Sonoran can be installed on a phone, a tablet or a computer. It then
opens from its own icon, in its own window, with no browser bar. This
document tells a reader how to install it, and what it does with no
network. The second half is for operators and developers. See #322.

## 1. Install it

Log in first. The app is behind the same login as the website, and the
browser must reach the app's files to install it.

### 1.1 Android (Chrome)

1. Open the dashboard in Chrome and log in.
2. Open the menu (the three dots) and choose **Install app**. On some
   versions it is **Add to Home screen**, then **Install**.
3. Open Sonoran from its icon.

Touch and hold the icon for three shortcuts: **Live map**, **Nodes**
and **RF map**.

### 1.2 iPhone and iPad (Safari)

1. Open the dashboard in Safari and log in.
2. Tap **Share**, then **Add to Home Screen**, then **Add**.
3. Open Sonoran from its icon.

**You must log in again in the app.** iOS keeps a separate set of
cookies for each home-screen app. Your Safari login does not carry over.
After that, the app keeps its own login for as long as the login server
allows.

Use Safari. On iOS 16.4 and later, other browsers can also add a
home-screen app, from their own Share menu.

### 1.3 A computer (Chrome or Edge)

Open the dashboard and log in. Click the install icon at the right end
of the address bar, or open the menu and choose **Install Sonoran**.

## 2. With no network

Sonoran shows live data only. It never shows an old copy as if it were
live.

- **The app opens with no network:** it shows "Sonoran is offline" and a
  **Try again** button. It shows no figures at all.
- **The network stops while the app is open:** a notice says "You are
  offline" and the time the page stopped updating. The page fades, and
  the status line in the menu turns red. The figures stay on the screen,
  but they are not live. When the network comes back the notice goes, and
  the next refresh brings the page up to date.
- **The network comes back:** the page you are on loads again at once.
  A request that was in flight when the network changed is ended, so it
  cannot hold up the pages after it. A request with no answer in a
  minute is ended too.

## 3. A new version

After a deploy, an open app shows "A new version of Sonoran is
available" and a **Reload** button. Nothing changes until the reader
chooses to reload, so a page never changes in the middle of a session.
An app that was closed opens on the new version.

In an installed app there is no browser back button. The node, link,
packet and traceroute pages have a **Back** button there. In a browser
tab they do not, because the browser has its own.

## 4. For operators

### 4.1 The login proxy

Every file of the app is behind the login proxy: Keycloak in
production, Authelia on the dev box. Nothing in the proxy must change
for the install to work, if the proxy keeps its session in a cookie.

- The page links the manifest with `crossorigin="use-credentials"`. A
  browser fetches a manifest **without cookies** unless the link says
  so. Without it the proxy answered with its login page, and the
  browser found no manifest. Measured on the dev box on 2026-10-02:
  `/static/manifest.webmanifest` gave a `302` to the login page.
- The service worker script, `/sw.js`, is fetched by the browser with
  the session cookie. If the session has expired, the browser cannot
  get it, and it keeps the worker it has.
- A page load in the app goes to the network every time. An expired
  session therefore reaches the proxy, and the proxy sends the reader
  to log in, as in a browser tab.

The proxy may let the manifest and the icons through without a login,
because they hold nothing private. That is not necessary, and nothing
depends on it.

**iOS:** a home-screen app keeps its own cookies. How long a reader
stays logged in is the session and refresh lifetime of the login
server. A short lifetime means the reader logs in again each time they
open the app.

### 4.2 What the service worker does

`web/static/sw.js`, served by `api/app.py` at `/sw.js`. A worker
controls only the pages at or below its own path, so it cannot live
under `/static/`. Under `WEB_BASE_PATH` it is at the base path.

- It handles page loads only. Every other request, the API, the map
  tiles and the login included, goes to the network as if no worker
  existed.
- Every API request from the page goes through `apiFetch` in `app.js`,
  which `abortRequests` (called by `pwa.js` on `offline` and `online`)
  or a 60 s timeout can end. Before this, one request stranded by
  airplane mode stopped every later page from drawing until the app was
  closed.
- It keeps **nothing** in a cache. The data is live, and a cached page
  could be a login page. The document is `no-cache`, and every asset is
  versioned with `?v=` and kept for a year by the HTTP cache, so a second
  cache could only disagree with the first.
- It shows the offline page only when a page load cannot reach any
  server. A redirect and an error status pass through as they are.
- The asset version is written into it, so every deploy changes its
  bytes. The browser then installs the new worker, and `pwa.js` shows
  the update notice.

The map tiles are not cached. The OpenStreetMap tile policy forbids
bulk copies for offline use.

`tests/unit/test_pwa.py` pins each of these points.

### 4.3 The icons

`icon-192.png` and `icon-512.png` are made from `favicon.png` by
`tools/make_app_icons.py`. The source is 256 px, so the 512 px icon is
an upscale. Make it again from a larger source if one is drawn.

## 5. What was checked, and how

In Chromium, behind a stand-in login proxy that redirects a request
with no session cookie to a login page on another origin:

- With the old link the manifest request carried no cookie and got the
  redirect, so Chromium had no manifest. With `use-credentials` it
  carried the cookie and Chromium read the manifest.
- The worker took control of the page, and a reload came from it.
  No API response came from it.
- The network turned off on an open page: the offline notice showed,
  the page faded, and both went when the network came back.
- The app opened with no network: the offline page, with status 503.
- An expired session with the network on: the reader reached the login
  page.
- A deploy while the page was open: the update notice showed, the old
  worker stayed in control until **Reload**, and the page then loaded
  the new version.
- In standalone mode, Back went to the earlier page, or to the list
  when there was no earlier page.

Still to check on real devices: the install itself on Android and iOS
against production, the Keycloak login inside an iOS home-screen app,
and the safe areas and status bar of a notched iPhone in standalone
mode.
