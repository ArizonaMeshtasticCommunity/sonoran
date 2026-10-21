/*
 * The words the dashboard uses for protocol values.
 *
 * A Meshtastic enum is a wire value. `CLIENT_MUTE` and
 * `NEIGHBORINFO_APP` are exact, and a reader who has never configured a
 * node cannot read either one. The house answer is already set by
 * `roleCell`: print a readable label, and keep the exact value on the
 * element, so a person who wants the enum hovers and gets it.
 *
 * This file holds the tables, because three files need them and each
 * one used to hold its own. app.js had `roleLabel` and the tables did
 * not call it; app.js also had `portnumLabel` and `familyLabel`, which
 * were the same function written twice; gaps.js had neither and printed
 * the raw enum beside a page that printed the label. Same value, three
 * spellings, on pages a reader moves between.
 *
 * It loads before every file that reads it. See the comment beside the
 * script tags in index.html, and AGENTS.md 9.14.2 for why order matters
 * on this page.
 *
 * Two rules for anything added here:
 *
 * 1. A label is a translation, never a correction. If a label would say
 *    something the enum does not, the enum is right and the label is a
 *    bug. `RAK4631` is a product name, so it is not in this file at all:
 *    prettifying a board name invents a model that nobody sells.
 * 2. The exact value stays reachable. Every caller that prints a label
 *    puts the wire value in `title`.
 */

'use strict';

