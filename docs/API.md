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
- `heard_by` — the gateways that heard this node. Each has `count`,
  `avg_snr`, `best_snr`, `avg_rssi`, `best_rssi`, `last_heard`.
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

Response:

```json
{
  "packet": { "...": "as in /api/packets, plus payload_json" },
  "observations": [
    {
      "gateway": "!11223344",
      "mqtt_topic": "msh/US/AZ/2/e/LongFast/!11223344",
      "rx_rssi": -87,
      "rx_snr": 6.5,
      "hop_limit": 1,
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

Each section has `channel`, `label`, `group`, `preset`, `count`,
`last_seen`, and `messages`.

The group is `Presets` when the channel name is a default LoRa preset
name, such as `LongFast` or `MediumFast`. Other groups are `Weather`,
`Emergency`, `Telemetry`, and `Custom`.

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

### 5.5 `GET /api/chat/conversation/{packet_id}`

Returns one message with its replies. Replies match on `reply_id`.

## 6. Map endpoints

### 6.1 `GET /api/map/nodes`

Returns nodes that have a current position.

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

- `minutes` — time window. Default 15.
- `limit` — maximum observations. Default 300.
- `channel` — the modem preset to return. A node on one preset cannot
  hear a node on another, so a map layer must draw one at a time.
  Without it the response mixes every channel together.

Response: `window_minutes`, `event_count`, `direct_count`, and `events`.
Each event has `time`, `packet_id`, `channel`, `portnum`, `snr`, `rssi`,
`hop_limit`, `hop_start`, `direct`, `from`, `gateway`, and `has_line`.

`direct` is true only when the packet used no hop
(`packet.hop_start = packet_seen.hop_limit`). It is false when either
value is unknown. A line for a relayed observation is a path, not a
radio link: the packet reached the gateway through other nodes, so the
straight line crosses ground the signal never took. See AGENTS.md 9.5.

`portnum` is the readable name, or the number as text when this build of
the protobufs does not know it.

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
  `role`, `hw_model`, `is_mqtt_gateway`, `has_position`, `last_heard`,
  `packet_count`, `known`.
- Link item: `source`, `target`, `kind`, `snr`, `count`, `time`.

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
