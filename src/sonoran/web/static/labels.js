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
   * The spelling is British, like the rest of the interface: the mesh
   * graph legend already says "Neighbour report".
   */
  const PORTNUM_LABELS = new Map([
    ['NEIGHBORINFO_APP', 'Neighbour info'],
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

  /** A port number name as a label, without the shouting.
   *
   * The argument may be the enum name, a number, or nothing at all. A
   * packet with no port number is still a packet, so it says so rather
   * than showing an empty cell.
   */
  function portnumLabel(portnum) {
    if (portnum == null || portnum === '') return 'Packet';
    const key = String(portnum);
    return PORTNUM_LABELS.get(key) || sentence(key.replace(/_APP$/, ''));
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
  function preferredPreset(items, nameOf = (item) => item) {
    const list = [...(items || [])];
    if (!list.length) return null;
    const wanted = (window.SONORAN && window.SONORAN.defaultPreset) || '';
    if (!wanted) return list[0];
    const match = list.find((item) => String(nameOf(item) ?? '') === wanted);
    return match === undefined ? list[0] : match;
  }

  window.SonoranLabels = {
    ROLES, roleLabel, portnumLabel, portnumWire, sentence, preferredPreset,
  };
}());