(function () {
  /*
   * Every device role the firmware knows, in the order the legend shows
   * them: the routing roles first, then the clients, then the rest.
   *
   * The colours live in app.css so the stylesheet stays the one source
   * of the palette. A role that is not in this list still draws, in the
   * muted colour, so a new firmware role never leaves an invisible node.
   */
  const ROLES = [
    { key: 'ROUTER', label: 'Router' },
    { key: 'ROUTER_LATE', label: 'Router late' },
    { key: 'ROUTER_CLIENT', label: 'Router client' },
    { key: 'REPEATER', label: 'Repeater' },
    { key: 'CLIENT', label: 'Client' },
    { key: 'CLIENT_MUTE', label: 'Client mute' },
    { key: 'CLIENT_BASE', label: 'Client base' },
    { key: 'CLIENT_HIDDEN', label: 'Client hidden' },
    { key: 'CLIENT_TAK', label: 'Client TAK' },
    { key: 'TAK_TRACKER', label: 'TAK tracker' },
    { key: 'TAK_PLUGIN', label: 'TAK plugin' },
    { key: 'ATAK_PLUGIN', label: 'ATAK plugin' },
    { key: 'TRACKER', label: 'Tracker' },
    { key: 'SENSOR', label: 'Sensor' },
    { key: 'LOST_AND_FOUND', label: 'Lost and found' },
  ];

  const ROLE_LABELS = new Map(ROLES.map((role) => [role.key, role.label]));

  /** The label for a role, or a readable form of an unknown one.
   *
   * A role of NULL is not the same as a role this table does not know.
   * The first is a node that reported no role, which AGENTS.md 9.22
   * says must never be read as an unknown to include. The second is a
   * firmware newer than this file, and it still gets a readable form.
   */
  function roleLabel(role) {
    if (!role) return 'No role reported';
    return ROLE_LABELS.get(role) || sentence(role);
  }

  /*
   * The packet families the mesh sends, by their port number name.
   *
   * Only the ones where the general rule below reads badly are listed.
   * `NEIGHBORINFO` runs two words together and `STORE_FORWARD` drops a
   * word, so both are spelled out. The rest fall through to `sentence`.
   *
   * "Neighbor", not "Neighbour". This label used to be British, to
   * match the rest of the interface and the embedded mesh-graph legend.
   * #240 asked for the American spelling, so every visible use of the
   * word changed together: a page that says "Neighbor info" in the
   * firehose and "Neighbours it reported" one click later is worse than
   * either spelling on its own. The mesh-graph legend is a separate
   * application in an iframe and still says "Neighbour report", which
   * this repository cannot change.
   *
   * The protocol keeps its own spelling everywhere it is a name and not
   * a word: `NEIGHBORINFO_APP` here, `neighbor_metrics` in the database,
   * `neighbor_name` in the API.
   */
  const PORTNUM_LABELS = new Map([
    ['NEIGHBORINFO_APP', 'Neighbor info'],
    ['NODEINFO_APP', 'Node info'],
    ['TEXT_MESSAGE_APP', 'Text message'],
    ['TEXT_MESSAGE_COMPRESSED_APP', 'Text message, compressed'],
    ['STORE_FORWARD_APP', 'Store and forward'],
    ['RANGE_TEST_APP', 'Range test'],
    ['DETECTION_SENSOR_APP', 'Detection sensor'],
    ['REMOTE_HARDWARE_APP', 'Remote hardware'],
    ['IP_TUNNEL_APP', 'IP tunnel'],
    ['MAP_REPORT_APP', 'Map report'],
    ['KEY_VERIFICATION_APP', 'Key verification'],
    ['POWERSTRESS_APP', 'Power stress'],
    ['ATAK_FORWARDER', 'ATAK forwarder'],
    ['ATAK_PLUGIN', 'ATAK plugin'],
    ['PAXCOUNTER_APP', 'Paxcounter'],
    ['ZPS_APP', 'ZPS'],
  ]);

  /*
   * Names for the things a `portnum` of 0 turns out to be (#157).
   *
   * 0 is both the real port `UNKNOWN_APP` and the sentinel the ingest
   * writes when it could not read a packet. A census against the live
   * database found that bucket was 91.7% PKI direct messages and 8.2%
   * packets on a channel with no key, so calling all of it "Unknown
   * app" was right about roughly one packet in a thousand -- and it
   * told operators their mesh was full of unknown traffic when it was
   * full of direct messages.
   *
   * Kept in their own table, NOT in `PORTNUM_LABELS`. That table is
   * also read backwards by `portnumWire` to turn what somebody types
   * in the firehose filter into a value the API takes. These are not
   * port numbers, so the API answers 422 for them, and putting them in
   * there would offer the filter three phrases that cannot work.
   */
  const TRAFFIC_LABELS = new Map([
    ['UNREADABLE_PKI', 'Direct message, encrypted'],
    ['UNREADABLE_NO_KEY', 'No key for this channel'],
    ['UNREADABLE_UNRECORDED', 'Unreadable, reason not recorded'],
  ]);

  /** A port number name as a label, without the shouting.
   *
   * The argument may be the enum name, a number, or nothing at all. A
   * packet with no port number is still a packet, so it says so rather
   * than showing an empty cell.
   */
  function portnumLabel(portnum) {
    if (portnum == null || portnum === '') return 'Packet';
    const key = String(portnum);
    return TRAFFIC_LABELS.get(key)
      || PORTNUM_LABELS.get(key)
      || sentence(key.replace(/_APP$/, ''));
  }

  /** `CLIENT_MUTE` as `Client mute`: first letter up, the rest down. */
  function sentence(value) {
    const words = String(value).replace(/_/g, ' ').trim().toLowerCase();
    if (!words) return '';
    return words[0].toUpperCase() + words.slice(1);
  }

  /*
   * The reverse of `portnumLabel`, for the one field a person types
   * into.
   *
   * The firehose filter is passed straight to the API, which takes a
   * number or the exact protobuf name and answers 422 for anything
   * else. So the field said "Port number or name", which is the API's
   * own vocabulary printed at the reader, and typing `position` failed.
   *
   * This translates what a person is likely to type. It does not widen
   * what the API accepts and it does not guess: an answer it does not
   * recognise is passed through unchanged, and the API still refuses it.
   */
  const WIRE_BY_LABEL = new Map();
  for (const [key, label] of PORTNUM_LABELS) WIRE_BY_LABEL.set(label.toLowerCase(), key);

  function portnumWire(text) {
    const value = String(text ?? '').trim();
    if (!value) return '';
    if (/^[0-9]+$/.test(value)) return value;
    const named = WIRE_BY_LABEL.get(value.toLowerCase());
    if (named) return named;
    const upper = value.toUpperCase().replace(/[\s-]+/g, '_');
    return upper.endsWith('_APP') ? upper : `${upper}_APP`;
  }

  /*
   * Which preset a picker opens on (#177).
   *
   * Every page used to open on whichever preset came first in the data
   * -- busiest, or first in a list -- so the landing view moved with
   * the traffic rather than with what the community runs. MediumFast
   * is this mesh's primary preset and it should be the one you land
   * on.
   *
   * The name comes from the server (`window.SONORAN.defaultPreset`)
   * rather than being written here, because the preference belongs to
   * a deployment: another mesh running LongFast should not have to
   * patch JavaScript.
   *
   * `items` is a list of anything carrying a preset name, and `nameOf`
   * says how to read it, because the four callers hold four shapes --
   * `{channel}`, `{preset}`, a plain string, an `<option>`.
   *
   * **Falls back to the first item when the preferred preset is not
   * present**, which is the old behaviour. A deployment that does not
   * run MediumFast, or a window with no MediumFast traffic in it, must
   * not land on an empty page to honour a preference.
   */
  /*
   * An automation tapback: a node saying how a message reached it.
   *
   * `*` direct, `1` to `7` the hop count (`7` is seven or more). A bare
   * digit is accepted, because some clients drop the keycap.
   *
   * WHAT IS DELIBERATELY NOT HERE, and it is a decision rather than an
   * oversight -- `docs/design/2026-09-26-ux-overhaul.md` §2.1. The
   * automation engine also sends `#` for "arrived over MQTT", and older
   * builds sent `0` or a direct hit (U+1F3AF); both are documented in
   * `docs/features/automation-engine.md` in Yeraze/meshmonitor. Will chose
   * on 2026-09-26 to recognise only the marks operators see on their own
   * radios, so an MQTT ack and an ack from an older node are now drawn as
   * reactions a person chose. That is the accepted cost. Do not "fix" it
   * back without checking that decision.
   */
  const AUTO_ACK_MARK = /^(?:[1-7*]\uFE0F?\u20E3?)$/u;

  /*
   * The channels where such a mark means a node rather than a person.
   *
   * In **Trivia** the digits are people answering the quiz, which is the
   * bug this rule fixes: an answer was being drawn as a delivery receipt.
   *
   * A literal list, not "presets plus core channels", although the server
   * marks both. azmsh is core and so is any channel the operators add
   * next, so the derived rule would quietly start claiming auto-acks on a
   * channel nobody had thought about. Three names that have to be edited
   * on purpose is the safer shape for a rule that puts words in somebody's
   * mouth.
   */
  const AUTO_ACK_CHANNELS = new Set(['MediumFast', 'LongFast', 'azmsh']);

  /** True when this tapback, on this channel, is a delivery receipt. */
  function isAutoAck(emoji, channel) {
    if (!AUTO_ACK_CHANNELS.has(String(channel ?? ''))) return false;
    return AUTO_ACK_MARK.test(String(emoji ?? '').trim());
  }

  /** What one auto-ack mark says about how the message arrived. */
  function autoAckMeaning(emoji) {
    const mark = String(emoji ?? '').trim().charAt(0);
    if (mark === '*') return 'direct';
    if (mark === '7') return '7 or more hops';
    return mark === '1' ? '1 hop' : `${mark} hops`;
  }

  /**
   * A preset's wire name, made readable: `MediumFast` -> `Medium Fast`.
   *
   * DERIVED from the name rather than looked up in a table. The server
   * has a label for every preset in `radio/presets.py` ("Medium fast"),
   * and copying those nine strings here would be a second list to keep
   * in step -- the failure this repository has already had with the
   * antenna and cable catalogues, which is why those are fetched.
   *
   * The cost of deriving is capitalisation: this says "Medium Fast" where
   * the server says "Medium fast". That is a visible difference and a
   * deliberate one, because the alternative is two lists that can
   * disagree about which presets exist at all.
   *
   * Unknown or empty names come back unchanged, so a new preset shows its
   * wire name rather than nothing.
   */
  function presetLabel(name) {
    const text = String(name ?? '').trim();
    if (!text) return '';
    return text.replace(/([a-z0-9])([A-Z])/g, '$1 $2');
  }

  function preferredPreset(items, nameOf = (item) => item) {
    const list = [...(items || [])];
    if (!list.length) return null;
    /*
     * The READER'S choice first, then the deployment's default.
     *
     * `SonoranPreset` holds the reader's choice, made on the Settings
     * page (the menu's selector is gone, part of #383). Consulting it
     * here rather than at each call site means every caller of this
     * helper follows the choice without knowing the store exists -- which
     * is how the graph tab strip and the coverage page started obeying
     * it without being rewritten.
     *
     * Guarded rather than assumed. If `preset.js` is ever absent -- a
     * future document that loads this file alone, or a reordered script
     * tag -- a missing store falls back to the server default, which is
     * exactly what this function did before the menu existed. Checked
     * before writing this: the embed document loads neither file, so it
     * is not the reason; the reason is that a helper four callers depend
     * on should not need a second script to work.
     */
    const store = window.SonoranPreset;
    // `single`, not `current`: these callers draw one preset, and under
    // "All presets" that is the deployment's default.
    const wanted = (store && (store.single ? store.single() : store.current()))
      || (window.SONORAN && window.SONORAN.defaultPreset)
      || '';
    if (!wanted) return list[0];
    const match = list.find((item) => String(nameOf(item) ?? '') === wanted);
    return match === undefined ? list[0] : match;
  }

  window.SonoranLabels = {
    ROLES, roleLabel, portnumLabel, portnumWire, sentence, preferredPreset, presetLabel, isAutoAck, autoAckMeaning,
  };
}());
