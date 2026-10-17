# API.md — API specification

This document describes the Sonoran JSON API.
It uses ASD-STE100 Simplified Technical English.

## 1. Rules

1. The API has GET endpoints only.
2. All responses are JSON.
3. All timestamps are ISO 8601 in UTC.
4. Node IDs accept these formats: `!xxxxxxxx`, plain hex, `0x` hex, decimal.
5. Node IDs in responses use the `!xxxxxxxx` format.
   Responses that name a node also carry `display_name`.
   The display name is the long name, then the short name,
   then the node ID. It is never empty.
6. List endpoints support cursor pagination:
   - `before`: return rows older than this timestamp or cursor.
   - `limit`: maximum rows. Default 100. Maximum 500.
7. Errors return a JSON object: `{"error": "message"}`.
8. The base path is `/api`.
9. Each caller has a request budget. See 1.1.

### 1.1 Request budget

The API is read-only and sits behind the login portal. The risk is a
script that copies the whole database through it. Each caller therefore
has a token bucket (`sonoran/api/limits.py`):

| Paths | At once | Sustained | Settings |
|---|---|---|---|
| `/api/coverage/tiles/`, `/api/embed/tiles/`, `/api/terrain/page/` | 3000 | 30 a second | `API_TILE_RATE_BURST`, `API_TILE_RATE_PER_SECOND` |
| Every other `/api/` path | 300 | 3 a second | `API_RATE_BURST`, `API_RATE_PER_SECOND` |

A reader does not reach these numbers. One dashboard page asks for 10
to 25 answers, and the live views poll once in 15 seconds. Tiles have
their own budget, because a map fetches them in hundreds, and a map
must not spend the budget of the rest of the page.

A request over the budget gets 429 with `Retry-After` in seconds. The
page, `/static/` and `/health` are never counted. The first refusal of
a caller in each minute is logged at WARNING.

A caller is its client address. `API_RATE_USER_HEADER` can name a
header that holds the signed-in user instead, so one reader is one
budget from any address. Set it **only** to a header the login proxy
replaces on every request. A header that the proxy passes through is
written by the caller, and a new name on each request is a new budget
on each request. The proxy is not the same on every deployment:
development uses Caddy and Authelia, which replace `Remote-User`, and
production uses Keycloak. So the setting has no default. A request
without the header is counted by its address. uvicorn reads that address from
`X-Forwarded-For` only when the proxy is in `FORWARDED_ALLOW_IPS`. On
this deployment that is the Docker gateway of the API container,
`172.18.0.1`, because Caddy reaches the API through it. Without the
setting every caller has the gateway's address and shares one budget.

**Off by default.** `API_RATE_LIMIT_ENABLED=true` turns it on. Turn it
on only where the API sees real client addresses: behind a proxy that
is not in `FORWARDED_ALLOW_IPS`, every reader has the proxy's address,
and all of them share one budget.

### 1.2 The `preset` parameter (#313)

The list endpoints take `preset`, a LoRa modem preset name such as
`LongFast` or `MediumFast`. It keeps the rows carried on that preset:

- `GET /api/nodes` and `GET /api/nodes/facets` (3.1, 3.1.1)
- `GET /api/packets` (4.1)
- `GET /api/chat` and `GET /api/chat/overview` (5.1, 5.3)
- `GET /api/stats/portnums` (8.4)

A topic channel is not a preset. `azmsh` runs on MediumFast and on
LongFast, so `channel=LongFast` never showed an azmsh message, on any
preset. Ingest now decides which preset carried each packet and stores
it (see `docs/DATABASE.md`). `preset` reads that tag:

    modem_preset = :preset
    OR (modem_preset IS NULL AND channel = :preset)

The second line is the fallback for a row written before the tag. Such
a row is read by its topic channel, which is exactly what the page did
before. The fallback fades out as retention expires the old rows: after
30 days for packets and messages. A node keeps its fallback until it
sends a packet that ingest tags.

For a node, the tag is `node.last_preset`, the preset of its newest
tagged packet, and the fallback column is `node.last_channel`. A node
whose last packet was on `azmsh` therefore stays on its own preset.

`preset` and `channel` are separate. Both may be given, and both then
apply: `channel=azmsh&preset=LongFast` is the azmsh traffic on LongFast.
A request without `preset` runs exactly the SQL it ran before.
`tests/unit/test_preset_param_legacy.py` holds that to the byte.

The name is matched without regard to case or separators, so `longfast`
and `LONG_FAST` work. A name that is not a preset, such as `azmsh`,
returns 422 rather than an empty list.

The map, graph, coverage, gaps and leaderboard endpoints do not take
`preset` yet. They still take `channel`, and the page sends the preset's
own channel name there.

### 1.3 Stored long-window answers (#371)

Some answers are built by the jobs service every few minutes and read
from its tables: `/api/graph` for 6, 24, 72 and 168 hours, the longest-link
board of `/api/stats/leaderboards` for its default window and `hours=24`,
`168` and `720`, `/api/stats/broadcast` for `hours=24`, `168` and `720`,
and `/api/map/nodes?channel=...&hours=168`. Any other window is computed
when asked, as before.

- **The same answer.** A stored answer equals the live one, apart from
  when it was measured. Names, roles and positions are read when the
  request is answered.
- **`built_at`.** The graph, the board and the broadcast rates say when
  their links or rates were measured. A stored answer is up to a few
  minutes old; a live one is as new as the request.
- **Never stale for long.** A build older than three build intervals
  (30 minutes, 90 for 30 days, by default) is not used.
- **How long an answer is held.** The Statistics answers and the graph
  are held in the API for 1/720 of their window: 30 s for a few hours,
  2 minutes for a day, `STATS_CACHE_MAX_SECONDS` (5 minutes) for 3 days
  or more and for a range that is over, 2 minutes with no window. Each
  answer states its `window_end`. `STATS_CACHE_SECONDS=0` turns every
  hold off.
- **`ETag`.** Answers under `/api/graph`, `/api/stats` and
  `/api/map/nodes` carry a weak `ETag` and `Cache-Control: private,
  no-cache`. A request with a matching `If-None-Match` gets `304 Not
  Modified` and no body.

## 2. System endpoints

### 2.1 `GET /health`

Returns service health.

Response:

```json
{
  "status": "ok",
  "database": "ok",
  "version": "0.1.0"
}
```

### 2.2 `GET /api/version`

Returns the application version and the schema revision.

## 3. Node endpoints

### 3.1 `GET /api/nodes`

Returns nodes, newest heard first by default.

The body is a bare array. The count of **everything matching the
filters** is in the **`X-Total-Count`** response header, which is not
the same as the number of rows returned: the list is capped, and a
caller that counts what it received reports the cap. A page that did
exactly that said "300 nodes match" on a mesh of 2,372.

Filters:

- `q` — search in long name, short name, node ID.
- `hw` — filter by hardware model.
- `role` — filter by role.
- `channel` — the channel the node was last heard on.
- `preset` — the modem preset of the node's newest tagged packet. See
  1.2. It is never lifted in the facet counts: it says which mesh is
  counted.
- `position` — `exact`, `coarse`, or `none`. How well the node's
  position is known, by the same rule the gaps assessment applies. A
  node that sent no precision field at all is `exact`, not missing: that
  is the ordinary case for a node heard directly over the radio.
- `licensed` — `true` for nodes that claim an amateur licence.
- `gateway` — `true` to show only MQTT gateways.
- `active_hours` — only nodes heard in the last N hours. Default: all.
- `quiet_hours` — the other side of `active_hours`: only nodes NOT heard
  for the last N hours. The two compose into a band, so
  `active_hours=168&quiet_hours=24` is "heard this week but not today".
  Both windows are measured from the server's clock, which is why this
  exists beside `before`: a caller naming the moment itself would filter
  on the wrong hour whenever its own clock was wrong, and a band built
  from one of each would be measured against two clocks. A node never
  heard at all matches neither, the same way it matches no `active_hours`.
- `before` — only nodes last heard before this time.
- `limit`, `offset`, `cursor` — paging. Default limit 100. Maximum 500.
  See "Paging" below.

- `gaps` — `bad`, `ok` or `unknown`, from the gaps assessment. **Requires
  `gaps_preset`**: a node can need help on one modem preset and be fine
  on another, so a state without a preset is the merge AGENTS.md 9.7
  forbids. Without it, 422. For a preset with no assessment written,
  **409** — which is a different fact from "no nodes are in that state",
  and must not be served as an empty list.

Ordering:

- `sort` — one of `last_heard`, `first_seen`, `name`, `node_id`, `hw`,
  `role`, `channel`, `position`. Anything else is a 422 naming the
  list. Default `last_heard`.
- `order` — `asc` or `desc`. Default `desc`.

`name` orders by the long name, then the short name, then the ID, which
is what the column shows. Nulls sort last in both directions: a node
with no role is not the smallest role. Every order is made total with
the node number, so a node cannot arrive on two pages or on none.

Paging:

- `cursor` — the rows after the last row of a previous page, in the
  same order. Every non-empty answer carries the cursor for its last
  row in the `X-Next-Cursor` header. A short page is the end. The
  cursor is opaque. It carries the `sort` and `order` it was made
  under, and under any other it returns 422, so a later page cannot
  come back in a different order. A cursor that cannot be read, or
  whose value has the wrong type for its sort, returns 422.

