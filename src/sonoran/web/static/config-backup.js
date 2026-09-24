/*
 * A backup the Meshtastic CLI can actually restore from (#117).
 *
 * The page offered "Download a backup of the current config first",
 * ticked by default, immediately above a control that writes to
 * somebody's radio. The file it produced could not restore anything.
 *
 * Found on real hardware, not here. `ConfigFixer.exportFixed` writes a
 * DeviceProfile-shaped document with top-level `device:`, `lora:` and
 * `module:`. `meshtastic --configure` reads **`config:`,
 * `module_config:`, `owner` and `channel_url`** and ignores everything
 * else, so the file loaded cleanly and restored nothing. It also
 * dropped the channels, the keys, bandwidth, spreadFactor and txPower,
 * wrote literal `undefined` values, and its header pointed at
 * `--import-config`, which is not a flag the CLI has.
 *
 * A backup that silently restores nothing is worse than no backup:
 * the tick box is what makes the write feel safe enough to do.
 *
 * This writes what the CLI reads, from what the USB read actually
 * returned, and refuses rather than writing a file that would not
 * work.
 */

import { encodeChannelUrl } from './vendor/config-checker/js/channel-url.js';

/* The keys `meshtastic --configure` consumes. Anything else in the
 * document is ignored by the CLI, so putting it there is decoration at
 * best and a false promise at worst. */
export const RESTORABLE_KEYS = ['owner', 'channel_url', 'config', 'module_config'];

/** snake_case, because that is what the CLI's YAML uses. */
function snake(name) {
  return String(name).replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
}

/*
 * YAML for plain nested objects, which is all a config is.
 *
 * Written here rather than pulled in: a config is scalars, nested
 * objects and one string list, and a dependency for that would be more
 * surface than the job needs. Anything it cannot represent faithfully
 * it refuses, rather than guessing -- see `writeValue`.
 */
function writeValue(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null;
    return String(value);
  }
  if (typeof value === 'string') {
    // Quote anything that could be read as another type, or that
    // carries a character YAML would take as syntax.
    if (value === '' || /^[\s]|[\s]$|[:#\-{}[\],&*?|>'"%@`]|^(?:true|false|null|~|\d)/i.test(value)) {
      return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
    }
    return value;
  }
  return null;
}

function writeBlock(value, indent) {
  const pad = '  '.repeat(indent);
  const lines = [];
  for (const [key, raw] of Object.entries(value)) {
    if (raw === null || raw === undefined) continue;
    const name = snake(key);
    if (Array.isArray(raw)) continue;
    if (typeof raw === 'object') {
      const inner = writeBlock(raw, indent + 1);
      // An empty section is not written. The CLI treats a present but
      // empty section as "set this section to nothing", which is the
      // same class of mistake as the whole-section write bug.
      if (inner.length) lines.push(`${pad}${name}:`, ...inner);
      continue;
    }
    const scalar = writeValue(raw);
    if (scalar !== null) lines.push(`${pad}${name}: ${scalar}`);
  }
  return lines;
}

/**
 * Build a `meshtastic --configure` document from a USB read.
 *
 * Throws rather than returning a file that would not restore. The
 * caller shows the message; a refusal a person can read beats a
 * download that quietly does nothing.
 */
export function buildBackup(read, { now = new Date() } = {}) {
  if (!read || typeof read !== 'object') {
    throw new Error('There is no config to back up.');
  }
  const config = read.config && Object.keys(read.config).length ? read.config : null;
  const moduleConfig = read.moduleConfig && Object.keys(read.moduleConfig).length
    ? read.moduleConfig : null;
  if (!config && !moduleConfig) {
    throw new Error(
      'The node\'s settings were not read, so a backup would be empty. Read the node again.',
    );
  }

  const lines = [
    '# Meshtastic configuration backup',
    `# Written by the azmsh.net config check on ${now.toISOString()}`,
    '#',
    '# Restore with:',
    '#     meshtastic --port <port> --configure this-file.yaml',
    '#',
    '# This holds the settings the CLI restores. It does NOT hold the',
    '# private key or the admin keys: a node does not report them and',
    '# nothing here can invent them.',
  ];

  const owner = read.myInfo && read.myInfo.longName;
  if (owner) lines.push(`owner: ${writeValue(owner)}`);
  const short = read.myInfo && read.myInfo.shortName;
  if (short) lines.push(`owner_short: ${writeValue(short)}`);

  // The channels, as the one string the CLI accepts for them.
  if (Array.isArray(read.channels) && read.channels.length && config && config.lora) {
    try {
      const url = encodeChannelUrl(read.channels, config.lora);
      if (url) lines.push(`channel_url: ${writeValue(url)}`);
    } catch {
      // A channel set this cannot encode is left out, and said so in
      // the header, rather than written wrong.
      lines.push('# The channels could not be encoded, so they are not in this file.');
    }
  }

  if (config) {
    const body = writeBlock(config, 1);
    if (body.length) lines.push('config:', ...body);
  }
  if (moduleConfig) {
    const body = writeBlock(moduleConfig, 1);
    if (body.length) lines.push('module_config:', ...body);
  }

  const text = `${lines.join('\n')}\n`;
  if (!/\nconfig:\n|\nmodule_config:\n/.test(text)) {
    throw new Error('The backup would have held no settings, so it was not written.');
  }
  return {
    data: text,
    filename: `meshtastic-backup-${now.toISOString().slice(0, 19).replace(/[:T]/g, '')}.yaml`,
    mimeType: 'text/yaml',
  };
}

export const ConfigBackup = { buildBackup, RESTORABLE_KEYS };
