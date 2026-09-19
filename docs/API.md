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

Returns nodes, newest heard first.

Query parameters:

- `q` — search in long name, short name, node ID.
- `hw` — filter by hardware model.
- `role` — filter by role.
- `gateway` — `true` to show only MQTT gateways.
- `active_hours` — only nodes heard in the last N hours. Default: all.
- `before`, `limit` — pagination.

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

### 3.2 `GET /api/nodes/{node_id}`

Returns full detail for one node.
Includes names, hardware, role, last position, last heard time, gateway status, and reported configurations.

### 3.3 `GET /api/nodes/{node_id}/packets`

Returns recent packets from this node.

Query parameters: `portnum`, `before`, `limit`.

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

- `family` — one of `device`, `environment`, `air_quality`, `power`, `pax`. Required.
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

### 3A.1 `GET /api/coverage`

Returns the current coverage run.

`available` is false when the job has never run. That is a working
state for a new deployment, not a fault.

The response carries the manifest of the run: `generated_at`, `bounds`
of the whole region, `data_bounds` of the coverage itself, `min_zoom`
and `max_zoom`, `active_hours`, the receiver the map assumes, `has_terrain`,
`has_landcover`, `missing_terrain_tiles`, and one entry for each modem
preset with its node counts, its covered area, and the sites it used.

`active_hours` is the position and traffic window for the nodes in the
run. A page uses the same value when it asks `/api/map/nodes` for the
optional node layer.

A page must open on `data_bounds`, not on `bounds`. The region covers
every degree the terrain service serves, which is far more ground than
any mesh reaches.

### 3A.2 `GET /api/coverage/tiles/{stamp}/{preset}/{layer}/{z}/{x}/{y}.png`

Returns one coverage tile, 256 pixels square, in the usual web map
scheme.

`stamp` identifies one coverage run. It comes from `GET /api/coverage`.
The URL always returns bytes from that run. It never moves to a newer
run.

`preset` is a modem preset name, such as `LongFast`. A preset is a
radio configuration, not a filter: a node on one preset cannot hear a
node on another, so each has its own coverage. See `AGENTS.md` 9.7.

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

## 3B. The public embed

These serve a page for somebody else's website. They are all 404 until
`EMBED_ENABLED` is true.

`sonoran/embed/sanitise.py` is the only place that decides what a
public viewer sees. `/api/map/nodes` is untouched: it serves the
dashboard, which is a different audience.

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

### 3B.3 `GET /api/embed/nodes`

The infrastructure sites a public page may show.

Routers, repeaters, and MQTT gateways only. A client node is usually a
person, often at home, and never appears. Each entry carries the short
name, the role, whether it is a gateway, and a position snapped to
`EMBED_POSITION_STEP` degrees. The long name, the hardware model, the
node ID, and the last heard time are all left out.

The position is snapped in this process, before it is sent. Rounding it
in the browser would mean the exact value had already left.

## 4. Packet endpoints

### 4.1 `GET /api/packets`

Returns packets, newest first. This is the firehose feed.

Query parameters:

- `portnum` — filter by payload type name or number.
- `from`, `to` — filter by node.
- `channel` — filter by channel name.
- `since` — only packets newer than this timestamp.
- `before`, `limit` — pagination.

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

Response:

```json
{
  "packet": { "...": "as in /api/packets, plus payload_json" },
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
      "seen_at": "2026-08-01T12:00:01Z"
    }
  ]
}
```

## 5. Chat endpoints

These endpoints return empty lists when text storage is disabled.

### 5.1 `GET /api/chat`

Returns text messages, newest first.

Query parameters: `channel`, `from`, `since`, `before`, `limit`.

### 5.2 `GET /api/chat/channels`

Returns the list of channels that have text messages, with counts.

### 5.3 `GET /api/chat/overview`

Returns every detected channel with its recent messages. The chat page
draws one section per channel, below the heading of its group.

Each section has `channel`, `label`, `group`, `preset`, `tier`,
`count`, `last_seen`, and `messages`.

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

Query parameters: `hours` (default 168), `per_channel` (default 25).

### 5.4 `GET /api/chat/tagged`

