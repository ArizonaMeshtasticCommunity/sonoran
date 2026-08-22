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

Three processes share one Python package:

| Process | Module entry point | Database role |
|---------|-------------------|---------------|
| ingest | `sonoran.ingest.pipeline:main` | INSERT and UPDATE only |
| api | `sonoran.api.app:create_app` | SELECT only |
| jobs | `sonoran.jobs.scheduler:run` | SELECT, INSERT (snapshots), DELETE (retention fallback) |

The daily snapshot has its own clock. Calibration and coverage share a
clock because coverage consumes the calibration file. A due calibration
finishes before coverage starts. A failed calibration leaves the last
published coverage run in place.

The coverage job writes no database row. It writes tiles and a manifest
to disk, because the tiles are the run, and holding the two apart lets
them disagree.

The database roles are enforced by PostgreSQL grants.
The grants are part of the first migration.

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
  5. Call `dedup.store_packet`.
  6. Call the matching handler.
  7. Handle errors per packet. Log, count, continue.
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

### 3.9 `jobs`

- Job: run scheduled maintenance.
- `retention.py` checks that TimescaleDB retention policies exist and work.
- `snapshots.py` writes one `daily_snapshot` row per day.
- `calibrate.py` reads current neighbour reports and writes one computed
  calibration file.
- `coverage.py` reads that file and publishes one complete static tile
  run.
- `scheduler.py` runs a due calibration before coverage. The snapshot
  remains independent.

### 3.10 `web/static`

- Job: the user interface.
- Static HTML, CSS, and JavaScript files. There is no build step.
- Files: `index.html`, `app.css`, `app.js`, `planner.js`,
  `planner-params.js`, `planner.worker.js`, `config-check.js`,
  `meshtastic-static.js`, `protobuf-runtime.js`, and `vendor/`.
- Libraries load from vendored files, not from public CDNs.
  This keeps the site working without third-party availability.
- Libraries: Leaflet for the map, ECharts for the charts and the mesh
  graph. Both are in `web/static/vendor`.
- The pages call the JSON API. All node names come from the API.
  The browser does no name lookup and no join.
- The API serves `index.html` and replaces `__SONORAN_CONFIG__` with the
  client settings: the API base, the map tile URL and attribution, the
  default map view, and the mesh-graph base URL.
- Pages: dashboard, map, coverage planner, config check, mesh graph,
  nodes, node detail, chat, weekly check-in, firehose, traceroutes,
  statistics.

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

#### Content Security Policy

The API sends a strict policy with the page. Three sources come from
configuration, so a change of deployment does not break the page:

- `img-src` holds the map tile host from `MAP_TILE_URL`.
- `connect-src` holds the API origin from `WEB_API_BASE_URL`.
  Without this the browser blocks every request when the API runs on
  another origin.
- `frame-src` holds the mesh-graph origin from `MESH_GRAPH_BASE_URL`.

Two more sources are fixed, and both exist for the coverage planner:

- `script-src` holds `'wasm-unsafe-eval'`. Without it the browser
  refuses to compile the engine and reports nothing the user can see.
- `worker-src` holds `'self'`, for the worker that runs the engine.

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
  -> ingest.dedup (packet row, packet_seen row, is_new flag)
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
web/static -> api (over HTTP only)
```

Reverse imports are forbidden.
CI checks the import rules with `import-linter` or an equivalent tool.

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
