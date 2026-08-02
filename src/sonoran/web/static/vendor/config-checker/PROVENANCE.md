# Config checker

These files are copied without change from the Arizona Meshtastic
Community config checker.

- Source: `git@github.com:ArizonaMeshtasticCommunity/config-checker`
- Commit: `e2a892d` (2026-06-11)
- Hosted by the community at https://cfgtest.azmsh.dev

## How it is used here

Sonoran uses this project's **logic** and draws the result itself. The
Config check page is `web/static/config-check.js`, which imports
`js/parser.js`, `js/checker.js` and `js/fixer.js` from here and renders
their output in the dashboard's own style.

This is the same arrangement as the coverage planner: the vendored code
is the engine, the interface belongs to Sonoran.

`index.html`, `css/style.css` and `js/app.js` are that project's own
interface. Sonoran does not load them. They are kept so the copy stays
whole and an update stays a re-copy of this directory, and so the page
still works if opened directly.

Three files here are loaded as classic scripts by Sonoran's own
`index.html`, because the logic modules read them off `window` rather
than importing them:

- `js/vendor/protobuf.min.js`
- `js/vendor/js-yaml.min.js`
- `js/protobuf/meshtastic-proto.js`

They keep upstream's Subresource Integrity hashes. Miss them out and
every parse fails with "jsyaml is not defined", while the
build-from-scratch path still works, because that one parses nothing.

Nothing here is edited. If something needs to change, change it
upstream and copy the result down.

## What was left out

The upstream repository also holds `tests/`, `.github/`, and
`wrangler.jsonc`, which is its Cloudflare Workers deployment. None of
that is served, so none of it is copied. Everything the page loads is
here.

## Everything stays on the device

The checker reads a config file, or a node over USB, entirely in the
browser. No config, channel key, or MQTT credential is sent anywhere,
and Sonoran adds no endpoint for this feature. The server only serves
these static files.

Read at commit `e2a892d`, the application makes exactly one outbound
request: `https://api.github.com/repos/meshtastic/firmware/releases/latest`,
to report whether a node's firmware is current. It carries no user data.
That host is in `connect-src` for this reason, and for no other.

## Why the headers matter

Two response headers matter to this page. See `AGENTS.md` 9.17.

- `connect-src` must hold `https://api.github.com`, or the firmware
  check fails with nothing visible.
- `script-src` carries no `unsafe-eval`, so protobuf.js cannot build its
  decoders the way it prefers, by compiling strings. Android `.cfg`
  files still work: `static/meshtastic-static.js` holds the same schema
  compiled ahead of time, and `config-check.js` points
  `Root.fromJSON` at it. Regenerate it with
  `tools/generate_protobuf_static.sh` whenever this directory is
  updated and its protobuf descriptor changes.
- `Permissions-Policy` must permit `serial=(self)` for reading a node
  over USB. Web Serial also needs a secure context: over plain HTTP the
  browser hides `navigator.serial` whatever the headers say.

## What was reviewed

The code was read at commit `e2a892d`, about 3,700 lines of first-party
JavaScript and 516 vendored. It was not executed during review.

- No `eval`, `new Function`, or `document.write`.
- Every `innerHTML` assignment is a fixed string. Nothing from a config
  file is ever interpolated into markup, so a crafted node name cannot
  become script. Values from a config are written with `textContent`.
- YAML is parsed with `SAFE_SCHEMA`, so a document cannot instantiate
  arbitrary types.
- No inline event handlers, so a strict policy does not break it.
- `protobuf.min.js` and `js-yaml.min.js` are local and carry Subresource
  Integrity hashes.
- The diagnostic report is built from a field whitelist, and upstream
  holds a test that asserts no input can reach it.

Upstream has no licence file. It is the community's own work.