Use `cursor`, not `offset`, to page (#250). `last_heard` changes all the
time. A node heard between two offset pages moves in the order, and
every row behind it moves by one: a row is then shown twice, or it is
never served at all. The second case cannot be seen by the caller. A
cursor names the last row by its sort value and its node number, so a
node that moves cannot shift the next page. `offset` still works.

### 3.1.1 `GET /api/nodes/facets`

Returns the values each filter could take and how many nodes sit behind
each one, so a picker can show the choice before it is made.

Takes the same filters as the list. **Each group is counted with its own
filter lifted and the rest in force.** Counting a group with itself
applied would show the chosen value holding everything and the others
holding nothing, which tells a reader only that the filter is on; what
they are asking is "if I picked this instead, how many would I have".

Groups: `hw`, `role`, `channel`, `position`, `gateway`, `licensed`, and
`gaps` — the last carrying a preset with each state, because that state
has no meaning without one.

Response item:

```json
{
  "node_id": "!a1b2c3d4",
  "node_num": 2717905876,
  "long_name": "Example Node",
  "short_name": "EXN",
  "hw_model": "TBEAM",
  "role": "CLIENT",
  "last_heard": "2026-08-01T12:00:00Z",
  "is_mqtt_gateway": true,
  "has_position": true
}
```

### 3.1.2 `GET /api/nodes/export`

Returns every node the list would show, as one file to download (#350).
The Nodes page uses it for its **Export** control.

It takes every filter of 3.1 and its `sort` and `order`. The list and
the export read them through one dependency (`node_list_params`) and
build their query with one function (`_node_list_query`), so a filter
cannot reach one and miss the other. The rows are the rows the list
gives for the same query, in the same order. The export does not page:
`limit`, `offset` and `cursor` are not read.

Parameters:

- `format` — `csv` (default) or `json`. Anything else is 422.
- `columns` — the list's columns, comma-separated, in the order the page
  draws them. Default: every column, in the order of the page. An
  unknown or repeated name is 422.

| Column | CSV headings | Fields of 3.1 |
|---|---|---|
| `name` | Name, Short name | `display_name`, `short_name` |
| `node_id` | Node ID | `node_id` |
| `hw` | Hardware | `hw_model` |
| `role` | Role | `role` |
| `flags` | Gateway, Position | `is_mqtt_gateway`, `has_position` |
| `last_heard` | Last heard | `last_heard` |

The file holds **no field that the list does not show**. It holds no
coordinates: the list shows only whether a node has a position.

The values are the values of 3.1. A time is ISO 8601 in UTC, which
stays true after the file is saved. The page shows "5m ago", which does
not. A role is the value the firmware sent, such as `CLIENT_MUTE`. The
page shows it in words.

The CSV file:

- RFC 4180, UTF-8, with a byte order mark so that Excel reads names with
  accents and emoji correctly. Lines end with CRLF.
- `true` and `false` for the two flags. An empty cell for no value.
- A cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return
  gets `'` before it. A spreadsheet runs such a cell as a formula, and a
  node name is typed by whoever owns the node. The JSON file is not
  changed.

The JSON file is an array of objects. Each object holds the fields of
the columns, in column order.

Headers:

- `Content-Disposition: attachment; filename="sonoran-nodes-YYYYMMDD-HHMMSSZ.csv"`
  (or `.json`), stamped in UTC.
- `Content-Type: text/csv; charset=utf-8` or `application/json`.
- `X-Total-Count`: the number of rows in the file.
- `Cache-Control: no-store`.

**Ceiling.** One file holds at most 10,000 nodes (`EXPORT_LIMIT` in
`api/export.py`). The whole Arizona mesh was 2,372. Over the ceiling the
export answers **422** with a sentence that says how many nodes match,
and it does not cut the file: a file that stops at a limit and does not
say so gives a wrong answer about the mesh. The count is checked first,
and the rows are read one past the ceiling, so nodes that arrive
between the two queries are found too.

One export is one request of the general request budget (1.1).

A CSV answer is an exception to rule 2, as the coverage tiles and the
terrain pages are. An error is JSON, as always.

### 3.2 `GET /api/nodes/{node_id}`

Returns full detail for one node.
Includes names, hardware, role, last position, last heard time, gateway status, and reported configurations.

### 3.3 `GET /api/nodes/{node_id}/packets`

Returns the packets of one node, sorted and filtered. The node page
draws its packet timeline from this (#54).

The body is a bare array. The count of every row that matches the
filters is in the `X-Total-Count` header, as for `GET /api/nodes`.

Query parameters:

- `direction` — `sent` (default): what the node sent. `heard`: what the
  node uploaded as an MQTT gateway for other senders. A `heard` listing
  reads 24 hours when no window is given, and at most 168 hours.
- `hours` — the time window. Optional for `sent`. At most 720.
- `portnum` — a port number, or its protobuf name.
- `channel` — one channel.
- `sort` — `time` (default), `type`, `to`, `channel`, `size`, `hops`,
  `gateways`, `snr`, `rssi`. Nulls sort last, whichever the order.
- `order` — `desc` (default) or `asc`.
- `offset`, `limit` — paging. Default limit 100. Maximum 500.
- `before` — a cursor: the rows after the last row of a previous page,
  in the same order. Every non-empty answer carries the cursor for its
  last row in the `X-Next-Before` header. A short page is the end.
  The cursor is opaque, and it carries the `sort` and `order` it was
  made under: under any other it returns 422, so a later page cannot
  come back in a different order. Invalid cursors return 422.

Use `before`, not `offset`, to page (#259). Packets arrive all the
time, and a packet that arrives between two offset pages moves a row
from one page to the next, so it is shown twice, or it is skipped.
A cursor names the last row, so a new packet cannot move it. Ties are
broken by `first_seen_at`, then `from_node`, then `packet_id`, so the
order is total.

A sort by `hops`, `gateways`, `snr` or `rssi` has to summarise every
observation in the window before it can order anything. It needs
`hours` of 168 or less, and returns 422 otherwise.

Item: `packet_id`, `portnum`, `channel`, `seen_at`, `from_node`,
`from_name`, `to_node`, `to_name`, `hop_start`, `hop_limit`, `gateways`,
`fewest_hops`, `direct_snr`, `direct_rssi`, `size_bytes`.

- `gateways` counts distinct gateways that uploaded the packet. The
  sender uploading its own packet is not counted (AGENTS.md 9.5.1).
- `fewest_hops` is the fewest relays any such gateway saw it use.
- `direct_snr` and `direct_rssi` are the best readings at a gateway that
  heard it with no hop used. A relayed reading belongs to the last hop,
  so it is never shown here (AGENTS.md 9.5).
- `size_bytes` is the length of the stored protobuf.

### 3.3.1 `GET /api/nodes/{node_id}/gaps`

Returns what the gaps assessment says about one node, one entry for
each preset (#56). It reads the file the gaps job wrote and opens no
database session. The node page's health cards (#52) and its potential
issues panel read this one response, so the two cannot disagree.

Response: `available`, `reason`, `assessments`, `not_listed`.

- `available: false` with `reason: "no_assessment"` is a working state:
  the job has not written an assessment yet.
- Each item of `assessments` holds `preset`, `window_hours`,
  `generated_at`, `gateways_active`, `signal_order`, `signal_labels`,
  and `node`: the node's row exactly as `GET /api/gaps/nodes` serves it.
  The preset the node sends most on comes first.
- `not_listed` names the assessed presets that do not list the node.
  "Not assessed" is a different answer from "assessed and fine".

### 3.3.2 `GET /api/nodes/{node_id}/history`

Returns the series behind the node page charts (#53).

Query parameters: `hours` — default 24, at most 720.

Response: `window_hours`, `bucket_seconds`, `device`, `packets`,
`direct_signal`.

- The window is cut into buckets of 5 minutes (up to 6 h), 15 minutes
  (up to 24 h), 1 hour (up to 7 days) or 6 hours, so no series holds
  more than about 300 points.
- `device` — one item a bucket: `time`, `battery_level`, `voltage`,
  `channel_utilization`, `air_util_tx`, each an average. Empty when the
  node sends no device telemetry.
- `packets` — `buckets` (every bucket of the window, so a silent stretch
  reads as zero) and `families`: `name`, `total`, `counts`.
- `direct_signal` — the six gateways that heard the node directly most
  often: `node_id`, `display_name`, `direct_count`, and `points` of
  `[time, snr, rssi]`. Direct means no hop used and a gateway that is
  not the node itself.

Every series stops at the present. Node clocks run wrong, and a row
dated tomorrow would otherwise stretch the axis (AGENTS.md 9.4).

### 3.3.3 `GET /api/nodes/{node_id}/routes`

Returns the route and neighbour widgets of the node page (#55).

Query parameters: `hours` — default 24, at most 720.

Response: `window_hours`, `position`, `position_known`, `hears`,
`heard_by`, `longest_segment`, `furthest_heard_by`, `furthest_heard`,
`furthest_heard_by_reason`, `furthest_heard_reason`,
`coarse_excluded`, `traces_read`, `hop_depth`.

- `position` — true when the node's own position is exact.
  `position_known` — true when it has a usable position at all, exact or
  rounded.
- `hears` — nodes this node heard: its own neighbour reports, traceroute
  hops that arrived at it, and packets it uploaded as a gateway with no
  hop used. `heard_by` — nodes that heard it: their neighbour reports
  that name it, traceroute hops that left it, and gateways that uploaded
  its packets with no hop used. Item: `node_id`, `display_name`,
  `count`, `best_snr`, `kinds` (`neighbor`, `traceroute`, `gateway`),
  `last`, `distance_km`, `approx_distance_km`, `distance_error_km`.
  A `gateway` count is distinct packets, not uploads.
- `longest_segment` — the longest single hop of any traceroute the node
  took part in: `from`, `to`, `distance_km`, `snr`.
- `furthest_heard_by` and `furthest_heard` — the most distant row of
  each list, ranked by `distance_km` or, when that is null,
  `approx_distance_km`.
- `furthest_heard_by_reason` and `furthest_heard_reason` — null when
  the tile has a distance. Otherwise one of `quiet` (it sent nothing in
  the window), `no_link` (no single-hop link on record), `no_position`
  (it has no usable position) or `partners_no_position` (no node at the
  other end has one).
- `hop_depth` — `packets`, `median`, and `counts` of `hops` and
  `packets`: the fewest hops each packet took to the nearest gateway.
  The node's own uploads are left out.

`distance_km` needs an exact position at both ends, by the rule the
gaps page uses. A pair with a coarse or missing position has no
`distance_km`, and a traceroute segment of that kind is counted in
`coarse_excluded`. A pair where both positions are usable and at least
one is rounded has `approx_distance_km` instead, with
`distance_error_km`: the sum of the two ends' precision deviations from
the firmware table, which bounds how far the rounding can move the
distance. The two are never both set on one row.

Every traceroute in the window that names the node is read, as an end
or as a hop either way (#290). There is no row limit: a limit decides
what evidence exists (AGENTS.md 9.19), and the newest 2000 used to be
about a tenth of the busiest node's 30 days. `traces_read` is how many
were read. `trace_limit_reached` is gone with the limit. The answer is
held for `ROUTES_CACHE_SECONDS` (default 300) for each node and window.

This is the slowest answer on the node page. On a busy gateway it took
5 to 8 seconds uncached on s.azmsh.dev (#304). The time was reading the
node's sightings out of the `packet_seen` heap, where they are spread
over about 100,000 pages; the join to `packet` was not the cost.
Revision 0017 makes the two time indexes of `packet_seen` covering and
keeps `hop_start` on each sighting, so these queries read the index
alone (`api/sightings.py`). Measured on a copy of the busiest gateway's
rows, the slowest query went from 5.1 s to 0.33 s at once, and to
0.07 s once rows written before 0017 expire.

The page does not wait for it either way: the health panel and the
history charts draw when their own answers arrive, and the Links panel
fills in when this one does.

The panel takes no `channel`, so a node on two presets has both in one
list (AGENTS.md 9.7).

### 3.4 `GET /api/nodes/{node_id}/heard-by`

Returns the gateways that heard this node, with counts and last heard time.
This is the data for the reliability report.

Each row has `node_id`, `display_name`, `count`, `direct_count`,
`relayed_count`, `last_heard`, `avg_snr`, `best_snr`, and `avg_rssi`.

`count` is every observation. `direct_count` is the observations that
arrived with no hop, and the signal figures are from those only. The
rest are relayed and carry no signal figure, because the reading on a
relayed observation belongs to the last hop, not to the link from this
node. See AGENTS.md 9.5.

A gateway that is the node itself uploads the node's own voice. That is
not a radio link, so it is never counted as direct and carries no
signal figure, even though its hop numbers are equal. See AGENTS.md
9.5.1.

### 3.5 `GET /api/nodes/{node_id}/telemetry`

Returns telemetry series for charts.

Query parameters:

- `family` — one of `device`, `environment`, `air_quality`, `power`, `pax`,
  `local_stats`. Required. `local_stats` is read by a contributor on
  request (#178), not sent by the node. Each point also has `job`,
  `location` and `source`: who measured it.
- `start`, `end` — time range. Default: last 24 hours.
- `max_points` — downsample target. Default 500.

Response: arrays of `[time, value]` pairs per field.

### 3.6 `GET /api/nodes/{node_id}/neighbors`

Returns the latest neighbor report for the node, with SNR per neighbor.

### 3.7 `GET /api/nodes/{node_id}/detail`

Returns every value that the node detail page shows. One request
replaces many. Fields:

- `node` — the node summary, plus `is_licensed`, `first_seen`,
  `last_channel`, `last_mqtt_topic`, and `position`.
- `neighbors` — the newest report for each neighbor, strongest SNR
  first. Each has `node_id`, `display_name`, `snr`, `last_rx_time`.
- `heard_by` — the gateways that heard this node, as in section 3.4.
  Each has `count`, `direct_count`, `relayed_count`, `avg_snr`,
  `best_snr`, `avg_rssi`, `last_heard`.
- `weather` — the newest environment telemetry. Empty when the node
  sends none. `weather_time` gives its time.
- `device`, `air_quality`, `power` — the newest telemetry of each family.
- `local_stats` — the newest LocalStats a contributor read from this node
  (#178, #182), with `time`, `location` and `source`. Empty when none has.
  `noise_floor` is the **measured** noise floor in dBm, not the theoretical
  one the coverage map uses.
- `activity` — `packet_count` and a count for each port number.
- `messages` — `count` and the newest messages this node sent.
- `graph` — the mesh-graph URLs for this node.

Query parameter: `hours` — the time window. Default 24.

### 3.8 `GET /api/nodes/{node_id}/signal`

Returns the observed signal quality of one node over time. Use it to
draw an SNR chart per gateway.

Query parameters: `hours` (default 24), `max_points` (default 500).

Response item: `time`, `gateway`, `gateway_name`, `snr`, `rssi`,
`hop_limit`.

### 3.9 `GET /api/nodes/{node_id}/graph`

Returns mesh-graph URLs for this node.

Response:

```json
{
  "node_graph": "https://graph.azmsh.net/graph/node/!a1b2c3d4?clickable=true",
  "node_page": "https://graph.azmsh.net/nodes/!a1b2c3d4"
}
```

### 3.10 `GET /api/nodes/{node_id}/radio`

Returns the radio characteristics a coverage prediction would use.

The mesh reports the hardware model and nothing else about the radio.
The other values come from the overrides file named by
`RADIO_OVERRIDES_PATH`, and from the calibration job.

`sources` names where each value came from. It is the reason this
endpoint exists: a reader must be able to tell a measurement from a
guess. Its values are `default`, `hardware`, `override`, and
`calibrated`.

`eirp_dbm` is the nameplate power leaving the antenna.
`effective_eirp_dbm` is the figure the coverage map predicts with. They
differ when the calibration job has moved the node.

`hardware_inferred` is true when the hardware model was not in the
table and its figures were worked out from the name.

Response:

```json
{
  "node_id": "!a1b2c3d4",
  "display_name": "Example Node",
  "hw_model": "RAK4631",
  "chipset": "SX1262",
  "hardware_inferred": false,
  "tx_power_dbm": 22.0,
  "antenna_gain_dbi": 5.8,
  "antenna_height_m": 12.0,
  "cable_loss_db": 1.5,
  "above_clutter": true,
  "eirp_dbm": 26.3,
  "effective_eirp_dbm": 26.3,
  "calibration_offset_db": 0.0,
  "is_measured": false,
  "locked": false,
  "note": "Rooftop omni on the water tank.",
  "sources": { "antenna_gain_dbi": "override", "tx_power_dbm": "hardware" }
}
```

## 3A. Coverage map endpoints

The coverage job predicts from every node the mesh reports and writes
map tiles. These endpoints serve what it wrote. They compute nothing.

**These are the dashboard's, and they are not public.** They serve
every site set a run published, including a diagnostic one, and
`/api/coverage` carries the site records a run used. A reverse proxy
that faces the open internet must not open this prefix. The public
surface is 3B, and 3B.5 lists it exactly.

### 3A.1 `GET /api/coverage`

Returns the current coverage run.

`available` is false when the job has never run. That is a working
state for a new deployment, not a fault.

The response carries the manifest of the run: `generated_at`, `bounds`
of the run's grid (the whole degrees its sites reach, inside the
terrain region; `docs/COVERAGE.md` 6), `data_bounds` of the coverage itself, `min_zoom`
and `max_zoom`, `active_hours`, the receiver the map assumes, `has_terrain`,
`has_landcover`, `missing_terrain_tiles`, and one entry for each modem
preset with its node counts, its covered area, and the sites it used.

`active_hours` is the position and traffic window for the nodes in the
run. A page uses the same value when it asks `/api/map/nodes` for the
optional node layer.

A page must open on `data_bounds`, not on `bounds`. The grid is whole
degrees and runs a site's full radius past it, which is more ground
than the mesh covers.

Each site in `presets[].nodes` carries `position_deviation_m`: how far
its position may be from the node, in metres, when the node shared
only a rounded one. Only an approximate map (below), or a deployment
with `COVERAGE_MIN_PRECISION_BITS=0`, has such sites. It
is null for an exact position or one given in the overrides file. A
site with a value is drawn around its rounded point, so its footprint
is approximate.

Each site also carries `position_source`: `operator` when the position
came from the overrides file (`RADIO_OVERRIDES_PATH`), and `reported`
when the node sent it. A page can then say "position set by the
operator". The position itself is never in the manifest (#315).

`site_sets` lists every map the run published, the precise
infrastructure map first. Each entry has `key`, `label`, `site_roles`,
`is_diagnostic`, `presets`, `data_bounds`, and two fields from #315:
`site_precision` (`precise` or `approximate`) and `approximate` (true
for an approximate map). A run made before #315 has neither, and a
reader must read a missing `approximate` as false. `presets` and
`is_diagnostic` at the top level are always the precise infrastructure
map.

### 3A.2 `GET /api/coverage/tiles/{stamp}/{preset}/{site_set}/{layer}/{z}/{x}/{y}.png`

Returns one coverage tile, 256 pixels square, in the usual web map
scheme.

The dashboard's tiles. A public page draws from 3B.4 instead, which
takes no site set and refuses a diagnostic run.

`stamp` identifies one coverage run. It comes from `GET /api/coverage`.
The URL always returns bytes from that run. It never moves to a newer
run.

`preset` is a modem preset name, such as `LongFast`. A preset is a
radio configuration, not a filter: a node on one preset cannot hear a
node on another, so each has its own coverage. See `AGENTS.md` 9.7.

`site_set` names which map of the run to read. One run can publish more
than one, and they are different answers to different questions:

| Site set | What it predicted from |
|---|---|
| `infrastructure` | Routers, router lates and repeaters, or a subset of them. The only map a public page ever draws |
| `extended` | Also the roles that repeat without being infrastructure, when `COVERAGE_INCLUDE_CLIENTS` is on. A diagnostic |
| `diagnostic` | Whatever `COVERAGE_SITE_ROLES` named, when that is not a subset of the infrastructure roles. A diagnostic |
| `infrastructure_approximate`, `extended_approximate`, `diagnostic_approximate` | The same roles as the set it names, and also positions rounded down to `COVERAGE_APPROXIMATE_MIN_BITS`, when `COVERAGE_INCLUDE_APPROXIMATE` is on. Dashboard only. A public page never draws it (#315) |

Every set without `_approximate` is predicted from precise positions
only. `COVERAGE_MIN_PRECISION_BITS` cannot lower that below 16 bits. See
`docs/COVERAGE.md` 9.1.2.

A run whose roles are not a subset of the infrastructure set writes
`diagnostic` and never `infrastructure`. The site set is part of the
path, so a path that said `infrastructure` while holding a footprint
around every client node in region was a path that lied. See
`AGENTS.md` 9.25.

`layer` is one of:

| Layer | Meaning |
|---|---|
| `usable` | The weaker of the two directions. The honest answer, and what a page shows first |
| `downlink` | A node is heard here |
| `uplink` | Here is heard by a node |

A tile that was never written is ground no node reaches, and returns
404. A map library already knows how to draw that.

The run stamp is part of the URL. Tiles of one run never change, so
they carry an immutable `Cache-Control` and an `ETag`. A new run has
new URLs and cannot reuse a browser's old tiles.

### 3A.3 `GET /api/coverage/calibration`

Returns the current comparison between neighbour reports and the radio
model. `available` is false when the current calibration window has no
evidence.

Each node carries its evidence counts, its residual scatter, and an
`applied` flag. `offset_db` is the bounded correction used by coverage
when `applied` is true. It is null when the node does not have enough
evidence or when its measurements disagree by more than 20 dB. The
value is never outside -15 to +15 dB.

No node is applied when `model_bias_db` or `residual_spread_db` is
outside the trusted 20 dB range.

## 3C. Coverage gap endpoints

Which nodes the mesh is not carrying well, measured from the packets the
database already holds. One modem preset at a time, always: a node on
Long fast cannot hear a node on Medium fast, so a merged answer would
invite a reader to fix a gap between two radios that have no way to
reach each other. See `AGENTS.md` 9.7.

**These endpoints read the stored rows and compute nothing.**
`jobs/gaps.py` writes the job output tables (`docs/DATABASE.md` 5B)
every `GAPS_INTERVAL_MINUTES`, and the routes select from them by key,
with the filters and the limit in SQL (#351). A request that ran the
gap queries would be heavier than the endpoint `docs/ISSUES.md` 2.9 is
already an open warning about.

**Nothing here reaches the public embed, and nothing here ever will.** A
list of weak nodes with positions is a list of houses with a reason to
visit them. It is a worse leak than the one `AGENTS.md` 9.25 guards
against, and `tests/unit/test_gaps.py` enumerates the embed router to
keep it out. The feature is dashboard only.

### The three states

Every signal returns `bad`, `ok` or **`unknown`**, and the third one is
not a footnote. A node that reports nothing is usually a node that is
switched off, not a node in trouble, and the API refuses to tell the two
apart when the data cannot. `unknown` is never served as a zero and
never as a pass.

There is **no 0 to 100 score**. A row's colour comes from `worst_state`.
A score would let two `unknown` signals and one `bad` average into
amber, and amber reads as "a bit broken" when the truth is "we cannot
tell".

### The signals

| Signal | `bad` means |
|---|---|
| `hears_but_is_not_heard` | Its receiver is proven to work and no gateway has heard it on the air. The strongest finding here, and the only case in which this project says a node cannot be heard. |
| `radio_isolated` | It is an MQTT gateway and no gateway heard any of its traffic over the air, by any path. Its packets reach us through its own internet link. |
| `rf_intermittent` | In fewer than `GAPS_RF_RATIO_BAD` of the hours it was awake, anything on the air heard it. |
| `weak_best_link` | Its best **measured** link has under `GAPS_MARGIN_BAD_DB` of margin above what the preset needs to demodulate. |
| `outside_predicted_usable` | The published coverage run predicts no usable coverage where it stands. This is the one signal here that reads a prediction and not a measurement. |

A signal's `evidence` object holds the counts the claim rests on, and
`sentence` is the claim in words. **Use `sentence`.** It says "none of
the 31 gateways active in this window heard it over the air", which is a
measurement. "It is isolated" is a judgement, and the difference is the
point of the whole feature.

### 3C.1 `GET /api/gaps`

Returns the counts for one preset, and what they cannot tell you.

`channel` is optional and takes a channel name as stored. It goes
through the preset table: a channel that is not a default preset name
rides on top of a preset and does not name one, so it returns
`available: false` with `reason: "not_a_preset"` rather than a guess.
With no `channel`, the busiest assessed preset is served.

`available: false` with `reason: "no_assessment"` is a working state,
not an error, exactly as `/api/coverage` treats a missing run.

There is no `hours` parameter. The window is whatever the job measured
and comes back as `window_hours`; a request cannot ask for another
window without recomputing, which these endpoints do not do.

```json
{
  "available": true,
  "preset": "LongFast",
  "label": "Long fast",
  "window_hours": 168,
  "generated_at": "2026-09-18T06:12:04+00:00",
  "gateways_active": 31,
  "assessed_count": 520,
  "coverage": {"stamp": "20260918T060000Z", "site_set": "infrastructure",
               "is_diagnostic": false, "available": true, "threshold_level": 61},
  "signals": {
    "radio_isolated": {"bad": 6, "ok": 318, "unknown": 196}
  },
  "needs_help_count": 63,
  "not_enough_evidence_count": 184,
  "reached_but_unpredicted_count": 48,
  "caveats": [{"key": "observers_are_gateways_only", "text": "..."}],
  "presets": [{"preset": "LongFast", "label": "Long fast", "node_count": 704}]
}
```

`gateways_active` is how many gateways uploaded anything on this preset
in the window. It is how strong a `radio_isolated` claim is, which is
why the page prints it.

`reached_but_unpredicted_count` is **a finding about the map, not about
the nodes**: nodes something on the air demonstrably reached, standing
where the model predicts nothing. It says where the prediction is
pessimistic.

`caveats` is what this feature cannot answer at all. A page shows it
permanently and never behind a toggle.

`signal_units` names what each numbered signal's value is measured in,
for a column heading (`rf_intermittent`: `% of hours heard`).
`signal_key` holds, for each signal, `measures`, `problem` and `owner`:
what the check looks at, what counts as a problem, and what the node's
owner can do, with this run's `thresholds` filled in. Both are
definitions from `gaps/signals.py`, so they are served for an
assessment written before they existed (#265).

### 3C.2 `GET /api/gaps/nodes`

Returns the assessed nodes of one preset, worst first.

The order is set by the job, once, so every reader gets the same one:
`bad_count`, then a fixed severity order between the signals, then the
packet count, so a node we know a lot about sorts above one we barely
know. It is not a score.

| Parameter | |
|---|---|
| `channel` | As above. |
| `signal` | One signal name. An unknown name returns `available: false` with `reason: "not_a_signal"`. |
| `state` | `bad`, `ok` or `unknown`. With no `signal`, a row matches when any signal holds that state. |
| `limit` | 1 to 500, default 100. |
| `cursor` | The `next_cursor` of the page before, with the same filters (#351). |

**Paging is by cursor.** An answer with more rows after it carries
`next_cursor`, an opaque string, and the last page carries `null`. A
cursor names the run it came from. Once the job has written a new run,
which it does every `GAPS_INTERVAL_MINUTES`, the cursor is refused with
409 and the reader starts again from the first page: a page that mixed
two runs could list a node twice or not at all. A cursor that is not
one is refused with 422.

```json
{
  "available": true,
  "preset": "LongFast",
  "matched_count": 63,
  "next_cursor": "eyJydW4iOiIyMDI2LTEwLTEyVDEyOjAwOjAwKzAwOjAwIiwiYWZ0ZXIiOjk5fQ",
  "nodes": [
    {
      "node_id": "!a1b2c3d4",
      "display_name": "Dobbins Lookout",
      "role": "CLIENT",
      "latitude": 33.32, "longitude": -112.06,
      "position_confidence": "exact",
      "position_deviation_m": 0.0,
      "is_mqtt_gateway": true,
      "mobile": false,
      "packets": 412, "rf_packets": 0, "ambiguous_packets": 3,
      "active_hours": 96, "rf_hours": 0, "direct_gateways": 0,
      "worst_state": "bad",
      "bad_count": 2,
      "unknown_count": 3,
      "signals": {
        "radio_isolated": {
          "state": "bad",
          "reason": "no_gateway_heard_it",
          "sentence": "None of the 31 gateways active in this window heard it over the air. ...",
          "value": null,
          "unit": null,
          "evidence": {"packets": 412, "rf_packets": 0, "gateways_active": 31}
        }
      }
    }
  ]
}
```

**`value` and `unit` (#265).** A signal's `value` is null unless the
signal measured a number, and a value always carries a `unit`: the job
cannot build a signal with a value and no unit. The units are
`fraction` (0 to 1, `rf_intermittent`: the share of awake hours in which
something on the air heard the node), `db` (a signed margin,
`weak_best_link`), `gateways` (a whole count; no signal sends it since #327, and it stays
so that a run written before that still reads), `dbm`
(the predicted level, `outside_predicted_usable`) and `m` (the position
error, only on the `unknown` state `position_too_coarse`). The
`fraction` is not rounded: a share just short of 1 stays short of 1, so a
reader can show ">99.9%" rather than a perfect score nobody measured.
A predicted level of nothing at all is `value: null`, never -200 dBm.
An assessment written before `unit` existed has none, and a reader must
then show no number rather than guess one.

`position_confidence` is `exact`, `coarse` or `none`. A `coarse` node is
still listed, with its `position_deviation_m`, and its
`outside_predicted_usable` signal is `unknown`: a deviation of 2.9 km
cannot be placed on a 90 m grid. A missing precision counts as exact,
which is the ordinary case for a node heard over the radio. See
`sonoran/positions.py`.

`mobile` is a modifier and not a fault. A handheld that cannot get out
is a real problem for its owner, so a mobile node stays in the list.

**No SNR here ever comes from a relayed observation or from a node's own
upload.** The first belongs to the last hop into the gateway and the
second is the node's own voice. See `AGENTS.md` 9.5 and 9.5.1.

### The siting half

Two more endpoints answer the other question: **where would one new node
help the most of them**. They read the stored siting answer
(`gaps_siting` and `gaps_siting_candidate`), which
`jobs/gaps_siting.py` writes **inside the coverage cycle** and never on
a clock of its own. That job runs the SPLAT engine, so it must not be
free to start during a coverage build. See `docs/GAPS.md` 10.

**The per node half is a measurement and this half is a prediction.**
They are served from two files, drawn in two shapes and two colours, and
a reader who mixes them up will go and buy a mast.

```
GET /api/gaps/areas?channel=LongFast
GET /api/gaps/candidates?channel=LongFast&area=0&limit=200
```

`GET /api/gaps/areas` returns the neighbourhoods, the demand points
inside each one, the radio every candidate was read with, what the run
cost, and the caveats. An area holds at least `GAPS_MIN_CLUSTER` places
that want help within `GAPS_CLUSTER_LINK_KM` of each other. Fewer than
that is a node, not an area, and `/api/gaps/nodes` already holds it.

```json
{
  "available": true,
  "preset": "LongFast",
  "demand_point_count": 11,
  "demand_node_count": 14,
  "areas": [
    {"area": 0, "point_count": 5, "node_count": 5, "width_km": 8.4,
     "centroid": [33.5940, -112.4830], "bounds": [33.565, -112.51, 33.63, -112.445],
     "node_ids": ["!0a51e001"], "points": [{"latitude": 33.63, "longitude": -112.51,
                                            "node_count": 1, "node_ids": ["!0a51e001"]}]}
  ],
  "assumed_radio": {"tx_power_dbm": 30.0, "antenna_gain_dbi": 2.15,
                    "cable_loss_db": 0.0, "antenna_height_m": 9.0,
                    "radius_km": 25.0, "rx_height_m": 1.5},
  "coverage": {"stamp": "20260919T061200Z", "available": true, "is_diagnostic": false},
  "cost": {"predictions": 3, "max_predictions": 24, "workers": 1,
           "engine_seconds": 9.6, "core_seconds": 9.6},
  "caveats": [{"key": "land_is_invisible", "text": "We cannot tell whether anybody owns ..."}]
}
```

`GET /api/gaps/candidates` returns the places, best first inside each
area. It pages by `cursor` and `next_cursor` exactly as
`/api/gaps/nodes` does, and a cursor names the siting answer it came
from.

```json
{
  "available": true,
  "preset": "LongFast",
  "area": 0,
  "matched_count": 34,
  "next_cursor": null,
  "candidates": [
    {"kind": "ground", "area": 0, "latitude": 33.5758, "longitude": -112.5792,
     "elevation_m": 1230, "prominence_m": 127, "node_id": null,
     "method": "splat", "state": "ok",
     "screen_score": 5, "screen_unknown": 0,
     "newly_usable": 5, "newly_usable_nodes": ["!0a51e001"],
     "already_usable": 0, "baseline_unknown": 0,
     "run_stamp": "20260919T061200Z", "reason": "confirmed_by_engine",
     "sentence": "The engine predicts that a node here would bring 5 of the places ..."}
  ]
}
```

Three fields carry the whole meaning of a row:

- **`kind`** is `existing_node` or `ground`. An `existing_node` is a
  node already standing there, read with the candidate radio instead of
  its own: "if the node at this address went to 1 W on a 9 m mast". It
  needs no land and no permission, which is why it wins a tie.
- **`method`** is `terrain_screen` or `splat`. A `terrain_screen` row is
  a cheap **ranking** and not a prediction: free space loss, the
  terminal clutter correction at both ends, and one knife edge. The
  engine did not run there. Only a `splat` row carries `newly_usable`.
- **`state`** is `ok`, `bad` or **`unknown`**, as everywhere in this
  feature. `unknown` means the ground under the candidate, or under
  every path from it, is terrain we do not hold. **`newly_usable` is
  then `null` and never `0`**: "we did not judge it" and "it would help
  nobody" are different answers.

`newly_usable` counts the demand points this candidate would bring
inside usable coverage **that the published run does not already
reach**. `already_usable` counts the ones it reaches that were already
covered, and `baseline_unknown` counts the ones we cannot say were
outside before, because the published run holds no level for any node
standing there.

**What this half cannot know travels with every answer**, in `caveats`,
and the page prints it without rewording it. Land ownership, access,
power, backhaul, a roof, a road, whether a building stands between the
site and a street, and whether the person who lives there wants a node
on it are all invisible here. So is the whole population with no node
yet: the demand set can only hold people who already bought a radio and
got it partly working, so it will always favour places that already half
work. **A siting suggestion that does not say so is a lie of omission.**

## 3B. The public embed

These serve a page for somebody else's website. They are all 404 until
`EMBED_ENABLED` is true, and each one refuses in a router dependency
rather than in a handler, so a request while the embed is off never
reaches the database. See `AGENTS.md` 9.16.3.

`sonoran/embed/sanitise.py` is the only place that decides what a
public viewer sees. `/api/map/nodes` is untouched: it serves the
dashboard, which is a different audience.

3B.5 is the exact list of paths a reverse proxy may open for the
embed. Nothing outside it is needed, and opening a prefix instead of
those paths exposes the dashboard's data.

### 3B.1 `GET /embed/coverage`

The embed document. Its own page, not the dashboard: the dashboard
carries `serial=(self)` for the config checker, and framing it would
take Web Serial onto a third party site.

This path alone sends no `X-Frame-Options` and sets `frame-ancestors`
from `EMBED_FRAME_ANCESTORS`. Every other path keeps `DENY` and
`'none'`. A value that is not an origin is dropped, and an empty list
gives `'none'`. It never becomes a wildcard.

### 3B.2 `GET /api/embed/coverage`

A cut down coverage manifest: the bounds, the zooms, the presets, and
the receiver the map assumes. The sites a run used, the terrain it was
missing, and how long it took are operational detail and are not here.

Held for 30 seconds, **including the answers that say there is no map**.
"No run yet" and "the run is diagnostic" are the cheapest answers to
give and were the two that were not cached, so a deployment in either
state read and parsed `index.json` inside the event loop on every
request — and those are exactly the states where a page asks on every
load.

### 3B.3 `GET /api/embed/nodes`

The infrastructure sites a public page may show.

Routers, repeaters, and MQTT gateways only. A client node is usually a
person, often at home, and never appears. Each entry carries the short
name, the role, whether it is a gateway, and a position snapped to
`EMBED_POSITION_STEP` degrees. The long name, the hardware model, the
node ID, and the last heard time are all left out.

The position is snapped in this process, before it is sent. Rounding it
in the browser would mean the exact value had already left.

Held for 300 seconds. This is the only part of the embed that reads the
database, and the sites of a mesh change over hours.

The query selects five columns and applies the role and position tests
in SQL. It used to be `select(Node)`: every row of the table and every
column of it, built into ORM objects and carried into Python, to answer
a question about the roughly five per cent of a mesh that is
infrastructure. The columns it dropped in Python included the long
name, the public key and the exact position — the very fields this
endpoint exists to keep back, fetched out of the database only to be
discarded.

**The rule that decides who is public did not move.** `public_nodes` in
`sonoran/embed/sanitise.py` still applies the role test to every row
that arrives, so the SQL narrows what is read and decides nothing. A
mistake in the query can only ever show fewer nodes, never more. See
`AGENTS.md` 9.25.

### 3B.4 `GET /api/embed/tiles/{stamp}/{preset}/{layer}/{z}/{x}/{y}.png`

One tile of the public coverage map: the infrastructure map of the
published run, and nothing else.

There is no site set in this URL, and that is the point rather than an
omission. A run can also publish a map predicted from client nodes, and
a client node is usually somebody's house. A footprint has a centre, so
the tiles are the leak that holding back the markers does not close.
The route serves the infrastructure map and has nowhere to be told
otherwise.

`stamp` is a cache key, not a lookup. It must be the run that is
published now, which is the `stamp` from `GET /api/embed/coverage`; any
other value answers 404. The bytes of one stamp never change, so the
answer carries an immutable `Cache-Control` and an `ETag`.

A diagnostic run publishes no public map. The whole route answers 404
for one, in a router dependency, so no handler body runs and no tile is
read from disk. `GET /api/embed/coverage` says the same thing with
`reason: "diagnostic"`.

A tile that was never written is ground no node reaches, and returns
404. A map library already knows how to draw that.

The dashboard reads 3A.2 instead. That route is not gated by
`EMBED_ENABLED`, takes the site set from the path, and serves a
diagnostic run, which is what the dashboard is for.

### 3B.5 The exact public surface

What the embed page needs to load, and nothing else. A reverse proxy
that publishes the embed allows exactly these:

| Path | What it is |
|---|---|
| `/embed/coverage` | The embed document |
| `/api/embed/coverage` | The cut down manifest (3B.2) |
| `/api/embed/nodes` | The public sites (3B.3) |
| `/api/embed/tiles/` | The public tiles (3B.4), by prefix |
| `/static/embed-coverage.js` | The page's own script |
| `/static/vendor/leaflet.js`, `/static/vendor/leaflet.css` | The map library |
| `/static/vendor/images/` | What `leaflet.css` refers to, by prefix |

Every path that carries mesh data is under `/embed/` or `/api/embed/`,
and both prefixes are 404 in full while `EMBED_ENABLED` is false. The
three static files are not under them because `leaflet.css` resolves
its image URLs relative to itself, and moving it would either break
those or need the whole static directory served twice. They carry no
mesh data, and the dashboard serves the same bytes from the same place.

**Do not open `/api/coverage*` by prefix to make the tiles work.** That
was the shape of the defect this list exists to prevent. It exposes:

- `/api/coverage/tiles/{stamp}/{preset}/{site_set}/...`, which serves
  the client-node map of the same run to anybody who types `extended`,
  and a diagnostic run to anybody who guesses a stamp;
- `/api/coverage`, whose `coarse_sites` carry display names with
  rounded positions and whose `presets[].nodes` carry node IDs and long
  names;
- `/api/coverage/calibration`, which names nodes and what each one
  measured.

None of that belongs on a page anybody may load.

## 4. Packet endpoints

### 4.1 `GET /api/packets`

Returns packets, newest first. This is the firehose feed.

Query parameters:

- `portnum` — filter by payload type name or number.
- `from`, `to` — filter by node.
- `channel` — filter by channel name.
- `preset` — keep packets carried on one modem preset. See 1.2.
- `since` — only packets newer than this timestamp.
- `before`, `limit` — pagination.
- `summary` — `true` adds `summary`, one short line of what the packet
  said, read from its decoded row: a message, a position with its
  precision, battery and voltage, temperature and humidity, a neighbor
  count, or a traceroute request or reply. It is null for a kind that
  stores nothing to show (node info, routing), and for a text message
  while text storage is off. The firehose asks for it. With it comes
  `summary_parts`: the same line as a list, where each part is text or a
  measurement `{"value": 21.5, "unit": "°C"}`. The units are SI (`°C`,
  `hPa`, `m`), and the browser writes each measurement in the reader's
  units. `summary` is the parts joined in SI, for a reader that does not
  convert (#291).

Response item:

```json
{
  "packet_key": "2717905876:123456789",
  "from_node": "!a1b2c3d4",
  "to_node": "^all",
  "portnum": "TEXT_MESSAGE_APP",
  "channel": "LongFast",
  "hop_start": 3,
  "hop_limit": 1,
  "first_seen_at": "2026-08-01T12:00:00Z",
  "seen_count": 4
}
```

### 4.2 `GET /api/packets/{from_node}/{packet_id}`

Returns one packet with its full observation list.

An observation is one MQTT upload. It says which gateway uploaded a
copy of the packet. It does not say which nodes could hear the sender:
a node that is not a gateway hears plenty and reports none of it. Use
`/api/nodes/{node_id}/neighbors` for the radio question.

One gateway uploads the same packet more than once, so the number of
observations is larger than the number of gateways. `gateway_count`
holds the distinct count. A page must not present the list length as a
number of gateways.

`self_reported` is true when the gateway is the sender. A node that
gateways its own traffic uploads the packet it has just transmitted,
which measures no radio link. Such a row always carries `hop_start`
equal to `hop_limit`, so it is excluded from `direct` by node as well
as by hop count.

`direct` is true only when no hop was used and the gateway is another
node. Only then does the signal reading describe the sender's own link.
See AGENTS.md 9.5.

`payload_json` is what the packet carried, for node info, routing,
traceroute, map report and pax counter. Field names are the protobuf's
own, and an enum is its name. It is null for every other family, which
either has a typed table read into `decoded` or is never kept, and for
packets stored before 2026-09-22. The API holds no channel key, so it
cannot decode a packet itself.

`decoded` holds `kind` and `values`, one entry per stored row, with the
columns of the table of that family. Column names are the database's.

For `kind=neighbors` each value carries two fields the database does not
store: `neighbor_id`, the `!hex` form of `neighbor_node_num`, and
`neighbor_name`, the display name of that node. The name follows the
usual rule — long name, then short name, then the ID — so it is always a
string a page can print, and a page must not re-derive the ID from the
number. No other kind carries a name, because no other kind points at a
second node.

Response:

```json
{
  "packet": { "...": "as in /api/packets, plus decoded and payload_json" },
  "gateway_count": 2,
  "observations": [
    {
      "gateway": "!11223344",
      "gateway_name": "Hilltop",
      "mqtt_topic": "msh/US/AZ/2/e/LongFast/!11223344",
      "channel": "LongFast",
      "rx_rssi": -87,
      "rx_snr": 6.5,
      "hop_limit": 1,
      "hops_taken": 2,
      "self_reported": false,
      "direct": false,
      "seen_at": "2026-08-01T12:00:01Z",
      "relayed_by": {
        "byte": "4f",
        "candidates": [{"node_id": "!a1b2c34f", "display_name": "Mesa relay"}]
      }
    }
  ]
}
```

`relayed_by` is the node that sent this gateway its copy, as the
firmware gives it: one byte, the last of the node number (AGENTS.md
9.20). `byte` is that byte in hex. `candidates` are the nodes whose
number ends in it and that were heard within a day of the packet,
newest first. More than one candidate means the byte names none of them
for sure. It is null for an upload that carried no relay, and for rows
stored before migration `pr378`.

## 5. Chat endpoints

These endpoints return empty lists when text storage is disabled.

### 5.1 `GET /api/chat`

Returns text messages, newest first.

Query parameters: `channel`, `preset`, `from`, `q`, `since`, `before`,
`limit` (1 to 500), `reactions`, `metrics`.

A message has no preset of its own. With `preset` (see 1.2) it is joined
to its packet on (`from_node_num`, `packet_id`, `first_seen_at` =
`seen_at`), which is the whole of `uq_packet_dedup`, so it matches one
packet at most. A message with no packet row falls back to its channel.

With `metrics=true`, each message carries `metrics`: how it travelled.
The channel page (`#chat/<channel>`) asks for it. It is null when the
message has no packet row.

| Field | Meaning |
|---|---|
| `gateway_count` | Distinct gateways that uploaded it. Never uploads, and never the sender uploading its own packet. |
| `direct_gateways` | Of those, how many heard it with no hop used. |
| `fewest_hops` | The fewest relays any gateway saw it use. |
| `best_direct_snr`, `best_direct_rssi` | The best reading from a direct gateway. A relayed upload's reading belongs to its last hop, so it never counts. |
| `want_ack` | The sender asked for an acknowledgement. Whether one came back is not recorded, so nothing claims it. |

See `AGENTS.md` 9.5 and 9.5.1 for why each rule is there.

Tapbacks are grouped under the message they react to. The page draws
each emoji once with its count, folds all but the four most sent into
"+N more", and draws the digit tapbacks apart as "Hop-count tapbacks"
(#312). A digit says how the message arrived at whoever sent it: `*`
direct, `1` to `7` hops (`7` is seven or more). MeshMonitor's Auto
Acknowledge sends these (its `hopEmoji`, in
`docs/features/automation-engine.md` of Yeraze/meshmonitor), and a
person can send them too. Nothing in the packet tells the two apart, so
the label names what the digit means and not who sent it. They are drawn
apart only on MediumFast, LongFast and azmsh; on any other channel, such
as Trivia, a digit is a person's answer and stays a reaction. The page
writes each one out in words beside its sender.

### 5.2 `GET /api/chat/channels`

Returns the list of channels that have text messages, with counts.

### 5.3 `GET /api/chat/overview`

Returns every detected channel with its recent messages. The chat page
draws one section per channel, below the heading of its group.

Each section has `channel`, `label`, `group`, `preset`, `tier`,
`count`, `reactions`, `last_seen`, and `messages`.

`count` is the number of messages in the window, without tapbacks. It
is the same set that `GET /api/chat` pages through, so the chat page
can load every message the count promises (#297). `reactions` is the
number of tapbacks in the window. A channel that holds only tapbacks
keeps its section, with a `count` of 0. `last_seen` is the newest row
of either kind.

Groups are drawn in this order:

| Group | What lands there |
|---|---|
| `Presets` | The channel name is a default LoRa preset name, such as `LongFast` or `MediumFast`. |
| `Weather` | A weather word in the name (`weather`, `wx`). |
| `Games` | The name is exactly `Trivia`. |
| `Traffic` | A traffic word in the name (`traffic`, `roads`). |
| `Emergency` | `emergency`, `emcomm`, `ares`, `races`. |
| `Telemetry` | `telemetry`, `sensor`. |
| `Testing` | A channel named in `CORE_CHANNELS` that matches no topic above. |
| `Custom` | Everything else. Sorted last, deliberately. |

`Custom` is the inbox. A channel nobody has classified yet arrives
there, so a name appearing in it is the signal to file it above — or to
go and ask whoever made it. `Games` is matched on the exact name for the
same reason: a lowercase `trivia` beside `Trivia` is two channels to the
radio and a typo to a human, and filing it under `Games` would have
hidden the fact that somebody had made a channel by accident.

`tier` is a separate question from `group`: it is `core` for any preset
and for the channels `CORE_CHANNELS` claims, `extra` otherwise. The
group says what a channel is about; the tier says whether it is part of
this mesh or something running beside it. A core channel keeps whatever
topic group it matched.

Query parameters: `hours` (default 168), `per_channel` (default 25),
`preset`.

With `preset` (see 1.2) each section counts and lists only the messages
carried on that preset, and a channel with none on it has no section.
The chat page sends the menu's preset. It used to fetch every channel and
keep, in the browser, the topic channels on the default preset only, so
azmsh was never shown on LongFast.

### 5.4 `GET /api/chat/tagged`

Returns messages that carry one hashtag, grouped by week. The weekly
mesh network check-in uses the `#meshnet` tag. A week starts on Monday
in UTC.

**One channel only (#262).** The endpoint reads the channel named by the
`default_preset` setting (MediumFast on this mesh) and no other. The
scope applies to both reads: the message list and the 52-week aggregate
that the streaks come from. A tagged message on any other channel is not
returned and does not count toward a streak. The scope is on the server
because a caller never sees the rows a streak is counted from, so a
filter in the caller would leave other channels inside every run. The
match is exact, not case-folded. The response carries `channel`, the
name that was read.

Query parameters:

- `tag` — the tag word, with or without the hash sign. Default
  `meshnet`. Letters, numbers, and underscore only.
- `weeks` — how many weeks to return. Default 8.
- `limit` — maximum messages. Default 500.

Each week has `week_start`, `week_end`, `in_progress`, `message_count`,
`check_in_count` (how many different nodes checked in), `check_ins`,
`not_seen`, `messages` and `messages_shown`.

Every week in the window is returned, including one nobody checked in —
a gap is the point of this endpoint, and a week simply absent from the
list reads as a week that never happened. Weeks older than the earliest
tagged message the read could find are left out, because there is no
evidence about them either way.

Each message carries `streak_weeks`, `streak_at_least` and `first_ever`:
the sender's run as of the week of that message, from the same aggregate
and the same rules as `check_ins`. `streak_weeks` is null, never 0, when
no run is known for the message.

`message_count` is measured by an aggregate and `messages` is capped by
`limit`, so on a busy week the two disagree. `messages_shown` is the
length of the list, so a caller can say which number is the fact.

**Streaks.** A `check_ins` entry carries `node_id`, `display_name`,
`message_count`, `first_seen`, `last_seen`, `streak_weeks`,
`streak_at_least` and `first_ever`. A `not_seen` entry — the nodes that
checked in the week before and not in this one — carries `node_id`,
`display_name`, `streak_weeks` and `streak_at_least`.

`streak_weeks` is the number of consecutive weeks, ending at and
including this one, in which the node checked in. Two messages in one
week are one check-in; a gap ends a run and nothing bridges it. The
current week is unfinished, so a node with no message yet appears in
`not_seen` with the run it still holds through last week, and is never
described as having broken it. The seven rules in full, including why,
are above `_streak_as_of` in `sonoran/api/routes/chat.py`.

The read looks 52 weeks further back than the window, so a run is not
shortened by whichever window the caller picked. `streak_at_least` says
the run reaches the oldest week the read could see and is therefore a
lower bound. `streaks` reports `lookback_weeks`, `floor_week` and
`current_week`.

`streaks` is **null** when nothing could be assessed: no tagged message
anywhere in the lookback and `text_storage` false, which means message
bodies are not being kept and there will never be a check-in to find. An
empty response is then a fact about the configuration rather than about
the community, and a caller must not draw it as everybody at zero.

### 5.5 `GET /api/chat/conversation/{from_node}/{packet_id}`

Returns one message with its replies.

The message is addressed the way a packet is, by the node that sent it
and the packet ID, because a packet ID is only unique per sender.
`text_message` is indexed on that pair. A malformed `from_node` is a 422;
an unknown message is a 404.

Replies match on `reply_id`, which carries the parent's packet ID and
nothing else, so a reply cannot be constrained to this sender. Tapbacks
carry `reply_id` too and are excluded here; read them from the
`reactions` field of a message instead.

## 6. Map endpoints

### 6.1 `GET /api/map/nodes`

Returns nodes that have a current position.

Query parameters:

- `active_hours` — keep nodes heard inside this window. Optional.
- `channel` — keep nodes that sent traffic seen on this channel. Use
  `unknown` for traffic with no stored channel. Without this parameter
  the response holds every positioned node.
- `hours` — the window `channel` looks over. Default 32, which is the
  window the map's neighbour links use, so a line always has both of
  its nodes on the map.

A node belongs to a channel when it sent traffic seen on it inside the
window. That is a claim about what the node was doing, not about how it
is configured, so a node that really does run two presets appears on
both. Live data had 14 such nodes against 709.

The map must pass `channel` whenever it draws one preset. A node on
LongFast cannot hear a node on MediumFast, so drawing both sets of dots
under one preset's lines invites the reader to join two nodes that have
no way to reach each other. See AGENTS.md 9.7.

Response item: `node_id`, `short_name`, `lat`, `lon`, `altitude`,
`last_heard`, `role`, `is_mqtt_gateway`.

### 6.2 `GET /api/map/edges`

Returns recent neighbor links for map lines.
The only source is neighbor reports, in which a node names the nodes it
hears itself, so a straight line between the two is a real radio link.

Traceroutes are deliberately absent. This endpoint used to add one edge
for each traceroute, drawn between the two ends of the trace. Those ends
can be many hops apart and often have no link at all, so the line meant
nothing. Use `/api/map/traceroute-paths` instead.

Query parameters:

- `hours` — time window. Default 12.
- `limit` — maximum edges. Default 1000.
- `channel` — the modem preset to draw. Use `unknown` for links with no
  stored channel. Without this parameter the response holds every
  channel together, which a map layer must not draw as one set. A node
  on one preset cannot hear a node on another preset.

Response item: `from_node`, `to_node`, `snr`, `kind` (always
`neighbor`), `channel`, `time`.

### 6.3 `GET /api/map/traffic`

Returns recent packet observations for the live traffic layer. Each
event holds the sender, the gateway that heard it, and what kind of
packet it was. When both ends have a position, `has_line` is true and
the map may draw a line between them.

Every packet family is included: node info, position, traceroute,
telemetry, routing, text, waypoints, and the rest. A packet on a channel
with no configured key decodes as `UNKNOWN_APP`, which is normal.

Query parameters:

- `minutes` — time window. Default 15. Maximum 1440.
- `limit` — maximum observations returned. Default 300. Maximum 2000.
  It caps the events only. The counts are of the whole window.
- `channel` — the modem preset to return. A node on one preset cannot
  hear a node on another, so a map layer must draw one at a time.
  Without it the response mixes every channel together.

Response: `window_minutes`, `event_count`, `direct_count`,
`returned_count`, `truncated`, and `events`. Each event has `time`,
`packet_id`, `channel`, `portnum`, `snr`, `rssi`, `hop_limit`,
`hop_start`, `hops_taken`, `direct`, `from`, `gateway`, and `has_line`.

`event_count` and `direct_count` count the window, not the rows that
came back, so a wider window always answers with more. `returned_count`
is how many events the limit left, and `truncated` says the window held
more than that. The events are the newest ones, so a client that draws
observations as they arrive needs only enough to cover a refresh.

A client must group the events before it draws them. One packet arrives
as many rows, because `packet_seen` records MQTT uploads and a gateway
uploads the same packet more than once: one live packet had 22 uploads
from 15 gateways. Group on (`from.node_id`, `packet_id`), which is the
packet identity AGENTS.md 9.1 gives, and count **distinct** gateways
rather than rows. Drawing a mark per row says a node was heard by
fifteen others, which is the one reading AGENTS.md 9.5.1 exists to
forbid. The dashboard does this in `web/static/map-live.js`.

The dashboard's map calls this endpoint every 15 s. It calls
`/api/map/nodes` at most every 120 s and `/api/graph/channels` at most
every 600 s, because both answer questions that change slowly and were
previously paid for on every refresh. Those intervals are a client
concern; nothing here enforces them.

`direct` is true only when the packet used no hop
(`packet.hop_start = packet_seen.hop_limit`) and the gateway is not the
sender. It is false when either value is unknown. A gateway that is the
sender uploads its own voice, which every hop rule alone reads as
direct, so it is excluded by node as well; the packet page does the
same. See AGENTS.md 9.5 and 9.5.1. `direct_count` follows the same rule,
so a mesh whose senders are their own gateways does not report every
one of them as a direct link. A line for a relayed observation is a
path, not a radio link: the packet reached the gateway through other
nodes, so the straight line crosses ground the signal never took.

`hops_taken` is how many hops the packet burned to reach this gateway.
It is the whole of what is known about a relayed route. Which nodes the
packet passed through is recorded nowhere, because an ordinary packet
carries no route. Only a traceroute holds its own path, which is what
`/api/map/traceroute-paths` draws. See AGENTS.md 9.20.

`portnum` is the readable name, or the number as text when this build of
the protobufs does not know it.

`portnum`, `hop_start`, `hops_taken`, and `direct` all read from the
packet row behind the observation. The read looks back ten minutes
before the window, because a packet is first heard a little before the
other gateways upload it. Uploads arrive within seconds, so this covers
live traffic. An observation whose packet was first heard longer ago
than that reads with a null `portnum` and `hop_start`, and `direct`
false. This affects a late upload, from a gateway that reconnected or
held a backlog, and the historical rows that carry a gateway clock and
not ours (AGENTS.md 9.4). Those rows age out with retention.

### 6.4 `GET /api/map/traceroute-paths`

Returns recent traceroutes as the chain of hops each one really took.
The map animates each path as it arrives.

Query parameters:

- `minutes` — time window. Default 15. Maximum 1440.
- `limit` — maximum traces. Default 40. Maximum 200.
- `channel` — the modem preset to draw, as for `/api/map/edges`.
- `completed_only` — return replies only. Default true.

Anybody can send a traceroute to any node, and most never come back: in
live traffic 1,278 of 1,808 in a day were requests with no reply. A
request only says somebody asked. Its hop list is whatever the packet
managed on the way out, which is not a path to the node that was asked,
so drawing it claims a route that was never proved.

A reply is the proof, and it is the only row that carries `request_id`.
Set `completed_only` to false to see the attempts too.

Response: `window_minutes`, `completed_only`, `trace_count`, and `traces`. Each trace has
`id`, `trace_id`, `time`, `channel`, `is_reply`, `from`, `to`,
`link_count`, and `hops`.

`id` is the row identity, which is what `#traceroute/{id}` opens.
`trace_id` is the mesh-graph key and is not the same: a reply is keyed
on the request it answers.

`link_count` is the number of segments in the path. It is one more
than the "hops" the traceroute pages report, which count the nodes in
between.

The path runs from the node that asked to the node that answered. A
reply carries its endpoints the other way round, and this endpoint
corrects that, so `from` is always the node that started the trace.

Each hop has `from`, `to`, `snr`, and `has_line`. `has_line` is true
only when both ends hold a position and are not the same node. A client
must not draw a hop without it.

`snr` is in dB, or null. The stored values are quarter dB, and the
firmware writes INT8_MIN for a hop it could not measure. Both are
handled here. A reading of null means "not measured", not a weak
signal. About two thirds of reports are shorter than their hop list, so
the last hops usually carry no reading.

### 6.5 `GET /api/map/track/{node_id}`

Returns the position history of one node for track display.

Query parameters: `hours` (default 24), `max_points` (default 500).

## 7. Mesh graph endpoints

One graph holds one channel. A LoRa modem preset is a different radio
configuration, so a node on LongFast cannot hear a node on MediumFast.
A graph that mixes presets would show links that cannot exist.

### 7.1 `GET /api/graph/channels`

Returns every channel that has mesh links in the window. The graph page
draws one tab for each. The busiest channel comes first, so the page can
select it by default.

Query parameter: `hours` — the time window. Default 24.

Response item: `channel`, `label`, `group`, `preset`, and
`link_report_count`. Links with no stored channel come back with the
channel `unknown`.

Each channel carries a `tier`:

- `core` — a LoRa modem preset, or a channel named in `CORE_CHANNELS`.
  This is the mesh proper.
- `extra` — everything else, such as a weather or trivia channel
  running beside the mesh.

Core channels sort before extra ones, so the default selection is
always a channel the mesh really runs on. The pickers show the two
apart.

The list holds every channel with activity, not only those with links.
A chat or weather channel produces no neighbor report and no
traceroute, so it has `link_report_count` 0 and a `packet_count` above
zero. The map can point its live traffic layer at such a channel. The
mesh graph page leaves them out, because a channel with no link has no
graph to draw.

### 7.2 `GET /api/graph`

Returns the mesh of one channel as nodes and links. The response is
ready to draw. The browser does no join.

A link comes from neighbor reports and traceroute hops. Both are the
same kind of evidence, one packet heard across the link, so they add up
to one link and neither outranks the other (#73). A reply's way back
counts as well: each hop of it is a packet heard in the other
direction.

A traceroute row becomes hops through `sonoran.api.traces`, which
applies three rules. A reply reads in the request direction, because
its stored endpoints run backwards. A hop past the last SNR slot did
not happen yet, and draws no link. An unanswered request has an empty
route, so it evidences no link at all.

Query parameters:

- `hours` — the time window. Default 24.
- `limit` — maximum link reports to read. Default 2000.
- `channel` — the channel to draw. Use `unknown` for links with no
  stored channel. Without this parameter the response holds every
  channel together, which a page must not draw as one graph.

Response: `window_hours`, `channel`, `node_count`, `link_count`,
`nodes`, `links`.

- Node item: `node_id`, `node_num`, `display_name`, `short_name`,
  `role`, `hw_model`, `is_mqtt_gateway`, `lat`, `lon`, `has_position`,
  `last_heard`, `packet_count`, `known`.
- Link item: `source`, `target`, `kind`, `kinds`, `snr`, `count`,
  `each_way`, `strength`, `confirmed`, `time`.

`source` and `target` give the direction of the first report: `target`
heard `source`. `each_way` counts the reports in each direction,
`[source to target, target to source]`. `kinds` lists the kinds of
report behind the link.

`strength` grades that evidence:

- `weak` — fewer than 10 reports in total.
- `one_way` — enough reports, but fewer than 3 in one direction.
- `two_way` — at least 3 reports in each direction.

The graph page draws `two_way` solid, `one_way` dashed and `weak`
dotted. The limits are `WEAK_LINK_SAMPLES` and `TWO_WAY_MIN_SAMPLES` in
`routes/graph.py`.

`lat` and `lon` are the node's last known position, or null. They come
with the node so the page can lay the graph out over the ground it sits
on. A position that is not a real place is dropped, by the same rule the
map uses (`sonoran.positions`). `has_position` is true only when both
values survive that rule, so a node with a Null Island fix reports
false.

`confirmed` says whether anything that completed evidences the link. A
neighbor report always does: a node names a neighbour it hears itself.
A traceroute does when it is a reply, because the request reached the
far end and came back.

`confirmed` is false when only an unanswered request evidences the
link. The broker saw the request in flight, so the hops it had already
made are real and were really measured. Nothing confirmed the round
trip. `strength` has replaced it on the graph page, and it stays in the
response for any other reader.

### 7.3 `GET /api/graph/link`

Returns the reports that evidence one link on the graph. Every report
names the packet that carried it, so the packet page opens from here.

Both nodes are read through the same rules as `GET /api/graph`, so a
link the graph draws always has at least one report here. The query
selects traceroutes that name both nodes, in the outward route or the
way back, rather than the newest rows
in the window. Selecting by recency let the row limit hide the
evidence of a link that the graph had already drawn.

Query parameters:

- `a`, `b` — the two node IDs. Required.
- `hours` — the time window. Default 24. Pass the window the graph
  used, or a link found over seven days reports no evidence.
- `channel` — the channel, as for `GET /api/graph`.

Response: `a`, `b`, `window_hours`, `report_count`, `best_snr`,
`reports`.

- Report item: `kind`, `reported_by`, `packet_id`, `channel`, `snr`,
  `time`. A traceroute report also carries `hop` and `path_length`.

## 8. Statistics endpoints

### 8.00 The window every statistics widget reads (#294)

The Statistics page has one range control, and every widget on it reads
the same window. `sonoran/api/window.py` is the one place that turns the
query into a window. These endpoints take it: `/api/stats`, `/top`,
`/leaderboards`, `/hardware`, `/daily`, `/activity` and `/broadcast`.

Query parameters, one form or the other:

- `hours` — 1 to 720. A rolling window that ends now.
- `since`, and optionally `until` — a fixed window. A value with no time
  zone is local time in `DISPLAY_TIMEZONE`, so `since=2026-09-01` is
  midnight in Arizona, 07:00 UTC. `until` is exclusive and never later
  than now. Without `until` the window ends now.

The answer is 422 when both forms are given, when `until` has no
`since`, when the window does not start before it ends and before now,
or when it is longer than 720 hours (30 days). 720 hours is the default
packet retention: a longer window over `packet` reads ground that is
already deleted.

A fixed window can still start before the oldest packet kept. The
answers that are objects then carry, with `window_hours`:

- `window_start`, `window_end` — the window in UTC.
- `retained_from` — now minus `RETENTION_DAYS_PACKET`. Where it is later
  than `window_start`, the widget counted from there, and the page says
  so on the widget.

Each endpoint keeps its old default when no window is given, so an
older caller gets the answer it always got. Each windowed answer is held
for `STATS_CACHE_SECONDS` in a cache with a bounded number of keys.

### 8.0 Three of these read the whole table, and are held

`/api/stats`, `/api/stats/hardware` and `/api/stats/portnums` are the
only answers in the API with **no time window**. They count every row
ever kept, so the work grows with retention and never with what the
reader asked for. Everything else here takes `hours` and reads a slice.

The dashboard calls all three on every load, on a three-core box that
also runs the ingest and the coverage engine.

Each is now held for `STATS_CACHE_SECONDS` (default 30). One reader is
answered from the database; everybody else inside the window shares
that answer. The figures are a sense of scale on a dashboard, and a
mesh does not change its totals in a way anybody reads at second
resolution. Set it to `0` to count on every request.

The hold is taken with a lock, which is the half that matters under
load. Without one, every request arriving in the instant a hold expires
runs its own scan, so the endpoint costs its full price multiplied by
the number of concurrent readers at exactly the moment it is busy.
`sonoran/api/cache.py` holds that, and the embed endpoints use it too.

#### What this cost, measured

On a real TimescaleDB (`timescale/timescaledb-ha:pg17`) at head, seeded
with 950 nodes, 200 000 `packet` rows and 60 000 `packet_seen` rows
spread over a 30-day retention window. Best of three runs, warm cache:

| Query | Time |
|-------|-----:|
| `SELECT count(*) FROM node` | 0.7 ms |
| `SELECT count(*) FROM packet` | 11.8 ms |
| `SELECT count(*) FROM packet_seen` | 4.0 ms |
| `SELECT count(*) FROM node WHERE is_mqtt_gateway` | 0.6 ms |
| **one `/api/stats` request** | **17.1 ms** |
| `/api/stats/portnums` (`GROUP BY packet.portnum`) | 15.9 ms |
| `/api/stats/hardware` (`GROUP BY node.hw_model`) | 0.7 ms |
| **one dashboard load, all three** | **33.6 ms** |

These are full scans, so the figures scale with the row count: the
production `packet` table is larger than the one measured, and the
measurement box (a 2-core, 955 MiB Docker VM) could not be seeded
higher without the backend being killed. Read the table as the shape of
the cost, not as the production number. The point is that it is
proportional to everything retained and is paid on every page load.

#### Why not an approximate count

`pg_class.reltuples` was the obvious alternative and does not work
here. On a hypertable the rows live in the chunks, not the parent, so
the parent's estimate is **0**. Measured on the same database after
`ANALYZE`:

| Table | `pg_class.reltuples` | real count |
|-------|---------------------:|-----------:|
| `node` | 950 | 950 |
| `packet` | **0** | 200 000 |
| `packet_seen` | **0** | 60 000 |

An approximation would therefore have to sum every chunk's estimate —
more query, not less — and would still hand a page whose entire purpose
is to report counts a number that is wrong by an unknown amount. So the
figures stay exact and the readers share them.

### 8.1 `GET /api/stats`

Returns the dashboard summary: `node_count`, `packet_count`,
`observation_count` (uploads) and `gateway_count`.

Query parameters:

- `hours` — optional, 1 to 720. Count `packet_count` and
  `observation_count` over the last `hours` of receive time
  (`packet.first_seen_at`, `packet_seen.seen_at`), bounded at both ends,
  so a row dated in the future does not count (AGENTS.md 9.4).
  `node_count` and `gateway_count` stay totals of every node ever seen
  and every node ever flagged a gateway, with or without `hours` (#292).
- `since`, `until` — a fixed window instead of `hours`. See 8.00. The
  Statistics page sends its range this way or as `hours`.

With a window the response also carries the window fields of 8.00, and:

- `window_hours` — the window counted.
- `previous` — `packet_count` and `observation_count` for the window of
  the same length just before. It is null when that window starts
  before `RETENTION_DAYS_PACKET`: those rows are gone, and a comparison
  with them would show a rise that did not happen.

Without a window the answer is unchanged: every row the database holds.
The dashboard asks for `hours=24`.

Held for `STATS_CACHE_SECONDS`, one answer for each window, in a cache
with a bounded number of keys. See 8.0.

### 8.2 `GET /api/stats/top`

Returns top talkers by unique packet count.

Query parameters: the window (8.00, default 24 hours), `limit` (default
20). The window is bounded at both ends: it had a lower bound only, so a
packet row dated in the future counted in every window (AGENTS.md 9.4).

Item: `node_id`, `display_name`, `packet_count`, `air_util_tx`.
`air_util_tx` is the node's own average share of air time spent
sending, from its device telemetry, or null. On a shared channel a busy
sender is a cost to everybody else, and the page shows the two side by
side (#60).

### 8.2.1 `GET /api/stats/leaderboards`

Returns leaderboards that reward what helps the mesh (#60). None of them
counts packets.

Query parameters: `channel` — the preset. Without it, the assessed
preset with the most nodes. A window (8.00) moves `longest_link` to it.
Without one, that board reads its own 72 hours.

`reachable` and `direct_gateways` follow a quick range: `hours` of 24,
168 or 720 (#294). The gaps job writes their counts for each of those
windows (`docs/GAPS.md` 6.1). They do not follow:

- a fixed window (`since`, `until`), which no job can write in advance;
- any other `hours`;
- a quick range whose file the job has not written yet.

They then hold the gaps assessment's own window, `GAPS_WINDOW_HOURS`.
A 720 hour window is cut to `RETENTION_DAYS_PACKET` and does not follow
when that is shorter.

Every board carries `window_hours`, the window it holds, and
`follows_window`, true only when that is the window asked for. The page
reads `follows_window` and says "not the page range" where it is false.

Response: `available`, `preset`, `presets`, `assessed`, `boards`.

Each board: `key`, `title`, `measure`, `window_hours`, `cannot_know`,
`rows`. `reachable` also carries `not_ranked`. Each row: `node_id`, `display_name`, `value`, `unit`, `detail`;
a link row also carries `other_id` and `other_name`.
`unit` is SI (`km` for a link) or a word (`%`, `gateways`). The API does
not convert. The page writes `value` and `unit` through
`SonoranUnits.measure`, which gives miles or kilometres from the reader's
setting (#291).

- `reachable` — "Most reliably answers traceroutes" (#293): the share
  of traceroutes sent to a node by other nodes that it answered. A
  request is answered when a reply carries its packet ID as
  `request_id`, from the node asked, to the node that asked. A node
  needs at least 10 traceroutes from at least 2 senders; the board
  carries `not_ranked`, the number of traced nodes below that floor.
  Ranked by the low end of the Wilson 95 percent interval. `value` is
  the share in `%`; `detail` is "N of M answered, S senders". An answer
  no gateway uploaded counts as unanswered. Read from the gaps job
  (`docs/GAPS.md` 6.2). A gaps file written before #293 holds no counts,
  and the board then says so in `measure` and has no rows.
- `direct_gateways` — distinct gateways that heard the node with no hop
  used, never its own upload. Read from the gaps job.
- `longest_link` — the longest links graded `two_way` by
  `GET /api/graph`, with an SNR at least `GAPS_MARGIN_BAD_DB` above what
  the preset needs, and an exact position at both ends. It reads 72
  hours, at most 10,000 reports of each kind, and is held for 15
  minutes.

### 8.3 `GET /api/stats/hardware`

Returns node counts grouped by hardware model.

Without a window, every node ever seen. With one (8.00), only the nodes
that sent a packet inside it. The packet is the evidence, not
`node.last_heard`: that holds only the latest time, so a node heard in a
past range and again since would drop out of that range.

### 8.4 `GET /api/stats/portnums`

Returns packet counts grouped by payload type.

Query parameters:

- `hours` — keep packets first seen inside this window. Optional; without
  it, every packet the database holds.
- `channel` — keep packets seen on this channel. Optional; without it,
  every channel.
- `preset` — keep packets carried on one modem preset. See 1.2. The
  dashboard's chart sends this, as the firehose does, so the two count
  the same packets.

All are optional because two callers want different things. The
firehose's type suggestions want every type this mesh has ever sent, so
that each suggestion returns rows. The dashboard's packet-types chart
passes both, because a slice of it is a link into the firehose (plan
§7.1) and the two pages have to be counting the same packets.

This section used to say `hours` had a default of 24. The endpoint took
no parameters at all, so that window did not exist — and the dashboard
panel reading those figures is headed "Packet types (24 h)". Both were
corrected together.

Three of the names this returns are not port numbers: `UNREADABLE_PKI`,
`UNREADABLE_NO_KEY` and `UNREADABLE_UNRECORDED` are what a `portnum` of 0
turns out to be (§ on `traffic_label`, and #157). `/api/packets?portnum=`
answers 422 for them, and filtering on `0` instead would return all four
groups, so they are not usable as a packet-type filter.

### 8.5 `GET /api/stats/snapshots/daily`

Returns rows from `daily_snapshot`, newest first.

Query parameters: `days` (default 30). It is a row limit, not a date
filter.

These are whole-table counts the jobs service takes once a UTC day, so
`packet_count` is "packets still kept", not packets sent that day. The
Statistics page no longer draws them. See 8.5.1.

### 8.5.1 `GET /api/stats/daily`

Returns what the mesh did on each local day of the window (#294).

Query parameters: the window (8.00, default 720 hours).

Response: the window fields, `timezone`, and `days`. Each day has `day`
(`YYYY-MM-DD` in `DISPLAY_TIMEZONE`), `packet_count` (packets first
seen), `observation_count` (uploads) and `node_count` (distinct nodes
that sent a packet). A day with no traffic is a zero. A day older than
`retained_from` is left out, because its rows are gone and a zero would
say the mesh was quiet.

### 8.6 `GET /api/stats/activity`

Returns packet counts for each hour, split by packet family. This is the
"what is the mesh actually doing" chart. Node info and position usually
dominate.

Query parameters: the window (8.00, default 24 hours).

Response: the window fields, `bucket`, `hours` (the start of each
column), and `families`. Each family has `name`, `total`, and `counts`,
one value for each column and zero where nothing was sent. The busiest
family is first, so a stacked chart reads from the bottom.

`bucket` is `hour` up to 72 hours and `day` above that. A 30 day chart
by hour has 720 columns. A day is a local day in `DISPLAY_TIMEZONE`, and
its column starts at local midnight.

The time is when this process received the packet, never a time the
packet carries. See AGENTS.md 9.4.

### 8.7 `GET /api/stats/broadcast`

Returns how often each node sends, against the firmware defaults, with
what the device telemetry says about its health.

Query parameters: the window (8.00, default 24 hours), `limit`
(default 40).

Response: the window fields, `intervals` (the defaults used),
`notable_ratio`, `loop_restarts`, `loop_hours`, `node_count`,
`notable_count`, `power_loop_count`, and `nodes`.

Each node has `node_id`, `display_name`, `packet_count`, `families`,
`notable`, `faster_than_default`, and `health`.

Each family holds `count`, `interval_seconds` (the measured average),
`default_seconds`, `ratio` (how many times faster than the default),
`faster_than_default`, and `notable` (at or above `notable_ratio`).

`health` is null when the node sent no device telemetry. Otherwise it
holds `battery_level`, `voltage`, `uptime_seconds`, `on_battery`,
`restarts`, `restarts_24h`, `nodeinfo_ratio_24h`, `restarted`, and
`likely_power_loop`.

**Read this as a reason to ask, never as a verdict.** Three limits:

1. The interval is the window divided by the count, so it is an average.
   A node that joined halfway through looks half as busy as it is.
2. The count holds every packet of the family, not only the ones the
   broadcast timer sent. A node sends its node info when it boots and
   when another node asks for it, so a node that restarts all day, or a
   node with a curious neighbour, looks misconfigured when it is not.
3. A node that sent nothing is absent, not slow.

A battery above 100 percent means the node is on mains. That is how the
firmware reports a powered device.

**Restarts are counted, not inferred (#365).** A restart is a device
telemetry reading whose `uptime_seconds` is lower than the node's reading
before it, with the readings in our receive order (AGENTS.md 9.4).
`restarts` counts them in the window, and `restarts_24h` is the most
inside any 24 hours of it. The first reading of the window is never a
restart. A node that restarts unheard between two boots shows one
restart, and a node with no device telemetry shows none.

`likely_power_loop` is true when `restarts_24h` is `loop_restarts` or
more **and** the node sent its node info faster than the default inside
that same busiest 24 hours (a booting node sends it). `nodeinfo_ratio_24h`
is that rate, 1.0 being the default; it is null below `loop_restarts`.
Both numbers come from a measurement on our data (`docs/DECISIONS.md`,
#365). The table lists these nodes first, then the
nodes at `notable_ratio` or more. The battery is shown, never judged:
the old 5 to 35 percent "brownout band" had no source (AGENTS.md
§3A.2), and `brownout_band` and `brownout_risk` are gone.

### 8.8 `GET /api/stats/reliability/{node_id}`

Returns the reliability report for one node:

- packets sent by the node
- gateways that heard it, with counts
- hop count distribution
- heard and missed summary versus expected report intervals

## 9. Traceroute endpoints

### 9.1 `GET /api/traceroutes`

Returns recent traceroutes, newest first.

Query parameters: `from`, `to`, `before`, `limit`.

Response item includes the route, the return route, SNR lists, and the mesh-graph URL for the source node.

### 9.2 `GET /api/traceroutes/{id}`

Returns one traceroute with full detail, the mesh-graph URL
(`graph_url`), and `drawing_url`, the recoloured drawing below.

`reply_id` is the row ID of the newest stored reply to this trace, or
null. A reply is a row of its own: it carries this trace's `packet_id`
as its `request_id`, and it is sent by the node that was asked to the
node that asked. It is always null for a reply. The trace page reads it
to say "no reply was seen" only when none was stored (#288). This field
is on this endpoint only, not on the list in 9.1.

### 9.3 `GET /api/traceroutes/{id}/drawing.svg`

Returns mesh-graph's drawing of the trace as `image/svg+xml`,
recoloured for the dark site: the page is transparent, edges and loose
text are light, and node fills keep mesh-graph's own colours. 404 when
the trace is unknown or mesh-graph holds no drawing, 502 when mesh-graph
cannot be reached or sends no SVG. Cached for five minutes.

## 10. mesh-graph URL building

The API returns links from `MESH_GRAPH_BASE_URL`, and the UI links to
the mesh-graph pages for full views.

There is one exception to "links only": the trace drawing (9.3). mesh-graph
draws on white, the site is dark, mesh-graph is not changed here, and a
CSS filter over its picture inverts its colours too (issue #51). So the
API fetches that one SVG from `MESH_GRAPH_INTERNAL_URL` on the compose
network, rewrites only its neutral colours, and serves it. The UI shows
it in an `<img>`, where an SVG runs no script and follows no link. It is
not a general proxy: one route, one mesh-graph path, the trace key taken
from the database row, and no user input reaches the upstream URL.

## 11. Terrain endpoints

These endpoints feed the coverage planner. They read the filesystem, the
tile source and, for 11.3, a configured geocoder. They never touch the
database. See `docs/PLANNER.md`.

### 11.1 `GET /api/terrain/page/{tile}`

Returns the elevation page of one SRTM tile.

`tile` is a skadi name: `N34W112`, `S34E018`. Anything else is rejected
with 422 before any file or URL is built from it.

The body is **not** JSON. It is 2 880 000 bytes of little-endian int16:
a 1200 x 1200 grid in the cell order the SPLAT! engine reads. The
browser reads it straight into an `Int16Array`.

| Response | Meaning |
|---|---|
| 200 | The page follows. |
| 404 | No terrain is held for that tile. |
| 422 | Not a tile name. |

A 404 is normal, not a failure. It means the tile is outside the region
this service covers, or the tile source does not publish it, which is
true of open sea. The planner reads 404 as sea level, which is what the
engine does with a page it was never given.

Headers:

```
Content-Type: application/octet-stream
Cache-Control: public, max-age=31536000, immutable
ETag: "N34W112-2880000"
```

A page never changes, so the browser is told to keep it forever.

A tile outside the configured region is refused even when it is cached.
Without that check the endpoint would fetch and keep any tile on earth
for anybody who asked.

#### The outbound fetch this endpoint can start

Anybody may call this. While `TERRAIN_ALLOW_DOWNLOAD` is true, a
request for an **in-region, uncached** tile makes this process open an
outbound HTTP connection and then run a CPU-bound decode in a worker
thread. The disk cache is bounded by the region. The work in flight was
not:

- The per-tile lock stops the *same* tile being fetched twice. It says
  nothing about different tiles, and the region holds 56 of them, so a
  cold cache and a few callers could put every one in flight at once.
- The timeout was **120 seconds**, so one request could hold a
  connection and a worker thread for two minutes.

Two bounds now apply, and neither removes the exposure:

| Setting | Default | What it bounds |
|---|---|---|
| `TERRAIN_TIMEOUT_SECONDS` | 30 | How long one fetch may hold its thread |
| `TERRAIN_DOWNLOAD_CONCURRENCY` | 2 | How many different tiles are fetched at once |

**The recommended posture is to remove it.** Run
`tools/prefetch_terrain.py` once and set `TERRAIN_ALLOW_DOWNLOAD=false`.
The API then cannot make an outbound request at all, which is the only
complete answer; the bounds above are for a box that has not prefetched
yet. This is the same reasoning as `AGENTS.md` 7: the terrain endpoint
serves one configured region and must never become a general proxy for
the tile source.

### 11.2 `GET /api/terrain/region`

Returns the area terrain is held for. The planner reads it to warn
before a run reaches past the edge of the data.

Response:

```json
{
  "lat_min": 30,
  "lat_max": 38,
  "lon_min": -116,
  "lon_max": -108,
  "page_bytes": 2880000
}
```

The maximum values are the far edge of the last tile, not its corner.

### 11.3 `GET /api/geocode`

Turns an address or a place name into coordinates, for the planner's
site box. **The one endpoint on this API that talks to a third party on
a reader's behalf, and the only one that carries words a reader typed.**
Read `src/sonoran/api/routes/geocode.py` before changing it.

Query: `q`, 2 to 120 characters. A control character is refused rather
than stripped.

```json
{
  "places": [
    {
      "name": "Flagstaff, Coconino County, Arizona, United States",
      "lat": 35.1987522,
      "lon": -111.651822
    }
  ]
}
```

`places` may be empty. That is an answer: nothing of that name is in
this region, and a place outside it has no terrain to predict over
anyway.

| Status | Meaning |
|---|---|
| 404 | `GEOCODE_URL` is empty, so the feature is off here. The dashboard is told the same through `window.SONORAN.geocode` and draws no search box. |
| 422 | The query is too short, too long, or holds a control character. |
| 429 | This client's budget, or the upstream's own rate, is spent. Wait and ask again; do not retry automatically. |
| 502 | The geocoder did not answer, or answered with a shape this does not read. |

What it guarantees, and why each one is there:

- **Bounded to the home region.** `MAP_HOME_*` is sent to the upstream
  as a viewbox with `bounded=1`, and every answer is checked again here.
  So this cannot be used as a general purpose geocoder, in the same way
  `/api/terrain/page` refuses a tile outside its region.
- **Rate limited twice.** Ten lookups a minute per client address, and
  no more than one outbound request a second from this process whoever
  asked. A request that would wait more than two seconds for its turn is
  refused instead of queued.
- **Not in the log.** A GET puts the query in the request line, and the
  API is GET-only by architecture (`AGENTS.md` 4). The access log line
  reads `GET /api/geocode?[removed]`, and httpx's own INFO line for the
  outbound request is silenced. Both are in `sonoran/logging.py`.
- **Cached.** Bounded to 128 answers for an hour, which the upstream's
  usage policy asks for.

### 11.4 `GET /api/climate/page/{tile}`

Returns the Köppen-Geiger classes of one degree square, for the
planner's radio climate (#239). See `docs/PLANNER.md` 4.3.

`tile` is a skadi name, as in 11.1, and is named for the square's
south-west corner: Phoenix, at 112.07 W, is in `N33W113`. Anything else
is rejected with 422.

The body is **not** JSON. It is 14 400 bytes: a 120 x 120 grid, one
byte for each cell, holding the class number of the source legend (1 =
Af to 30 = EF), or 0 where the map has no class. **Row 0 is the north
edge and column 0 the west edge**, which is not the order of a terrain
page.

| Response | Meaning |
|---|---|
| 200 | The page follows. |
| 404 | The square is outside the configured region, or outside the data that ships. |
| 422 | Not a tile name. |

Headers:

```
Content-Type: application/octet-stream
Cache-Control: public, max-age=31536000, immutable
ETag: "climate-N35W112-14400"
```

The data ships inside the package (`sonoran/climate/`), so this never
reads a cache and never makes an outbound request. It answers for the
configured region only, by the same test as 11.1
(`TERRAIN_LAT_MIN` and the rest), so it is not a general source of
climate data. The data itself covers 30 to 38 north and 116 to 108
west; a region set wider than that gets 404 past the edge.

There is deliberately **no** endpoint that answers one point. The
planner sends no site to the server (`docs/PLANNER.md` 2), so it asks
for the square, as it does for terrain, and reads the cell itself.

### 11.5 `GET /api/climate/classes`

Returns the Köppen to ITM table the planner and the coverage job both
use, and what the data is. The planner keeps no copy of the table.

```json
{
  "source": "Köppen-Geiger 1991-2020, Beck et al. (2023), CC BY 4.0",
  "cells_per_degree": 120,
  "page_bytes": 14400,
  "fallback": "desert",
  "extent": {"lat_min": 30, "lat_max": 38, "lon_min": -116, "lon_max": -108},
  "classes": [
    {
      "code": 18,
      "symbol": "Dsb",
      "name": "Cold, dry summer, warm summer",
      "climate": "continental_temperate",
      "reason": "..."
    }
  ]
}
```

`classes` holds all 30 classes, in order. `climate` is a key of
`CLIMATE_CODES` in `coverage/params.py`. `fallback` is the climate used
where no class is known; the planner says so when it uses it.

## 11A. Planner catalogue endpoints

The coverage planner reads its hardware lists from `/api/radio`. Each
answer is cached for a day (`Cache-Control: public, max-age=86400`).
The cables, adapters and boards lists are not described here yet.

### 11A.1 `GET /api/radio/antennas`

Returns `band_low_mhz`, `band_high_mhz` and `antennas`, a list with one
object for each antenna. Each object holds every field of `Antenna` in
`sonoran/radio/antennas.py`. These fields matter most to a reader:

| Field | Meaning |
|---|---|
| `key` | The stable name of the entry. The planner picker uses it. |
| `gain_dbi_claimed` | The maker's gain claim, in dBi. It is a claim, not a measurement. Show it as one. |
| `kind` | One of `stub`, `whip`, `mobile_whip`, `gooseneck`, `fiberglass_omni` and `yagi`. |
| `directional` | True when the antenna has to be aimed. The planner shows a bearing box for it only. |
| `horizontal_beamwidth_deg` | The half-power width in azimuth, in degrees, or null when the listing gives none. The planner shapes the map with it. |
| `vertical_beamwidth_deg` | The half-power width in elevation, or null. |
| `front_to_back_db` | Null for every entry, because no listing states it. The planner caps the modelled loss behind the antenna at 15 dB for that reason. See `docs/PLANNER.md` 4.4. |
| `caveat` | A sentence about a doubtful figure in the listing. Show it beside the gain. |

`directional`, `horizontal_beamwidth_deg` and `front_to_back_db` were
added for the Yagi aiming in the planner. A reader that does not know
them can ignore them.

## 12. RF map endpoints

What the community's own receivers hear beyond Meshtastic, aircraft
first. Nothing here is fetched from anywhere else: a thing that is not
in these answers was not received by any of our stations. See
`docs/design/rf-map.md`. The message format stations publish is
`docs/rf-message-v1.schema.json`.

Aircraft in `RF_HIDDEN_IDS` (the FAA LADD and PIA lists, loaded by an
operator) are never stored and never returned.

### 12.0 `GET /api/rf/kinds`

`known`, every kind a station may send, `stored`, the kinds the
ingest keeps today, and `views`, the things kept that are not
observation kinds (`spectrum`, `sweeps`, `custom`). The RF page draws its sources list from
it, so a source whose phase has not landed reads as "not stored yet".

RF is separate from Meshtastic everywhere: its own tables, its own
topics, its own ingest. It adds no node, packet, upload or gateway to
any Meshtastic count.

### 12.1 `GET /api/rf/stations`

Every location. A location is one station on the map. It can have
more than one source: one Pi or decoder each, with its own login and
heartbeat (#305).

Each item: `station`, `display_name` and `owner` from the registry
(null when the location is not in it), `registered`, `lat` and `lon`
rounded by the agent, `precision_m` (by how much), `kinds` (of every
source heard from in the last day), `agent_version`, `last_seen` (null
before the first heartbeat), `online` (a heartbeat from any source in
the last five minutes), `counts` since the heartbeat before: `heard`,
`sent`, and `dropped` by thinning, summed over the sources that report
now, `spectrum_last`, the newest minute of any range the station swept
in the last day, or null, and `trust`: `new`, `trusted` or
`quarantined`, set by an operator, never by the station (#324). A
sweeper is known by what it sends, not by the kinds its heartbeat lists.

`sources` lists each source: `source` (null for an agent that sends
none), `kinds`, `agent_version`, `last_seen`, `online`, `counts`,
`registered`, true when the source holds a login now, and `sweeps`, what
the source reports it sweeps: `tool`, `tool_version`, `name`,
`f_start_hz`, `f_end_hz`, `bin_hz`, `gain_db`, `interval_s`, `ppm`,
`dwell_s` and `command`. It is what the station says about itself, and
is shown as such. A source in the registry that has not sent a heartbeat
has `last_seen` null.

### 12.2 `GET /api/rf/latest`

The newest point of everything heard in the window, newest first.

Query parameters: `kind` (`adsb`, `uat`, `aprs`, `sonde`, `ism`),
`minutes` (1 to 60, default 5), `limit` (1 to 5000, default 2000). The
count of the whole window is in `X-Total-Count`.

Each item: `kind`, `id`, `t`, `lat`, `lon`, `alt_m`, `alt_ref`, `gs_kn`,
`track_deg`, `rssi_db`, `station` (the station that heard this point),
and `meta` (for aircraft: `callsign`, `squawk`, `category` when sent).

### 12.3 `GET /api/rf/track/{kind}/{id}`

One thing's points, oldest first, one per 20 s bucket. `hours` is 1 to
48, default 1. 404 for an unknown kind or a hidden aircraft.

### 12.4 `GET /api/rf/heard/{station}`

Where one station has heard things, on a grid of about 2 km
(`cell_deg`, 0.02). Each cell: `lat`, `lon`, `best_rssi_db` and `heard`.
`kind` defaults to `adsb`, `hours` is 1 to 336, default 24. Measured,
not modelled: the RF page draws a station's reach from it.

For `kind=aprs` it holds what the station itself decoded (design 5.1):
a sender heard **directly**, or the digipeater or gateway named as `via`
for a relayed packet. A digipeater is placed where its own beacons put
it. A relayed sender, an object, and a position its sender blurred past
1 km place no cell. All of them are still on the map in `/api/rf/latest`.

### 12.5 `GET /api/rf/spectrum/{station}`

One station's minutes of one swept range, for the waterfall (design
7.4). `hours` is 1 to 168, default 6. `start`, an ISO time with a zone
in the last 3 days, asks for full resolution instead: the 2 hours from
`start`, one row per minute, and `hours` is ignored. `range` picks one
of the station's ranges, as 12.5.1 names it; without it, the range of
the newest minute in the window. 422 for a name that is not a station
ID, a `range` that is not one, or a `start` outside the last 3 days or
without a zone.

Response: `station`, `hours`, `range` (`id`, `source`, `name`,
`f_start_hz`, `f_end_hz`, `bin_hz`, `bins`), `bucket_minutes`,
`f_start_hz`, `bin_hz`, `bins`, `gain_db`, `sweeps_per_minute`,
`newest`, and `rows`, oldest first: every row of the window. Each row:
`t`, `minutes` (how many minutes of the range it holds), and per bin
`p50`, `p95`, `busy` and `peak`, the loudest single moment. A row longer
than a minute also has `peak_min`: per bin, the minute, counted from `t`,
of that loudest moment, so a short transmission seen in a long window
can be opened at full resolution. A row with `minutes` 0 holds no sweep
of the range and has no levels: it is **not swept**, never quiet. A
dongle that takes turns between ranges makes many (#324). An empty
window has no layout fields and an empty `rows`.

- A window longer than 240 minutes is bucketed in the database, so no
  answer holds more than 240 rows. In a bucket a bin keeps the median of
  its medians, the highest 95th percentile (a burst is never averaged
  away) and the mean busy share.
- A window longer than 24 hours reads the hourly rollup
  (`rf_spectrum_hour`), one row an hour, built the same way by the jobs
  process every 10 minutes. `bucket_minutes` is 60, and the window ends
  at the newest finished hour, which `newest` names.
- `p50` is the noise floor. A mesh packet is a short burst, so it does
  not move the median of a minute's sweeps. `p95` shows the bursts, our
  own traffic included.
- Levels are tenths of a dB relative to that station's receiver. They
  compare one station with itself and never two stations.
- One range at a time: two ranges are never mixed in one answer.

### 12.5.1 `GET /api/rf/spectrum/{station}/ranges`

Every range the station swept in the last `days` (1 to 14, default 7),
newest first, for the waterfall's picker (#324). Each: `id`
(`source:f_start_hz:bin_hz:bins`, `-` for an agent that sends no
source), `source`, `name` (the station's label), `f_start_hz`,
`f_end_hz`, `bin_hz`, `bins`, `newest` and `minutes`.

### 12.5.2 `GET /api/rf/sweeps`

What is being swept: every range any station swept in the last `hours`
(1 to 336, default 24), lowest first, for the "what is being swept"
chart (#324). Each: `station`, `display_name`, the fields of a range
(12.5.1), `gain_db`, `newest`, `minutes`, and `reported`, the matching
entry of what the source reports it sweeps (12.1), or null. A range a
source reports and sent no minute of is listed with `minutes` 0 and `id`
null.

### 12.5.3 `GET /api/rf/custom`

The newest point of each thing members' mods sent in the last `minutes`
(1 to 1440, default 60), newest first (#324). `station` and `mod` narrow
it; `limit` is 1 to 5000, default 2000, and the count of the whole window
is in `X-Total-Count`.

Each: `station`, `source`, `mod`, `id`, `t` (the mod's time after the
clock guard), `sent_t` (the time it sent), `received_at` (ours),
`placement`, `lat`, `lon`, `precision_m`, and `meta`. `placement` is
`reported` (the position the mod sent), `heard_here` (the station's
rounded position, with its `precision_m`), or `none` (no position: the
table only).

Every point is one station's unverified claim, never part of a shared
layer. A mod an operator hid (`sonoran-rf-trust hide-mod`) and every mod
of a quarantined station or source are left out. Text in `meta` arrives
without invisible or direction-changing characters, and the page shows
it as text only.

### 12.5.4 `GET /api/rf/noise-floor`

The latest **measured** noise floor of each node with a position (#182).
A contributor read it from the node on request (#178,
`docs/design/contributors.md`). It is not the theoretical floor the
coverage map uses.

Query parameter: `hours` — the window, 1 to 720. Default 24: two of a
router's 12 hour intervals, so one missed round still shows.

Each row: `node_id`, `long_name`, `short_name`, `role`, `lat`, `lon`,
`time`, `noise_floor_dbm`, `channel_utilization`, and `measured_by`
(`location`, `source`, `display_name`). A node with no reading in the
window is not listed: "not measured", never "quiet".

### 12.6 `GET /api/rf/channels`

Where each preset's default channel sits in the US band, computed the
way the firmware does: `slot = djb2(name) % slots`, centre `902 MHz +
bandwidth / 2 + slot × bandwidth`. `sonoran/radio/channels.py`.

Response: `region`, `start_hz`, `end_hz`, and `channels`, lowest first:
`name`, `label`, `bandwidth_hz`, `slot` (the index, from 0),
`centre_hz`, `low_hz`, `high_hz`, and `custom`. LongFast is 906.875 MHz,
MediumFast 913.125 MHz.

Channels the mesh set itself come from `RF_CUSTOM_CHANNELS`, such as
`MediumFast:18`, with `custom` true and a name such as `MediumFast slot
18`. The slot counts from 1, as the app and the frequency slot calculator
count it: MediumFast slot 18 is 906.375 MHz.

