# ARCHITECTURE.md — Module contracts and data flow

This document describes the modules of Sonoran.
It describes the job of each module.
It describes what each module may and may not do.
It uses ASD-STE100 Simplified Technical English.

## 1. Design rules

1. Each module has one job.
2. Modules communicate through small, documented interfaces.
3. The `decode` and `crypto` modules never touch the database.
4. The `api` module never imports `mqtt` or `ingest` internals.
5. All I/O is asynchronous.
6. A failure in one packet never stops the pipeline.

## 2. Process layout

Three processes always run, and two more are optional. All share one
Python package:

| Process | Module entry point | Database role |
|---------|-------------------|---------------|
| ingest | `sonoran.ingest.pipeline:main` | INSERT and UPDATE only |
| api | `sonoran.api.app:create_app` | SELECT only |
| jobs | `sonoran.jobs.scheduler:run` | SELECT, INSERT (snapshots), DELETE (retention fallback) |
| rf-ingest (profile `rf`) | `sonoran.rf.ingest:run` | the ingest role, plus SELECT on `rf_trust` (AGENTS.md 9.29) |
| contrib (profile `contrib`) | `sonoran.contrib.service:run` | the jobs role: SELECT, INSERT, UPDATE, DELETE on the `contrib_` tables, SELECT and INSERT on `local_stats` (#178) |

The daily snapshot has its own clock. Calibration and coverage share a
clock because coverage consumes the calibration file. A due calibration
finishes before coverage starts. A failed calibration leaves the last
published coverage run in place.

The coverage job writes no database row. It writes tiles and a manifest
to disk, because the tiles are the run, and holding the two apart lets
them disagree.

The database roles are enforced by PostgreSQL grants.
The grants are part of the first migration.

### 2.1 Each process holds one credential

A grant only holds what a process cannot reach. `env_file: .env` hands
a service the whole file, and `.env` holds the superuser password, the
superuser migration DSN, three role DSNs and three role passwords. A
service given all of them has the split on paper: anything that reads
`os.environ` — a crash reporter, a debug dump, a shell in a running
container — hands over the superuser, and the api is the process on the
public internet.

`extra="ignore"` in `sonoran/config.py` means the application ignores
the values it has no field for. That is not the protection. The value
is still in the process environment, and the environment is what leaks.

So `docker-compose.yml` merges `x-no-credentials` into every service,
which blanks all eight, and each service then grants back the one it
uses:

| Service | Holds |
|---------|-------|
| api | `DATABASE_URL_API` |
| ingest | `DATABASE_URL`, `CHANNEL_KEYS` and `MQTT_PASSWORD` |
| rf-ingest | `DATABASE_URL` and `RF_MQTT_PASSWORD` |
| contrib | `DATABASE_URL_JOBS` and `CONTRIB_MQTT_PASSWORD` |
| jobs | `DATABASE_URL_JOBS` |
| migrate | `DATABASE_URL_MIGRATE` and the three `AZMSH_*_PASSWORD` |
| mesh-graph | four MQTT variables, and no `.env` at all |

The three broker passwords are blanked by their own anchors
(`x-no-mqtt`, `x-no-rf-mqtt`, `x-no-contrib-mqtt`), merged into every
service but the one that logs in with it. That service does not set
the password in `environment:` at all, because `environment:` beats
every `env_file` and would replace a password a host gives it in an
override file. `tests/unit/test_broker_credentials.py` pins this.

**A credential added to `.env` later must be added to
`x-no-credentials` too**, or it is shared with every service by
default. The list is a denylist because an allowlist would have to
enumerate every one of the sixty-odd settings each service reads, and
that list would rot. The denylist is short, it is only credentials, and
this paragraph is the maintenance rule that goes with it.

`mesh-graph` is the exception and gets an allowlist, because it is the
one service in the stack that is not our code. It is also pinned by
digest rather than tracking `latest`, so an upstream push is not a
deploy here.

#### An override's `env_file` is added, not substituted

**This file is not the last word on what a service receives.** A
deployment may keep a `docker-compose.override.yml`, Compose reads it
automatically, and an `env_file` named there is added to the service.
Taking `env_file: .env` out of the base file therefore does **not**
take `.env` off a service whose override names it.

It is not hypothetical. The live deployment's override gave
`mesh-graph`

    env_file:
      - .env
      - .env.emqx

so the allowlist above was in the base file while the container still
received the whole of `.env`. Measured inside the running container: 8
non-empty credentials, including the Postgres superuser password and
the Meshtastic channel keys.

Reproduced here with `docker-compose config`, against this repository's
base file and an override of that shape:

| | base only | with the override |
|---|---:|---:|
| `mesh-graph` environment keys | 4 | 68 |
| non-empty credentials | 0 | **8** |

The eight are `POSTGRES_PASSWORD`, `CHANNEL_KEYS`, `DATABASE_URL`,
`DATABASE_URL_API`, `DATABASE_URL_JOBS` and the three
`AZMSH_*_PASSWORD`.

The merge was checked the other way round as well, on `api`, which does
carry `env_file: .env` here. An override adding only `.env.extra` gives
that service **both** files: 69 keys, with `MQTT_HOST` from `.env` and
`EMQX_EXTRA` from `.env.extra`. So an override can only widen what a
service receives. It can never narrow it.

So two rules follow:

1. **Check the resolved configuration, never the file you edited.**
   `docker compose config` on the deployment prints what each service
   will actually receive, overrides included. A change to credential
   scoping is not verified until it has been read there.
2. **An override that needs an extra env file must name only that
   file** for the service in question. `.env.emqx` alone, not
   `.env` and `.env.emqx`.

The deployment's override has been corrected: that service now resolves
to 0 credentials with all four MQTT variables intact.

#### `environment:` beats `env_file:`, so the allowlist cannot be redirected

The correction above left a second fault in place. `mesh-graph`'s four
variables are set under `environment:`, interpolated from `.env`, and
Compose gives `environment:` precedence over any `env_file:`. The
override's `env_file: [.env.emqx]` was therefore not narrowing anything
and not redirecting anything: every key in it was overridden by the
base file. The container held the four variables from `.env`, which
named the upstream broker and its login, and for two days `mesh-graph`
read the upstream broker directly instead of the local bridge the
deployment had chosen.

Reproduced with `docker compose config`, `.env` naming one broker and
the override's env file another:

| override for `mesh-graph` | resolved `MQTT_HOST` |
|---|---|
| `env_file: [.env.other]` | the one in `.env` |
| `environment: !reset {}` then `env_file: [.env.other]` | the one in `.env.other` |

So a third rule:

3. **To change a variable the base file sets under `environment:`,
   the override must set it under `environment:` too**, or reset the
   block with `environment: !reset {}` and then name its env file. An
   `env_file` alone is silently ignored for those keys.

The base file's `mesh-graph` command also used to ignore `MQTT_HOST`
and `MQTT_PORT` and connect to the `broker` written in
`mesh-graph.config.toml`. It now writes both into the config it runs,
so the broker is set in one place, the environment, as it is for the
ingest.

## 3. Module contracts

### 3.1 `config`

- Job: load and validate settings from environment variables.
- Uses `pydantic-settings`.
- Exports one `Settings` object.
- Every other module receives `Settings` as a parameter.
- No module reads `os.environ` directly.

Key settings:

- `DATABASE_URL` — per-process connection string.
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_USE_TLS`.
- `MQTT_TOPICS` — list of topic filters.
- `CHANNEL_KEYS` — list of full base64 AES keys.
- `MESH_GRAPH_BASE_URL` — public base URL of the mesh-graph instance.
- `WEB_BASE_PATH` — optional reverse-proxy base path. The dashboard and API
  use this path without HTML rewriting.
  Use a path with no trailing slash, such as `/mesh`.
  The dashboard uses browser-relative URLs and local assets only.
  It does not require CDN, tile, canvas, or gateway rewrite support.
- `STORE_TEXT_MESSAGES` — boolean. Default false until the privacy decision is final.
- `GATEWAY_PRESET_CONFLICT_MINUTES` — default 60. A gateway that uploads
  on two different preset-named topics within this many minutes is
  ambiguous, and its other uploads get no modem preset (#313).
- `RETENTION_DAYS_*` — retention policy overrides. Run the migration service
  after a value changes.
- `LOG_LEVEL`.

### 3.2 `mqtt`

- Job: connect to the broker. Receive messages. Reconnect on failure.
- Uses `aiomqtt`.
- `client.py` yields `(topic, payload)` pairs through an async iterator.
- `topics.py` parses topic strings into structured data:
  region path, channel name, gateway ID, payload format.
- A broker can omit the gateway ID from the topic. In this case, ingest uses
  the gateway ID from the protobuf envelope.
- The module never parses protobuf.
- The module never touches the database.

Interface:

```python
async def message_stream(settings: Settings) -> AsyncIterator[RawMqttMessage]
```

`RawMqttMessage` fields: `topic`, `payload` (bytes), `received_at` (datetime, UTC),
and the parsed topic fields.

### 3.3 `crypto`

- Job: decrypt a `MeshPacket` payload.
- Input: encrypted bytes, packet ID, sender node number, list of keys.
- Output: decrypted bytes, or a `DecryptionError`.
- The function tries each key in order.
- Pure function. No I/O. No database.

Interface:

```python
def decrypt_packet(encrypted: bytes, packet_id: int, from_node: int, keys: list[bytes]) -> bytes
```

### 3.4 `decode`

- Job: turn bytes into typed Python objects.
- `envelope.py`: parse `ServiceEnvelope`. Extract the `MeshPacket` and envelope metadata.
- `payloads.py`: parse `Data`, then use one decoder per `PortNum`.
- Each decoder returns a dataclass or pydantic model.
- Unknown portnum values return a generic `UnknownPayload`.
  They are never an error.
- Pure functions. No I/O. No database.

Interface:

```python
def parse_envelope(payload: bytes) -> ParsedEnvelope
def decode_payload(portnum: int, data: bytes) -> DecodedPayload
```

### 3.5 `ingest`

- Job: move data from MQTT to the database.
- `pipeline.py` is the orchestrator. It runs this loop:
  1. Read one `RawMqttMessage`.
  2. Parse the envelope.
  3. Decrypt the payload.
  4. Decode the payload.
  5. Ask `presets.PresetTracker.observe` for the modem preset of this
     upload (#313).
  6. Call `dedup.store_packet`. The preset goes on the `packet_seen` row,
     and on the `packet` row when the packet is new.
  7. Call `preset_writes.store_vote`. It counts the upload's vote and
     updates `packet.modem_preset` and `node.last_preset` when the
     majority changes.
  8. Call the matching handler.
  9. Handle errors per packet. Log, count, continue.
- `presets.py` decides the modem preset of each upload and packet. It
  holds each gateway's current preset and a short tally of each recent
  packet's votes, in memory, and touches no database. One tracker lives
  for the life of the process. At start, `preset_writes.load_gateway_presets`
  seeds it from `node.uplink_preset`. See `docs/DATABASE.md` 3.4.1.
- `preset_writes.py` stores what `presets.py` decides, with plain
  `UPDATE ... WHERE key = ...` statements. It never reads a `packet`
  row and never uses `ON CONFLICT DO UPDATE` (AGENTS.md 9.1, 9.2).
- `dedup.py` implements the deduplication contract:
  - Insert into `packet_key` with `ON CONFLICT DO NOTHING`.
    The affected row count says whether the packet is new.
  - Write one `packet` row when it is new. Write a `packet_seen` row for
    every observation.
- `handlers/` has one module per packet family.
  Each handler stores payload-specific rows.
  `meshpacket.py` stores routing metrics from each unique packet header.
  `presence.py` keeps the `node` table current. It writes `is_mqtt_gateway`
  and `last_heard` from every MQTT message, not only new packets.

Handler interface:

```python
async def store_payload(
    session: AsyncSession, decoded: DecodedPayload, context: HandlerContext
) -> None
```

`HandlerContext` fields: the stored packet ID, source and destination node,
channel, Data message metadata, and receive time.

### 3.6 `db`

- Job: define the schema. Give sessions to other modules.
- `models.py` has all SQLAlchemy models.
- `session.py` builds async engines and session factories per process role.
- `migrations/` has the Alembic environment and revisions.
- No business logic lives here.

### 3.6.1 `radio`

- Job: say what radio a node has.
- `presets.py` is the one modem preset table. It holds the spreading
  factor, the bandwidth, and the sensitivity of each preset, and the
  noise floor that turns a reported SNR into a received power.
- `hardware.py` maps a hardware model to the radio in it. The transmit
  power and the antenna gain in it are assumptions, not facts.
- `overrides.py` reads the operator file named by
  `RADIO_OVERRIDES_PATH`.
- `resolve.py` puts the three together. It is the only place that
  decides the radio characteristics of a node, so the coverage job, the
  calibration job, and the API cannot disagree.
- Every resolved value carries the name of its source.
- This package must never touch the database. It has the same rule as
  `decode` and `crypto`.

### 3.6.2 `coverage`

- Job: predict where a radio is heard.
- `units.py` holds the one conversion from metres to feet. SPLAT! reads
  feet and nothing else here does.
- `params.py` holds the values the engine takes. It is the Python side
  of `web/static/planner-params.js`.
- `engine.py` runs the vendored SPLAT! WebAssembly file with `wasmtime`.
  The module imports three functions and asks for no files, no clock,
  and no network.
- `grid.py` is the only place that decides how a raster maps to the
  ground. Every engine raster shares one lattice, so a raster is placed
  on the region grid rather than resampled onto it.
- `sites.py` turns a node into a prediction, and one prediction into
  both directions of a link.
- `render.py` colours a grid and writes map tiles.
- `store.py` keeps a run on disk. A run is one directory and becomes
  visible in one step, so a reader never sees half of one.
- `calibrate.py` fits bounded node corrections and a network-wide model
  bias. A fit outside its trust guards gives no correction.
- The planner page runs the same file in a browser worker. A hash test
  pins the two to the same rasters.
- The engine is under the GNU General Public License, version 3. See
  `AGENTS.md` 7.1.
- This package must never touch the database.

### 3.6.3 `embed`

- Job: decide what a public viewer of the coverage map may see.
- `sanitise.py` is the only place that decides it. Infrastructure roles
  and MQTT gateways only, positions snapped to a grid, short names
  only.
- It is the same arrangement as `positions.py` and `api/traces.py`: one
  module holds the rule, so two pages cannot disagree.
- `frame_ancestors` checks every origin the settings name through the
  same test the other security headers use. It never returns a
  wildcard.
- The embed is off until `EMBED_ENABLED` is true.
- This package must never touch the database.

### 3.6.4 `gaps`

- Job: decide which nodes the mesh is not carrying well, and where one
  new node would help the most of them. One modem preset at a time,
  always.
- `signals.py` is the only place that decides what a per node signal
  means. `siting.py` is the only place that decides what a demand
  point, an area, a candidate and the terrain screen mean.
- `store.py` is where an answer is written and read: the job output
  tables in `docs/DATABASE.md` 5B (#351). The per node job writes
  `gaps_run`, `gaps_node` and `gaps_trace_answer`; the siting job writes
  `gaps_siting` and `gaps_siting_candidate`. They are written by
  different jobs on different clocks, so each replaces only its own
  rows. A route reads by key, with its filters and its limit in SQL.
- Every signal and every candidate has **three** states, and the third
  is `unknown`. It is never served as a zero and never as a pass.
- `siting.py` reads terrain out of the cache through
  `terrain/srtm.py::page_cell` and never re-implements the transform.
  See `AGENTS.md` 9.13 and 9.13.1.
- Neither module touches the database. `signals.py` is handed rows, and
  `siting.py` is handed the written assessment.

### 3.7 `api`

- Job: serve read-only JSON and static files.
- FastAPI application factory in `app.py`.
- `routes/` has one module per route group:
  `chat.py`, `graph.py`, `map.py`, `nodes.py`, `packets.py`,
  `stats.py`, `terrain.py`, `traceroutes.py`.
- `schemas.py` has the pydantic response models.
- `dependencies.py` gives database session access to route handlers.
- `channels.py` groups channel names into families for the UI.
- `names.py` resolves node display names from the database.
- `window.py` turns the statistics query (`hours`, or `since` and
  `until`) into one window. It is the only place that does, so the
  widgets on the Statistics page cannot disagree about a range (#294).
- `traces.py` turns one stored traceroute row into a path. It is the
  only place that decides what a row proves. `graph.py`, `map.py`, and
  `traceroutes.py` all read rows through it, so that the pages cannot
  disagree about which links exist. See AGENTS.md 9.18.
- The application connects with the SELECT-only database role.
- The module registers GET routes only.
- Static files are served with security headers:
  Content-Security-Policy, X-Content-Type-Options, Referrer-Policy.
- `routes/graph.py` builds mesh-graph URLs from `MESH_GRAPH_BASE_URL`.

### 3.8 `terrain`

- Job: supply ground elevation to the coverage planner.
- This module must never touch the database. It has the same rule as
  `crypto` and `decode`.
- `srtm.py` turns an SRTM tile into an engine page. It does no input and
  output. Every function is pure.
- `store.py` keeps pages on disk and, when it is allowed to, downloads
  the tiles it does not hold.
- The prediction itself does **not** happen here. It runs in the
  browser, in a WebAssembly build of SPLAT!. This module only feeds it.
  See `docs/PLANNER.md`.

An engine "page" is one degree square of elevation: 1200 x 1200 int16
values in the cell order SPLAT! expects, 2 880 000 bytes. Making one
takes three steps, and the engine depends on the exact result of all
three:

1. Read the 3601 x 3601 big-endian int16 `.hgt` tile.
2. Reduce it to 1201 x 1201 with an area-weighted average.
3. Apply the `srtm2sdf` transform: repair sub-zero cells from their
   neighbours, drop the north row and the east column, and reorder.

Step 3 is bit-exact against the original C code and a golden test pins
it. Step 2 cannot be bit-exact, and does not need to be. See
`AGENTS.md` 9.13.

Pages never change, so each is made once. `tools/prefetch_terrain.py`
fills the cache for the whole region. After that,
`TERRAIN_ALLOW_DOWNLOAD=false` leaves the API with no outbound request
at all.

The region is a bounding box in configuration. A tile outside it is
never fetched and never served, so the endpoint cannot be used as a
general proxy for the tile source.

### 3.8.1 `climate`

- Job: say which ITM radio climate a place is in (#239).
- This module must never touch the database.
- `store.py` reads `koppen_1991_2020.u8.gz`, a 960 x 960 byte crop of
  the Beck et al. (2023) Köppen-Geiger map. It ships inside the package,
  so it needs no download, no cache and no setting. Row 0 is north and
  column 0 is west, which is **not** the order of a terrain page.
- `koppen.py` holds the Köppen to ITM table, one row for each of the 30
  classes, with a reason for each. It is the only copy: the planner
  reads it from `/api/climate/classes`.
- `climate_at` answers a place. Outside the crop, or where the map has
  no class, it answers `desert` and marks the answer as not known. It
  never guesses a class.
- `PROVENANCE.md` beside the data holds the licence (CC BY 4.0), the
  attribution and the changes made. `tools/make_climate_crop.py` makes
  the file again from the published source.

Readers: the planner page (through `api/routes/climate.py`), the
coverage job (`coverage/sites.py::engine_params`) and the calibration
(`jobs/calibrate.py::_params`). See `docs/PLANNER.md` 4.3.

### 3.8.2 `contrib`

- Job: give mesh jobs to members' contributors and keep what they bring
  back (#178). See `docs/design/contributors.md`.
- `schema.py` is the contract, exported to
  `docs/contributor-message-v1.schema.json`.
- `dispatch.py` holds the rules, with no database and no broker: which
  node, which contributor, and whether a result is accepted.
- `store.py` reads and writes the `contrib_` tables and `local_stats`.
- `service.py` is the process: one broker connection, and a tick that
  expires, plans, publishes and clears jobs.
- It reads `rf.schema` for the station and source id rules, so a
  contributor's ids are the registrar's.

### 3.9 `jobs`

- Job: run scheduled maintenance.
- `retention.py` checks that TimescaleDB retention policies exist and work.
- `snapshots.py` writes one `daily_snapshot` row per day.
- `calibrate.py` reads current neighbour reports and writes one computed
  calibration file.
- `coverage.py` reads that file and publishes one complete static tile
  run. `predict_sites` is its seam for a caller that wants each site's
  own raster rather than a map, and it holds every engine rule.
- `gaps.py` measures the per node half of the coverage gaps feature. It
  is only SQL, so it keeps its own clock.
- `gaps_siting.py` answers "where would one new node help". It runs the
  engine, so it runs **inside** the coverage cycle and never beside it.
- `read_models.py` builds the long-window views the API reads (#371):
  link evidence for the graph and the longest-link board, broadcast
  rates, and the coverage page's node lists. SQL and Python, no engine,
  on its own clock. See `docs/DATABASE.md` 8.1.
- `supervisor.py` runs each job run as its own process
  (`python -m sonoran.jobs.run_task <name>`), each with a memory ceiling
  (`JOBS_MEMORY_LIMITS`). A watchdog stops a job that passes its ceiling,
  alone; runs overlap when they fit in the container's memory, and wait
  their turn otherwise; each run's peak is kept and plans the next. A
  child raises its own OOM score, so the kernel takes a job, never the
  supervisor. `JOBS_ISOLATE=false` runs every job in one process, as
  before.
- `scheduler.py` runs a due calibration, then coverage, then the siting
  half, on one clock. The snapshot and the per node gap assessment
  remain independent, because neither uses the engine.

  **Anything that uses the engine joins `_coverage_cycle`.** Tasks
  registered in `build_tasks` run under `asyncio.gather`, so a second
  engine user there would be free to start during a coverage build, and
  the engine has no IO to yield on.

### 3.10 `web/static`

- Job: the user interface.
- Static HTML, CSS, and JavaScript files. There is no build step.
- Files: `index.html`, `app.css`, `app.js`, `map-defaults.js`,
  `node-sheet.js`, `map-live.js`, `map-watch.js`, `planner.js`, `planner-params.js`,
  `planner.worker.js`, `config-check.js`, `meshtastic-static.js`,
  `gaps.js`, `siting.js`,
  `protobuf-runtime.js`, and `vendor/`.
- Libraries load from vendored files, not from public CDNs.
  This keeps the site working without third-party availability.
- Libraries: Leaflet for the map, ECharts for the charts and the mesh
  graph. Both are in `web/static/vendor`.
- ECharts and the config checker's scripts are not loaded by every
  page (#277). They sit inside `<template data-lazy-scripts>` in
  `index.html`, and `loadScripts` in `app.js` adds them when a page
  needs them: `render` loads ECharts before a page in `CHART_PAGES`, and
  `PAGES.config` loads the checker. A page that starts drawing a chart
  must be added to `CHART_PAGES`.
- `map-defaults.js` loads straight after Leaflet and sets what every
  map shares. On a touch screen (`pointer: coarse`) every map draws on
  a canvas with a 20 px hit tolerance, and a tap goes to the nearest
  dot, not to the dot drawn last (#266). Under
  `prefers-reduced-motion: reduce` no map animates its zoom or fades,
  and `chart()` in `app.js` turns off ECharts animation (#284).
- `node-sheet.js` shows a node's map summary on a phone (below 40rem)
  in a sheet at the foot of the screen, not in a Leaflet bubble (#281).
  `SonoranSheet.bind(marker, build, key)` replaces `bindPopup` on the
  live map and on coverage: a mouse still gets the bubble. The sheet is
  non-modal, has a peek and a half height, a 44 px close, and Back
  closes it.
- The pages call the JSON API. All node names come from the API.
  The browser does no name lookup and no join.
- The API serves `index.html` and replaces `__SONORAN_CONFIG__` with the
  client settings: the API base, the map tile URL and attribution, the
  default map view, and the mesh-graph base URL.
- Pages: dashboard, map, coverage planner, config check, mesh graph,
  nodes, node detail, chat, weekly check-in, firehose, traceroutes,
  statistics.

A column or a summary tile that needs explaining carries its sentence
in `data-hint`, and `revealHints` in `app.js` turns each one into a
button on the heading it explains. The button is a `<button>` with
`aria-expanded`, so a finger and a keyboard both reach it; a `title`
attribute reaches neither, which is why none is written. The panel is
a popover, which draws in the browser's top layer, so `.table-wrap`'s
sideways scroll cannot clip it while the panel stays where it is in
the document for a screen reader. Where the popover API is missing the
same element is shown with `hidden` and `position: fixed`, which
escapes a plain `overflow` ancestor as well, and `app.js` closes it on
Escape and on a tap outside. Each column's own exact protocol values
are listed in its panel.

The config check page uses the community config checker's logic,
vendored in `web/static/vendor/config-checker/`, and draws the result in
`web/static/config-check.js`. The vendored interface is not loaded. This
is the same arrangement as the coverage planner: vendored engine, our
interface.

Android `.cfg` exports are protobuf, and protobuf.js normally builds
its decoders by compiling strings with `new Function`. The dashboard
forbids that, so the schema is compiled ahead of time instead:

| File | What it is |
|------|------------|
| `meshtastic-static.js` | The schema, compiled by `tools/generate_protobuf_static.sh`. Explicit encoders and decoders. Calls `Function` nowhere. |
| `protobuf-runtime.js` | Hands the vendored protobuf runtime to the module above, which imports it by name. |

`config-check.js` points `protobuf.Root.fromJSON` at those types, so the
vendored parser reads a `.cfg` unchanged and the policy is left alone.
Regenerate after any update to the vendored checker that changes its
protobuf descriptor. The script refuses to install a result that
compiles code, that was generated against a different major version of
the runtime, or whose runtime import was not rewritten.

That feature has no server side at all. A config file, a channel key,
and an MQTT password are read in the browser and never sent anywhere.
The API gains no endpoint for it. See `AGENTS.md` 9.17.
- Graph images come from mesh-graph URLs.

The coverage planner is the one page that is not a thin view over the
API. It is kept in its own files for that reason, and `app.js` holds
only a `PAGES.planner` entry that hands over to it.

`planner.js` loads **before** `app.js`. The router runs as the last act
of `app.js`, and it needs `window.SonoranPlanner` to exist by then, or a
reload on `#planner` falls back to the dashboard. The planner uses the
helpers from `app.js` only inside functions, which run long after both
files have loaded. A test pins the order.

The prediction runs in module web workers, one for each of up to four
processor cores, each holding its own copy of the engine. See
`docs/PLANNER.md`.

#### The live map animation

`map-live.js` and `map-watch.js` load before `app.js`, for the reason
the planner does: the router runs as the last act of `app.js` and a
reload straight to `#map` calls the map page at once. Neither file
reads an `app.js` binding at load time — `app.js` passes each one
everything it needs — so the order carries no other risk. A test pins
it. The design is `docs/design/live-map-watch-mode.md`.

`map-live.js` is the animation. Three things about it are contracts,
not implementation details:

- **The unit is the packet, not the upload.** Observations are grouped
  on (`from.node_id`, `packet_id`), which is the identity `AGENTS.md`
  9.1 gives. At most three arcs are drawn, to the gateways that burned
  the fewest hops, and the rest become a `+N` numeral beside the sender
  and an exact count in the panel. `packet_seen` holds MQTT uploads, so
  a line per row says "fifteen nodes heard this", which is the reading
  9.5.1 exists to forbid. Measured on seeded traffic: 2,000
  observations became 269 packets and 2,701 strokes became 768 arcs.
- **Flatness is evidence.** Only a `direct` observation and a
  traceroute hop draw a straight line, because a straight line is the
  claim that two radios heard each other. Everything else bows by its
  hop count, an unknown hop count is stippled, and a self-upload draws
  no arc at all. See 9.5, 9.20.
- **Speed is not data.** Flight time is a constant 850 ms for every
  mark. Every gateway stamps its own `rx_time` and node clocks have
  been 28 hours out (9.3, 9.4), so latency is not measurable and a mark
  that moved at a distance-dependent speed would be read as one.

It is one `<canvas>` in a Leaflet pane of its own, one
`requestAnimationFrame` loop, and a pre-allocated pool of 256 mark
slots, capped at 220 alive. The pane is created as a direct child of
the map container rather than inside the transformed map pane, so the
canvas stays pinned and every mark is reprojected each frame; the pane
sets `filter: none`, because the rule that warms the basemap has
already inverted one overlay's palette once. The canvas hides between
`zoomstart` and `zoomend`, when Leaflet transforms its panes and a
container-pinned canvas does not receive the transform.

Each poll's events are **replayed across the poll interval** rather
than fired in one frame, ordered on `seen_at` — our own receive clock,
and the only time value in the system a client may order on. The
display therefore runs about one interval behind live and says so. The
status line also prints "drawing N of M packets" whenever the pool
refuses anything, because the eye cannot count marks.

The **Live traffic** list under the map follows the same replay
(#386). Before, the list took the whole poll at fetch time, so five or
six rows arrived together, each up to fifteen seconds before its line.
Now the engine calls `onRelease` in each frame that releases packets,
and `paintTrafficFeed` in `app.js` leaves out every packet that
`pendingKeys()` says is still waiting. So a row arrives in the same
frame as its line. A paused map holds the list too. A packet that
leaves the queue in another way (its kind is hidden, the backlog is
skipped, the queue cap drops it) is listed at once, because nothing
waits for it.

Each row wears its packet family: the family's `--pkt-*` token on the
row's left edge and on a CSS mark of the family's shape, beside the
packet type in words. These are the tokens the map reads, so the row
and its relayed line have the same colour in both themes. A flat
(direct) line takes the colour of its signal, and the row's SNR cell
has that colour. The mark is CSS, not a canvas like `familySwatch`,
because a canvas keeps the colour it was painted with after a theme
change. The text is always there, so the row does not rest on colour
alone (WCAG 1.4.1).

The **packet type menu** in the map's controls row chooses which
packet families the traffic layer draws (#385). It is a button and a
drop-down of checkboxes, one for each entry of
`SonoranLive.FAMILY_ORDER`, with the family's mark and name. Each
change applies at once. The menu is a popover (`wireHint` with
`placeMenu`), so it opens in the top layer over the map and takes no
room in the row. Before, it was a `<details>` that opened a line of
chips inside the row, which pushed the header down and closed only on
its own summary. Now Escape, a tap outside, Done or the button close
it. The top layer also clears the sideways scroll of the watch bar on
a phone, which clips an ordinary absolute panel. Do not give the
`.family-menu` rule a `display` value: it wins over the browser's
`display: none` for a shut popover, and the menu then never closes.
The choice is kept per browser, as the hidden set, so a family that a
later build adds is drawn by default.

`app.js` caches `api/graph/channels` for ten minutes and
`api/map/nodes` for two. Both were refetched on every map refresh,
four times a minute per open tab, and the channel list runs three
24-hour `GROUP BY` aggregates.

`map-watch.js` is fullscreen watch mode. It is a state of the map kept
in the URL fragment (`#map/watch/<tab>/<height>`), not a new page: a
`Referer` never carries a fragment, so the state survives a reload, is
shareable, and leaks nothing (9.9.1). It asks for the Fullscreen API on
`.map-shell` and falls back to a `body.watch-mode` class, because iOS
Safari does not grant `requestFullscreen` on an arbitrary element; both
paths end with the same class on the same element, so there is one set
of CSS rules. It **moves** the controls row and the two feed panels
into the overlay rather than copying them, so there is one preset
picker and one feed renderer. The preset name, the node scope, the
honesty counter, the replay lag and the OpenStreetMap attribution never
hide.

Every chart can go full screen, and the control comes from `chart()` in
`app.js` rather than from the eleven call sites, so no chart can be
left without one. It borrows watch mode's two decisions: the box is
**moved** into the overlay so one ECharts instance keeps drawing, and
the overlay is fixed to the viewport in CSS with the Fullscreen API
layered on top, because iOS Safari refuses `requestFullscreen` on an
arbitrary element. ECharts measures its container once, so both
entering and leaving call `resize()`. Full screen also turns on
`dataZoom`, but only where the x axis is `time` or `category` — a zoom
on the count axis of a horizontal bar chart hides bars rather than
showing a range. The control is a real `<button>`, so Space and Enter
both work. The two charts drawn outside `chart()` — the RF band
occupancy chart in `rf.js` and the planner's profile in `planner.js` —
do not have it.

#### 3.10.1 The packet page, by kind

A packet page (`#packet/<from>/<packet id>`) is read in this order:

1. **One sentence** that says what the packet was, in plain words.
2. **Who heard it**: the gateways that uploaded it, with the signal of
   the direct ones. It is first because no other page shows it for one
   packet. See `AGENTS.md` 9.5.1 for what the list is and is not.
3. **What it said**, in the terms of its kind.
4. **The envelope**: from, to, channel, hops allowed, the fewest hops
   any gateway saw, whether an ack was asked for, and the rest.
5. **Raw data**, closed, holding everything the API returned.

What each kind shows under "What it said":

| Port | Shows | Source |
|---|---|---|
| `TEXT_MESSAGE_APP` | The message, large, with hashtags marked. | `text_message` |
| `POSITION_APP` | Latitude, longitude, altitude, and the precision in metres, then a map. A rounded position says how far it was rounded. | `position_metrics` |
| `TELEMETRY_APP` | Named readings with units: device, environment, air quality or power. | the four telemetry tables |
| `NEIGHBORINFO_APP` | A table of the neighbors it reported, each by name, with the SNR it heard it at. | `neighbor_metrics`, named through `node` |
| `TRACEROUTE_APP` | The path, hop by hop, and the mesh-graph drawing. | `traceroute` |
| `NODEINFO_APP` | The names, hardware, role and key the node sent. A packet stored before 2026-09-22 shows a sentence saying it is not stored, and a link to the node page. | `packet.payload_json` |
| `ROUTING_APP` | The result: an acknowledgement or the error reason. A packet stored before 2026-09-22 shows a sentence saying it is not stored. The ID of the packet it acknowledges is not stored, so an ACK cannot be matched to its message (#293). | `packet.payload_json` |
| any other | "No decoded value is stored for this packet." | none |

The envelope says which key sealed the packet: the recipient's public
key (PKI) or the channel key. Ingest keeps `pki_encrypted` in
`mesh_packet_metrics`, and the packet endpoint reads it from there.

What the page does not claim, because the database does not hold it:

- Whether an acknowledgement came back. The firmware acknowledges with
  a `ROUTING_APP` packet whose `request_id` is the original packet ID
  and whose `error_reason` is `NONE`, but ingest does not store routing
  packets, so only the request is known.
- The content of a node-info or routing packet.
- Which node relayed it. `relay_node` holds only the last byte of a
  node number (`mesh.proto`), which cannot name a node.

#### Content Security Policy

The API sends a strict policy with the page. Three sources come from
configuration, so a change of deployment does not break the page:

- `img-src` holds the map tile host from `MAP_TILE_URL`.
- `connect-src` holds the API origin from `WEB_API_BASE_URL`.
  Without this the browser blocks every request when the API runs on
  another origin.
- `frame-src` holds the mesh-graph origin from `MESH_GRAPH_BASE_URL`.

Each of those, and the `frame-ancestors` of the embed, is built by
`safe_origin` in `sonoran/embed/sanitise.py`. That is the only origin
check in the project and nothing may build one another way: `urlsplit`
keeps a semicolon inside a network location, a semicolon starts a new
CSP directive, and a browser honours a directive's first occurrence, so
a setting could inject a policy that overrode ours. An origin that is
refused is left out and logged, because the browser blocks it silently.

The branch that decides which policy to send reads
`starlette.routing.get_route_path(scope)`, not `scope["path"]`, so a
deployment under `WEB_BASE_PATH` behind a proxy that does not strip the
prefix still gets one. It used to get none at all.

Two more sources are fixed, and both exist for the coverage planner:

- `script-src` holds `'wasm-unsafe-eval'`. Without it the browser
  refuses to compile the engine and reports nothing the user can see.
- `worker-src` holds `'self'`, for the worker that runs the engine.
  It also covers the service worker at `/sw.js` (docs/APP.md).

`manifest-src` holds `'self'`, for the installed app's manifest. A
policy with no `manifest-src` falls back to `default-src`, which says the
same today. It is named so that a stricter `default-src` cannot stop the
install.

`connect-src` also always holds `https://api.github.com`. The config
checker asks it which firmware release is current. That is the only
outbound request the dashboard makes and it carries no user data.

`Permissions-Policy` exists for the same page. It grants `serial` to
this origin, for reading a node over USB, and denies the camera, the
microphone, the location, and the rest to everything. Web Serial also
needs a secure context, so the feature is missing until the dashboard is
served over HTTPS.

`X-Frame-Options` is `DENY` and `frame-ancestors` is `'none'`. Nothing
may put the dashboard inside a page of its own, not even this origin.

Terrain is served by this application, so it needs no connect source of
its own. That is the reason the browser is not sent to the public tile
host for elevation data.

## 4. Data flow: one packet

```
MQTT broker
  -> mqtt.client (RawMqttMessage)
  -> decode.envelope (ParsedEnvelope with MeshPacket)
  -> crypto.decrypt (plaintext Data bytes)
  -> decode.payloads (typed payload object)
  -> ingest.presets (the modem preset of this upload, from memory)
  -> ingest.dedup (packet row, packet_seen row, is_new flag)
  -> ingest.preset_writes (packet.modem_preset, node.last_preset on a new majority)
  -> ingest.handlers.<family> (node update, metric rows)
```

A failure at any step:

- is caught in `pipeline.py`,
- is logged with the topic and packet ID,
- increments the error counter,
- does not stop the loop.

## 5. Data flow: one API request

```
Browser
  -> api route
  -> SQLAlchemy query (SELECT only)
  -> pydantic response model
  -> JSON
```

The API never triggers writes.
The UI polls endpoints on an interval for updates.

## 6. Dependency direction

Allowed direction only:

```
config -> (all)
mqtt -> decode -> crypto
ingest -> mqtt, decode, crypto, db
api -> db
jobs -> db
rf -> db
contrib -> db, rf (the id rules only)
web/static -> api (over HTTP only)
```

Reverse imports are forbidden.
CI checks the import rules with `import-linter` or an equivalent tool.

One deliberate exception: `jobs` may call the view functions of `api`
(`jobs/gaps.py` reads `api/traces.py`; `jobs/read_models.py` calls
`graph.link_evidence` and `stats.broadcast_ranking`). A stored view must
be computed by the same code as the live one, or the two would drift
apart. It never goes the other way: `api` does not import `jobs`.

## 7. Error handling policy

1. Network errors: retry with backoff. Reconnect MQTT.
2. Decode errors: log, count, skip the packet.
3. Database errors in ingest: retry the transaction. Drop the packet after the retry limit. Log it.
4. Database errors in api: return HTTP 503.
5. Never show stack traces to users.

## 8. Logging policy

1. Use structured logs (JSON) through `sonoran.logging`.
2. One log line per event. Include context fields.
3. Count these events as metrics: packets received, packets new, packets duplicate, decrypt failures, decode failures, handler failures.
4. Expose the counters on `/health` for the api process and on stdout for the ingest process.
