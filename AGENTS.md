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

## 6.1 Releases (mandatory)

**After you merge to `main`, you must publish a release.** A merge without
a release is not finished work: the people who reported the bug are never
told, and the change log has a hole in it.

1. After your last merge in a session, run `python tools/release.py draft`.
2. Read the draft. Every "Done" issue must be closed now, and every
   @handle is a notification to a real person.
3. Run `python tools/release.py publish`. It makes a tag and a release,
   no commit, and it starts no CI run.
4. In your next pull request, run `python tools/release.py changelog`
   and include `CHANGELOG.md`. Never commit it to `main` by itself: that
   is one more CI run on self-hosted hardware.
5. Before you end a session, run `python tools/release.py check`. It
   exits 1 when merged work is not in a release. If you cannot publish,
   say so in your report.

Fill in the pull request template: "Release notes", "Issues" and
"Thanks" become the release. Write "part of #N" for an issue that must
stay open, never any form of close, fix or resolve beside its number.
See `docs/RELEASING.md`.

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

0. Run `tools/check_config_checker_pin.sh` to see whether upstream has
   moved past the pin. It needs read access to the upstream repository;
   set `CONFIG_CHECKER_REPO` to a URL you can read.
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

A value that comes from settings and reaches a header is a value
somebody can choose, so it goes through **one** check:
`safe_origin` in `sonoran/embed/sanitise.py`. Never build an origin any
other way.

`urlsplit` is not a validator. It keeps a semicolon and a space inside
a network location, and a semicolon in a `Content-Security-Policy`
starts a new directive. `api/app.py` had its own `_origin` that checked
nothing, so a crafted `MAP_TILE_URL` injected a directive — and it
landed **before** the real one, which is what matters, because a
browser honours a directive's first occurrence:

    script-src 'unsafe-inline' *                        <-- injected
    script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'  <-- ours, ignored

`sanitise.py` had the right check all along, for `frame-ancestors`, and
its docstring claimed the other headers used it too. They did not. If
you add a fourth source, use `safe_origin` and add a case to
`test_every_directive_appears_once`, which checks the whole header
rather than one directive so it covers a source nobody remembered.

A refused origin is logged, because the browser gives no sign: a tile
host missing from `img-src` draws nothing and says nothing.

### 9.9.2 The header decision must use the routed path

`scope["path"]` carries the mount prefix when `WEB_BASE_PATH` is set and
the proxy does not strip it. The security middleware matched on it, so
under that deployment **neither** branch matched:

- The embed took `X-Frame-Options: DENY` and would not frame. Closed,
  so only a trap.
- The dashboard was served with **no `Content-Security-Policy` at all**.
  Open, and the reason this was a defect rather than an untidiness.

Use `starlette.routing.get_route_path(scope)`, which is the helper the
router itself uses to match a route, so the header decision and the
route resolution cannot disagree.

The tests passed throughout, because `TestClient` builds a scope whose
path excludes `root_path` unless it is told otherwise. A test that
cannot see the production shape is a test that reports green over it;
pass `root_path=` to `TestClient` **and** request the prefixed path to
get the shape a non-stripping proxy sends.

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

### 9.11 `packet.payload_json` holds only an allowlist

Decoded values live in the typed table of their family. Read them back
by (`node`, `packet_id`). Since 2026-09-22 ingest also writes
`payload_json` for the families with no table of their own: node info
(without the MAC address), routing, traceroute, map report and pax
counter. `sonoran/decode/stored.py` holds the allowlist.

The public API holds no channel key, so it can never decode a packet
after the fact. What ingest does not keep is gone. Never add a family
that can carry what a person typed: text, store and forward, waypoint,
range test. Never add admin. Only `STORE_TEXT_MESSAGES` decides whether a
message body is kept. Older rows stay NULL.

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

### 9.13.1 A terrain page is written south-up and east-first

