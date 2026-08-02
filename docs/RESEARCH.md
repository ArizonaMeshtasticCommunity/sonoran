# RESEARCH.md — Research on source applications and the protocol

This document records the research for Sonoran.
It uses ASD-STE100 Simplified Technical English.
Research date: 2026-08-01.

## 1. Source application 1: az-meshtastic-metrics-exporter

Repository: `https://github.com/logans-stuff/az-meshtastic-metrics-exporter`

### 1.1 What it does

1. It subscribes to a Meshtastic MQTT server.
2. It decrypts packets with one or more channel keys.
3. It parses the protobuf messages.
4. It stores metrics in TimescaleDB hypertables.
5. It updates node details and topology in regular PostgreSQL tables.
6. Grafana dashboards show the data.

### 1.2 Storage layout

Regular tables:

- `messages` — deduplication table with auto-expiry
- `node_details` — node ID, names, hardware, location, MQTT status, last-heard topic and channel
- `node_neighbors` — topology from NeighborInfo packets
- `node_configurations` — module configurations and update intervals

TimescaleDB hypertables:

- `device_metrics` — battery, voltage, channel utilization, uptime
- `environment_metrics` — temperature, humidity, pressure, air quality sensors
- `air_quality_metrics` — particulate matter values
- `power_metrics` — multi-channel voltage and current
- `pax_counter_metrics` — WiFi and BLE device counts
- `mesh_packet_metrics` — packet routing and network statistics
- `position_metrics` — historical GPS coordinates
- `text_message_metrics` — decrypted text message bodies

All hypertables have retention policies.
Default retention is 3 months for general data.
Default retention is 30 days for positions and text messages.

### 1.3 Strengths

- It has the widest packet type coverage of our tools.
- It supports multiple decryption keys.
- It uses TimescaleDB retention policies.
- It deploys with Docker Compose.
- Configuration uses a `.env` file.

### 1.4 Weaknesses

- It does not deduplicate packets across MQTT uplinks.
  Each uplink writes its own copy of the same packet.
  We removed filters in the past to keep unfiltered data per uplink.
- It has no user-facing web UI. Grafana is separate.

### 1.5 What we take from it

- The packet type list.
- The hypertable and retention pattern.
- The multi-key decryption configuration.
- The environment-variable configuration pattern.

## 2. Source application 2: meshview

Repository: `https://github.com/ArizonaMeshtasticCommunity/meshview`
(Fork of `pablorevilla-meshtastic/meshview`.)

### 2.1 What it does

1. It watches MQTT topics for Meshtastic messages.
2. It imports the messages into a database.
3. It serves a web UI to view the data.

Technology: Python 3.13, aiohttp, aiomqtt, SQLAlchemy async, Alembic, Jinja2.
Database: SQLite by default. PostgreSQL is supported through asyncpg.

### 2.2 Deduplication model

This is the model we copy.

- The `packet` table has one row per unique packet.
- The `packet_seen` table has one row per observation of a packet.
- An observation is one MQTT uplink from one gateway.
- Each observation keeps its own metadata: gateway, topic, RSSI, SNR, time.
- The `traceroute` table stores forward and return paths.
- The `node` table stores the latest known state of each node.

### 2.3 Features

- Live map with node markers and edges.
- Firehose page with all packets.
- Chat and conversation pages with reply tracking.
- Node list with filters.
- Statistics pages with daily snapshots.
- Reliability report: heard and missed status per node, hop counts, gateway tables, map view.
- JSON API. Examples: `/api/chat`, `/api/edges`, `/api/stats`, `/api/config`, `/api/snapshots/daily`.
- Real-time updates through Server-Sent Events.
- Alembic migrations and scheduled cleanup.

### 2.4 Strengths

- Correct deduplication.
- Rich feature set that our users know.
- Async architecture.

### 2.5 Weaknesses

- The traceroute display is poor. We offload traceroutes to mesh-graph.
- SQLite has reliability problems at our volume.
  Schema changes need a full table rebuild in SQLite.
  The project documents this problem itself.
- The codebase mixes web, API, and MQTT logic.

### 2.6 What we take from it

- The `packet` plus `packet_seen` schema.
- The feature list for the UI.
- The daily snapshot idea.
- The reliability report idea.
- Alembic for all schema changes.

## 3. Source application 3: mesh-graph

Repository: `https://github.com/ianmcorvidae/mesh-graph`

### 3.1 What it does

1. It listens for Meshtastic traceroute packets over MQTT.
2. It stores them in its own SQLite database.
3. It exposes network topology graphs over an HTTP API and a web UI.

Technology: Python 3.11+, FastAPI, NetworkX, Graphviz.
Container image: `ghcr.io/ianmcorvidae/mesh-graph:latest`.

