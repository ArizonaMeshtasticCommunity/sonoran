/*
 * The words a Meshtastic newcomer meets on this site, in plain words.
 *
 * One place for every explanation (AGENTS.md 3B, docs/NEWCOMER.md). An
 * element with `data-term="snr"` gets a button that opens the entry
 * below; `revealHints` in app.js builds it with the same popover as the
 * column hints, so there is one pattern on the site and not two.
 *
 * The reader: somebody in their first weeks of Meshtastic. They know
 * what a node and a message are. They do not know SNR, hops or presets.
 *
 * Each entry:
 *
 *   label  The word as the reader sees it.
 *   plain  One to three short sentences, no other jargon. Say what it
 *          is and why the reader cares. No numbers without a source.
 *   more   Optional. A meshtastic.org or Meshtastic GitHub page.
 *   words  The spellings that make on-screen text need this tooltip.
 *          `tests/unit/test_newcomer_glossary.py` reads them. Leave it
 *          empty for a word too common to mark at every use, such as
 *          "channel": then mark the first use in a panel by hand.
 *
 * `docs/GLOSSARY.md` is made from this file:
 *
 *     uv run python -m tools.newcomer_check --write-doc
 *
 * Sources for the facts, read 2026-10-21:
 *   LoRa config     https://meshtastic.org/docs/configuration/radio/lora/
 *   Device roles    https://meshtastic.org/docs/configuration/radio/device/
 *   Channels        https://meshtastic.org/docs/configuration/radio/channels/
 *   Mesh algorithm  https://meshtastic.org/docs/overview/mesh-algo/
 *   Encryption      https://meshtastic.org/docs/overview/encryption/
 *   Modules         traceroute, neighbor-info, mqtt and telemetry pages
 *   Telemetry       meshtastic/protobufs telemetry.proto DeviceMetrics
 *                   (channel_utilization, air_util_tx)
 */

'use strict';

