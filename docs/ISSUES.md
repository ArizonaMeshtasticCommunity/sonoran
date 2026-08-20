# ISSUES.md — Open work

This file replaces the build phases in `docs/PLAN.md`. The first
roadmap is complete, so work is tracked here instead.

Read `AGENTS.md` section 9 before you start. It lists the traps this
project has already sprung.

Each issue has a state:

- **Open** — nothing done yet.
- **Partly done** — some of it works. The gap is written down.
- **Blocked** — waiting on a decision or on data.
- **Watch** — believed correct, not yet proven in live traffic.

---

## 1. Data integrity

### 1.1 Historical duplicate rows in `packet` and `packet_seen`

**State:** Open. Deliberately deferred.

Deduplication was broken until revision 0009. About 8,200 duplicate
packet rows remain from before the fix, roughly 87 percent of the rows
written in that period.

Effects: packet counts on the dashboard are inflated, and "busiest
nodes" partly ranks by how many gateways heard a node.

The payload tables were already cleaned: `neighbor_metrics`,
`traceroute`, `text_message`, `position_metrics`, `device_metrics`,
`environment_metrics`, `air_quality_metrics`, `power_metrics`,
`pax_metrics`.

Options: leave it and let the 30-day retention clear it, or dedupe in
place keeping the earliest row per (`from_node_num`, `packet_id`). Take
a dump first.

### 1.2 `packet_pk` is dead weight

**State:** Open.

Every payload table carries `packet_pk`, which points at the generated
`packet.id`. It is NULL on every row and can never be filled. See
`AGENTS.md` 9.1.

Drop the column in a migration once nothing reads it.

### 1.3 `packet.payload_json` is never written

**State:** Open.

The column exists and stays NULL. Decoded values live in the typed
tables. Either drop the column, or populate it during ingest if a raw
view is wanted.

### 1.4 Telemetry rows cannot always be matched to a packet

**State:** Partly done.

Telemetry timestamps come from the payload, not from the packet, so the
backfill could not match every historical row:

| Table | Matched | Total |
|-------|---------|-------|
| `position_metrics` | 1,201 | 2,592 |
| `device_metrics` | 396 | 1,512 |
| `neighbor_metrics` | 597 | 597 |
| `traceroute` | 1,371 | 1,373 |
| `text_message` | 97 | 97 |

Rows written after revision 0010 all carry `packet_id`. Only history is
affected, and it ages out with retention.

### 1.5 Historical rows carry a gateway clock, not ours

**State:** Partly done. The ingest is fixed. The history is not.

`AGENTS.md` 9.4 is plain: never use a packet time to answer "when did we
hear this". The ingest broke that rule. `_first_seen_at` preferred
`packet.rx_time`, which is stamped by whichever gateway relayed the
packet, from that gateway's own clock.

Measured on live data before the fix:

| Table | Rows in the future | Total |
|-------|--------------------|-------|
| `packet` | 349 | 15,235 |
| `mesh_packet_metrics` | 348 | 14,966 |
| `neighbor_metrics` | 26 | 935 |
| `packet_seen` | 0 | 87,142 |

`packet_seen.seen_at` was always correct: it came from
`ObservationInput`, which used the receive time. The rest inherited
`first_seen_at`, including the payload tables through `HandlerContext`.

**Fixed:** `heard_at` in `ingest/pipeline.py` now returns the receive
time and takes the message rather than the packet, so there is nothing
left to get wrong. The gateway's claim is still stored, in
`packet.rx_time`. An integration test pins it.

**Not fixed:** rows written before the change keep the wrong time, and
they cannot be repaired. The true receive time was never stored, so
there is nothing to restore it from. The nearest available substitute
is the matching `packet_seen.seen_at`, which is correct and could be
copied back where a row has one:

    UPDATE packet p SET first_seen_at = s.seen_at
    FROM (SELECT from_node_num, packet_id, min(seen_at) seen_at
          FROM packet_seen GROUP BY 1, 2) s
    WHERE p.from_node_num = s.from_node_num
      AND p.packet_id = s.packet_id
      AND p.first_seen_at <> s.seen_at;

