/**
 * diagnostics.js — privacy-safe error diagnostics for the AZ Meshtastic Config Checker.
 *
 * GOAL: when a user hits a bug, give them (and us) enough to understand WHAT broke
 * WITHOUT ever capturing their config contents, channel names, PSK/keys, MQTT
 * credentials, QR/URL input, or any setting values.
 *
 * PRIVACY MODEL — whitelist, never blacklist:
 *   The diagnostics report is built field-by-field from a fixed WHITELIST of
 *   non-sensitive metadata. There is NO code path that copies a caller-supplied
 *   object wholesale into the report, so config/PSK/url-input can never leak even
 *   if a future caller passes a sensitive object by mistake. Only the explicit
 *   whitelisted scalars below are ever emitted:
 *     - tool version (release tag)        — public
 *     - browser + OS (sanitized UA)       — coarse, no fingerprinting beyond UA
 *     - the STEP that failed               — from a fixed enum, not free text
 *     - error class/name                   — e.g. "TypeError", "RangeError"
 *     - error message                      — SCRUBBED for embedded payload
 *     - detected source FORMAT              — "yaml" | "json" | "android" | etc. (a label, not data)
 *     - file size in bytes / file extension — size + ".cfg"/".yaml", never the name or bytes
 *     - timestamp (UTC, second precision)
 *
 * No personal data leaves the browser automatically. Default behavior is a
 * client-side, copyable report the user chooses to share. There is no network
 * beacon (and the page CSP would block one anyway: connect-src is 'self' +
 * api.github.com only).
 */

export const DIAG_VERSION = 'v3.1.0';

// Fixed set of operations we attribute failures to. Anything not in this set
// is coerced to 'unknown' so a caller can't smuggle free-form (potentially
// sensitive) text into the "step" field.
export const STEPS = Object.freeze({
  PARSE: 'parse',
  CHANNEL_URL_DECODE: 'channel-url-decode',
  FIXER: 'fixer',
  EXPORT: 'export',
  FIRMWARE_CHECK: 'firmware-check',
  SERIAL_CONNECT: 'serial-connect',
  SERIAL_READ: 'serial-read',
  SERIAL_APPLY: 'serial-apply',
  RENDER: 'render',
  UNKNOWN: 'unknown',
});
const STEP_VALUES = new Set(Object.values(STEPS));

// Allowed source-format labels (these are classifications, never user content).
const ALLOWED_FORMATS = new Set(['android', 'backup', 'yaml', 'json', 'serial', 'unknown', '']);

// Allowed file extensions (a type, never the user's filename).
const ALLOWED_EXT = new Set(['.cfg', '.yaml', '.yml', '.json', '']);

/**
 * Scrub an error message so it can be safely emitted.
 *
 * Error messages CAN sometimes contain echoed input (e.g. JSON.parse throwing
 * with a snippet, or `Unexpected token X`). We therefore:
 *   1. cap length hard,
 *   2. strip anything that looks like base64/hex blobs (PSK, channel URLs,
 *      protobuf bytes), long quoted strings, and key/URL-ish tokens,
 *   3. collapse digits-with-context so we don't leak coordinates etc.
 *
 * This is defense-in-depth ON TOP OF the whitelist: even the one free-ish field
 * is aggressively sanitized.
 */
export function scrubMessage(msg) {
  if (msg == null) return '';
  let s = String(msg);

  // Meshtastic share URLs and any URL → redact wholesale.
  s = s.replace(/https?:\/\/\S+/gi, '[url]');
  // base64url / base64 blobs of length >= 12 (PSK is 16/32B b64 ~ 24/44 chars).
  s = s.replace(/[A-Za-z0-9_\-+/]{12,}={0,2}/g, '[redacted]');
  // hex blobs length >= 12 (keys, byte dumps).
  s = s.replace(/[0-9a-fA-F]{12,}/g, '[redacted]');
  // quoted strings (parsers love to echo the offending token in quotes).
  s = s.replace(/"[^"]*"/g, '"[redacted]"').replace(/'[^']*'/g, "'[redacted]'");
  // long runs of digits (coords, secs, ids) -> [n]
  s = s.replace(/\d{5,}/g, '[n]');

  s = s.trim();
  if (s.length > 200) s = s.slice(0, 200) + '…';
  return s;
}

/**
 * Reduce a full User-Agent to coarse browser + OS family. We deliberately drop
 * exact build numbers / device models to limit fingerprinting.
 */
