// Build one self-contained HTML file from the dashboard.
//
// The file has the markup, the styles, the scripts, and a recording of
// the API in it. It needs no server and no network. Use it to show a
// change to someone who cannot run the stack.
//
// The file holds page content only. It has no <html>, <head>, or
// <body> tag, because the Artifact host adds them.
//
//   node tools/dev/record.js /tmp/recording.json
//   node tools/dev/artifact.js /tmp/recording.json /tmp/preview.html
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const STATIC = path.join(ROOT, 'src', 'sonoran', 'web', 'static');

const RECORDING = process.argv[2] || '/tmp/sonoran-recording.json';
const OUT = process.argv[3] || '/tmp/sonoran-preview.html';

const read = (p) => fs.readFileSync(path.join(STATIC, p), 'utf8');
const dataUri = (p, mime) =>
  `data:${mime};base64,${fs.readFileSync(path.join(STATIC, p)).toString('base64')}`;

// ---------------------------------------------------------------- css

// Leaflet asks for three images with a relative URL. Put them in the
// stylesheet, because the file must not ask for anything.
let leafletCss = read('vendor/leaflet.css');
for (const name of ['marker-icon.png', 'layers.png', 'layers-2x.png']) {
  leafletCss = leafletCss.split(`url(images/${name})`).join(
    `url(${dataUri(`vendor/images/${name}`, 'image/png')})`,
  );
}

const appCss = read('app.css');

// --------------------------------------------------------------- html

const html = read('index.html');
const body = html.slice(html.indexOf('<body') , html.lastIndexOf('</body>'));
let markup = body.slice(body.indexOf('>') + 1);

// The logo is the only image in the markup.
markup = markup.replace('src="static/logo.png"', `src="${dataUri('logo.png', 'image/png')}"`);

// Take out every script tag. They are added again below, in order,
// with the file contents in them.
markup = markup.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '');

// ------------------------------------------------------------ scripts

const recorded = JSON.parse(fs.readFileSync(RECORDING, 'utf8'));

// The traceroute pages put a drawing from the mesh-graph service on
// the page, and they link to it. That service is another host, and
// this file must not ask another host for anything. Take the links
// out. The dashboard already has a message for a trace with no link.
const GRAPH_KEYS = ['graph_url', 'node_graph_url'];

function stripGraphUrls(value) {
  if (Array.isArray(value)) {
    value.forEach(stripGraphUrls);
    return;
  }
  if (value === null || typeof value !== 'object') return;
  GRAPH_KEYS.forEach((key) => {
    if (key in value) value[key] = null;
  });
  Object.keys(value).forEach((key) => stripGraphUrls(value[key]));
}

stripGraphUrls(recorded);

// The dashboard reads its settings from window.SONORAN. An empty tile
// URL turns the basemap off, which is what we want: a tile server is
// another host, and the file must not reach one.
const config = {
  apiBase: '',
  graphBaseUrl: '',
  timezone: 'America/Phoenix',
  tileUrl: '',
  tileAttribution: '',
  mapCenter: [34.0, -111.5],
  mapZoom: 7,
};

