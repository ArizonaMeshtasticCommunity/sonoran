# DATABASE.md — Database schema

This document describes the Sonoran database schema.
The database is TimescaleDB (PostgreSQL with the TimescaleDB extension).
It uses ASD-STE100 Simplified Technical English.

## 1. Rules

**Packet identity comes from the protocol.** Every child table stores
the Meshtastic `packet_id` next to the node it came from. That pair
joins to `packet` and `packet_seen`, so any stored value can be traced
to the packet that carried it.

The `packet_pk` column pointed at the generated `packet.id`. The ingest
role has no SELECT right, so it can never read a generated key back and
the column is NULL on every row. It stays for now but nothing uses it.


1. All schema changes use Alembic migrations.
2. Never edit an applied migration.
3. All timestamps are UTC. High-volume tables use `timestamptz`.
4. Node numbers are unsigned 32-bit integers. Store them as `bigint`.
5. Node IDs in display use the `!xxxxxxxx` hex format. The API does the conversion.
6. High-volume tables are hypertables. The time column is the partition key.
7. Required Boolean columns use a database default of `false`.
   This rule also applies to raw SQL inserts.

## 2. Roles and grants

Created in the first migration:

| Role | Rights | Used by |
|------|--------|---------|
| `azmsh_ingest` | INSERT, UPDATE on all tables. No DELETE. SELECT on `node.node_num` only, as PostgreSQL requires it for node updates. | ingest process |
| `azmsh_api` | SELECT on all tables | api process |
| `azmsh_jobs` | SELECT, INSERT on `daily_snapshot`. DELETE where retention fallback needs it | jobs process |

## 3. Core tables

### 3.1 `node`

One row per node. Latest known state.

| Column | Type | Notes |
|--------|------|-------|
| `node_num` | bigint | primary key |
| `node_id` | text | `!xxxxxxxx` format |
| `long_name` | text | nullable |
| `short_name` | text | nullable |
| `hw_model` | text | nullable |
| `role` | text | nullable |
| `is_licensed` | boolean | default false |
| `public_key` | bytea | nullable |
| `last_lat` | double precision | nullable |
| `last_lon` | double precision | nullable |
| `last_altitude` | integer | nullable |
| `position_time` | timestamptz | nullable |
| `last_heard` | timestamptz | nullable |
| `is_mqtt_gateway` | boolean | default false |
| `last_mqtt_topic` | text | nullable |
| `last_channel` | text | nullable |
| `first_seen` | timestamptz | not null |
| `updated_at` | timestamptz | not null |

### 3.2 `packet_key`

The deduplication key of a packet. One row per unique packet.

This is a regular table, not a hypertable. Its primary key holds
(`from_node_num`, `packet_id`) without a time column, so the key is the
true packet identity. The `packet` hypertable cannot hold this key
alone: TimescaleDB requires the partition column in every unique
constraint, and each gateway stamps its own `rx_time`.

Ingest inserts here with `ON CONFLICT DO NOTHING`. The affected row
count says whether a packet is new, so ingest never needs to read the
table.

| Column | Type | Notes |
|--------|------|-------|
| `from_node_num` | bigint | primary key |
| `packet_id` | bigint | primary key |
| `first_seen_at` | timestamptz | index, for queries by time |

### 3.3 `packet`

One row per unique packet. Hypertable on `first_seen_at`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | bigint | generated, for joins |
| `from_node_num` | bigint | part of dedup key |
| `packet_id` | bigint | part of dedup key |
| `to_node_num` | bigint | nullable. 4294967295 means broadcast |
| `portnum` | integer | payload type |
| `channel` | text | nullable |
| `hop_start` | integer | nullable |
| `hop_limit` | integer | nullable |
| `want_ack` | boolean | default false |
| `priority` | integer | nullable |
| `rx_time` | integer | from the packet header |
| `first_seen_at` | timestamptz | not null. partition key |
| `raw_bytes` | bytea | the raw MeshPacket protobuf |
| `payload_json` | jsonb | decoded summary. nullable |

Constraints:

- `UNIQUE (from_node_num, packet_id, first_seen_at)` — deduplication key.
  The time column is part of the key because hypertables require it.

### 3.4 `packet_seen`

One row per observation of a packet. Hypertable on `seen_at`.

| Column | Type | Notes |
|--------|------|-------|
| `packet_id` | bigint | the Meshtastic packet ID. Join with the node column |
| `packet_pk` | bigint | unused. Always NULL. See the note in section 1 |
| `request_id` | bigint | the request this reply answers. mesh-graph keys a trace on it. nullable |
| `from_node_num` | bigint | not null |
| `to_node_num` | bigint | not null |
| `channel` | text | the channel that carried the report. nullable |
| `route` | jsonb | forward path, list of node numbers |
| `route_back` | jsonb | return path. nullable |
| `snr_towards` | jsonb | SNR per hop, forward. nullable |
| `snr_back` | jsonb | SNR per hop, return. nullable |
| `seen_at` | timestamptz | not null. partition key |

### 3.6 `text_message`

Decrypted text bodies. Hypertable on `seen_at`.

| Column | Type | Notes |
|--------|------|-------|
| `packet_id` | bigint | the Meshtastic packet ID. Join with the node column |
| `packet_pk` | bigint | unused. Always NULL. See the note in section 1 |
| `from_node_num` | bigint | not null |
| `to_node_num` | bigint | not null |
| `channel` | text | nullable |
| `body` | text | not null |
| `reply_id` | bigint | nullable. packet ID of the original message |
| `emoji` | boolean | default false |
| `seen_at` | timestamptz | not null. partition key |