### 3.2 Graph endpoints

All graph endpoints accept `?format=svg` (default), `?format=png`, or `?format=dot`.
All accept `?clickable=true` for clickable node links.

- `GET /graph/network` — directional graph of backbone nodes.
  Options: time range, `snr_labels`, `include_unknown_nodes`, `include_clients`.
- `GET /graph/trace/{trace_id}` — graph of one traceroute.
  Options: `from`, `to`, `date`, `direction`, `communities`.
- `GET /graph/node/{node_id}` — neighborhood graph around a node.
  Options: `direction` (`inbound`, `outbound`, `both`, `network`), `depth` (1 to 10).

Node IDs use the Meshtastic `!xxxxxxxx` hex format.

Data endpoints:

- `GET /api/nodes` — known nodes, newest first.
- `GET /api/traceroutes` — recent traceroutes, newest first.
  Both support cursor pagination with `after` and `limit`.

### 3.3 Integration plan

1. Run the official container in our Docker Compose stack.
2. Point it at the same MQTT broker.
3. Set `MESH_GRAPH_BASE_URL` in our application configuration.
4. Build deep links from our UI to its graph endpoints.
5. Embed graphs with SVG `<object>` tags.
6. Do not fork the code. Update the image tag to update.

The owner of mesh-graph has deep knowledge of Meshtastic network graphing.
We keep that logic in that application on purpose.

## 4. The Meshtastic MQTT data path

Reference: `https://buf.build/meshtastic/protobufs`

### 4.1 MQTT topics

- Topic pattern: `msh/{region}/.../{channel}/{gateway_id}`.
- Example: `msh/US/AZ/2/e/LongFast/!abcd1234`.
- The gateway ID is the node ID of the MQTT gateway that sent this uplink.
- JSON messages also exist on some brokers. We use the protobuf payload topics.

### 4.2 Message structure

1. The MQTT payload is a `ServiceEnvelope` protobuf.
2. The envelope contains a `MeshPacket`, a channel ID, and a gateway ID.
3. The `MeshPacket` has header fields: `from`, `to`, `id`, `hop_start`, `hop_limit`, `rx_time`, `rx_snr`, `rx_rssi`, and more.
4. The packet payload is encrypted with AES-CTR.
5. The key is the channel pre-shared key.
   The default public key is `1PG7OiApB1nwvP+rz05pAQ==` (AES-128).
6. The nonce comes from the packet ID and the sender node number.
7. The decrypted payload is a `Data` protobuf.
8. `Data.portnum` selects the payload type.
   Examples: `TEXT_MESSAGE_APP`, `POSITION_APP`, `NODEINFO_APP`, `TELEMETRY_APP`, `NEIGHBORINFO_APP`, `TRACEROUTE_APP`, `PAXCOUNTER_APP`.
9. The full `PortNum` list is at `https://buf.build/meshtastic/protobufs/docs/main:meshtastic#meshtastic.PortNum`.

### 4.3 Deduplication key

- The key is (`from`, `id`) from the MeshPacket header.
- The same packet arrives many times.
  Each MQTT gateway that heard the packet sends one uplink.
- Each uplink has its own RX metadata.
- The RX metadata is not part of the deduplication key.
  We store it in `packet_seen`.

### 4.4 Known key shorthand

The Meshtastic app shows well-known channel keys in a short form.
Example: `AQ==` means the default key with the last byte replaced.
The full form of `AQ==` is `1PG7OiApB1nwvP+rz05pAQ==`.
Our configuration must use full keys.
We document the expansion rule for operators.

## 5. Volume estimate

Assumptions:

- 1000 or more active nodes.
- 12 to 2000 packets per node per hour.

Estimates:

- Low case: about 300,000 packets per day across the mesh.
- High case: several million packets per day.
- With multiple MQTT gateways, each unique packet gives multiple `packet_seen` rows.

Consequences:

- SQLite is not acceptable. Confirmed decision D2.
- High-volume tables must be hypertables.
- Retention must drop whole chunks. Row-by-row deletes are too slow.
- Indexes must be minimal. Each index slows inserts.

## 6. Lessons learned

1. Deduplicate on storage, not on display.
   The exporter shows why: unfiltered duplicates make all counts wrong.
2. Keep observation data.
   The uplink list per packet is valuable for reliability reports.
3. Keep raw bytes.
   A raw archive lets us re-parse history when decoders improve.
4. Do not couple the graph engine to the dashboard.
   mesh-graph does graphs better than we will. Link to it.
5. Make the public surface read-only.
   Read-only means small attack surface and simple caching.
6. Use PostgreSQL from day one.
   SQLite rebuild problems cost the meshview project real downtime.