`srtm2sdf_transform` ends in `window[::-1, ::-1]`, so a page is **not**
in the order every other grid in this project uses. Row 0 is the
**south** edge and column 0 is the **east** edge, which is the order
`WriteSDF` walks. `coverage/grid.py::Grid` is the opposite on both axes:
row 0 is north and column 0 is west.

Anything that reads an elevation back out of a cached page goes through
`terrain/srtm.py::page_cell`, which is the only reading of that order:

    row    = round((latitude  - floor(latitude))  * PAGE_SIZE)
    column = PAGE_SIZE - 1 - round((longitude - floor(longitude)) * PAGE_SIZE)

One axis the wrong way round puts every candidate on the wrong hill and
nothing raises anything: the numbers are still plausible elevations.
`test_the_page_cell_order_is_read_back_exactly_as_it_was_written` builds
a grid whose every cell names its own position, runs the transform, and
reads it back, so the writer and the reader are pinned together.

**A tile is named for its south-west corner, which is not the rounding
anybody expects at a negative longitude.** `floor(-112.07)` is **-113**,
so a node at 112.07 W stands in `N33W113` and not in `N33W112`. Use
`tile_name_of`. A test that wrote its fake terrain into the wrong tile
read the whole window as "we hold no terrain here", which is a working
state, so the test failed later and somewhere else.

### 9.13.2 `preset_by_key` and `preset_for_channel` take different spellings

`ModemPreset` carries two names. `key` is `LONG_FAST`, the internal
name. `name` is `LongFast`, the channel name the firmware uses, and it
is what `node.last_channel`, `neighbor_metrics.channel` and the gaps
index all store.

`preset_by_key("LongFast")` returns None. It does not raise, so a caller
that reads an artefact written with `preset.name` and looks it up by key
silently produces nothing at all, and an empty result is a working state
everywhere in this project. Read a channel name with
`preset_for_channel`, which normalises case and separators as well.

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

### 9.16.1 The engine declares integers where JavaScript hides them

`splat_create` takes sixteen values. Three of them are `i32` and the
rest are `f64`:

    (f64 f64 f64 f64 f64 f64 f64 f64 f64 i32 i32 f64 f64 f64 f64 i32)

The three are the radio climate, the polarization, and the resolution.

JavaScript has one number type and the Emscripten loader converts, so
`planner.worker.js` can pass `4` or `4.0` and never notice. Python does
not, and `wasmtime` refuses a float where the module declared an
integer. Passing `float(climate)` there raises

    TypeError: don't know how to convert 4.0 to i32

and no run starts at all.

`EngineParams.to_arguments` returns the right type for each position,
and a test asserts the three stay whole numbers. Read the signature out
of the binary rather than the loader if a fourth is ever added: the
loader shows none of this.

### 9.16.2 A coverage level does not fit a signed byte

The engine reports a field strength as a byte with a 200 dB offset. It
is tempting to take the offset off and keep a signed byte, because a
level looks like a small negative number.

It does not fit. A signed byte reaches -128 and the sensitivity of Long
fast is -139 dBm. Every level clipped to -127, every level then sat
above every threshold, and the usable filter passed the whole map
without failing anything.

`sonoran/coverage/grid.py` keeps the engine's own encoding: an unsigned
byte, zero meaning no run reached the cell. `to_level` and `to_dbm` are
the only places that convert, and a threshold goes through `to_level`
before it meets a grid.

### 9.16.3 A route that must refuse cannot check inside the handler

A FastAPI handler body runs after every parameter is resolved. A check
at the top of the body has already opened a database session.

The embed must answer 404 while it is off, and it must do that without
touching the database. So the check is a dependency of the whole
router:

    router = APIRouter(dependencies=[Depends(_require_enabled)])

`tests/unit/test_embed.py` pins it.

### 9.16.4 An engine instance is made for a process, not for a run