const shim = `
(function () {
  'use strict';
  var RECORDED = window.__SONORAN_RECORDED__;

  // The recording was made against a server, where the path of a
  // request starts at the root: /api/nodes. This file can be at any
  // depth, and the dashboard asks for its data with a relative path.
  // The browser thus makes a URL that starts with the directory of
  // this file. Take that directory off again, or nothing matches.
  var BASE_DIR = location.pathname.replace(/[^/]*$/, '');

  function normalise(pathname) {
    if (BASE_DIR.length > 1 && pathname.indexOf(BASE_DIR) === 0) {
      return '/' + pathname.slice(BASE_DIR.length);
    }
    return pathname;
  }

  // Look up a recording by path and query. The query is sorted, so
  // the order of the parameters does not matter.
  function keyOf(url) {
    var u = new URL(url, location.href);
    u.searchParams.sort();
    return normalise(u.pathname) + (u.search || '');
  }

  // Build an index by path, so a query that was never recorded can
  // still find an answer for the same path.
  var byPath = {};
  Object.keys(RECORDED).forEach(function (key) {
    var p = key.split('?')[0];
    if (!(p in byPath)) byPath[p] = RECORDED[key];
  });

  function lookup(url) {
    var key = keyOf(url);
    if (key in RECORDED) return RECORDED[key];
    // The query was never recorded. Answer with the recording for the
    // same path, so the panel shows data instead of an error.
    var p = normalise(new URL(url, location.href).pathname);
    if (p in byPath) return byPath[p];
    return null;
  }

  var realFetch = window.fetch.bind(window);

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || String(input);
    // Anything that is not the API keeps the normal path. Nothing in
    // this file uses it, but a data: URL must still work.
    if (url.indexOf('data:') === 0 || url.indexOf('blob:') === 0) {
      return realFetch(input, init);
    }
    var body = lookup(url);
    if (body === null) {
      return Promise.resolve(new Response('{"detail":"not in this preview"}', {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }));
    }
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
  };

  // Two pages need hardware or a WebAssembly engine, so their code is
  // not in this file. Give the router something that does not fail,
  // and say why the page is empty.
  //
  // The router calls SonoranPlanner.show() with no argument, so the
  // name of the page is given here and not read from the call.
  function unavailable(pageName, title, reason) {
    return {
      show: function () {
        var host = document.querySelector('[data-page="' + pageName + '"]');
        if (!host) return Promise.resolve();
        host.innerHTML =
          '<div class="sonoran-preview-empty">' +
          '<h1>' + title + '</h1>' +
          '<p>' + reason + '</p>' +
          '<p>This page works in the full dashboard. Run ' +
          '<code>./tools/dev/preview.sh</code> to use it.</p>' +
          '</div>';
        return Promise.resolve();
      },
    };
  }

  window.SonoranPlanner = unavailable(
    'planner',
    'Coverage planner',
    'The planner compiles a WebAssembly signal engine and reads terrain ' +
    'tiles from the server. This file has neither, so a prediction ' +
    'cannot run here.'
  );
  window.SonoranConfigCheck = unavailable(
    'config',
    'Config check',
    'The config checker reads a Meshtastic node over USB with Web Serial. ' +
    'This file has no device to read.'
  );
}());
`;

const previewCss = `
/*
 * The dashboard has its own palette in app.css. Everything here reads
 * those custom properties, so the added parts match the interface and
 * a change to the palette reaches them too.
 */
.sonoran-preview-empty {
  padding: clamp(1.5rem, 5vw, 3rem);
  max-width: 44rem;
  color: var(--text);
}
.sonoran-preview-empty h1 {
  margin: 0 0 0.75rem;
  font-size: 1.6rem;
  text-wrap: balance;
}
.sonoran-preview-empty p {
  margin: 0 0 0.85rem;
  color: var(--muted);
  line-height: 1.65;
  max-width: 60ch;
}
.sonoran-preview-empty code {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0.1em 0.4em;
  color: var(--text);
}
.sonoran-preview-note {
  position: fixed;
  right: 1rem;
  bottom: 1rem;
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.45rem 0.7rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--muted);
  pointer-events: none;
}
.sonoran-preview-note::before {
  content: "";
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: var(--accent);
}
`;

const note = '<div class="sonoran-preview-note">Recorded data</div>';

const parts = [
  '<title>Sonoran Dashboard</title>',
  `<style>${leafletCss}</style>`,
  `<style>${appCss}</style>`,
  `<style>${previewCss}</style>`,
  markup,
  note,
  `<script>window.SONORAN = ${JSON.stringify(config)};</script>`,
  `<script>window.__SONORAN_RECORDED__ = ${JSON.stringify(recorded)};</script>`,
  `<script>${shim}</script>`,
  `<script>${read('vendor/leaflet.js')}</script>`,
  `<script>${read('vendor/echarts.min.js')}</script>`,
  `<script>${read('app.js')}</script>`,
];

fs.writeFileSync(OUT, parts.join('\n'));
const mb = (fs.statSync(OUT).size / 1024 / 1024).toFixed(2);
console.log(`wrote ${OUT} (${mb} MB, ${Object.keys(recorded).length} recorded responses)`);
