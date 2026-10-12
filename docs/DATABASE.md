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
| `azmsh_ingest` | INSERT, UPDATE on all tables. No DELETE. No table-level SELECT. SELECT on a few columns only, because PostgreSQL requires SELECT on each column an UPDATE names in its WHERE clause: `node.node_num` (0006); `node.uplink_preset`, `node.uplink_preset_at` and `node.last_preset_at` (i313); and the key of `packet`, `from_node_num`, `packet_id` and `first_seen_at` (i313). No other column of `packet` is readable. | ingest process |
| `azmsh_api` | SELECT on all tables | api process |
| `azmsh_jobs` | SELECT, INSERT on `daily_snapshot`. DELETE where retention fallback needs it. SELECT, INSERT and DELETE on the job output tables (5B, i351), and no UPDATE: a run is replaced, never edited | jobs process |

### 2.1 The role passwords

Each role is created with the password in its own environment variable:
`AZMSH_INGEST_PASSWORD`, `AZMSH_API_PASSWORD`, `AZMSH_JOBS_PASSWORD`.

There is no default. Revision 0001 stops, naming the variable, when one
is missing, empty, or still the `CHANGE_ME` placeholder that
`.env.example` carries. The refusal happens before any role statement
runs, so a deployment that is short one variable does not half-create
its roles.

It used to default all three to `change_me`, and `.env.example` shipped
that value inside all three DSNs while never naming these variables at
all. `tools/db_restore.sh` tells an operator to copy that file. So the
documented first run produced a working deployment whose three
least-privilege roles were each reachable with a password published in
this repository, and nothing reported a fault, because from the outside
there was not one.

Each password must match the one in the matching `DATABASE_URL`,
`DATABASE_URL_API` or `DATABASE_URL_JOBS`. These create the login;
those use it. Set them in pairs:

| Set this | To the same value as the password in |
|----------|--------------------------------------|
| `AZMSH_INGEST_PASSWORD` | `DATABASE_URL` |
| `AZMSH_API_PASSWORD` | `DATABASE_URL_API` |
| `AZMSH_JOBS_PASSWORD` | `DATABASE_URL_JOBS` |

If they disagree the migration still succeeds — it creates the role with
the `AZMSH_*` value — and the service then fails to authenticate. The
symptom is a container that will not start with `password
authentication failed for user "azmsh_api"`, which names the pair to
look at.

**If the migration stops and says a variable is missing**, add the three
to `.env`, matching the passwords already inside the three
`DATABASE_URL*` values, and run it again. Nothing has been written: the
refusal happens before the first role statement.

**Changing a password on a database whose roles already exist** is not
this migration's job. Revision 0001 creates a role only when it is
absent, so editing these variables afterwards changes nothing. Use
`ALTER ROLE azmsh_api PASSWORD '…'` as the superuser and update the
matching `DATABASE_URL_API` in the same change.