`SplatInstance` owns a WebAssembly linear memory. The memory grows to
the largest run the instance has made and never shrinks, which is why
one instance is held and reused: the second run costs no new memory.

Making a new instance for each prediction grows a new heap of several
hundred megabytes each time, and the old ones are never given back. The
store holds the three host functions, which are bound methods of the
instance, so the instance and its store hold each other. The cyclic
collector does not help: it counts objects, and the heap is memory no
Python object accounts for. `close` is the only way to give one back.

`test_an_instance_that_is_dropped_and_not_closed_keeps_its_heap`
measures it. Twenty megabytes for each dropped instance at a 20 km
radius, and it does not come back.

A three hundred node run was ended by the memory killer for this, with
each worker at 4.7 GB. `web/static/planner.worker.js` never had the
problem: it instantiates the module once and memoises the promise.

So one instance for each process, held for every site. Use `close`, or
the instance as a context manager, for a caller that must let one go.

### 9.16.5 A worker process is started by spawn, never by fork

`jobs/coverage.py` builds in a worker thread, because the engine holds
the processor and would otherwise stop the event loop of the whole jobs
process. It starts worker processes from inside that thread.

Fork copies only the thread that calls it. A lock that any other thread
held at that moment is held for ever in the child, and the logging lock
is the one that does it: this job logs from the main thread while it
works. The child then blocks before it runs a single instruction of the
initialiser.

There is no error and no timeout. The pool waits for a result that
never comes, the run never finishes, and the scheduler waits on a task
that never returns. It was found with two workers sitting in
`futex_wait` with no processor time at all, twenty minutes after they
were made.

It does not fail every time, which is worse. A run whose main thread
happens to hold no lock at the moment of the fork works.

    ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn"))

Spawn starts a new interpreter and inherits no locks. It costs about a
second for each worker, once, against a run of half an hour.

### 9.22 A role of NULL is a client, not an unknown (fixed at ingest, #197)

**Fixed for new rows.** `ingest/handlers/nodeinfo.py` used to read every
enum with

    if not value:
        return None

and Meshtastic numbers `CLIENT` as zero, so the most common node on a
mesh was stored with `role IS NULL`, exactly like a node that had never
sent a NodeInfo at all. The live map drew 167 clients on MediumFast in
the grey it keeps for "no role reported".

Roles now go through `_role_name`, which never returns None for a node
that introduced itself: zero is `CLIENT` (config.proto calls it the
"Default Role"), and a number this repository has not vendored keeps its
digits as `ROLE_<n>` rather than collapsing back into NULL.

`_enum_name` still treats zero as None, and still should -- `hw_model`
zero is `UNSET`, which really does mean nothing was reported. Fixing
role by changing the shared helper would have made every unset hardware
model read as whatever name zero has.

**Old rows are still NULL** and cannot be backfilled: nothing in the
database says which NULLs were clients. `roles.resolve_role` reads a
stored `long_name` or `short_name` as evidence that a User message was
processed, because `store_nodeinfo` writes those in one statement with
the role and nothing else in the ingest writes them. That inference
lives in `roles.py` only -- never add a second copy in a page -- and it
expires: when `SELECT count(*) FROM node WHERE role IS NULL AND
long_name IS NOT NULL` reaches zero, it can go.

Never read NULL as "unknown, so include it". The coverage map did, and
predicted from 689 nodes where 50 were infrastructure. `sonoran/roles.py`
holds the test and `tests/unit/test_roles.py` pins it.

The same trap is why `tests/integration/test_coverage_job.py::_add_node`
takes its role as a required keyword argument. It defaulted to `ROUTER`,
so every coverage test asserted about routers while its author believed
it asserted about nodes. Do not give it a default again.

### 9.23 The engine's clutter scalar is passed as zero on purpose

`coverage/params.py` sets `clutter_height_m=0.0` for every prediction.
That looks like a value somebody forgot to fill in. It is not.

