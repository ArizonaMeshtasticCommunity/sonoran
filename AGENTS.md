# AGENTS.md

This file gives rules to AI coding agents that work on this project.
Follow these rules at all times.

## 1. Project summary

This project is Sonoran, the azmsh.net Meshtastic dashboard.
It replaces two older tools:

- `az-meshtastic-metrics-exporter` (collector, no deduplication)
- `meshview` (web UI, weak traceroute display, SQLite problems)

The application does these things:

1. It reads Meshtastic packets from the azmsh.net MQTT broker.
2. It decrypts and decodes the packets.
3. It stores the packets in TimescaleDB (PostgreSQL) with deduplication.
4. It serves a read-only JSON API.
5. It serves a static web UI (no build step).
6. It links to a separate `mesh-graph` instance for traceroute graphs.

## 2. Technology stack

- Python 3.13 or newer
- FastAPI for the JSON API
- aiomqtt for MQTT
- SQLAlchemy 2.0 (async) with asyncpg
- Alembic for database migrations
- TimescaleDB (PostgreSQL) for storage
- Protobuf definitions from `buf.build/meshtastic/protobufs`
- Static frontend: HTML, HTMX, Alpine.js, Leaflet, ECharts
- numpy for the SRTM elevation transform
- A vendored WebAssembly build of SPLAT! for coverage prediction (GPL-3)
- Ruff for lint and format
- pytest for tests
- Docker Compose for deployment

## 3. Language and writing style

All documentation and code comments use ASD-STE100 Simplified Technical English.

- Use short sentences.
- Use one instruction per sentence.
- Use approved, simple words.
- Do not use slang.
- Do not use complex grammar.

## 4. Architecture rules

- The `decode` and `crypto` modules must never touch the database.
- The `api` module must never import `mqtt` or `ingest` internals.
- The API has GET endpoints only. Never add a POST, PUT, or DELETE endpoint.
- The API database role has SELECT rights only.
- The ingest database role has INSERT and UPDATE rights only.
- Modules talk to each other through small, documented interfaces.
- Keep functions small. Keep modules small.

## 5. Database rules

- Use Alembic for every schema change.
- Never edit a migration that is already applied.
- Test each migration with `upgrade` and `downgrade`.
- Deduplication key for packets is (`from_node_num`, `packet_id`).
- One `packet` row per unique packet. One `packet_seen` row per observation.
- Store the raw protobuf bytes of each packet in the `packet` table.
- High-volume tables are TimescaleDB hypertables with retention policies.

## 6. QA gates

A change is complete only when all of these pass:

1. `ruff check` passes.
2. `ruff format` is applied.
3. `mypy` passes (no new errors).
4. `pytest` passes.
5. New code has unit tests. Database code also has integration tests.
6. Alembic migrations apply cleanly.
7. The matching doc in `docs/` is updated.
8. Commit messages use conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).

See `docs/QA.md` for the full process.

## 7. Security rules

- The public API is read-only.
- Use the ORM for all queries. Do not use string SQL with user input.
- Serve static files with security headers (CSP, X-Content-Type-Options).
- Containers run as a non-root user.
- Never commit secrets. Use environment variables.
- The terrain endpoint serves one configured region only. It must never
  become a general proxy for the tile source.

## 7.1 Licensing

The coverage engine in `web/static/vendor/splat/` is under the GNU
General Public License version 3. The Sonoran web interface uses it and
therefore carries the same licence. Keep `LICENSE-GPL3` and the
attribution beside it. See `docs/PLANNER.md` section 6.

## 8. Common tasks

### Add a new packet type handler

1. Add a decoder in `src/sonoran/decode/payloads.py`.
2. Add a handler module in `src/sonoran/ingest/handlers/`.
3. Register the handler in `src/sonoran/ingest/pipeline.py`.
4. Add unit tests with a recorded fixture.
5. Update `docs/DATABASE.md` if you add storage.

### Update the vendored config checker

1. Copy the new files over `web/static/vendor/config-checker/`, leaving
   out `tests/`, `.github/`, and `wrangler.jsonc`. Never edit them here.
2. Record the new commit in that directory's `PROVENANCE.md`.
3. Run `tools/generate_protobuf_static.sh` if the protobuf descriptor
   changed. It refuses to install a result that compiles code at run
   time, that was built against a different major version of the
   vendored runtime, or whose runtime import was not rewritten.
