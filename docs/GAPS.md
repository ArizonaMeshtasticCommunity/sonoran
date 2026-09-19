# Coverage gaps: which nodes the mesh is not carrying well

**State: phase 1 is built.** The per node half. The area half, which
answers "where would one new node help the most people", is designed and
not built. `docs/design/coverage-gaps.md` is the whole design; this
document describes what runs.

## 1. What it answers, and what it never claims

One question: **which nodes are struggling, and in what way?** The answer
is a short list with the evidence beside each item, for one modem preset
at a time.

There is a second thing it must do, because the data forces it: say
plainly when it does not know. Every signal has three states and the
third is `unknown`. **`unknown` never renders as zero, as green, or as an
empty cell that reads like "fine".** A node that reports nothing is
usually a node that is switched off. It is not a node in trouble.

It never claims:

- that a node cannot hear the mesh, except in the one proven case in 4.2,
- that any two nodes have a radio link, or what its signal is,
- that a node is at fault when the evidence is thin,
- anything at all about a preset other than the one being read.

## 2. The fact the whole feature rests on

A packet of node N is in this database by exactly one of two routes.

- **N uploaded it.** `packet_seen.gateway_node_num = from_node_num`. N is
  an MQTT gateway and uploaded its own traffic. It proves nothing at all
  about radio.
- **Some other radio heard it and a gateway uploaded it.**
  `gateway_node_num <> from_node_num`. Whether that gateway heard N
  directly or after any number of relays, a radio received N's
  transmission.

The second is a positive radio signal that **costs nothing and claims no
link**. It says *some* radio heard N. It never says which one, and it
never carries a usable SNR, because the reading on a relayed observation
belongs to the last hop into the gateway. See `AGENTS.md` 9.5 and 9.20.

Read backwards it gives the negative: a node whose every upload is its
own was heard by no gateway, by any path. That is 4.1.

### 2.1 The observer set is MQTT gateways, and nothing else

`packet_seen` records MQTT uploads, so the only observers this database
can ever hold are gateways. Every other node on the mesh hears plenty and
reports none of it.

So "nobody heard this node" always means "no gateway heard it", and the
page says it in those words: **"none of the 31 gateways active in this
window heard it over the air"**. That is a fact a reader can weigh. "It
is isolated" is a judgement. The difference is not decoration.

### 2.2 The open hole, and the prerequisite still outstanding

A gateway can rebroadcast MQTT traffic onto the air. If a third gateway
heard that copy and uploaded it, the second upload would evidence a radio
path the node never used. The firmware marks a packet it took from MQTT
and `via_mqtt` is stored, so the copy should never be uploaded again.

**That is an assertion about firmware behaviour, and this project does not
assert what the vendor did not state.** The vendored `proto/` directory
holds only `UPSTREAM_REV.txt` and `update.sh`, so those field comments
cannot be quoted from this repository yet.

**Until they can be, and until the hole is measured on live data, a
`via_mqtt` packet counts as no evidence either way.** Such packets are
reported as `ambiguous_packets`, and a node whose every packet is
ambiguous reads `unknown`, never `bad`. This is the conservative branch
and it is what runs today. See design section 2.2 and 11.1.

`via_mqtt` is also not a per observation fact:
`store_mesh_packet_metrics` runs inside `if stored.is_new:`, so
`mesh_packet_metrics` holds the view of whichever gateway uploaded a
packet **first**. There is no per observation column, and a query that
read one would be inventing it.

## 3. One module holds each rule

| Module | Decides |
|---|---|
| `gaps/signals.py` | What every signal means. The only place. |
| `gaps/store.py` | Where an assessment is written and read. |
| `jobs/gaps.py` | Running it for each preset, and the counts. |
| `api/routes/gaps.py` | Serving the written file, and filtering it. |
| `web/static/gaps.js` | Drawing it. It paraphrases no finding. |

Every sentence on the page comes from the API's `sentence` field, which
`signals.py` wrote. The front end does not reword a claim.

## 4. The signals

The window is `GAPS_WINDOW_HOURS`, 168 by default, and it is bounded at
both ends on **our** clock. A node clock has been seen nearly 28 hours
ahead and some historical rows still carry one, so an unbounded upper
end would report hours that have not happened. Every window reads
`packet.first_seen_at`, `packet_seen.seen_at` and `neighbor_metrics.time`,
never `packet.rx_time`. See `AGENTS.md` 9.3 and 9.4.

**Counts are of distinct packets, never of rows.** One live packet had 22
uploads from 15 gateways, and about 8,200 duplicate `packet` rows survive
from before revision 0009. Every count groups by
(`from_node_num`, `packet_id`) first.

