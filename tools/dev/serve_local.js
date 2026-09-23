/*
 * Serve this repo's static tree, with /api proxied to a real instance.
 *
 *     node tools/dev/serve_local.js            # proxies to the dev box
 *     SONORAN_UPSTREAM=... node tools/dev/serve_local.js
 *
 * Playwright checks in this repo usually intercept `**\/static/*.js` and
 * serve the file from this tree, which works until a change touches
 * MARKUP. The deployed instance serves its own `index.html`, so new
 * elements are simply absent, and patching that HTML in flight is
 * fragile -- three attempts at it during #112 either corrupted the
 * document or raced the page's own initialisation.
 *
 * This serves the whole tree instead, so the page under test is the one
 * in the working copy, and proxies the API so it still has real data.
 *
 * It templates the two placeholders the real server fills, which is why
 * loading `index.html` straight off disk does not work: the page throws
 * on `__SONORAN_CONFIG__` before any script runs.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..', 'src', 'sonoran', 'web', 'static');
const UPSTREAM = process.env.SONORAN_UPSTREAM || 'http://203.0.113.10:8200';
const PORT = Number(process.env.PORT || 8811);
// `.mjs` and `.wasm` are not optional here. The planner's engine is an
// ES module worker that imports `splat_driver.mjs` and instantiates a
// `.wasm` beside it; served as text/plain the import fails silently and
// a prediction hangs forever on "Asking the engine which terrain it
// needs", with nothing in the console to say why.
const TYPES = { '.js': 'application/javascript', '.mjs': 'application/javascript',
                '.wasm': 'application/wasm', '.css': 'text/css', '.html': 'text/html',
                '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml',
                '.webmanifest': 'application/manifest+json', '.ico': 'image/x-icon' };

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname.startsWith('/api/')) {
    const proxied = http.request(UPSTREAM + req.url, { method: req.method }, (up) => {
      res.writeHead(up.statusCode, up.headers); up.pipe(res);
    });
    proxied.on('error', () => { res.writeHead(502); res.end('{}'); });
    req.pipe(proxied);
    return;
  }
  let file = url.pathname === '/' ? '/index.html' : url.pathname;
  file = file.replace(/^\/static\//, '/');
  const full = path.join(ROOT, file);
  if (!full.startsWith(ROOT) || !fs.existsSync(full) || fs.statSync(full).isDirectory()) {
    res.writeHead(404); res.end('not found'); return;
  }
  let body = fs.readFileSync(full);
  if (file === '/index.html') {
    // The server templates this; supply the same shape.
    body = body.toString()
      .replace('__SONORAN_CONFIG__', JSON.stringify({ tileUrl: '', tileAttribution: '', basePath: '' }))
      .replace(/__SONORAN_NONCE__/g, 'devnonce');
  }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(full)] || 'text/plain' });
  res.end(body);
}).listen(PORT, () => console.log(`serving this tree on http://127.0.0.1:${PORT}, /api -> ${UPSTREAM}`));