4. Check that the logic still exposes `ConfigParser`, `ConfigChecker`
   and `ConfigFixer`, and that nothing new is read off `window` beyond
   `protobuf`, `jsyaml` and `MeshtasticProto`. `config-check.js` imports
   the first three and `index.html` loads the last three.
5. Check `lookupType` is still asked only for `meshtastic.DeviceProfile`
   and `meshtastic.ChannelSet`. A third type must be added to
   `STATIC_TYPES` in `config-check.js`, which raises rather than
   returning undefined.
6. Test with a real file of each kind: an Android `.cfg`, a CLI YAML,
   and an iOS or web JSON. Building a config from scratch is not a test:
   it is the one path that parses nothing.

### Add a new API endpoint

1. Add the route in the correct file under `src/sonoran/api/routes/`.
2. Add the response model in `src/sonoran/api/schemas.py`.
3. Add an endpoint test.
4. Update `docs/API.md`.

### Change the database schema

1. Edit the models in `src/sonoran/db/models.py`.
2. Create a migration: `alembic revision --autogenerate -m "description"`.
3. Review the generated migration by hand.
4. Test: `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head`.
5. Update `docs/DATABASE.md`.

## 9. Traps in this project

Each item below cost real debugging time. Read this section before you
change ingest, the schema, or anything that draws signal quality.

### 9.1 Packet identity is the Meshtastic packet ID

Use (`from_node_num`, `packet_id`) as the identity of a packet. The
`packet.id` surrogate key cannot be read back: the ingest role has no
SELECT right, so `INSERT ... RETURNING` fails. Every `packet_pk` column
is therefore NULL and nothing may rely on it.

Every payload table stores `packet_id` beside its node column. Join on
that pair.

### 9.2 `ON CONFLICT DO UPDATE` is denied to the ingest role

PostgreSQL needs table-level SELECT for the DO UPDATE path, and a
column grant is not enough. The ingest role has INSERT and UPDATE only,
so this form always fails:

    INSERT ... ON CONFLICT (key) DO UPDATE SET ...

Use two statements instead. Both work with the current grants:

    INSERT ... ON CONFLICT (key) DO NOTHING
    UPDATE ... WHERE key = ...

`DO NOTHING` works because revision 0006 grants SELECT on the conflict
target column alone. See `ingest/handlers/presence.py`.

### 9.3 Every gateway stamps its own `rx_time`

The same packet arrives from many gateways with different `rx_time`
values, and often with none. A deduplication key that includes a packet
time therefore never matches a repeat.

TimescaleDB requires the partition column in a unique constraint, so
the `packet` hypertable cannot hold the true key. The `packet_key`
table exists for that: a plain table, primary key
(`from_node_num`, `packet_id`), written with ON CONFLICT DO NOTHING.
The affected row count says whether a packet is new.

### 9.4 Node clocks are wrong, sometimes badly

Node clocks have been seen nearly 28 hours ahead. Never use a packet
time to answer "when did we hear this". Use the time this process
received the MQTT message. Time-windowed queries over payload tables
inherit the same skew, so a row can sit in the future for a day or more.

This rule was already written down and the ingest broke it anyway.
`_first_seen_at` preferred `packet.rx_time` over the receive time, so
`packet.first_seen_at` carried whichever gateway relayed the packet.
Live data ended up with 349 packet rows in the future, the furthest more
than a day ahead. A six hour query returned eighteen hourly buckets, and
retention could not expire a row dated after its own window.

There is one way to get this time, `heard_at` in `ingest/pipeline.py`,
and it takes the message rather than the packet so there is nothing to
get wrong. The gateway's claim is still kept, in `packet.rx_time`.
`test_packet_time_is_our_clock_not_the_gateway_clock` pins it.

Rows written before the fix keep the wrong time. They cannot be
repaired, because the true receive time was never stored. They age out
with retention. See `docs/ISSUES.md` 1.5.

### 9.5 A gateway observation is usually not a direct link

`packet_seen.rx_snr` belongs to the last hop into that gateway, not to
the link between the sending node and the gateway. In live traffic
about 82 percent of observations were relayed and only 5 percent
direct.

An observation is direct only when no hop was used:

    packet.hop_start = packet_seen.hop_limit

Show a signal figure from direct observations only. For the signal of a
real radio link, use `neighbor_metrics`, which is a node reporting the
neighbours it hears itself.