(function () {
  const LORA = 'https://meshtastic.org/docs/configuration/radio/lora/';
  const ROLES = 'https://meshtastic.org/docs/configuration/radio/device/';
  const CHANNELS = 'https://meshtastic.org/docs/configuration/radio/channels/';
  const ALGO = 'https://meshtastic.org/docs/overview/mesh-algo/';
  const RADIO = 'https://meshtastic.org/docs/overview/radio-settings/';

  const TERMS = {
    // ---- Signal
    snr: {
      label: 'SNR (signal-to-noise ratio)',
      plain: 'How far a signal stands above the background noise, in dB. Higher is better. '
        + 'LoRa can still decode a signal a little below the noise, so a small negative SNR can still work.',
      more: RADIO,
      words: ['SNR', 'signal-to-noise'],
    },
    rssi: {
      label: 'RSSI (signal strength)',
      plain: 'How strong the signal was when it reached the receiving radio, in dBm. '
        + 'Closer to zero is stronger, so -70 dBm is a stronger signal than -110 dBm. '
        + 'A strong signal can still be noisy, so read it together with SNR.',
      words: ['RSSI'],
    },
    dbm: {
      label: 'dB and dBm',
      plain: 'dBm is a power level, and dB is a difference between two levels. '
        + 'Every 3 dB is about twice the power, and every 10 dB is ten times.',
      words: ['dBm'],
    },
    sensitivity: {
      label: 'Sensitivity',
      plain: 'The weakest signal a radio can still decode, in dBm. '
        + 'It depends on the preset: a slower preset hears weaker signals, so it reaches further.',
      more: RADIO,
      words: ['sensitivity'],
    },
    'signal-margin': {
      label: 'Signal margin',
      plain: 'How far above the radio\'s limit a signal is, in dB. '
        + 'A link with more margin keeps working when the weather, leaves or a moving person weaken it.',
      words: ['signal floor', 'margin', 'above the limit'],
    },
    'noise-floor': {
      label: 'Noise floor',
      plain: 'The background radio noise a radio hears when no node is sending. '
        + 'A higher noise floor hides weak signals, so the radio hears less.',
      words: ['noise floor'],
    },
    'antenna-gain': {
      label: 'Antenna gain (dBi)',
      plain: 'How much an antenna focuses its signal toward the horizon instead of up and down, in dBi. '
        + 'More gain reaches further along the ground, but less above and below the antenna.',
      words: ['dBi', 'antenna gain'],
    },
    lora: {
      label: 'LoRa',
      plain: 'The long-range, low-power radio method Meshtastic uses. '
        + 'It is slow, but it can reach many kilometres with a small battery.',
      words: ['LoRa'],
    },

    // ---- How packets travel
    packet: {
      label: 'Packet',
      plain: 'One transmission on the mesh. A text message is one kind of packet; '
        + 'positions, battery readings and node introductions are other kinds.',
      words: [],
    },
    'packet-type': {
      label: 'Packet type',
      plain: 'What a packet carries, such as a text message, a position or telemetry. '
        + 'Meshtastic marks every packet with a number for this, the port number (portnum).',
      words: ['packet type', 'portnum'],
    },
    hop: {
      label: 'Hop',
      plain: 'One relay: a node hears a packet and sends it on. '
        + 'A packet heard straight from the sender used no hops.',
      more: ALGO,
      words: ['hop', 'hops', 'relayed'],
    },
    'hop-limit': {
      label: 'Hop limit',
      plain: 'How many times a packet may be relayed. It is 3 by default and at most 7. '
        + 'Each relay takes one off, and at zero no node sends it on again.',
      more: `${LORA}#max-hops`,
      words: ['hop limit', 'hops allowed', 'max hops'],
    },
    direct: {
      label: 'Heard direct',
      plain: 'Heard straight from the sending node, with no relay between them. '
        + 'Only a direct reading says how well those two radios hear each other.',
      words: ['heard direct', 'direct link'],
    },
    'relay-node': {
      label: 'Relay node',
      plain: 'The node that last sent this copy on. A packet keeps only the last byte of that '
        + 'node\'s number, so Sonoran can often only list the nodes it could be.',
      words: ['relay node', 'last relay'],
    },
    gateway: {
      label: 'Gateway (MQTT)',
      plain: 'A node that also sends what it hears to a server on the internet, over MQTT. '
        + 'Sonoran sees the mesh only through gateways: a packet that no gateway heard is not here.',
      more: 'https://meshtastic.org/docs/configuration/module/mqtt/',
      words: ['gateway', 'MQTT gateway'],
    },
    mqtt: {
      label: 'MQTT',
      plain: 'The internet messaging system that gateways use to copy mesh traffic to a server. '
        + 'Sonoran reads its packets from the azmsh.net MQTT server.',
      more: 'https://meshtastic.org/docs/configuration/module/mqtt/',
      words: ['MQTT'],
    },
    upload: {
      label: 'Upload',
      plain: 'One copy of a packet that one gateway sent to the server. '
        + 'A gateway can upload the same packet more than once, so a count of uploads is not a count of gateways.',
      words: ['upload', 'uploads', 'uploaded'],
    },
    'channel-utilization': {
      label: 'Channel utilization',
      plain: 'How busy the radio frequency is: the share of time the radio heard any signal, '
        + 'from every node and from noise. When it is high, nodes send less to keep the air clear.',
      more: 'https://meshtastic.org/docs/configuration/module/telemetry/',
      words: ['channel utilization', 'channel utilisation', 'channel use', 'ChUtil'],
    },
    airtime: {
      label: 'Airtime (TX utilization)',
      plain: 'The share of the last hour that this node spent sending. '
        + 'A high number means the node talks a lot and takes air time from others.',
      more: 'https://meshtastic.org/docs/configuration/module/telemetry/',
      words: ['airtime', 'air time', 'TX utilization', 'air util'],
    },

    // ---- Presets and channels
    'modem-preset': {
      label: 'Modem preset',
      plain: 'The radio settings a mesh agrees on, such as LongFast or MediumFast. '
        + 'Each one trades range for speed. A node only hears nodes on the same preset.',
      more: `${LORA}#modem-preset`,
      words: ['modem preset', 'preset'],
    },
    'long-fast': {
      label: 'LongFast',
      plain: 'The preset a new node uses until somebody changes it. '
        + 'It reaches far, but each message takes a long time on the air.',
      more: `${LORA}#modem-preset`,
      words: ['LongFast', 'Long Fast'],
    },
    'medium-fast': {
      label: 'MediumFast',
      plain: 'A preset that sends faster than LongFast, with a little less range. '
        + 'Each message takes less air time, which helps a busy mesh.',
      more: `${LORA}#modem-preset`,
      words: ['MediumFast', 'Medium Fast'],
    },
    'frequency-slot': {
      label: 'Frequency slot',
      plain: 'The exact frequency in the band that a node uses. '
        + 'Two nodes on the same preset hear each other only if they also use the same slot.',
      more: `${LORA}#frequency-slot`,
      words: ['frequency slot'],
    },
    channel: {
      label: 'Channel',
      plain: 'A named group for messages, with its own key. Many channels can share one preset, '
        + 'so a channel is not the same as a preset.',
      more: CHANNELS,
      words: [],
    },
    encryption: {
      label: 'Encrypted',
      plain: 'The contents are scrambled with a key, so only nodes with that key can read them. '
        + 'The key of the default channel is public, so anybody can read what is sent on it.',
      more: 'https://meshtastic.org/docs/overview/encryption/',
      words: ['encrypted', 'encryption', 'undecryptable', 'PSK'],
    },
    pki: {
      label: 'PKI (private direct message)',
      plain: 'A direct message locked with a key that only the sender and the receiver can make. '
        + 'Nobody else can read it, Sonoran included.',
      more: 'https://meshtastic.org/docs/overview/encryption/',
      words: ['PKI', 'public key'],
    },

    // ---- Nodes
    'node-id': {
      label: 'Node ID',
      plain: 'The node\'s own number, written after a "!", such as !a1b2c3d4. '
        + 'It does not change when the owner renames the node.',
      words: ['node ID'],
    },
    'node-info': {
      label: 'NodeInfo',
      plain: 'The packet in which a node gives its names, hardware, role and public key. '
        + 'A node sends it soon after it starts, and then every few hours.',
      words: ['NodeInfo', 'node info'],
    },
    telemetry: {
      label: 'Telemetry',
      plain: 'Readings a node sends about itself and its sensors, such as battery, voltage, '
        + 'channel use and temperature.',
      more: 'https://meshtastic.org/docs/configuration/module/telemetry/',
      words: ['telemetry'],
    },
    firmware: {
      label: 'Firmware',
      plain: 'The software that runs on the radio. Some features need a newer version.',
      words: ['firmware'],
    },
    licensed: {
      label: 'Licensed (ham) mode',
      plain: 'The owner has an amateur radio licence and turned on licensed mode. '
        + 'The node then sends without encryption, because amateur radio rules forbid it.',
      more: ROLES,
      words: ['licensed'],
    },
    'position-precision': {
      label: 'Position precision',
      plain: 'How exactly a node shares where it is. Many owners round it on purpose, '
        + 'so the dot on the map is only near the node, inside a circle as wide as the rounding.',
      more: `${CHANNELS}#position-precision`,
      words: ['approximate position', 'rounded position', 'position precision',
        'uncertainty circle', 'exact position'],
    },

    // ---- Roles (labels.js holds the names, this holds what they mean)
    role: {
      label: 'Device role',
      plain: 'The job a node is set to do in the mesh. Most nodes should be Client, the default. '
        + 'Router roles are for fixed nodes on high, clear sites.',
      more: ROLES,
      words: ['role', 'device role'],
    },
    'role-client': {
      label: 'Client',
      plain: 'The default role, for a node you carry or message from. '
        + 'It relays a packet only when no other node nearby has done so.',
      more: ROLES,
      words: [],
    },
    'role-client-mute': {
      label: 'Client mute',
      plain: 'A node that never relays packets from other nodes. '
        + 'Good for a second node in the same place as another.',
      more: ROLES,
      words: ['Client mute'],
    },
    'role-client-hidden': {
      label: 'Client hidden',
      plain: 'A node that sends only when it must, to stay quiet or save power.',
      more: ROLES,
      words: ['Client hidden'],
    },
    'role-client-base': {
      label: 'Client base',
      plain: 'A personal base station. It always relays packets to and from the nodes its owner '
        + 'marked as favorites, and treats the rest like a client.',
      more: ROLES,
      words: ['Client base'],
    },
    'role-router': {
      label: 'Router',
      plain: 'A fixed node that always relays every packet once, to carry the mesh further. '
        + 'Only for a high, clear site: a router in a poor spot uses up hops.',
      more: ROLES,
      words: [],
    },
    'role-router-late': {
      label: 'Router late',
      plain: 'A fixed node that always relays every packet once, but only after the other nodes had their turn. '
        + 'It fills holes in local coverage.',
      more: ROLES,
      words: ['Router late'],
    },
    'role-router-client': {
      label: 'Router client',
      plain: 'An old role that firmware 2.3.15 removed. A node that still shows it runs very old firmware.',
      more: ROLES,
      words: ['Router client'],
    },
    'role-repeater': {
      label: 'Repeater',
      plain: 'An infrastructure node that relays packets with as little extra traffic as it can. '
        + 'Firmware 2.7.11 removed it; use Router or Router late.',
      more: ROLES,
      words: ['repeater'],
    },
    'role-tracker': {
      label: 'Tracker',
      plain: 'A node that sends its GPS position first, for something that moves.',
      more: ROLES,
      words: [],
    },
    'role-sensor': {
      label: 'Sensor',
      plain: 'A node that sends its sensor readings first.',
      more: ROLES,
      words: [],
    },
    'role-tak': {
      label: 'TAK',
      plain: 'A node set up for the ATAK team-awareness app, which sends fewer routine packets.',
      more: ROLES,
      words: [],
    },
    'role-tak-tracker': {
      label: 'TAK tracker',
      plain: 'A node that sends its position to the ATAK team-awareness app on its own, '
        + 'and fewer routine packets.',
      more: ROLES,
      words: ['TAK tracker'],
    },
    'role-lost-and-found': {
      label: 'Lost and found',
      plain: 'A node that sends its location as a message on the default channel, '
        + 'to help its owner find it again.',
      more: ROLES,
      words: ['Lost and found'],
    },

    // ---- Tools and maps
    traceroute: {
      label: 'Traceroute',
      plain: 'A test packet that records each node it passes, there and back, with the SNR of each hop. '
        + 'Only nodes that have the channel key show up in it.',
      more: 'https://meshtastic.org/docs/configuration/module/traceroute/',
      words: ['traceroute', 'trace route'],
    },
    'neighbor-info': {
      label: 'Neighbor info',
      plain: 'A report in which a node lists the nodes it hears directly, with the SNR of each. '
        + 'It is off by default, and a node sends it every few hours at most.',
      more: 'https://meshtastic.org/docs/configuration/module/neighbor-info/',
      words: ['neighbor info', 'neighbour info', 'neighbor link', 'neighbor report'],
    },
    'coverage-prediction': {
      label: 'Predicted coverage',
      plain: 'A computer estimate of where a node\'s signal should reach, from the terrain and the radio settings. '
        + 'It is not a measurement: what the mesh really heard can differ.',
      words: ['predicted', 'prediction'],
    },
    'line-of-sight': {
      label: 'Line of sight and terrain',
      plain: 'A LoRa signal travels best when the two antennas can see each other. '
        + 'Hills and buildings block it, so coverage often stops at a ridge line.',
      words: ['line of sight', 'terrain'],
    },
  };

  for (const entry of Object.values(TERMS)) {
    Object.freeze(entry.words);
    Object.freeze(entry);
  }
  Object.freeze(TERMS);

  /*
   * The role key a node reports, as the id of its entry. labels.js has
   * the name; this has the meaning. `CLIENT_MUTE` -> `role-client-mute`.
   */
  function roleTerm(role) {
    const id = `role-${String(role || '').toLowerCase().replace(/_/g, '-')}`;
    return TERMS[id] ? id : 'role';
  }

  window.SonoranGlossary = Object.freeze({
    terms: TERMS,
    get: (id) => TERMS[id] || null,
    roleTerm,
  });
})();