The scalar was measured on flat ground at 906 MHz. A 9 m clutter
height costs a 30 m antenna 0.00 dB and a 3 m antenna 66 dB, so it is
a step at the antenna height and not a loss. The receiving end is
charged 0.00 dB at any height, and the receiving end is the 1.5 m
handheld the whole map is drawn for.

The correction is `coverage/clutter.py`, which is ITU-R P.2108-1 3.1
charged at both terminals. Turning the scalar back on double-charges
the transmitter and still charges the receiver nothing.

### 9.24 `usable` is the weaker direction of one node, then the best node

Not the weaker of the two combined layers. Taking the best of each
direction across every site first, and the minimum afterwards, lets one
node answer for the downlink and another for the uplink, and paints
ground as usable both ways where no single radio closes both.

`jobs/coverage.py::_predict` builds it beside the two directions, for
each site, before anything is combined. Do not derive it from the
finished layers.

### 9.26 The calibration fit reads every role. The map does not.

These are opposite questions and the answer is opposite.

The coverage map predicts from infrastructure, because only a node that
stays where it is can hold coverage open. The fit measures what a radio
heard, and it needs both ends of a link. On the Arizona mesh 50 of 931
positioned nodes are infrastructure, so a role-filtered fit would throw
away almost every measurement there is.

A client is poor evidence of where the mesh reaches and good evidence
of what a radio heard. `jobs/calibrate.py::read_peers` reads the role
only to pick an antenna height. Do not add a role test to it.
`test_the_fit_reads_every_role_and_the_map_does_not` pins it.

### 9.28 Check the project board before starting an issue, every time

Tyler gates work through the **Roadmap** board: an issue on it is not to
be started until its Status is **Ready**. The statuses are `Ideation`,
`Ready`, `Blocked`, `In progress`, `Done`.

**Ask the board. Do not carry the answer.** As of 2026-09-24, four
issues are on it and all four are `Ideation`:

    #178 Noise Floor Tracking
    #179 Sonoran-Contributor docker service
    #181 Sonoran - Contributor management
    #182 Sonoran - Noise Floor display

That number was **one** when it was first reported, and three more were
filed afterwards. A session repeated the original answer as though it
were durable and came close to starting work that was gated. The fact
was true when it was learned and false when it was used, which is the
whole hazard: **board membership is a live value, not a remembered
one.**

    gh api graphql -f query='query{organization(login:"ArizonaMeshtasticCommunity")
      {projectV2(number:1){items(first:60){nodes{content{... on Issue{number}}
      fieldValues(first:12){nodes{... on ProjectV2ItemFieldSingleSelectValue
      {name field{... on ProjectV2FieldCommon{name}}}}}}}}}}'

An issue **absent** from the board is not gated and is fair game.

#### The trap: an empty answer that means two different things

`gh issue view N --json projectItems` returns a bare `[]` when the token
lacks the `project` scope — **no error, no warning**. That is
indistinguishable from "this issue is on no board", and it is how a
session concluded an issue was ungated when it had simply been unable to
look. See 9.19 and the entry on instruments in `docs/DECISIONS.md`: an
empty result and a true negative are the same bytes until the instrument
is proven.

**The worst part is that it survives being tested.** Someone checks the
`gh issue view` form on a machine that has the scope, sees correct data,
concludes the command is sound, and carries that conclusion to a host
where it is false. The command is not wrong; it is wrong *conditionally*,
and the condition is invisible in its output. A test that passes is not
evidence here, because the failing case looks identical from inside the
passing one.

The GraphQL query above **errors loudly** on a missing scope, so prefer
it. If you use the `gh issue view` form, check the scope first:

    gh auth status | grep -i 'token scopes'   # needs `project`

The token carries `project` (read and write) as of 2026-09-24, so a
gated issue moved to `Ready` can also be set to `In progress` and then
`Done` from here, which is what Tyler asked for.