export function sanitizeUserAgent(ua) {
  if (!ua) return 'unknown';
  let browser = 'unknown';
  // Order matters (Edge/Chrome/Safari overlap).
  if (/Edg\//.test(ua)) browser = 'Edge';
  else if (/OPR\/|Opera/.test(ua)) browser = 'Opera';
  else if (/Firefox\//.test(ua)) browser = 'Firefox';
  else if (/Chrome\//.test(ua)) browser = 'Chrome';
  else if (/Safari\//.test(ua)) browser = 'Safari';

  // major version only
  let ver = '';
  const m = ua.match(new RegExp(`(?:${browser === 'Edge' ? 'Edg' : browser}|Version)\\/(\\d+)`));
  if (m) ver = ' ' + m[1];

  let os = 'unknown';
  if (/Windows/.test(ua)) os = 'Windows';
  else if (/Android/.test(ua)) os = 'Android';
  else if (/iPhone|iPad|iOS/.test(ua)) os = 'iOS';
  else if (/Mac OS X|Macintosh/.test(ua)) os = 'macOS';
  else if (/Linux/.test(ua)) os = 'Linux';

  return `${browser}${ver} / ${os}`;
}

/**
 * Build ONE sanitized diagnostic entry from a context object.
 *
 * `ctx` may contain anything; we only ever read the whitelisted keys below and
 * sanitize each. Unknown keys are ignored — nothing is copied wholesale.
 */
export function buildEntry(ctx = {}, env = {}) {
  const step = STEP_VALUES.has(ctx.step) ? ctx.step : STEPS.UNKNOWN;

  const err = ctx.error;
  const errorName = err && err.name ? String(err.name).slice(0, 60) : (ctx.errorName ? String(ctx.errorName).slice(0, 60) : 'Error');
  const errorMessage = scrubMessage(err && err.message != null ? err.message : ctx.errorMessage);

  const format = ALLOWED_FORMATS.has(ctx.format) ? ctx.format : 'unknown';

  let ext = '';
  if (typeof ctx.fileExt === 'string' && ALLOWED_EXT.has(ctx.fileExt.toLowerCase())) {
    ext = ctx.fileExt.toLowerCase();
  } else if (typeof ctx.fileName === 'string') {
    // Derive extension ONLY — never store the name.
    const dot = ctx.fileName.lastIndexOf('.');
    const cand = dot >= 0 ? ctx.fileName.slice(dot).toLowerCase() : '';
    ext = ALLOWED_EXT.has(cand) ? cand : '';
  }

  let fileSize = null;
  if (typeof ctx.fileSize === 'number' && isFinite(ctx.fileSize) && ctx.fileSize >= 0) {
    fileSize = Math.round(ctx.fileSize);
  }

  return {
    ts: (env.now || (() => new Date()))().toISOString().replace(/\.\d{3}Z$/, 'Z'),
    version: env.version || DIAG_VERSION,
    browser: sanitizeUserAgent(env.userAgent),
    step,
    errorName,
    errorMessage,
    format,
    fileExt: ext,
    fileSize,
  };
}

/**
 * In-memory diagnostics buffer + report formatter. No persistence, no network.
 */
export class Diagnostics {
  constructor(env = {}) {
    this.entries = [];
    this.maxEntries = env.maxEntries || 25;
    this.env = {
      version: env.version || DIAG_VERSION,
      userAgent: env.userAgent || (typeof navigator !== 'undefined' ? navigator.userAgent : ''),
      now: env.now || (() => new Date()),
    };
  }

  record(ctx) {
    const entry = buildEntry(ctx, this.env);
    this.entries.push(entry);
    if (this.entries.length > this.maxEntries) {
      this.entries.splice(0, this.entries.length - this.maxEntries);
    }
    return entry;
  }

  clear() { this.entries = []; }

  hasErrors() { return this.entries.length > 0; }

  /**
   * Produce the copyable, human-readable, SANITIZED report. Built only from
   * whitelisted entry fields above.
   */
  generateReport() {
    const header = [
      'AZ Meshtastic Config Checker — diagnostic report',
      `tool version: ${this.env.version}`,
      `browser: ${sanitizeUserAgent(this.env.userAgent)}`,
      `generated: ${this.env.now().toISOString().replace(/\.\d{3}Z$/, 'Z')}`,
      'NOTE: no config contents, channel names, keys, or input data are included.',
      '',
    ];
    if (this.entries.length === 0) {
      return header.concat(['(no errors recorded)']).join('\n');
    }
    const lines = this.entries.map((e, i) => {
      const meta = [];
      if (e.format && e.format !== 'unknown') meta.push(`format=${e.format}`);
      if (e.fileExt) meta.push(`ext=${e.fileExt}`);
      if (e.fileSize != null) meta.push(`size=${e.fileSize}B`);
      const tail = meta.length ? ` [${meta.join(' ')}]` : '';
      return `#${i + 1} ${e.ts} step=${e.step} ${e.errorName}: ${e.errorMessage}${tail}`;
    });
    return header.concat(lines).join('\n');
  }
}

// Convenience singleton for the app (browser only — guarded so Node tests can
// construct their own with injected env).
export const diagnostics = typeof window !== 'undefined' ? new Diagnostics() : null;