### 9.5.1 "Heard by" is a list of uploads, not of listeners

`packet_seen` records MQTT uploads, so the only observers this database
can ever hold are gateways. Every other node hears plenty and reports
none of it. A page that names the list "heard by" promises a coverage
answer and gives a plumbing one.

Two things then read as facts and are not:

- One gateway uploads the same packet many times, so the length of the
  list is not a number of gateways. One live packet had 22 uploads from
  15 gateways. Use `gateway_count`.
- The sender is often its own gateway, and uploads what it just sent.
  Those rows carry `hop_start` equal to `hop_limit`, so the hop rule
  alone calls them direct and then offers the reading as the sender's
  own link. On the same live packet all three "direct" rows were the
  sender, and no other gateway had heard it directly at all. `direct`
  now needs a different node as well as no hop.

### 9.6 Traceroute SNR needs care

- Values are in quarter dB. Divide by four.
- A hop the firmware could not measure carries INT8_MIN (-128). That is
  "not measured", not -32 dB. Treat it as unknown.
- `snr_towards` is often shorter than the hop list, so trailing hops
  have no reading at all. Roughly two thirds of reports are short.

### 9.7 One graph per modem preset

A LoRa preset is a different radio configuration. A node on LongFast
cannot hear a node on MediumFast. Never draw two presets in one graph:
the lines between them cannot exist. `neighbor_metrics` and
`traceroute` both store `channel` for this reason.

The rule covers the dots as well as the lines. `/api/map/nodes` took no
`channel` for a long time while every other layer on that page took
one, so switching the preset picker changed the lines and left all 395
positioned nodes in place. The reader is then invited to join two nodes
that have no way to reach each other. A node belongs to a channel when
it sent traffic seen on it, which is a claim about what it was doing
rather than how it is configured, so a genuine dual-preset node appears
on both. Live data had 14 of those against 709.

The picker also offers channels that are not presets, such as Weather
and PKI. Those ride on top of a preset, so filtering the nodes by one
of them gives the handful that talk there rather than a radio set. The
map keeps an "Every node" toggle for that reason.

### 9.8 mesh-graph keys a trace on the request ID

mesh-graph serves `/graph/trace/{trace_id}`, where its ingest reads:

    trace_id = decoded.get("requestId", packet.id)

A traceroute reply carries `request_id` pointing at the request it
answers, and is keyed on that. A request carries none and is keyed on
its own packet ID. Link with `request_id or packet_id`, never with the
node graph URL.

### 9.9 The Content-Security-Policy is built from configuration

Three origins come from settings and each must be added, or the browser
blocks the feature with no visible error:

- `img-src` needs the map tile host and the mesh-graph host.
- `connect-src` needs the API origin. Without it every fetch fails and
  the page renders empty.
- `frame-src` needs the mesh-graph origin.

### 9.9.1 The OpenStreetMap tiles need a Referer

The map showed OpenStreetMap's "blocked" placeholder tile, not the map,
and nothing in the console said why. The cause was our own security
header: `Referrer-Policy` was `no-referrer`, so the browser sent no
`Referer` to the tile host. The OSM tile server answers a request with
no `Referer` with the placeholder tile, because its usage policy asks a
site to identify itself and the `Referer` is how a browser does that.
Confirmed on this deployment: the real tile came back with a `Referer`,
the placeholder without one.

The fix is not to leave OSM. It is `strict-origin-when-cross-origin` in
`api/app.py`, which sends the origin, never a path. The dashboard keeps
its state in the URL fragment, which a `Referer` never carries, so this
leaks nothing a path would. Keep the attribution. See `docs/API.md`.

### 9.10 Channel keys come from settings, not from `.env`

`CHANNEL_KEYS` is usually absent from `.env`, so the built-in default
public key applies. Any offline script must read keys through
`get_settings()`. Passing an empty environment variable silently
decodes nothing.

### 9.11 `packet.payload_json` is never written

The ingest pipeline does not populate it. Decoded values live in the
typed table of their family. Read them back by (`node`, `packet_id`).

### 9.12 A replay test can skip the code it means to test

`process_message` runs the payload handlers only when a packet is new.
Tests that replay the same recorded fixture will find the packet already
stored and quietly skip the handler. Clear the rows for that packet
first, as `test_one_packet_from_many_gateways_stores_one_body` does.

### 9.13 The terrain transform must stay bit-exact