### 9.25 A diagnostic coverage run never reaches the public embed

`COVERAGE_SITE_ROLES=ALL` predicts from every node, which is what it is
for. It also predicts from every client, and a client is usually
somebody's house. Each one then draws a footprint, and a footprint has
a centre.

`embed/sanitise.py` keeps the markers back and always has. The tiles
are the leak. So `/api/embed/coverage` answers `available: false` with
`reason: "diagnostic"` for such a run rather than labelling it, and the
public page says a diagnostic is not published there.

Do not "improve" this into a banner. A banner tells a reader what they
are looking at; it does not stop them reading the middle of a circle.

**The JSON refusal is not the whole of it, and used not to be any of
it.** The embed drew its tiles from `/api/coverage/tiles`, the
dashboard's route, which has no `EMBED_ENABLED` dependency and no
diagnostic test and takes the site set from the path. Publishing the
embed meant opening that path, and one segment then fetched the client
map. So there are now two more locks, and both are load-bearing:

1. The public tiles are `/api/embed/tiles/{stamp}/{preset}/{layer}/...`
   on the **embed** router, so `_require_enabled` reaches them. There is
   no site set in the URL, the stamp must be the published run, and a
   diagnostic run is refused by `_require_published_map`, a dependency
   of the whole tile router. That is 9.16.3 one level down: the route
   that carries the pixels is the route that has to refuse.
2. A diagnostic run writes its tiles under the site set `diagnostic`,
   never `infrastructure`. The path carries the set, so a path that
   said `infrastructure` while holding a client footprint was a path
   that lied, and the tiles are what a reader fetches.

`docs/API.md` 3B.5 is the exact list of paths a proxy may open. Never
`/api/coverage` by prefix: it publishes the dashboard's tiles of every
site set, the node names and rounded positions in `coarse_sites` and
`presets[].nodes`, and the calibration.

`embed/sanitise.py` also takes no settings argument, and must not gain
one. If the public role test read `COVERAGE_SITE_ROLES`, one
environment variable would put the whole mesh on a public map.
`test_a_diagnostic_run_can_never_widen_the_public_map` pins it.

### 9.27 A run can publish more than one map, and only one is public

`COVERAGE_INCLUDE_CLIENTS` makes a run predict a second map from the
nodes that repeat traffic without being infrastructure: `CLIENT`,
`CLIENT_BASE` and `ROUTER_CLIENT`. It answers a real question, which is
why a neighbourhood works where no router covers it.

Three things hold it apart from the public map, and each one is
load-bearing:

1. The tile path carries the site set:
   `{preset}/{site_set}/{layer}/{z}/{x}/{y}.png`. Two maps of the same
   preset are different answers and must never share a tile.
2. `Manifest.presets` and `Manifest.is_diagnostic` stay the
   **infrastructure** map. A reader that takes them without asking for
   a site set gets the narrow answer, and `/api/embed/coverage` is that
   reader. `Manifest.site_sets` carries every map, and the dashboard
   reads it.
3. The public tile route takes no site set. It is
   `/api/embed/tiles/{stamp}/{preset}/{layer}/...`, it reads
   `SITE_SET_INFRASTRUCTURE`, and there is nowhere in the URL to name
   another set.

The third one used to be a constant in
`web/static/embed-coverage.js`, on a route that took the set from the
path. A constant in a page the public loads is a rule for a browser
that means no harm; it is not a lock. When something must be refused,
refuse it where the bytes are served.

`EXTENDED_ROLES` is not a subset of `INFRASTRUCTURE_ROLES`, so
`is_diagnostic_role_set` already calls the wider map diagnostic and
`/api/embed/coverage` already refuses a diagnostic run. That is the
first lock, and it was there before this feature.