The split is only worth what the deployment keeps apart. `docker-compose.yml`
gives each service its own DSN and blanks every other credential, so
the api container does not hold the ingest role's password or the
superuser's. See `x-no-credentials` there.

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
| `last_position_precision_bits` | integer | nullable; precision of the latest position |
| `position_time` | timestamptz | nullable |
| `last_heard` | timestamptz | nullable |
| `is_mqtt_gateway` | boolean | default false |
| `last_mqtt_topic` | text | nullable |
| `last_channel` | text | nullable |
| `last_preset` | text | nullable. The modem preset of the newest packet from this node whose preset is known (#313). Moves forward in time only. NULL until ingest tags one; a reader then falls back to `last_channel` |
| `last_preset_at` | timestamptz | nullable. The receive time of that packet |
| `uplink_preset` | text | nullable. For a gateway: the preset its newest preset-named topic named. Ingest reads it back at start |
| `uplink_preset_at` | timestamptz | nullable. When that upload arrived |
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
| `payload_json` | jsonb | what the packet carried, for node info, routing, traceroute, map report and pax counter only (`decode/stored.py`). NULL for every other family and for rows stored before 2026-09-22. |
| `modem_preset` | text | nullable. The modem preset that carried the packet: the majority of its observations' `modem_preset`. A NULL observation does not vote, and a tie keeps the stored value (#313). NULL on rows written before revision i313, and when no observation had a known preset |

Constraints:

- `UNIQUE (from_node_num, packet_id, first_seen_at)` — deduplication key.
  The time column is part of the key because hypertables require it.

### 3.4 `packet_seen`

One row per observation of a packet. Hypertable on `seen_at`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | bigint | generated |
| `packet_pk` | bigint | unused. Always NULL. See the note in section 1 |
| `from_node_num` | bigint | not null. With `packet_id`, the packet this observes |
| `packet_id` | bigint | not null |
| `gateway_node_num` | bigint | not null. The node that uploaded it |
| `mqtt_topic` | text | not null |
| `channel` | text | nullable |
| `rx_rssi` | integer | nullable. The last hop into the gateway (AGENTS.md 9.5) |
| `rx_snr` | double | nullable. The last hop into the gateway |
| `hop_limit` | integer | nullable. Hops left when the gateway heard it |
| `hop_start` | integer | nullable. The same header's hop start, so `hop_start = hop_limit` says direct without a join (#304). NULL on rows written before revision 0017, which are not backfilled: read them through `api/sightings.py`, which joins those to `packet` |
| `seen_at` | timestamptz | not null. partition key |
| `modem_preset` | text | nullable. The modem preset of this upload (#313): the topic's own preset when the topic is preset-named, else the gateway's current preset, else NULL. NULL when the gateway is ambiguous: it uploaded two different preset-named topics within `GATEWAY_PRESET_CONFLICT_MINUTES` |

#### 3.4.1 How ingest decides a modem preset

A topic channel such as `azmsh` is not a preset. It rides on top of the
preset the gateway is set to, and this mesh runs it on two presets.
Firmware names an unnamed primary channel after its preset, so a gateway
that uploads on `.../e/LongFast/...` is on LongFast.

`sonoran/ingest/presets.py` holds the rules in memory and touches no
database. `sonoran/ingest/preset_writes.py` stores the result. The
rules are in that module's docstring. In short:

1. An upload on a preset-named topic is on that preset, and it sets the
   gateway's current preset. The newest wins, so a reconfigured gateway
   switches at once.
2. Any other upload is on its gateway's current preset. A gateway that
   uploaded two different presets within the conflict window has no
   current preset, so its uploads get NULL and cast no vote.
3. A packet takes the majority of its uploads. Ingest has no SELECT on
   `packet`, so it counts the votes in memory for about ten minutes and
   runs `UPDATE packet ... WHERE from_node_num, packet_id, first_seen_at`
   only when the majority changes. A packet's first vote is in its
   INSERT. After a restart a packet's tally starts again at its next
   upload.
4. The sender's `node.last_preset` follows the packet's preset, with
   `WHERE last_preset_at IS NULL OR last_preset_at <= :t`.

There is no backfill. Old rows keep NULL, and the API reads a NULL row
by its channel, as before (`docs/API.md` 1.2). MapReports are not
stored, so they cannot help yet: `/2/map/` topics are dropped when the
topic is parsed.

### 3.5 `traceroute`

Parsed traceroute data. Hypertable on `seen_at`.

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

## 5A. RF map tables

What the community's own receivers hear beyond Meshtastic, aircraft
first. Written by `sonoran-rf-ingest`, read by `/api/rf`. Revision 0013.
The design is `docs/design/rf-map.md`.

| Table | Kind | One row per | Kept |
|---|---|---|---|
| `rf_station` | plain | location (one station on the map): rounded position, `last_seen` of any source, and the registry fields `display_name`, `owner`, `registered_sources`, `registry_at`. `last_seen` is NULL for a location in the registry with no heartbeat yet. Kinds and counts are kept for an agent that sends no source | always |
| `rf_source` | plain | (`station_id`, `source`): one Pi or decoder, from its own heartbeat: kinds, counts, agent version, `last_seen`, and `sweeps`, what it reports it sweeps (revision 0020). `-` is an agent that sends no source. Revision 0018 (#305) | always |
| `rf_track` | hypertable on `bucket` | (`kind`, `thing_id`, 20 s bucket), across every station; the first point received wins, unless a station of higher trust sends one. `source`, `trust` and `received_at` say who holds it (revision 0020) | 2 days |
| `rf_heard` | hypertable on `bucket` | (`station_id`, `kind`, `thing_id`, 5 min bucket): hearings, best level, where | 14 days |
| `rf_latest` | plain | (`kind`, `thing_id`): the newest point, updated in place. Its time is never after we received it, and a station of lower trust replaces it only once it is a minute old. `source`, `trust`, `received_at` as `rf_track` | always |
| `rf_spectrum_hour` | hypertable on `t` | (`station_id`, `source`, hour, range): each finished hour rolled up from `rf_spectrum` by the jobs process every 10 minutes, with the same per-bin rules as a waterfall row; `minutes` says how many minutes it holds. Read by the 3 and 7 day windows. Revision 0019 | 14 days |
| `rf_spectrum` | hypertable on `t` | (`station_id`, `source`, `f_start_hz`, `bin_hz`, `bins`, minute): one minute of one swept range; `p50`, `p95`, `peak` and `busy` arrays, one entry per bin, NULL for a bin not swept; `name`, the station's label for the range. Revision 0014; keyed by range since 0020 (#324). Minutes stored before 0020 have the station's source where it had only one (revision 0021), else `-` | 14 days |
| `rf_custom` | hypertable on `t` | (`station_id`, `mod`, `thing_id`, `t`): a point from a member's mod, with `source`, `sent_t`, `received_at`, `placement` (`reported`, `heard_here`, `none`), `lat`, `lon` and `meta`. Never part of a shared layer. Revision 0020 | 14 days |
| `rf_trust` | plain | (`station_id`, `source` or `*`): an operator's trust level, 0 quarantined, 1 new (the default, no row), 2 trusted. Written by `sonoran-rf-trust` | always |
| `rf_hidden_mod` | plain | (`station_id`, `mod`): a mod an operator hid from every viewer | always |
| `rf_operator_log` | plain | one change an operator made: trust, hiding, purging; `at`, `actor`, `action`, `station_id`, `detail` | always |

`sonoran-rf-ingest` writes as `azmsh_ingest`. It holds INSERT and UPDATE
on these tables and SELECT on only the columns a conflict target or an
`UPDATE ... WHERE` reads, so every upsert is `INSERT ... ON CONFLICT DO
NOTHING` then `UPDATE`, as `AGENTS.md` 9.2 requires. `azmsh_api` and
`azmsh_jobs` read them. `rf_spectrum` and `rf_custom` are insert only: a
repeated minute or point is ignored, so the ingest role holds INSERT and
SELECT on their key columns there and nothing else. The ingest role also
reads `rf_trust`, which only operators write, and SELECT on `trust` in
`rf_track` and `rf_latest` for its `UPDATE ... WHERE`. No application
role can read or write `rf_operator_log`; `rf_trust` and
`rf_hidden_mod` are written only by the database owner.

`thing_id` is the identity of what was heard: the ICAO address, lower
case, for aircraft. `rssi_db` is in the receiver's own units, so it
compares one station with itself and never two stations.

## 5B. Job output tables (#351)

What the background jobs compute, and the API serves. Before #351 these
were JSON files beside the coverage runs. The coverage tiles and the
run manifest stay on disk.

**Each table holds the latest run only.** A job replaces a whole run in
one transaction: it deletes the run's rows, inserts the new ones, and
commits once. A reader sees the old run or the new one, never half of
each. None is a hypertable, and none grows with time: the size is about
nodes x windows x presets.

| Table | Key | Holds | Written by |
|---|---|---|---|
| `gaps_index` | `id` (always 1) | When the gaps job last ran, and its window | `jobs/gaps.py` |
| `gaps_run` | `preset`, `scope`, `asked_hours` | One assessment (`scope` `assessment`, `asked_hours` 0), or one Statistics window of leaderboard counts (`scope` `board`, `asked_hours` 24 or 720). `summary` (`jsonb`) holds the top-level fields | `jobs/gaps.py` |
| `gaps_node` | run key, `node_num` | One node of one run: the evidence counts as columns, and `rank`, the order the job set (worst first). `node_num` references `node` | `jobs/gaps.py` |
| `gaps_signal` | run key, `node_num`, `signal` | One signal of one node: `state`, `reason`, `value` and `unit` as columns, `position` (the job's order), and `evidence` as `jsonb`, because its shape is the signal's own | `jobs/gaps.py` |
| `gaps_trace_answer` | run key, `node_num` | The traceroute counts of the reachable board (#293) | `jobs/gaps.py` |
| `gaps_siting` | `preset` | One preset's siting answer. `summary` holds the cost, the thresholds, the coverage it used and the caveats | `jobs/gaps_siting.py` |
| `gaps_siting_area` | `preset`, `area` | One neighbourhood of struggling nodes: counts, node numbers, centroid, bounds and width | `jobs/gaps_siting.py` |
| `gaps_siting_point` | `preset`, `area`, `position` | One demand point of an area: its place, its node numbers and their names | `jobs/gaps_siting.py` |
| `gaps_siting_candidate` | `preset`, `position` | One candidate place, in the order the job ranked it: every field of `gaps.siting.Candidate` as a column | `jobs/gaps_siting.py` |
| `coverage_calibration` | `id` (always 1) | The fit as a whole: bias, scatter, rounds, summary | `jobs/calibrate.py` |
| `coverage_calibration_node` | `node_num` | What the measurements say about one node | `jobs/calibrate.py` |

**Foreign keys.** Every child row belongs to its run or answer and is
deleted with it (`ON DELETE CASCADE`), so deleting a run is one
statement. `gaps_node.node_num` references `node`: the job leaves out,
and logs, a row whose node has no record yet, so that key never fails a
run. `gaps_trace_answer` does not reference `node`, because a node can
be traced and never send anything.

**What stays `jsonb`.** A run's `summary` (its window, thresholds,
labels, caveats and counts) and a signal's `evidence`. Both are read
whole and never filtered on. Everything a page filters, sorts or pages
by is a column.

**Names are read live.** `gaps_node` stores no name, short name or role.
A reader joins `node`, so a node renamed after a run reads with its new
name. The position stays as the job assessed it, because the findings
belong to that position.

**The old files are imported once.** The jobs process imports the old
JSON files at start into any of these tables that is empty
(`jobs/legacy_import.py`), and leaves the files in place for a rollback.

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

The Statistics page reads no window longer than 720 hours, the default
`packet` retention (#294). A window can still start before the oldest
row kept; the API then returns `retained_from` and the page says on each
widget that it counts from there. If `RETENTION_DAYS_PACKET` is lowered,
the 30 day button counts less than 30 days and each widget says so. If it
is raised, the 720 hour cap in `sonoran/api/window.py` and the page's
`STATS_RANGES` stay where they are until they are changed with it.

The gaps job's leaderboard windows (`docs/GAPS.md` 6.1) are cut to
`RETENTION_DAYS_PACKET` the same way. Their files say the hours they
hold, and the board says "not the page range" when that is less than
the range.

## 7. Indexes

Keep indexes minimal. Each index slows inserts.

- `packet_key`: index on `first_seen_at`.
- `packet`: dedup unique key (above). Index on (`from_node_num`, `first_seen_at` desc).
- `packet_seen`: index on (`from_node_num`, `seen_at` desc). Index on (`gateway_node_num`, `seen_at` desc).
  Both are covering since revision 0017: they INCLUDE `from_node_num`, `packet_id`,
  `gateway_node_num`, `rx_snr`, `rx_rssi`, `hop_limit` and `hop_start`
  (`models.SIGHTING_INCLUDE`). A node's rows are spread over the whole heap, and
  reading them there took 5 s for a busy gateway; from the index alone it took
  tens of milliseconds (#304).
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
- No index on `modem_preset` or `last_preset` (#313). The list pages read
  newest first through the time index they already use and test the tag
  on each row they reach, as they did with `channel`. An index on the tag
  cannot serve the fallback `OR (modem_preset IS NULL AND channel = ...)`,
  and every index on `packet_seen` costs every insert.

## 8. Continuous aggregates (later phase)

These are optional. Add them after phase 8 if query speed needs help.

- Hourly packet counts per node.
- Hourly channel utilization per node.
- Daily gateway activity.

Use TimescaleDB continuous aggregates with refresh policies.

## 9. Backup and restore

Two scripts move the data between boxes:

- `tools/db_backup.sh` takes a logical dump of the running database, plus
  the cluster roles, into `~/sonoran-backups`. It is safe to run while the
  stack is up. Pass `--no-text` to leave message bodies out.
- `tools/db_restore.sh` loads that dump into a fresh instance, following
  the TimescaleDB restore procedure (`timescaledb_pre_restore`, then
  `pg_restore`, then `timescaledb_post_restore`). It drops and recreates
  the target database, so it asks first.

Prefer a logical dump over a raw copy of the data volume. A raw copy only
works when both ends run the exact same image, and it carries none of the
safety a dump has.

### 9.1 Scheduled backups

The `backup` service takes a backup once a day (#216). It runs
`tools/db_backup_scheduled.sh` in an image built from the database image,
so `pg_dump` always has the major version of the server.

Why it exists: on 2026-09-25 the production box rebooted, and the
database did not start again. The storage lost writes that Postgres had
flushed, so `pg_control` was stale. The recovery needed `pg_resetwal`
and a repair of the catalog. The newest backup was two days old.

Each backup is the same two files that `tools/db_backup.sh` makes, so
`tools/db_restore.sh` restores either one:

- `azmsh-<UTC timestamp>.dump`
- `roles-<UTC timestamp>.sql`

The rules:

- A dump is written under a temporary name. It gets its real name only
  after `pg_restore` reads the whole file back. A failed dump never enters
  the rotation, and never pushes a good backup out.
- The service does not start a dump if the free space is less than two
  times the newest dump.
- The rotation keeps the newest `BACKUP_KEEP_DAILY` backups (default 7).
  It also keeps the newest backup of each of the newest
  `BACKUP_KEEP_WEEKLY` ISO weeks (default 4). It never removes the newest
  backup.
- The rotation touches only files named exactly
  `azmsh-YYYYMMDD-HHMMSS.dump`. A dump made by hand with another name
  stays until a person removes it.
- `last-good` in the backup directory holds the time and the name of the
  last good backup. The container healthcheck fails when that backup is
  older than the interval plus 12 hours. Look at `docker compose ps`: an
  `unhealthy` backup service means the backups have stopped.
- `failures` in the backup directory counts the failed attempts since
  the last good backup. The healthcheck also fails when it reaches
  `BACKUP_FAIL_LIMIT` (default 3, about 45 minutes at the default
  retry). Without it, a backup that fails on each retry stays healthy
  for 36 hours (#244). A good backup removes the file.
- After a restart, the service waits out the rest of the interval if the
  last good backup is recent. A container that restarts often does not
  dump the database each time.

The settings are in `.env.example`. The files go to `BACKUP_HOST_DIR`
(default `./backups` in the project root), which is a host directory so
that a person can copy the files without Docker. It is in `.gitignore`
and in `.dockerignore`: without the second, every `docker build` sends
every dump to the daemon.

The container writes as `BACKUP_UID`:`BACKUP_GID`, default `1000:1000`,
the `postgres` user of the image. The host directory must be writable by
that uid. Under rootless Docker, set both to `0`: root in the container
is the account that runs Docker, so the files belong to that account on
the host.

To take a backup now, or to test the service:

```
docker compose run --rm backup once
docker compose run --rm backup check
```

A backup on the same disk does not survive the loss of that disk. Copy
the files to another machine for that case.

The data volume mounts at `/home/postgres/pgdata`, which is where the
`timescaledb-ha` image keeps `PGDATA`. Mounting it anywhere else leaves
the data in the container's writable layer, where a container rebuild
loses it.
