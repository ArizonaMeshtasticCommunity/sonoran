# Coverage gaps: which nodes the mesh is not carrying well

**State: both halves are built.** Section 4 is the per node half, which
measures. Section 10 is the siting half, which predicts.
`docs/design/coverage-gaps.md` is the whole design; this document
describes what runs.

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

**One gateway that is close to the node is `ok`.** The common false
positive was a repeater on a roof and a client inside the house. The
repeater is the one gateway that hears the client, and that is the setup
working as intended.

The test is the median RSSI of the direct observations:

```
ok when direct_gateways == 1
    and direct_rssi_readings >= GAPS_SOLE_GATEWAY_MIN_READINGS   (5)
    and direct_rssi_dbm      >= GAPS_SOLE_GATEWAY_CLOSE_RSSI_DBM (-60)
```

It is RSSI because a strong signal bounds the distance. At 915 MHz, a
path loss of 90 dB is about 0.8 km in free space. So -60 dBm from the
30 dBm the US band allows means about a kilometre with plain antennas,
and a few kilometres with high gain ones. SNR cannot do this: it tops
out near +11 dB on any strong link. Positions cannot do it either:
most nodes round theirs to 13 bits, about 2.9 km, so two nodes on one
roof often read "0 m" and a pair heard at -48 dBm read 49.5 km apart.

Measured on the live mesh (2026-09-21, 7 day window, 152 flagged nodes):

| | median RSSI | SNR |
|---|---|---|
| pairs with precise positions under 1 km | -1 to -58 dBm | +6 to +13 dB, spread under 1 dB |
| single links that really are marginal | -90 to -128 dBm | mostly below 0 dB |

The line sits in the gap between the two groups. It reads no names and
makes no guess about who owns what. The sentence states the reading and
says what it means.

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

### 6.1 The leaderboard windows (#294)

Two leaderboards on the Statistics page rank nodes from this job's
evidence: "Most reliably answers traceroutes" (6.2) and "Heard directly
by the most gateways". The page has a range control with 24 h, 7 d and 30 d. Will
chose on 2026-10-08 that these two boards follow it (option A).

