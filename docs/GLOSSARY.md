# GLOSSARY.md — The words Sonoran explains

This file is made from `src/sonoran/web/static/glossary.js`. Do not
edit it by hand. Change the glossary, then run:

    uv run python -m tools.newcomer_check --write-doc

Each word below has a tooltip in the dashboard. An element with
`data-term="<id>"` shows it. See `docs/NEWCOMER.md` for when to use one.

| Id | Word | What it means |
|---|---|---|
| `snr` | SNR (signal-to-noise ratio) | How far a signal stands above the background noise, in dB. Higher is better. LoRa can still decode a signal a little below the noise, so a small negative SNR can still work. [Learn more](https://meshtastic.org/docs/overview/radio-settings/) |
| `rssi` | RSSI (signal strength) | How strong the signal was when it reached the receiving radio, in dBm. Closer to zero is stronger, so -70 dBm is a stronger signal than -110 dBm. A strong signal can still be noisy, so read it together with SNR. |
| `dbm` | dB and dBm | dBm is a power level, and dB is a difference between two levels. Every 3 dB is about twice the power, and every 10 dB is ten times. |
| `sensitivity` | Sensitivity | The weakest signal a radio can still decode, in dBm. It depends on the preset: a slower preset hears weaker signals, so it reaches further. [Learn more](https://meshtastic.org/docs/overview/radio-settings/) |
| `signal-margin` | Signal margin | How far above the radio's limit a signal is, in dB. A link with more margin keeps working when the weather, leaves or a moving person weaken it. |
| `noise-floor` | Noise floor | The background radio noise a radio hears when no node is sending. A higher noise floor hides weak signals, so the radio hears less. |
| `antenna-gain` | Antenna gain (dBi) | How much an antenna focuses its signal toward the horizon instead of up and down, in dBi. More gain reaches further along the ground, but less above and below the antenna. |
| `lora` | LoRa | The long-range, low-power radio method Meshtastic uses. It is slow, but it can reach many kilometres with a small battery. |
| `packet` | Packet | One transmission on the mesh. A text message is one kind of packet; positions, battery readings and node introductions are other kinds. |
| `packet-type` | Packet type | What a packet carries, such as a text message, a position or telemetry. Meshtastic marks every packet with a number for this, the port number (portnum). |
| `hop` | Hop | One relay: a node hears a packet and sends it on. A packet heard straight from the sender used no hops. [Learn more](https://meshtastic.org/docs/overview/mesh-algo/) |
| `hop-limit` | Hop limit | How many times a packet may be relayed. It is 3 by default and at most 7. Each relay takes one off, and at zero no node sends it on again. [Learn more](https://meshtastic.org/docs/configuration/radio/lora/#max-hops) |
| `direct` | Heard direct | Heard straight from the sending node, with no relay between them. Only a direct reading says how well those two radios hear each other. |
| `relay-node` | Relay node | The node that last sent this copy on. A packet keeps only the last byte of that node's number, so Sonoran can often only list the nodes it could be. |
| `gateway` | Gateway (MQTT) | A node that also sends what it hears to a server on the internet, over MQTT. Sonoran sees the mesh only through gateways: a packet that no gateway heard is not here. [Learn more](https://meshtastic.org/docs/configuration/module/mqtt/) |
| `mqtt` | MQTT | The internet messaging system that gateways use to copy mesh traffic to a server. Sonoran reads its packets from the azmsh.net MQTT server. [Learn more](https://meshtastic.org/docs/configuration/module/mqtt/) |
| `upload` | Upload | One copy of a packet that one gateway sent to the server. A gateway can upload the same packet more than once, so a count of uploads is not a count of gateways. |
| `channel-utilization` | Channel utilization | How busy the radio frequency is: the share of time the radio heard any signal, from every node and from noise. When it is high, nodes send less to keep the air clear. [Learn more](https://meshtastic.org/docs/configuration/module/telemetry/) |
| `airtime` | Airtime (TX utilization) | The share of the last hour that this node spent sending. A high number means the node talks a lot and takes air time from others. [Learn more](https://meshtastic.org/docs/configuration/module/telemetry/) |
| `modem-preset` | Modem preset | The radio settings a mesh agrees on, such as LongFast or MediumFast. Each one trades range for speed. A node only hears nodes on the same preset. [Learn more](https://meshtastic.org/docs/configuration/radio/lora/#modem-preset) |
| `long-fast` | LongFast | The preset a new node uses until somebody changes it. It reaches far, but each message takes a long time on the air. [Learn more](https://meshtastic.org/docs/configuration/radio/lora/#modem-preset) |
| `medium-fast` | MediumFast | A preset that sends faster than LongFast, with a little less range. Each message takes less air time, which helps a busy mesh. [Learn more](https://meshtastic.org/docs/configuration/radio/lora/#modem-preset) |
| `frequency-slot` | Frequency slot | The exact frequency in the band that a node uses. Two nodes on the same preset hear each other only if they also use the same slot. [Learn more](https://meshtastic.org/docs/configuration/radio/lora/#frequency-slot) |
| `channel` | Channel | A named group for messages, with its own key. Many channels can share one preset, so a channel is not the same as a preset. [Learn more](https://meshtastic.org/docs/configuration/radio/channels/) |
| `encryption` | Encrypted | The contents are scrambled with a key, so only nodes with that key can read them. The key of the default channel is public, so anybody can read what is sent on it. [Learn more](https://meshtastic.org/docs/overview/encryption/) |
| `pki` | PKI (private direct message) | A direct message locked with a key that only the sender and the receiver can make. Nobody else can read it, Sonoran included. [Learn more](https://meshtastic.org/docs/overview/encryption/) |
| `node-id` | Node ID | The node's own number, written after a "!", such as !a1b2c3d4. It does not change when the owner renames the node. |
| `node-info` | NodeInfo | The packet in which a node gives its names, hardware, role and public key. A node sends it soon after it starts, and then every few hours. |
| `telemetry` | Telemetry | Readings a node sends about itself and its sensors, such as battery, voltage, channel use and temperature. [Learn more](https://meshtastic.org/docs/configuration/module/telemetry/) |
| `firmware` | Firmware | The software that runs on the radio. Some features need a newer version. |
| `licensed` | Licensed (ham) mode | The owner has an amateur radio licence and turned on licensed mode. The node then sends without encryption, because amateur radio rules forbid it. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `position-precision` | Position precision | How exactly a node shares where it is. Many owners round it on purpose, so the dot on the map is only near the node, inside a circle as wide as the rounding. [Learn more](https://meshtastic.org/docs/configuration/radio/channels/#position-precision) |
| `role` | Device role | The job a node is set to do in the mesh. Most nodes should be Client, the default. Router roles are for fixed nodes on high, clear sites. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-client` | Client | The default role, for a node you carry or message from. It relays a packet only when no other node nearby has done so. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-client-mute` | Client mute | A node that never relays packets from other nodes. Good for a second node in the same place as another. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-client-hidden` | Client hidden | A node that sends only when it must, to stay quiet or save power. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-client-base` | Client base | A personal base station. It always relays packets to and from the nodes its owner marked as favorites, and treats the rest like a client. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-router` | Router | A fixed node that always relays every packet once, to carry the mesh further. Only for a high, clear site: a router in a poor spot uses up hops. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-router-late` | Router late | A fixed node that always relays every packet once, but only after the other nodes had their turn. It fills holes in local coverage. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-router-client` | Router client | An old role that firmware 2.3.15 removed. A node that still shows it runs very old firmware. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-repeater` | Repeater | An infrastructure node that relays packets with as little extra traffic as it can. Firmware 2.7.11 removed it; use Router or Router late. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-tracker` | Tracker | A node that sends its GPS position first, for something that moves. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-sensor` | Sensor | A node that sends its sensor readings first. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-tak` | TAK | A node set up for the ATAK team-awareness app, which sends fewer routine packets. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-tak-tracker` | TAK tracker | A node that sends its position to the ATAK team-awareness app on its own, and fewer routine packets. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `role-lost-and-found` | Lost and found | A node that sends its location as a message on the default channel, to help its owner find it again. [Learn more](https://meshtastic.org/docs/configuration/radio/device/) |
| `traceroute` | Traceroute | A test packet that records each node it passes, there and back, with the SNR of each hop. Only nodes that have the channel key show up in it. [Learn more](https://meshtastic.org/docs/configuration/module/traceroute/) |
| `neighbor-info` | Neighbor info | A report in which a node lists the nodes it hears directly, with the SNR of each. It is off by default, and a node sends it every few hours at most. [Learn more](https://meshtastic.org/docs/configuration/module/neighbor-info/) |
| `coverage-prediction` | Predicted coverage | A computer estimate of where a node's signal should reach, from the terrain and the radio settings. It is not a measurement: what the mesh really heard can differ. |
| `line-of-sight` | Line of sight and terrain | A LoRa signal travels best when the two antennas can see each other. Hills and buildings block it, so coverage often stops at a ridge line. |
