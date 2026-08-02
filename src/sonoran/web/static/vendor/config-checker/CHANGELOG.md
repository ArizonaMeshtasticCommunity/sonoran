# Changelog

All notable changes to the Arizona Meshtastic Config Checker are documented here.
This project uses date-based releases tagged in GitHub Releases.

## v3.1.0 — 2026-06-11

### Added

- **Privacy-safe diagnostics / user error reporting.** When the checker hits an
  error, a "Copy diagnostic report" control now appears so users can share a
  *sanitized, anonymous* report with the community to help debug bugs. The report
  captures only non-sensitive metadata: error type/class, the operation that
  failed (parse / channel-url-decode / fixer / export / serial / firmware-check),
  the tool version, browser + OS family (coarse, from UA), the detected config
  *format* label, file *extension*, file *size* in bytes, and a timestamp.
- **Hard privacy guarantee — whitelist, never blacklist.** It is structurally
  impossible for config contents, channel names, PSK/keys, MQTT credentials,
  QR/URL input, the filename, or any setting value to enter a report. Every field
  is read from a fixed whitelist (`js/diagnostics.js`); the one free-ish field
  (the error *message*) is aggressively scrubbed of URLs, base64/hex blobs, and
  quoted tokens; the failed-step and format values are enum-locked; the filename
  is reduced to its extension only. No network beacon — nothing leaves the
  browser unless the user copies the report themselves (and the page CSP would
  block an external send anyway).
- **Regression test proving no PII leak** (`tests/diagnostics-suite.mjs`, 22
  assertions): seeds every caller-supplied field with unique secret sentinels
  (PSK, channel name, share URL, MQTT creds, filename, coordinates, raw bytes)
  and asserts none appear in a generated report, while the useful non-sensitive
  fields are still present. Wired into `npm test`.

### Fixed

- **Stale live-site URL in docs.** README pointed to `config.azmsh.net`, which no
  longer resolves; the live community deploy is `cfgtest.azmsh.dev`. Updated.
- **Auto-fix/export now fails safe.** The auto-fix click handler is wrapped in a
  try/catch so an export error surfaces a message (and a diagnostic entry)
  instead of silently throwing.

## v3.0.1 — 2026-06-11

### Fixed

- **`protobuf is not defined` — checker fully broken in-browser.** The page loaded
  protobuf.js and js-yaml from jsDelivr using a *floating* version tag
  (`protobufjs@7`, `js-yaml@4`) combined with a pinned Subresource Integrity (SRI)
  hash. When protobuf.js published v7.6.3 (2026-06-09), the bytes served at the
  floating URL changed, the SRI digest no longer matched, and the browser **blocked
  both scripts**. With the `protobuf` global never defined, any decode (channel URL
  parse, Android binary `.cfg` parse, fixer export) threw `protobuf is not defined`.
  Reproduced in a real browser (SRI block confirmed in the console), root-caused, and
  fixed.
- **Fix: libraries are now self-hosted.** `protobuf.js 7.6.3` and `js-yaml 4.2.0` are
  vendored into `js/vendor/` at exact pinned versions, served from `'self'`, with SRI
  hashes computed against the vendored bytes. Because the bytes are now immutable, the
  SRI guard can no longer break from an upstream republish. The `https://cdn.jsdelivr.net`
  allowance was dropped from the Content-Security-Policy. No user-facing workflow change.
  Verified end-to-end in a browser: a sample Meshtastic ChannelSet encodes and decodes
  with zero console errors, and the full Node regression suite passes.
- Durable follow-up (not in this patch): migrate the hand-rolled script tags to a Vite
  bundle so dependency versioning is managed by a lockfile instead of vendored files.

## v3.0.0 — 2026-06-03

Breaking-ish release: MQTT credentials are no longer stored in client source,
and Android binary `.cfg` exports now fully round-trip channels. No user-facing
workflow changes, but the source-of-truth for MQTT validation changed (hashes)
and the binary exporter now writes channels into `channel_url`.

### Security / privacy
- **MQTT credentials removed from client source.** The public AZ mesh MQTT
  broker host, username, and password are no longer shipped in plaintext in
  `js/constants.js`. They are replaced with SHA-256 hashes. The checker hashes
  whatever the user has in their own config and compares hashes — a match means
  the node is correctly configured, without the answer key sitting in the
  source for bots/scrapers to lift. (Community request: Logan/Tyler.)
  - This is obfuscation against casual scraping, **not** cryptographic secrecy.
    The real credentials are distributed via the Discord `#getting-started`
    guide and the azmsh.net site; the checker only verifies, it never hands
    them out.
  - **No fixer behavior change.** The auto-fixer never injected these values —
    users supply their own MQTT credentials through the MQTT form (which points
    them at Discord). Hashing the checker's comparison values changes nothing
    about repair/export.
  - The credential comparison values are not shipped in the public source;
    ask in #getting-started for the current broker credentials.
- Added `js/sha256.js` — a tiny dependency-free, synchronous SHA-256 (browser +
  Node compatible). Keeps the no-build, client-side design intact and avoids the
  async ergonomics of WebCrypto `subtle.digest` in the check flow.

### Fixed
- **#20 — Android binary `.cfg` channel coverage.** Upstream `DeviceProfile`
  protobuf has no `channels` field; channels live in `channel_url` (a
  base64url-encoded `ChannelSet`). The checker previously dropped channels on
  every binary round-trip. Added `js/channel-url.js` to decode/encode the
  Meshtastic shareable channel URL (`https://meshtastic.org/e/#<base64url>`):
  - The parser now extracts channels from `channel_url` when a binary export
    has no embedded channel list.
  - The binary exporter now writes channels back into `channel_url` instead of
    setting a non-existent `channels` field (which the encoder silently
    dropped). Channel names, PSK bytes, and uplink/downlink flags survive a full
    parse → validate → fix → re-parse round-trip.

### Values confirmed canonical
- Node-info broadcast interval `43200` (12h) and stationary neighbor-info
  interval `39600` (11h) are confirmed correct and match the community
  `#getting-started` guide. The azmsh.net site has been reconciled to these
  values (a stale duplicate page listing `10800` / `14400` was removed).
- Per owner decision, the checker does **not** add `hop_limit` or `ignore_mqtt`
  checks.

### Tests
- Regression suite extended from 73 to 96 assertions, all green:
  - `tests/suite.mjs`: 76 assertions (adds MQTT credential-hashing coverage —
    hashes-not-plaintext invariant, matcher correctness, wrong-cred WARN paths,
    and an env-gated full PASS path).
  - `tests/channel-suite.mjs`: 20 assertions (adds the full #20 lifecycle —
    binary `.cfg` with `channel_url` → parse → validate → fix → re-parse with
    channel name + PSK bytes intact, plus malformed-URL robustness).

## v2.2.0 — 2026-06-03
- Test suite added; public channel-0 model (#18); firmware baseline 2.7.15.

## v2.1.1 and earlier
- See GitHub Releases history.