Returns messages that carry one hashtag, grouped by week. The weekly
mesh network check-in uses the `#meshnet` tag. A week starts on Monday
in UTC.

Query parameters:

- `tag` — the tag word, with or without the hash sign. Default
  `meshnet`. Letters, numbers, and underscore only.
- `weeks` — how many weeks to return. Default 8.
- `limit` — maximum messages. Default 500.

Each week has `week_start`, `week_end`, `message_count`,
`check_in_count` (how many different nodes checked in), and `messages`.

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

A link comes from a neighbor report or from a traceroute hop. A
neighbor link replaces a traceroute link between the same two nodes,
because the neighbor report carries a measured SNR.

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
- Link item: `source`, `target`, `kind`, `snr`, `count`, `confirmed`,
  `time`.

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
trip, so the evidence runs one way. Such links are true but weaker.
The graph page draws them fainter and can hide them.

### 7.3 `GET /api/graph/link`

Returns the reports that evidence one link on the graph. Every report
names the packet that carried it, so the packet page opens from here.

Both nodes are read through the same rules as `GET /api/graph`, so a
link the graph draws always has at least one report here. The query
selects traceroutes that name both nodes, rather than the newest rows
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

### 8.1 `GET /api/stats`

Returns the dashboard summary: node counts, packet counts, gateway counts, messages per hour.

### 8.2 `GET /api/stats/top`

Returns top talkers by unique packet count.

Query parameters: `hours` (default 24), `limit` (default 20).

### 8.3 `GET /api/stats/hardware`

Returns node counts grouped by hardware model.

### 8.4 `GET /api/stats/portnums`

Returns packet counts grouped by payload type.

Query parameters: `hours` (default 24).

### 8.5 `GET /api/stats/snapshots/daily`

Returns rows from `daily_snapshot`, newest first.

Query parameters: `days` (default 30).

### 8.6 `GET /api/stats/activity`

Returns packet counts for each hour, split by packet family. This is the
"what is the mesh actually doing" chart. Node info and position usually
dominate.

Query parameter: `hours` (default 24, maximum 720).

Response: `window_hours`, `hours` (the hour each column stands for), and
`families`. Each family has `name`, `total`, and `counts`, one value for
each hour and zero where nothing was sent. The busiest family is first,
so a stacked chart reads from the bottom.

The time is when this process received the packet, never a time the
packet carries. See AGENTS.md 9.4.

### 8.7 `GET /api/stats/broadcast`

Returns how often each node sends, against the firmware defaults, with
what the device telemetry says about its health.

Query parameters: `hours` (default 24), `limit` (default 40).

Response: `window_hours`, `intervals` (the defaults used),
`notable_ratio`, `brownout_band`, `node_count`, `notable_count`,
`power_loop_count`, and `nodes`.

Each node has `node_id`, `display_name`, `packet_count`, `families`,
`notable`, `faster_than_default`, and `health`.

Each family holds `count`, `interval_seconds` (the measured average),
`default_seconds`, `ratio` (how many times faster than the default),
`faster_than_default`, and `notable` (at or above `notable_ratio`).

`health` is null when the node sent no device telemetry. Otherwise it
holds `battery_level`, `voltage`, `uptime_seconds`, `on_battery`,
`brownout_risk`, `restarted`, and `likely_power_loop`.

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

`brownout_risk` is true inside `brownout_band`, which is 5 to 35
percent. In that band a node has enough charge to boot and start
transmitting but not enough to hold the current a transmission draws, so
it browns out and restarts. That is why a node with a low battery can be
one of the noisiest on the mesh. Below the band a node is usually flat
and silent, which is a different problem.

`likely_power_loop` is true only when the node both restarted inside the
window and sits in that band. It is deliberately narrow.

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

Returns one traceroute with full detail and the mesh-graph URL.

## 10. mesh-graph URL building

The API never proxies mesh-graph.
It returns URLs from `MESH_GRAPH_BASE_URL`.
The UI embeds the SVG endpoints with `<object>` tags.
The UI links to the mesh-graph pages for full views.

## 11. Terrain endpoints

These endpoints feed the coverage planner. They read the filesystem and
the tile source. They never touch the database.
See `docs/PLANNER.md`.

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