`src/sonoran/terrain/srtm.py` is a port of the site planner's
`src/terrain/srtm.ts`, which is itself a port of `srtm2sdf.c`. The
coverage engine reads terrain profiles straight out of these cells, so
one wrong cell is one wrong hill.

Two stages, two different rules:

- `srtm2sdf_transform` is **bit-exact** and must stay so. A golden test
  pins the whole London tile by hash. Do not update the hash to make a
  test pass. Find out what changed.
- `downsample_average` **cannot** be bit-exact against GDAL. About 6
  cells in 100 000 differ by one metre, always where the true average
  falls within 1e-4 of a half metre. The site planner has the same
  disagreement and asks for 99.9 percent exact with a largest error of
  one metre. This port measures 99.994 percent. Do not chase the rest.

Two details of `srtm2sdf` look like bugs and are not. When no neighbour
qualifies, the repair reuses the value of the last neighbour it read.
And the walk changes the grid as it goes, so a repaired cell can be the
neighbour that repairs a later one. That is why the walk cannot be
vectorised or run in parallel.

### 9.14 The planner needs three things the browser blocks by default

Each of these fails silently, which is the trap.

1. The Content-Security-Policy needs `'wasm-unsafe-eval'` in
   `script-src`. Without it the browser refuses to compile the engine
   and the page shows nothing at all. See 9.9.
2. `planner.js` must load **before** `app.js`. `app.js` runs the router
   as its last act, and the router needs `window.SonoranPlanner` to
   exist by then. Otherwise a reload on `#planner` quietly shows the
   dashboard. `test_planner_scripts_load_before_the_router` pins it.
3. The terrain cache directory must belong to the application user. A
   new Docker named volume takes the owner of the directory it covers,
   so the image creates `/var/lib/sonoran/terrain` and gives it to
   `azmsh`. Without that the container downloads each tile and then
   cannot write it.

### 9.15 The engine takes antenna heights in feet

SPLAT! reads heights as feet. The planner form asks for metres, as
everybody expects, and `planner-params.js` converts. Passing metres
straight through overstates every antenna by 3.28 times and draws
coverage that does not exist.

### 9.16 WebAssembly heap views go stale

Every `HEAPU8`, `HEAP32` and `HEAPF64` view must be read again after any
call that can grow the heap, including `_splat_malloc`. A view taken
before the growth points at a buffer that has been thrown away, and
reads rubbish without raising anything. Every `_splat_malloc` also needs
a `_splat_free` in a `finally`: the module has no garbage collector.

### 9.17 The config check page imports vendored logic and its globals

`web/static/vendor/config-checker/` is a copy of the community config
checker. Sonoran uses its **logic** and draws the result itself, in
`web/static/config-check.js`. That is the same arrangement as the
coverage planner. The vendored files are never edited here, and an
update is a re-copy of the directory. See its `PROVENANCE.md`.

Nothing about this feature runs on the server. A config, a channel key,
and an MQTT password are read in the browser and sent nowhere. There is
no endpoint for it and there must never be one. A test asserts that.

Five things keep it working, and each fails quietly:

1. The logic modules read `protobuf`, `jsyaml` and `MeshtasticProto` off
   `window`. Sonoran's `index.html` loads those three as classic scripts
   before `config-check.js`. Miss them and every parse dies with
   "jsyaml is not defined", while building a config from scratch still
   works, because that path parses nothing. Test with a real file, not
   with the build button.
2. `config-check.js` is a module, so it runs after `app.js`. `app.js`
   holds a `configReady` promise that the module resolves, and
   `PAGES.config` waits on it. Without that a reload on `#config` finds
   nothing registered and falls back to the dashboard.
3. `connect-src` must hold `https://api.github.com`. It is the only
   outbound request the dashboard makes, and it asks which firmware
   release is current. It carries no user data.
4. Android `.cfg` files are protobuf, and protobuf.js builds its
   decoders by compiling strings with `new Function`, which
   `script-src` forbids. The way round is not `unsafe-eval`: that would
   give back the permission that stops a crafted config becoming running
   code. `static/meshtastic-static.js` is the same schema compiled ahead
   of time by `tools/generate_protobuf_static.sh`, and
   `config-check.js` points `protobuf.Root.fromJSON` at it, so the
   vendored parser works unchanged. Two traps live in that script, and
   it refuses to install a bad result rather than let either through:
   the generator must be the same major version as the vendored runtime
   (protobuf.js 8 emits `reader.tag()`, which 7.6.3 has not got), and
   the generated runtime import must be rewritten to the local shim,
   because a browser cannot resolve a bare specifier.