Membership of the set is quoted from `meshtastic/config.proto` in
`sonoran/roles.py`, never inferred. `CLIENT_MUTE` is out because the
proto says it "does not forward packets from other devices". `SENSOR`,
`TAK` and `LOST_AND_FOUND` are out because the proto never says whether
they forward, and this project does not assert what the vendor did not
state. `TRACKER` and `TAK_TRACKER` are out because they move.

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

### 9.21 A calibration estimate is not a radio reading

`neighbor_metrics.snr` is measured. `NodeFit.offset_db` is inferred.
Never present the second value as if a node reported it.

The censored regression once had no bound and did not fit its global
model bias during each expectation round. A node with seven silent
links and no reported link reached -1830.35 dB. Some usable raw offsets
also passed 50 dB. The radio-profile resolver held the value to 15 dB,
but the report still showed the impossible estimate and the bad node
could pull the rest of the fit.

Keep all of these guards:

1. Fit the global bias in every censored-data round.
2. Bound and anchor node offsets in every round.
3. Check the bound again when a stored file is read.
4. Give no offset to a node with too little evidence or wide scatter.
5. Reject the whole fit when its bias or scatter is outside 20 dB.
6. Run a due calibration before coverage, never beside it.
7. Hold a `lock_calibration` node at zero **inside** the fit, and keep
   the 15 dB bound when you do.

Guard 7 has a trap in it. The bound used to be applied by the same
projection that held the offsets summing to zero. A pinned node is
already the anchor, so a pinned fit must not re-centre anything — that
would drag the pinned node off zero — and it therefore does not run that
projection. The bound is then applied on its own, in the same place. Take
the clip out and you are back to the -1830.35 dB estimate this section
is about. `test_pinning_a_node_still_bounds_the_others` pins it.

Pinning also moves the reported model bias, on purpose. With nothing
pinned the bias is measured against the mean of every guess; with a node
pinned it is measured against that radio. Two runs either side of a lock
are two different answers and neither is a fault.

The live fit on 2026-08-21 had a bias near -41 dB and was rejected. Do
not increase the guard to make live data pass. First prove that absence
from an aggregated neighbour list means the radio link was silent.

The 2026-09-18 run read 420 links and 362 of them, 86 percent, were
censored. The solver handles censoring correctly — measured against
planted truth it recovers a bias to within 0.6 dB at 48 percent
censoring — and it cannot survive a censored observation that is not
true: false silence drives the fitted bias down almost linearly with its
share while the reported-only mean stays at zero.

`summary.mean_db` is that reported-only mean, and it has now been read:
-13.57 dB. So the -44.62 splits into -13.57 dB of real error on the
links the mesh measured and -31.05 dB opened by rows that record
silence. Inverting the intercept score equation puts the mean censoring
bound at -42.3 dB, and only about 6 percent of silence that deep is
credible against the links we did measure. Two things follow and both
are load-bearing: **do not lower `MAX_CANDIDATES` to make the bias look
better** — it moves the bias 30 dB while the reported mean does not
move at all, so it is a dial and not a measurement — and **do not raise
the trust guard**. Fix the evidence instead; the same mesh without the
false silence fits at -14.46 dB, inside the guard, with nothing
weakened. The full decomposition, the falsification table and the path
forward are in `docs/ISSUES.md` 2.4.2.

## 10. Reference documents

- `docs/PLAN.md` — the purpose, decisions, and requirements
- `docs/ISSUES.md` — open issues, and what is wanted next
- `docs/RESEARCH.md` — research on the source applications and the protocol
- `docs/ARCHITECTURE.md` — module contracts and data flow
- `docs/DATABASE.md` — the full database schema
- `docs/API.md` — the API specification
- `docs/QA.md` — the QA process
- `docs/PLANNER.md` — the coverage planner, its parameters, and its licence
- `docs/GAPS.md` — which nodes the mesh is not carrying well, where one new
  node would help, and what neither of those can say
- `docs/REVIEW.md` — code review findings, and which are still open
- `docs/RELEASING.md` — how to publish a release, and what it costs in CI