That rewrites the partition column of a hypertable, so take a dump
first and expect it to be slow. Retention clears the problem in 30 days
without any of that, which is why this is written down rather than done.

The statistics endpoints bound their queries at `now()` meanwhile, so a
surviving future row cannot invent an hour that has not happened.

---

## 2. Known gaps in the interface

### 2.1 `/api/chat/conversation/{packet_id}` is broken

**State:** Open.

It matches on `packet_pk`, which is always NULL, so it can never find a
message. `text_message` now has `packet_id`, so the fix is to key on
that. Nothing in the dashboard calls it yet.

### 2.2 The mesh graph is dense at full scale

**State:** Partly done.

The whole-preset view draws around 250 nodes and 550 links. Force
settings scale with node count, and the Backbone and One node views
exist, but the whole view is still busy.

**Done since:** the graph now lays out on the ground. Nodes that report
a position are projected onto the canvas, and the rest are seeded beside
the neighbours that do, so the Phoenix and Tucson knots land where they
belong and hold between redraws. A spacing sweep then opens crowded
points apart: on the busiest preset the gap between neighbouring nodes
runs about three times what it was, while the mesh as a whole grows by
under a fifth. Nodes are coloured by role, the same as the map, and the
busiest few carry a label. The layout picker offers "On the ground,
spread", "On the ground, exact", and "Free force". A reader can drag a
node and it stays put across a redraw, and "Reset layout" undoes it.

**Still open:** the "spread" sweep is every pair against every other, so
it is capped at 1500 nodes and skipped above that. Fading links below a
signal threshold is not done. Geographic clustering, as opposed to
geographic layout, is not done.

### 2.3 The live traffic layer draws lines that are not radio links

**State:** Partly done.

`/api/map/traffic` returns one event for each observation, holding the
sender and the gateway that heard it, and the map draws a line between
them. Most of those lines are not radio links.

`AGENTS.md` 9.5 measured it: about 82 percent of observations were
relayed and only 5 percent were direct. A relayed packet reached the
gateway through other nodes, so the straight line between sender and
gateway crosses ground the signal never took.

This is the same fault the traceroute lines had, and it is now the
larger one, because the traffic layer is on by default and draws
several hundred lines.

An observation is direct only when no hop was used:

    packet.hop_start = packet_seen.hop_limit

`/api/map/traffic` now returns `hop_start` and a `direct` flag, and the
map draws a direct observation as a solid line in its signal colour and
a relayed one faint and dotted. Live traffic measures about 11 percent
direct.

What is left: the relayed lines are still drawn, only quietly. They
still join two nodes that may be far apart with no link between them.
Consider dropping them altogether, or drawing them to the node that
relayed the packet once that is known.

### 2.4 The coverage planner covers one site at a time

**State:** Closed. The coverage map answers the other question.

The planner still predicts one transmitter for each run, and that is
the right shape for it: a person trying a mast anywhere, in the
browser, telling nobody where. The other question, where the mesh is
blind when every node is considered together, is now the coverage map.
See `docs/COVERAGE.md`.

The merge is not the merge this note expected. `mergeFirstTouch` in
`planner.js` merges radial slices of one run on one grid. Putting
different sites together is a different operation, because each run
comes back on its own degree-aligned region. `coverage/grid.py` does
it, and it needs no resampling: every engine raster sits on the same
lattice of 1200 cells to the degree, so a raster is placed at a whole
cell offset and no value changes.

Two things the note did not anticipate:

- A coverage map has two directions and they are not the same. See
  `coverage/sites.py`.
- The whole map cannot be recomputed by every reader, so it runs in the
  jobs process. `docs/PLANNER.md` 2 says why that does not weaken the
  rule about the planner page.

### 2.4.1 The calibration reads neighbour reports only

**State:** Open.

`jobs/calibrate.py` fits its per-node correction from
`neighbor_metrics`. Traceroute carries a per-hop SNR as well and would
roughly double the evidence.