### 4.1 `radio_isolated` — present through MQTT, not heard on the air

`bad` when the node is an MQTT gateway, cleared the packet floor, and no
gateway heard any of its traffic over the air, with no neighbour report
naming it and no traceroute hop evidencing it.

**A node that is not a gateway can never be `bad` here.** It returns `ok`
with the reason `not_an_mqtt_gateway`: its packets could only have
reached us because a radio heard them. That is section 2 read backwards,
and it removes most of the mesh from the signal at no cost.

### 4.2 `hears_but_is_not_heard` — the one honest asymmetry

`bad` when the node satisfies 4.1 **and** published at least
`GAPS_MIN_NEIGHBOUR_REPORTS` neighbour reports with a measured signal.

Its receiver demonstrably works and its transmissions demonstrably reach
no gateway. That points at the transmit side: an antenna, a cable, a
region setting, or a power of zero. It is the strongest single finding
this feature can produce and the only case in which this project will
say a node cannot be heard.

Anything else is `unknown`, **never `ok`**. The absence of neighbour
reports is almost always the NeighborInfo module being switched off,
which says nothing about the radio. The signal has no `ok` state.

### 4.3 `rf_intermittent` — sometimes gets out, sometimes not

Link stability is not measurable here, so this measures something that
is. Of the hours the node was awake, in how many did anything on the air
hear it?

The ratio is over **hours and not packets**, because one chatty hour
would otherwise decide the answer. It is a ratio within the node and
never a rate across nodes, because two nodes with different broadcast
intervals are not comparable on an hour count.

### 4.4 `sole_observer` — one gateway hears it directly

`bad` when exactly one gateway has heard it with no hop used.

**This is not a single point of failure.** The observer set is gateways,
so it says "one gateway can hear it", which is a statement about our
instrumentation as much as about the mesh. Zero direct gateways is
`unknown`, not `bad`: a well connected node three hops deep is heard
directly by nobody, and that is normal.

### 4.5 `weak_best_link` — the best measured link has little margin

Only measured readings, from three sources: a `neighbor_metrics.snr` in
either direction, a traceroute hop SNR read through `api/traces.py`, and
a direct observation by another node.

```
required_snr_db(preset) = preset.sensitivity_dbm - noise_floor_dbm(preset)
snr_margin_db           = snr - required_snr_db(preset)
```

`required_snr_db` is in `radio/presets.py`, beside `noise_floor_dbm`, so
the one preset table stays the one preset table. For Long fast it is
about **-25 dB**, which is why a reported SNR of -20 dB is a working link
with about 5 dB to spare and not a broken radio. A raw SNR cannot be read
without the preset beside it.

The **best** link is the right statistic: a node with one strong link and
twenty weak ones is fine.

Never `NodeFit.offset_db`. It is inferred, not reported, and the live fit
is currently rejected outright. See `AGENTS.md` 9.21.

### 4.6 `outside_predicted_usable` — the prediction does not reach it

The one signal that reads a prediction. The page must never draw it in
the same colour as a measurement.

`unknown` when no run is published for the preset, when the node has no
usable position, when the position is known to be coarse, or when the
published run is a **diagnostic**: a diagnostic predicts from client
nodes that move. See `AGENTS.md` 9.25 and 9.27.

The inverse is counted separately as `reached_but_unpredicted`, and **it
is a finding about the map and not about the node.** A node something on
the air reached, standing where the model predicts nothing, is coverage
the model missed.

### 4.7 `mobile` — a modifier, not a fault

The spread of a node's reported positions over the window. A mobile node
is still listed, because a handheld that cannot get out is a real problem
for its owner. It is the area half of this feature that must leave it
out, because a footprint drawn to serve a node that moves serves nobody
tomorrow.

## 5. What the coverage job adds

A finished run keeps **no level grid**. `_build_site_set` holds the
region grids in RAM, renders colour ramped PNG tiles, and deletes them,
and a tile entirely below the threshold is never written. So the exact
dBm at a point cannot be recovered from disk afterwards, and reading it
back from an alpha channel at zoom 11 gives a boolean where a margin is
wanted.

So the job samples the grids **while they are still in memory**, after
`_charge_receiver`, and writes one artefact into the pending directory:

```
{coverage_cache_dir}/runs/{stamp}/coverage-at-nodes.json
```

```json
{"stamp": "20260918T060000Z",
 "presets": {"LongFast": {"threshold_level": 61,
   "site_sets": {"infrastructure": {"305419896": {"usable": 78, "downlink": 92, "uplink": 78}}}}}}
```

It goes into the pending directory so the run's own rename publishes it.
There is no second write and no second rename, so a reader can never see
a level from one run beside a stamp from another.

