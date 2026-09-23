/*
 * Read a node's configuration over USB (#116).
 *
 * The transport half. The framing lives in `serial-frames.js`; this is
 * the conversation on top of it:
 *
 *   1. open the port at 115200
 *   2. send `ToRadio { want_config_id: <random> }`
 *   3. read `FromRadio` frames until `config_complete_id` matches
 *   4. hand back what arrived, shaped like a parsed config file
 *
 * **The port is the resource that matters.** A port left open blocks
 * the Meshtastic app and the CLI, so every path out of here closes it
 * -- success, timeout, protocol error, and the reader navigating away.
 *
 * **Nothing leaves the browser.** No fetch, no worker, no storage. The
 * config that comes back contains channel PSKs, the MQTT password and
 * the admin keys, and the page's promise is that they stay here.
 * `test_serial_read.py` asserts this file reaches for none of those.
 */

import { FrameDecoder, frame } from './serial-frames.js';

/** What the firmware runs at. Not configurable: the protocol fixes it. */
export const BAUD_RATE = 115200;

/*
 * How long to wait for `config_complete_id` before giving up.
 *
 * A node answers `want_config` with a burst -- my_info, metadata, the
 * config sections, the module config sections, then one channel per
 * slot. On a slow board that is a few seconds. Ten is comfortably past
 * it and still short enough that somebody does not think the page has
 * hung.
 */
export const CONFIG_TIMEOUT_MS = 10_000;

/*
 * The sections a `Config` and a `ModuleConfig` can carry.
 *
 * Seeded empty on every read so a node that does not report a section
 * does not make the checker throw on a field of it.
 */
const CONFIG_SECTIONS = Object.freeze([
  'device', 'position', 'power', 'network', 'display', 'lora', 'bluetooth', 'security',
]);
const MODULE_SECTIONS = Object.freeze([
  'mqtt', 'serial', 'externalNotification', 'storeForward', 'rangeTest', 'telemetry',
  'cannedMessage', 'audio', 'remoteHardware', 'neighborInfo', 'ambientLighting',
  'detectionSensor', 'paxcounter',
]);

/** The sentinel the read race resolves to when the clock wins. */
const TIMED_OUT = Symbol('timed out');

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

/** True when this browser can talk to a node at all. */
export function serialSupported() {
  return typeof navigator !== 'undefined' && 'serial' in navigator;
}

/**
 * Why the button is not offered, in one line a reader can act on.
 *
 * Returns null when it IS offered. Web Serial needs a secure context
 * as well as the API, and `localhost` counts as secure -- so a
 * developer does not see a message a visitor would.
 */
export function serialUnavailableReason() {
  if (typeof window !== 'undefined' && window.isSecureContext === false) {
    return 'USB needs a secure connection (https). You can still upload an exported config.';
  }
  if (!serialSupported()) {
    return 'USB needs Chrome or Edge on a computer. You can still upload an exported config.';
  }
  return null;
}

/**
 * One `FromRadio` exchange with a node.
 *
 * `port` is a Web Serial port, already chosen by the reader through
 * `navigator.serial.requestPort()` -- that call must happen in a click
 * handler, so it is the caller's job, not this function's.
 *
 * `decode` turns payload bytes into an object; injected rather than
 * imported so the tests can drive this without protobuf.js, and so the
 * descriptor stays the caller's choice.
 *
 * `onProgress` is called with a short sentence as things arrive. The
 * issue asks for progress, and a burst of thirty frames with no sign
 * of life reads as a hang.
 */
export async function readConfig(port, {
  decode,
  encodeWantConfig,
  wantConfigId = Math.floor(Math.random() * 0x7fffffff),
  timeoutMs = CONFIG_TIMEOUT_MS,
  onProgress = () => {},
  now = () => Date.now(),
} = {}) {
  await port.open({ baudRate: BAUD_RATE });
  const decoder = new FrameDecoder();
  const collected = {
    channels: [],
    // Every section seeded empty, because a node only sends the ones
    // it has and `ConfigChecker` reads fields off them unguarded --
    // `moduleConfig.mqtt.enabled` on a node that reported no MQTT
    // section threw `Cannot read properties of undefined`, which
    // reaches the reader as a stack trace rather than an answer.
    //
    // An absent section and an empty one mean the same thing here: no
    // settings reported. That is not the same as "the defaults", and
    // the checker already treats a missing field as unset.
    config: Object.fromEntries(CONFIG_SECTIONS.map((name) => [name, {}])),
    moduleConfig: Object.fromEntries(MODULE_SECTIONS.map((name) => [name, {}])),
  };
  let reader = null;
  let writer = null;
  try {
    writer = port.writable.getWriter();
    await writer.write(frame(encodeWantConfig(wantConfigId)));
    writer.releaseLock();
    writer = null;
    onProgress('Asked the node for its configuration…');

    reader = port.readable.getReader();
    const deadline = now() + timeoutMs;
    for (;;) {
      /*
       * The read is RACED against the deadline, not checked before it.
       *
       * Checking between reads looks equivalent and is not: a node
       * that goes quiet never resolves `read()` at all, so the loop
       * blocks and the deadline is never reached. The page then hangs
       * with no error, which is the opposite of what #116 asks for.
       *
       * Found by a test with a port that never answers -- the first
       * version of this function hung it forever.
       */
      const remaining = deadline - now();
      const result = remaining <= 0 ? TIMED_OUT : await Promise.race([
        reader.read(),
        sleep(remaining).then(() => TIMED_OUT),
      ]);
      if (result === TIMED_OUT) {
        throw new Error(
          'The node did not finish sending its configuration in time. '
          + 'Unplug it, plug it back in, and try again.',
        );
      }
      const { value, done } = result;
      if (done) throw new Error('The node closed the connection before it finished.');
      for (const payload of decoder.push(value)) {
        const message = decode(payload);
        if (!message) continue;
        if (message.configCompleteId === wantConfigId) {
          onProgress('Done.');
          return collected;
        }
        absorb(collected, message, onProgress);
      }
    }
  } finally {
    // Every exit closes the port. A port left open blocks the
    // Meshtastic app and the CLI, and the reader has no way to know.
    if (writer) { try { writer.releaseLock(); } catch { /* already gone */ } }
    if (reader) {
      try { await reader.cancel(); } catch { /* already gone */ }
      try { reader.releaseLock(); } catch { /* already gone */ }
    }
    try { await port.close(); } catch { /* already closed */ }
  }
}

/**
 * Fold one `FromRadio` into the shape `ConfigChecker` already reads.
 *
 * The point of this function is that the checker and the fixer run
 * unchanged on a config that arrived over USB -- #116 asks for exactly
 * that, and a second code path for serial configs would be a second
 * place for the rules to drift.
 */
function absorb(into, message, onProgress) {
  if (message.myInfo) {
    into.myInfo = message.myInfo;
    onProgress('Reading configuration…');
  }
  if (message.metadata) into.metadata = message.metadata;
  if (message.channel) into.channels.push(message.channel);
  if (message.config) {
    // A `Config` arrives one section at a time, each in its own field.
    for (const [section, value] of Object.entries(message.config)) {
      if (value && typeof value === 'object') into.config[section] = value;
    }
  }
  if (message.moduleConfig) {
    for (const [section, value] of Object.entries(message.moduleConfig)) {
      if (value && typeof value === 'object') into.moduleConfig[section] = value;
    }
  }
}