5. `Permissions-Policy` must grant `serial=(self)`. Web Serial also
   needs a secure context: over plain HTTP the browser hides
   `navigator.serial` whatever the headers say, so the USB feature is
   missing until the dashboard is served over HTTPS. Nothing in the code
   can work round that.

### 9.18 A traceroute row is not a path

`sonoran/api/traces.py` holds the only correct reading of a traceroute
row. The graph, the map, and the traceroute pages all go through it.
They must keep doing so. Three pages once held a copy of these rules
each, the copies disagreed, and the graph drew links that the link page
could then find no evidence for.

Three rules apply, and each one drew a false link when it was missed:

1. A reply travels back, so `from_node_num` is the node the request was
   asked of. `trace_endpoints` swaps them. Reading a reply as stored
   keeps the middle of the path and invents the first hop and the last.
   One intermediate hop hides the fault, because the two links come out
   the same either way round. Two hops show it.
2. A hop past the last slot in `snr_towards` did not happen yet. The
   broker sees a packet while it travels, so a report often stops part
   way along its intended path. `evidenced_hops` cuts it there. A slot
   holding INT8_MIN still counts: the hop happened and only its reading
   is missing.
3. An unanswered request has an empty route, so its intended path is
   one hop from end to end. Drawing that claims the two nodes hear each
   other directly, which is the one thing the trace failed to show.
   Half of all rows in live data are these.

A request with a route is a fourth case, and it is not a fault. The
broker saw the request in flight, so the hops it had already made are
real and were really measured. Its readings stop one short of its
intended path, which is rule 2 doing its job: the hop to the far end
had not happened, which is why no reply came. Such links are true, and
the evidence for them runs one way. `Edge.confirmed` marks them, and
the graph page draws them fainter behind a toggle. In live data they
were 141 of 982 traceroute links, about 14 percent.

Note the two words are not the same. "Unconfirmed" on that page means
no SNR reading. "One-way" means measured, but no reply came back.

### 9.19 A row limit must never decide what evidence exists

`/api/graph` read 2000 traceroute rows and `/api/graph/link` read the
newest 500. With two thousand traceroutes a day, the graph drew plenty
of links whose evidence lay outside the smaller window. Clicking such a
link opened a page that said no report evidences it.

Raising the limit only moves the cut. A query that answers "what
evidences this link" must select by the nodes it asks about, not by
recency. `_mentions` in `routes/graph.py` does that, over the route
JSONB as well as the two endpoints.

The same trap has a front end half. `PAGES.link` in `app.js` asked for
a fixed 24 hours while the graph drew whatever `[data-graph-hours]`
said. A link found over seven days then opened an empty page.
`graphHours` carries the window across.

### 9.20 An ordinary packet does not carry its route

Only a traceroute holds the nodes it passed through. Every other packet
arrives with the sender, the gateway that uploaded it, and a hop count,
and nothing at all about the ground between them. A live traffic line is
therefore a straight line between two ends of a route that was never
straight. Say the hop count and leave the rest unclaimed. The one place
a true path can be drawn is `/api/map/traceroute-paths`.

`MeshPacket.relay_node` looks like the missing piece and is not. The
firmware truncates it to one byte, the low byte of the relayer's node
number, and `mesh_packet_metrics.relay_node_num` stores that byte as it
arrives. Values run 2 to 255. With 694 nodes active in a day this mesh
had 215 distinct bytes, 3.2 candidate nodes for an average byte, 12 for
the worst, and only 5.4 percent of relay observations resolving to a
single node. It also names the last hop alone, never the path. Drawing
a line from it would be a guess.

## 10. Reference documents

- `docs/PLAN.md` — the purpose, decisions, and requirements
- `docs/ISSUES.md` — open issues, and what is wanted next
- `docs/RESEARCH.md` — research on the source applications and the protocol
- `docs/ARCHITECTURE.md` — module contracts and data flow
- `docs/DATABASE.md` — the full database schema
- `docs/API.md` — the API specification
- `docs/QA.md` — the QA process
- `docs/PLANNER.md` — the coverage planner, its parameters, and its licence
- `docs/REVIEW.md` — code review findings, and which are still open