**What the job writes.** The assessment holds `GAPS_WINDOW_HOURS`, which
is 7 d by default, and it is the board for that window. For each other
quick range the job writes one more run for each preset (#351): a
`gaps_run` row with `scope` `board` and `asked_hours` set to the range,
and its `gaps_node` and `gaps_trace_answer` rows. See
`docs/DATABASE.md` 5B.

`asked_hours` is the range as the page names it: 24 or 720 by default.
The run holds `preset`, `channels`, `window_hours`, `generated_at`, the
node rows and the traceroute counts. Each node row holds `node_id`, `display_name`,
`packets` and `direct_gateways`, with the names the assessment rows
use. `trace_answers` is described in 6.2, and the assessment holds the
same key for its own window. The node rows of the assessment do not
change, so the gaps page and the node page read it as before.
`/api/gaps` does not serve `trace_answers`.

**What it does not compute.** No signals, no siting, no neighbour or
position reads, and not the full traceroute read. A board needs none of
them. `signals.read_reach_evidence` makes only the two reads that hold
the counts, and they are the same reads the assessment makes
(`_packet_summary` and `_read_direct_gateways`), not copies.
`signals.read_trace_answers` is the third read, and the assessment
makes it too.

**What it costs.** For each preset and window that is due, two aggregate
reads over `packet`, `packet_seen` and `mesh_packet_metrics`, and the
traceroute read of 6.2. A 30 d
window that is longer than the assessment also reads its own channel
names, once for all presets. The cost of these reads grows with the
rows in the window, so against the 7 d assessment:

| Window | Rows against 7 d | Rebuilt | Share of a run, on average |
|--------|-----------------:|---------|---------------------------:|
| 24 h | about 1/7 | every run | about 0.14 of the two reads |
| 30 d | about 4.3 | every 6 hours | about 0.36 of the two reads |

A file is rebuilt when it is older than 1/120 of its window
(`REFRESH_SHARE` in `gaps/boards.py`): 12 minutes for 24 h, which is
every 30 minute run, and 6 hours for 30 d. So a 30 d board is at most
about 1 percent of its window old. The run that rebuilds the 30 d file
is the expensive one: about 4.3 times the two reads. These figures are
reasoned from row counts, not measured. The job logs the time of each
board file, as `gaps boards, preset ...: N nodes over H hours in S s`,
so read that line on the live box before you trust them. This job is
on its own clock and runs no engine, so it does not join the coverage
cycle. It still shares three cores with ingest, the API and a coverage
build.

**What 30 d can mean.** The boards read `packet` and `packet_seen`, which
are kept for `RETENTION_DAYS_PACKET` days, 30 by default. TimescaleDB
drops a whole chunk only when all of it is older than that, so at the
default the full 30 days are there. `mesh_packet_metrics` is kept for
90 days. A window is cut to packet retention: with 14 days kept, the
30 d file holds 336 hours and says so, and the board says "not the page
range". Counting deleted hours would rank a node as silent in hours
that are simply gone.

**What a custom range does.** A from/to range is a fixed period, and no
job can know in advance which periods a reader will ask for. The two
boards then show the assessment's own window and say "not the page
range". They never show a near window as if it were the range. The same
happens for any `hours` that is not a quick range, and before the job
has written a window's file, for example just after a deploy: an older
deployment's files still serve.

**A file without traceroute counts is rebuilt at once.** A board file
written before #293 has no `trace_answers`. `boards.is_due` treats it as
due, so the 30 d file does not go on serving "not counted yet" for six
hours after a deploy.

**One function.** `_reachable_board` in `api/routes/leaderboards.py` is
the whole of what the reachable board measures, for every window: the
floor, the order and the words. The job writes the counts and nothing
else.

### 6.2 Reachability: answered traceroutes (#293)

"Most consistently reachable" used to rank the share of the hours a
node was awake in which a gateway heard it. Will said that this is
uptime, and he decided on 2026-10-08 to replace it. It
was one way only: it said that a gateway heard the node, and nothing
about whether traffic sent **to** the node arrived. A node beside any
gateway scored 100 percent by sending one packet an hour, and ties were
then broken by hours awake.

The board is now "Most reliably answers traceroutes". It ranks the
share of traceroutes sent to a node that it answered. A traceroute
request and its reply are the only round trip this database can prove.

**How a request is matched to its answer.** A request has `request_id`
NULL and its own `packet_id`. A reply carries the request's `packet_id`
in `request_id` (`AGENTS.md` 9.8), and it travels back, so its `from` is
the node that was asked (9.18). `traces.answer_counts` reads every row
through `trace_endpoints`, so a request and its answer give the same
key: (asker, target, request packet ID). The asker is in the key
because a packet ID belongs to its sender.

- A request or a reply seen more than once counts once.
- A reply whose request was never seen counts in neither number.
- A reply from a node that was not asked does not count.
- A self-trace is ignored. A sender is a distinct `from_node_num` of a
  request, and it must not be the target.
- A traceroute to the broadcast address names no target.

**Unanswered as far as we can tell.** Only what a gateway uploaded is in
the database (9.5.1). A node can answer and no gateway hear the answer.
The board says this in its hint, in those words.

**The window.** The board follows the page range, like the direct
board (6.1). A request counts when we received it inside the window, on
our clock (9.4), and on this preset, by `traceroute.channel` (9.7). The
last 15 minutes are left out (`ANSWER_GRACE` in `gaps/signals.py`),
because an answer to a request sent a moment ago may still be on the
way. A reply counts when it was received before the end of the window.
It is matched to its request, so it is not filtered by channel again.

**The floor.** A node needs at least 10 traceroutes from at least 2
senders (`MIN_TRACES`, `MIN_SENDERS`). Below ten, one lost answer moves
the share by more than ten points. One sender is one vantage point, and
its own path to the node would decide the whole score. A node below the
floor is not ranked, and the board says how many were left out. A node
that nobody traceroutes is not on the board at all, and is not counted
as left out.

**The order.** By the low end of the Wilson 95 percent interval, then
the share, then the number of traceroutes. So 95 of 100 ranks above
10 of 10: the second is the better share and the weaker evidence. The
value shown is the plain share, with "N of M answered, S senders".

**What the job writes.** `trace_answers` in the assessment and in each
board file: one row for every node traced, below the floor or not, with
`node_id`, `display_name`, `requests`, `answered` and `senders`. The
floor is the route's, so it can count what it left out. These rows are
not node rows: a node can be traced on a preset and send nothing else
on it.

**What it costs.** One statement for each preset and window. It reads
the distinct requests in the window through
`ix_traceroute_channel_time`, and only the replies that join to one of
them. The assessment already reads every traceroute row of its window
as a whole ORM object for the trace signal, so this read is the smaller
of the two. 9.19 gives about two thousand traceroutes a day, so a 30 d
window holds about 60 000 rows, and it is read once in six hours.
Reasoned, not measured: the `gaps boards` log line times the whole
board file, this read included.

**What it cannot know.**

- An answer that no gateway uploaded counts as unanswered.
- People and automations choose which nodes they trace, so the sample
  is not random.
- A gateway uploads its own traffic, so traceroutes sent by gateways are
  always seen. The sample leans towards gateway senders.
- The route between sender and node counts as much as the node does.
  The two-sender floor limits that, and does not remove it.

**Not done here.** The share of `want_ack` messages that were
acknowledged is closer to "packets that got through". It needs the
acknowledged packet's ID, which is `Data.request_id` on a routing
packet, and ingest stores that for traceroutes only. That needs a
schema change. It is a separate piece of work.

## 7. Where it appears

`#gaps`, its own page. The nav entry says "Gaps" and the heading says
"Coverage gaps": the nav is a column of short nouns, and three entries
that all began with "Coverage" made it unreadable. The coverage map is
"Coverage" and the coverage planner is "Planner" for the same reason.
The fragment is unchanged.

In reading order: one sentence, the counts, the map, the table, the
unknown bucket, and the limits list.

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

`single_path_hop`, the traceroute signal of design 4.7. It would be
`unknown` for almost every node today, because traceroutes are user
initiated and sparse.

`GET /api/gaps/nodes/{node_id}` and the "Connection health" panel on the
node page, which is design phase 1b.

The planner permalink of `docs/ISSUES.md` 2.6. Every candidate should
carry an "open in the planner" link with its position, power and height
filled in. It is the cheapest real handoff this feature could have and
it is the natural next thing to build.

## 10. The siting half: where one new node would help

Section 4 measures. **This section predicts, and the page never draws
the two in the same colour.** It answers the other half of the question
the owner asked: where would a 1 W node bring the most struggling nodes
into usable coverage?

| Module | Decides |
|---|---|
| `gaps/siting.py` | Demand, clusters, candidates, and the terrain screen. |
| `jobs/gaps_siting.py` | Running the engine on the top few, and the counts. |
| `api/routes/gaps.py` | Serving `/api/gaps/areas` and `/api/gaps/candidates`. |
| `web/static/siting.js` | Drawing it. It paraphrases no finding. |

It reads no database at all. The demand is the per node assessment the
gaps job already wrote, the baseline is `coverage-at-nodes.json` from
the last coverage run, and everything else is terrain out of the cache.

### 10.1 The demand, and what it is not

The demand set for one preset is the nodes with a fault we can measure,
leaving out three kinds:

- a node with no exact position, because a position accurate to
  kilometres cannot choose a hilltop,
- a **mobile** node, because a footprint drawn to serve a node that
  moves serves nobody tomorrow,
- a node that is already fine, which is inside the predicted usable map
  **and** heard on the air **and** with margin on its best measured
  link.

Then the survivors are snapped to a `GAPS_DEMAND_CELL_M` grid and one
demand point is kept for each occupied cell, carrying its nodes. **Five
radios in one house must not outvote a ranch five miles out**, and
without that a single address decides where the mesh builds next.

**The bias to say out loud, and the page does say it.** The demand set
can only hold people who already own a node and got it partly working.
It cannot see the valley with nobody in it, or the neighbourhood where
three people gave up. A siting tool built on it will always favour
places that already half work.

### 10.2 Areas

Single linkage at `GAPS_CLUSTER_LINK_KM`, over the demand points, with
numpy and no new dependency. A valley of struggling nodes is a chain and
not a ball, which is what single linkage is for.

A group of fewer than `GAPS_MIN_CLUSTER` points is dropped. **It is not
an area; it is a node, and `/api/gaps/nodes` already holds it.** The
areas are reported worst first, by how many nodes they hold, and capped
at `GAPS_MAX_CLUSTERS` so that the engine budget below is bounded.

### 10.3 Candidates, in two kinds

**Kind A, a node that is already there.** Every node inside the area
with an exact position, read with the candidate radio instead of its
own: "if the node at this address went to 1 W on a 9 m mast". No new
site, no land, no permission, and it wins a tie against new ground for
exactly that reason.

**Kind B, a place on the ground.** From terrain, and never from a site
database, because there is no site database. The area's box is grown by
`GAPS_SEARCH_RADIUS_KM` and the cells that are the highest of a window
about a kilometre across, and stand `GAPS_MIN_PROMINENCE_M` above the
median of that window, are taken. The highest cell of a flat plain is
still the highest cell and is not a site, which is what the prominence
test is for. The list is thinned to `GAPS_CANDIDATE_SPACING_KM` and
capped at `GAPS_CANDIDATES_PER_CLUSTER`, so one ridge cannot fill every
slot with sixty cells of itself.

**There is no candidate grid.** A 5 km grid over the Arizona region is
about 27,000 candidates, which at the measured cost of the engine is
roughly six core-days.

**The candidate radio is an assumption and the page prints all four
numbers**: `GAPS_CANDIDATE_TX_POWER_DBM`, the stock antenna gain, the
stock cable loss, and `GAPS_CANDIDATE_HEIGHT_M`. A reader who wants a
different mast opens the planner.

### 10.4 The terrain screen, which may not say no by mistake

Running the engine on every candidate is not affordable, so they are
screened with a cheap model first. The screen has **one rule**: it may
pass a candidate the engine then rejects, and it may never reject one
the engine would have liked. A pre-filter with false negatives throws
the answer away in silence, and nothing downstream can get it back.

So it charges four things and nothing else: free space loss, the
`coverage/clutter.py` terminal correction at both ends, **one** knife
edge for the worst obstruction, and no more. The earth is curved under
the path at the usual 4/3 radius, because a flat earth would hide every
obstruction on a long path. The two directions are compared separately
and the weaker one decides, for this one candidate, before anything is
combined: `AGENTS.md` 9.24 applies here for the same reason it applies
to the map.

A candidate is scored by how many demand points it would **newly**
reach: the places the published run already covers are left out,
because the question is what a new node would add.

**What the screen does and does not separate, measured.** Over 3.3 km,
a planted kilometre of rock takes about fifty decibels off the margin,
which is the discrimination the ranking runs on. It does **not** close
the link: a 1 W node on Long fast has sixty decibels to spend over a
short path, and a single knife edge is a famously optimistic model. The
same wall over 22 km does close it. That is the screen behaving as
designed rather than a fault, and
`test_the_screen_rejects_a_path_a_ridge_really_does_close` pins both
halves of it.

**On open ground the screen separates almost nothing**, because a 1 W
node with line of sight reaches a handheld at these ranges from
wherever it stands. Sixty rows that all reach the same five places is a
ranking with a long flat head, not sixty answers, so the page shows the
rows the engine predicted and the head of the ranking, and opens the
rest in place.

### 10.5 The engine, on the top few only

The top `GAPS_SPLAT_PER_CLUSTER` of each area, capped at
`GAPS_MAX_PREDICTIONS` over the whole run, are predicted with the real
engine through `jobs/coverage.py::predict_sites`. That function holds
every engine rule in one place: one instance for a process, spawn and
never fork, closed in a `finally`, and niced.

**Each candidate is scored by sampling its own raster at the demand
points.** A region grid of Arizona is 88 MB and the question is a few
dozen point lookups, so no region grid is built and no candidate
footprint ever joins the published map. The radius is
`GAPS_CANDIDATE_RADIUS_KM`, 25 km, and not the 60 km the coverage map
uses: a 1 W node at 9 m talking to a 1.5 m handheld does not reach
60 km and the cost grows with the square of the radius.

A candidate the engine refused is `unknown` and never "no benefit".

### 10.6 The three states, again

| State | Means |
|---|---|
| `ok` | It was judged, and it would bring somebody in. |
| `bad` | It was judged, and it would bring nobody in. |
| `unknown` | It was **not** judged: the ground under it, or under every path from it, is terrain we do not hold. |

**`newly_usable` is `null` when the state is `unknown`, and never
zero.** "We did not judge it" and "it would help nobody" are different
answers and the page draws them differently: a dashed pin and an em
dash for the first, a solid count for the second.

### 10.7 What one run costs

Measured on the development mesh, at the shipped defaults, with
`GAPS_WORKERS=1`:

| | |
|---|---|
| Areas | 1 |
| Candidates screened | 49 |
| Engine predictions | 3, of a ceiling of 24 |
| Engine time | 4.7 s, which is 1.6 core-seconds a prediction at 25 km |
| Whole job, both presets, wall | 5.8 s |
| Peak resident set | 118 MB |

The design's budget came off the coverage run in `docs/COVERAGE.md` 9.1:
18.4 core-seconds a site at 60 km, which scales by the square of the
radius to about 3.2 at 25 km, so 24 predictions is about 77
core-seconds. This machine is faster than the box that figure came from
and measures 1.6. **Use the larger figure for a deployment**: either
way the ceiling is under two minutes on one niced worker, against a
coverage interval of six hours.

Everything before the engine is arithmetic. The clustering is a
distance matrix over a few hundred points and the screen is numpy over
cached terrain pages.

### 10.8 Where it runs, and why it is not its own task

**Inside `_coverage_cycle`, after `coverage.run_once`, and never as a
peer `Task`.**

The scheduler runs tasks with `asyncio.gather`, so a task registered
beside the others runs on its own clock and is free to start during a
coverage build. This job uses the engine, and the engine has no IO to
yield on: a worker holds its core until it finishes. On a three core
box that also serves a public dashboard and takes MQTT, that is the
last core.

The per node job of section 6 is the opposite case and correctly keeps
its own clock, because it is only SQL.

To run one by hand:

```bash
sonoran-gaps-siting-once
```

It needs a gap assessment to site against and reads the last published
coverage run for its baseline. Both missing is a working state and the
page says which.

### 10.9 What this half cannot know

These are served by the API with every answer and shown permanently on
the page. They are not a disclaimer. Each one is a fact about a real
site that terrain cannot hold, and **a recommendation that does not
carry them is a lie of omission**.

- Whether anybody owns the ground, can reach it, or may put anything on
  it.
- Whether there is power, a roof, a pole, a road, or an internet link.
- Whether a building stands between the site and a street. Clutter is a
  correction at each end of a path, not a model of what is on the
  ground. See `docs/COVERAGE.md` 11.3.
- Whether the person at the other end wants a node on their roof.
- Anybody who has no node yet. See 10.1.
- Whether the prediction is right. It runs on nameplate radio figures,
  because the measured calibration was rejected as too far out to
  apply. See `AGENTS.md` 9.21.

The tool names terrain. A human names a site.

### 10.10 Seeing it in a preview

`tools/dev/seed.py` puts five MQTT-only gateways in the valley east of
the White Tank Mountains. They are one area, and the terrain around
them is real: the ridge six to eight kilometres west of them stands
about 780 m above the valley floor and comes back as a candidate.

Two struggling nodes fifty kilometres apart are two nodes, which is
what the seed held before, and the page then correctly answered "no
area". That is a true answer and not the one worth looking at.

The siting half needs terrain, so fill the cache first, and it needs a
coverage run for its baseline:

```bash
uv run python tools/prefetch_terrain.py --lat 33 --lon -113
uv run python tools/prefetch_terrain.py --lat 33 --lon -112
uv run sonoran-coverage-once
uv run sonoran-gaps-once
uv run sonoran-gaps-siting-once
```

With no terrain at all every candidate reads `unknown`, which is the
honest answer and is worth seeing too.