It is left out because the only correct reading of a traceroute row is
`sonoran/api/traces.py`, and the jobs process does not import the api
package. Moving that reading into a module both can import is the work
to do first. See `AGENTS.md` 9.6 and 9.18 for why the reading is not
something to write a second time.

### 2.5 The planner draws 90 m terrain only

**State:** Open.

The engine reads 30 m terrain as well (`resolutionIppd: 3600`). That is
nine times the data for each page: 25.9 MB instead of 2.88 MB, and nine
times the memory in the browser. `tools/prefetch_terrain.py` and
`terrain/srtm.py` would both need the higher resolution path, which
upstream calls `srtm2sdf-hd`.

At 90 m the model already follows ridge lines. The gain from 30 m is
mostly in close country and on narrow passes.

### 2.6 A site plan cannot be kept

**State:** Open.

Nothing about a run is stored or linked. Closing the tab loses it.
Upstream encodes a whole plan in the URL (`src/permalink.ts`), which
would suit this project too and needs no storage and no write endpoint.

### 2.7 mesh-graph may hold no drawing for a trace

**State:** Watch.

mesh-graph keeps its own database from its own MQTT subscription, so a
trace we hold may be missing there. The embed hides itself and explains
when that happens. Recent sampling resolved 30 of 30.

### 2.8 Traceroute request IDs on old rows

**State:** Partly done.

187 historical replies were recovered by decoding stored packet bytes.
Any reply whose packet row has aged out cannot be recovered. New
replies capture the field during ingest.

### 2.9 `/api/map/traffic` counts the window one row at a time

**State:** Open.

The window count reads the packet row behind each observation with a
correlated subquery, so a wide window over a busy mesh runs one index
probe per observation. The endpoint is public and the map refreshes it
every fifteen seconds. A grouped join against the distinct packet keys
of the window, with the duplicate rows removed first, would answer in
one pass. This is finding 2.1 in `docs/REVIEW.md`, left open there for a
benchmarked rewrite.

---

## 3. Wanted next

### 3.0 The broadcast report cannot separate a timer from a reply

**State:** Open. A limit of the data, not a bug.

`/api/stats/broadcast` measures how often a node sends each family and
compares that to the firmware default. It cannot tell a scheduled
broadcast from a reply to a request, or from the packet a node sends
when it boots.

That matters most for node info, which is the family the report flags
most often. A node that restarts all day, or one whose neighbours keep
asking it for its details, looks misconfigured when it is not.

The uptime and battery figures alongside make the common case readable:
a short uptime says the node is restarting. A better answer would need
either the configured interval, which the mesh does not publish, or a
count of the requests each node answered.

Until then the panel says "worth a look", the docs repeat it, and
nothing in the interface calls a node misconfigured.

### 3.1 Real URL paths instead of hash routes

**State:** Open.

Pages use `#packet/...` and `#traceroute/...`. Real paths would need the
API to serve the dashboard for those routes and the client router to
read `location.pathname`.

### 3.2 More payload views

**State:** Partly done.

A position packet draws a map. Telemetry, text, and neighbour reports
show labelled values. Traceroute shows the path and the mesh-graph
drawing.

Still plain: waypoints, store and forward, paxcounter, and any packet
family with no typed table.

### 3.3 Node page history charts

**State:** Open.

The node page shows the latest value of each telemetry family and the
direct link signal over time. Battery, channel use, and temperature
history would suit the same treatment.

### 3.4 Position tracks on the map

**State:** Open.

`/api/map/track/{node_id}` returns position history and nothing draws
it. A moving node could show a trail.

---

## 4. Operational notes

### 4.1 Text storage is on

`STORE_TEXT_MESSAGES=true`. Message bodies are stored and kept for
`RETENTION_DAYS_TEXT` days. This is a privacy decision. Turning it off
leaves the Chat and Weekly check-in pages empty.

### 4.2 Backups taken during cleanup

Cleanup work wrote CSV dumps to `~/sonoran-backups/`. They are outside
the repository and are not part of any backup schedule.

### 4.3 Undecryptable channels are normal

Ingest logs `no channel key produced a valid payload` for channels whose
key is not configured. This is expected and harmless. It is not a
failure of the pipeline.