`threshold_level` is `to_level(preset.sensitivity_dbm)`, so a reader
needs no preset table to decide what counts as usable.

**A node absent from the object is unknown. It is never written as a
zero.** A node outside the region grid is simply not in the run. A stored
zero is a different answer: the model predicts nothing where that node
stands.

### 5.1 Why the sample is a cell wide

The engine marks a cell covered when a radial of its sweep passed through
it, and **no radial passes through the cell the sweep starts from**. A
site therefore sampled its own position as `NO_COVERAGE` and read as
standing outside its own footprint, which is a false accusation about the
one node we are most certain of. It was found by running the job, not by
reading it: every router in the preview came back `outside_usable`.

So the sample takes the strongest cell within one cell, which is
1/1200 of a degree or about 90 m — the resolution of the grid itself. It
is not smoothing. It removes the artefact and moves nothing else: 90 m is
far finer than the 365 m that is the best position precision the public
broker ever relays, so no node crosses the threshold on ground it is not
standing on.

This is a deviation from the design, which specified a single cell. The
design's premise that a stored zero means "the run reached this cell and
found nothing" does not hold for a transmitter's own cell.

## 6. Where it runs

`jobs/gaps.py` is registered as its own `Task` in `jobs/scheduler.py` and
runs every `GAPS_INTERVAL_MINUTES`, 30 by default.

**Its own clock is correct for this job and would be wrong for the next
one.** The scheduler runs tasks with `asyncio.gather`, so tasks run
beside each other, and only calibration and coverage share one clock in
`_coverage_cycle`. This job runs **no engine**: it is SQL and a few
thousand dictionary operations, so it cannot take a core from a coverage
build. It also wants to be fresher than a six hour coverage run.

**The engine work of the area half is the opposite case and must join
`_coverage_cycle`.** A task registered beside the others is free to start
during a coverage build, and on a three core box that is the last core.

To run one by hand:

```bash
sonoran-gaps-once
```

## 7. Where it appears

`#gaps`, "Coverage gaps", its own page. In reading order: one sentence,
the counts, the map, the table, the unknown bucket, and the limits list.

`gaps.js` loads **before** `app.js`. `app.js` runs the router as its last
act, and a reload straight onto `#gaps` would otherwise fall back to the
dashboard. See `AGENTS.md` 9.14.2.

Two things on that page are not negotiable and are pinned by tests:

- **The unknown bucket is its own section**, with its own count and its
  own explanation, and not a filter somebody has to find. A node with no
  `bad` signal and at least one `unknown` is listed as unmeasured, never
  as healthy.
- **The limits list is permanently visible.** It holds what the feature
  cannot answer at all, in plain words.

No line is drawn between two nodes anywhere on the page, because no
signal on it names both ends of one link. A node whose position is coarse
or missing is not drawn on the map at all — a marker is a claim about
where something is — and the page says how many it left off and why.

**Nothing about this feature reaches the public embed.** There is no route
under `/api/embed` and no layer on `/embed/coverage`. A list of weak nodes
with positions is a list of houses with a reason to visit them.

## 8. Every default is a starting point

**None of these thresholds has been measured on live data.** Design
section 11.1 names the six measurements to take first, and until they are
taken these are guesses that happen to work on the seed:

| Setting | Default |
|---|---|
| `GAPS_WINDOW_HOURS` | 168 |
| `GAPS_MIN_PACKETS` | 20 |
| `GAPS_MIN_ACTIVE_HOURS` | 12 |
| `GAPS_RF_RATIO_BAD` | 0.5 |
| `GAPS_MARGIN_BAD_DB` | 5.0 |
| `GAPS_MIN_NEIGHBOUR_REPORTS` | 2 |
| `GAPS_MOBILE_SPREAD_KM` | 1.0 |

The measurements that matter most: how many nodes are gateways at all
(4.1 applies to nobody else), how sparse `neighbor_metrics` is (4.2 and
4.5 rest on it), and how many nodes each signal flags. **If a signal
flags 300 nodes it is not a finding, it is a definition problem.**

There is no alerting, and there must not be until those numbers exist.
This is a report, not a monitor, and an unvalidated signal wired to a
notification is a false alarm generator.

## 9. What is not built

The area half: demand points, clustering, terrain candidate generation,
the terrain screen, and SPLAT confirmation. Design sections 6, and phases
2 and 3.

`single_path_hop`, the traceroute signal of design 4.7, is phase 2. It
would be `unknown` for almost every node today, because traceroutes are
user initiated and sparse.

`GET /api/gaps/nodes/{node_id}` and the "Connection health" panel on the
node page are phase 1b.