Note: this table is written only when `STORE_TEXT_MESSAGES` is true.

## 4. Metric tables

All metric tables are hypertables on their time column.
All have `node_num` (bigint, not null) and `time` (timestamptz, not null).
All have an optional `packet_pk` reference (unused, always NULL).
All have a `packet_id` column (bigint, nullable), matched with `node_num` to join to the packet that carried the reading.

### 4.1 `device_metrics`

`battery_level` (real), `voltage` (real), `channel_utilization` (real),
`air_util_tx` (real), `uptime_seconds` (bigint).

### 4.2 `environment_metrics`

`temperature` (real), `relative_humidity` (real), `barometric_pressure` (real),
`gas_resistance` (real), `iaq` (integer), `lux` (real), `uv_lux` (real),
`wind_direction` (integer), `wind_speed` (real), `rainfall` (real).

### 4.3 `air_quality_metrics`

`pm10_standard` (integer), `pm25_standard` (integer), `pm100_standard` (integer),
`pm10_environmental` (integer), `pm25_environmental` (integer),
`pm100_environmental` (integer).

### 4.4 `power_metrics`

`ch1_voltage` (real), `ch1_current` (real),
`ch2_voltage` (real), `ch2_current` (real),
`ch3_voltage` (real), `ch3_current` (real).

### 4.5 `pax_metrics`

`wifi_count` (integer), `ble_count` (integer), `uptime_seconds` (bigint).

### 4.6 `mesh_packet_metrics`

Packet routing and network statistics.

`from_node_num` (bigint), `to_node_num` (bigint), `packet_id` (bigint),
`reporting_gateway_node_num` (bigint), `via_mqtt` (boolean),
`message_size_bytes` (integer), `relay_node_num` (bigint),
`next_hop_node_num` (bigint), `transport_mechanism` (text), `pki_encrypted` (boolean).

### 4.7 `position_metrics`

`latitude` (double precision), `longitude` (double precision),
`altitude` (integer), `ground_speed` (integer), `ground_track` (integer),
`precision_bits` (integer), `sats_in_view` (integer).

### 4.8 `neighbor_metrics`

One row per neighbor link per report.

`neighbor_node_num` (bigint, not null), `channel` (text, nullable),
`snr` (real), `last_rx_time` (timestamptz),
`node_broadcast_interval_secs` (integer).

The `channel` column holds the channel that carried the report. The
mesh graph draws one graph per channel, because a node on one modem
preset cannot hear a node on another preset. Rows written before
revision 0007 have a NULL channel.

### 4.9 `node_config`

Latest reported module configuration per node. Regular table, not a hypertable.

| Column | Type | Notes |
|--------|------|-------|
| `node_num` | bigint | part of primary key |
| `config_type` | text | part of primary key. example: `lora`, `mqtt`, `telemetry` |
| `config_json` | jsonb | not null |
| `updated_at` | timestamptz | not null |

## 5. Snapshot table

### 5.1 `daily_snapshot`

One row per day. Written by the jobs process.

| Column | Type | Notes |
|--------|------|-------|
| `day` | date | primary key |
| `node_count` | integer | nodes heard that day |
| `packet_count` | integer | unique packets that day |
| `observation_count` | integer | packet_seen rows that day |
| `gateway_count` | integer | active MQTT gateways that day |
| `text_count` | integer | text messages that day |
| `created_at` | timestamptz | not null |

## 6. Retention policy

Applied in migrations with `add_retention_policy`.

| Table | Default retention |
|-------|-------------------|
| `packet` | 30 days |
| `packet_seen` | 30 days |
| `traceroute` | 90 days |
| `text_message` | 30 days |
| `position_metrics` | 30 days |
| `device_metrics` | 90 days |
| `environment_metrics` | 90 days |
| `air_quality_metrics` | 90 days |
| `power_metrics` | 90 days |
| `pax_metrics` | 90 days |
| `mesh_packet_metrics` | 90 days |
| `neighbor_metrics` | 90 days |

The migration service applies `RETENTION_DAYS_*` environment overrides.
Run the migration service after a retention setting change.
`daily_snapshot` and `node` have no retention.

## 7. Indexes

Keep indexes minimal. Each index slows inserts.

- `packet_key`: index on `first_seen_at`.
- `packet`: dedup unique key (above). Index on (`from_node_num`, `first_seen_at` desc).
- `packet_seen`: index on (`from_node_num`, `seen_at` desc). Index on (`gateway_node_num`, `seen_at` desc).
  Index on (`from_node_num`, `packet_id`, `seen_at` desc) for joining to packets.
- `traceroute`: index on (`from_node_num`, `seen_at` desc). Index on (`to_node_num`, `seen_at` desc).
  Index on (`channel`, `seen_at` desc). Index on (`from_node_num`, `packet_id`).
- `text_message`: index on (`channel`, `seen_at` desc). Index on (`reply_id`).
  Index on (`from_node_num`, `packet_id`).
- metric tables: index on (`node_num`, `time` desc). Index on (`node_num`, `packet_id`).
- `mesh_packet_metrics`: also index on (`from_node_num`, `time` desc). Index on (`to_node_num`, `time` desc).
  Index on (`reporting_gateway_node_num`, `time` desc).
- `neighbor_metrics`: also index on (`channel`, `time` desc).
- `node`: index on `last_heard`. Index on `short_name`.

## 8. Continuous aggregates (later phase)

These are optional. Add them after phase 8 if query speed needs help.

- Hourly packet counts per node.
- Hourly channel utilization per node.
- Daily gateway activity.

Use TimescaleDB continuous aggregates with refresh policies.
