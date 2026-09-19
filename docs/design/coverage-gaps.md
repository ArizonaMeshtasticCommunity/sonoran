# Coverage gaps: which nodes need help, and where a new node would help

**State:** design only. Nothing here is built.

This document answers one request: show the nodes that are not
connected well, and show the places where one new node would help the
most people.

Read `AGENTS.md` section 9 before you build any of it. Section 9.5,
9.5.1, 9.7, 9.20, 9.22, 9.24 and 9.25 each forbid an obvious version of
this feature. The traps are named in place below.

---

## 1. What it answers, and what it must never claim

Two questions, one subject.

1. **Per node.** Which nodes are struggling, and in what way? The
   answer is a short list with the evidence beside each item.
2. **Per area.** Where would one new well sited node bring the most
   struggling nodes into usable coverage? The answer is a small set of
   places, each with a number of nodes it would serve.

The second question is a prediction. The first is a measurement. They
must never be drawn in the same colour.

There is a third thing the feature must do, because the data forces it:
say plainly when it does not know. A node that reports nothing is
usually a node that is switched off. It is not a node in trouble. Every
signal in this design has three states, and the third one is
`unknown`. **`unknown` must never render as zero, as green, or as an
empty cell that reads like "fine".**

---

## 2. What this database can and cannot see

This section is the foundation. Every signal below is built from it.

### 2.1 The observer set is MQTT gateways, and nothing else

`packet_seen` records MQTT uploads. The only observers this database
can ever hold are gateways. Every other node on the mesh hears plenty
and reports none of it. See `AGENTS.md` 9.5.1.

So "nobody heard this node" always means "no gateway heard it". Say
that, in those words, on the page.

### 2.2 A packet reaches this database by exactly one of two routes

This is the single most useful fact in the whole design.

A packet of node N is in the database because:

- **N uploaded it.** N is an MQTT gateway and uploaded its own traffic.
  A row where `packet_seen.gateway_node_num = packet_seen.from_node_num`
  is that. It proves nothing at all about radio.
- **Another node heard it and a gateway uploaded it.** A row where
  `gateway_node_num <> from_node_num` is that. Whether the gateway
  heard N directly or after relays, some radio received N's
  transmission.

That gives a positive radio signal that costs nothing and claims no
link: **an upload by a different node is evidence that the mesh heard
N over the air.** It does not say who heard N, and it must never be
drawn as a line. `AGENTS.md` 9.20 is clear that an ordinary packet
carries nothing about the ground it crossed.

It also gives the negative: a node whose every upload is its own upload
was not heard by any gateway, directly or through any number of relays.
That is the MQTT-only case, and section 4.1 builds it.

**One hole to close.** A gateway can rebroadcast MQTT traffic onto the
air. If a third gateway then heard that copy and uploaded it, the
second upload would be evidence for a radio path that N never used.
The firmware marks a packet it took from MQTT, and `via_mqtt` is
stored, so the copy should never be uploaded again. That is an
assertion about firmware behaviour, and this project does not assert
what the vendor did not state. Before shipping section 4.1, do two
things:

1. Quote the `via_mqtt` and `TransportMechanism` field comments from
   `meshtastic/mesh.proto` at the revision in `proto/UPSTREAM_REV.txt`
   into `sonoran/gaps/signals.py`. The vendored `proto/` directory
   holds only `UPSTREAM_REV.txt` and `update.sh`, so the text is not in
   this repository yet.
2. Measure it. Section 11.1 gives the query.

Until both are done, treat a `via_mqtt` packet as no evidence either
way, which is what section 4.1 does.

### 2.3 `via_mqtt` exists for the first uploader only

`ingest/pipeline.py` calls `store_mesh_packet_metrics` inside
`if stored.is_new:`. So `mesh_packet_metrics` holds one row for each
unique packet, carrying the view of **whichever gateway uploaded it
first**. `via_mqtt`, `relay_node_num`, `next_hop_node_num` and
`transport_mechanism` are all that gateway's, not every gateway's.

Do not write a query that reads `via_mqtt` per observation. There is no
such column.

`packet.hop_start` is safe to use across observations, because the
sender sets it and it does not change in flight. `packet.hop_limit` is
the first uploader's remaining count and varies between uploads, which
is why the direct test uses `packet_seen.hop_limit`. That is the rule
`_heard_by` in `api/routes/nodes.py` already follows.

### 2.4 The evidence ladder

Ranked from strongest to weakest. A signal must say which rung it
stands on.

| Rung | Evidence | What it proves |
|---|---|---|
| 1 | `neighbor_metrics` row | Node A's receiver closed a link from node B. Measured SNR. |
| 2 | Traceroute hop, read through `api/traces.py` | A hop happened, sometimes with a measured SNR. A real path. |
| 3 | Direct observation: `packet_seen.hop_limit = packet.hop_start` and `gateway_node_num <> from_node_num` | That gateway's receiver closed a link from the sender. Measured SNR. |
| 4 | Any observation by a different node | Some radio heard the sender. No link, no SNR. |
| 5 | Self upload: `gateway_node_num = from_node_num` | The node is alive and has an internet path. Nothing about radio. |
| 6 | Silence | Nothing. Not a fault, not a pass. |

Rung 3 is what `_heard_by` already computes. Reuse it rather than write
the join again.

### 2.5 What the data cannot answer

Say these out loud on the page. Do not invent a proxy.

- **"Can this node hear the mesh?"** Not answerable for most nodes. A
  receiver leaves no trace. The exceptions are a node that publishes
  `neighbor_metrics` rows, which proves its receiver works, and a
  non-gateway node that answered a traceroute, which proves it received
  the request over the air. Everything else is `unknown`, for ever.
- **"Which node relayed this packet?"** Not answerable.
  `mesh_packet_metrics.relay_node_num` is one byte, and only 5.4
  percent of relay observations resolve to a single node. See
  `AGENTS.md` 9.20.
- **"Did this link stop working?"** A neighbour list is a node's own
  neighbour table. It decays slowly and can be truncated to fit a
  packet. Absence from a list is not proof of silence. This is the same
  unproven assumption that holds the calibration back: see
  `docs/ISSUES.md` 2.4.1 and `AGENTS.md` 9.21. Do not build link
  stability on it.
- **"Where do people live who have no node yet?"** Not answerable. The
  demand set is biased towards people who already bought a radio and
  got it partly working. Section 6.1 repeats the warning where it
  matters.

---

## 3. One preset at a time, always

A node on Long fast cannot hear a node on Medium fast. Every signal,
every cluster, every candidate score is keyed on one modem preset. See
`AGENTS.md` 9.7.

A node belongs to a preset when it sent traffic seen on it, which is
the rule `/api/graph/channels` and `/api/map/nodes` already use. A node
that is active on two presets gets two independent assessments and
appears twice. Live data had 14 such nodes against 709.

A channel that is not a default preset name, such as Weather or PKI,
rides on top of a preset and does not name one.
`preset_for_channel` returns `None` for those, and such traffic is left
out of the assessment rather than guessed at.

There is no "every preset" view of this feature. A merged answer would
invite a reader to fix a gap between two radios that cannot hear each
other.

---

## 4. The per node signals

Each signal is a small function with one job. All of them live in
`sonoran/gaps/signals.py`, which is the only module that decides what a
signal means. That is the arrangement `positions.py`, `roles.py` and
`api/traces.py` already use.

The window `W` defaults to `coverage_active_hours`, which is 168 hours.
Retention is 30 days, so `W` may never exceed that. Every window is
bounded at `now()`, because a node clock can be nearly 28 hours ahead
and `docs/ISSUES.md` 1.5 says some historical rows still carry one. All
windows use our clock: `packet.first_seen_at`, `packet_seen.seen_at`,
`neighbor_metrics.time`. Never `packet.rx_time`. See `AGENTS.md` 9.3
and 9.4.

**Count distinct packets, never rows.** One live packet had 22 uploads
from 15 gateways, and about 8,200 duplicate `packet` rows survive from
before revision 0009 (`docs/ISSUES.md` 1.1). Every count groups by
(`from_node_num`, `packet_id`) first.

The SQL below is written as SQL to be read. The implementation uses the
ORM, as `AGENTS.md` section 7 requires.

### 4.0 The base table: one row per packet, with its evidence

```sql
WITH keys AS (
    SELECT p.from_node_num,
           p.packet_id,
           max(p.hop_start)      AS hop_start,
           min(p.first_seen_at)  AS first_seen_at
    FROM packet p
    WHERE p.channel = :channel
      AND p.first_seen_at >= :since
      AND p.first_seen_at <  now()
    GROUP BY 1, 2
),
obs AS (
    SELECT k.from_node_num,
           k.packet_id,
           k.first_seen_at,
           bool_or(s.gateway_node_num <> s.from_node_num)      AS heard_by_other,
           bool_or(s.gateway_node_num <> s.from_node_num
                   AND s.hop_limit = k.hop_start)              AS direct_by_other,
           count(DISTINCT s.gateway_node_num) FILTER (
               WHERE s.gateway_node_num <> s.from_node_num
                 AND s.hop_limit = k.hop_start)                AS direct_gateways,
           max(s.rx_snr) FILTER (
               WHERE s.gateway_node_num <> s.from_node_num
                 AND s.hop_limit = k.hop_start)                AS best_direct_snr
    FROM keys k
    JOIN packet_seen s
      ON  s.from_node_num = k.from_node_num
      AND s.packet_id     = k.packet_id
      AND s.seen_at      >= :since
    GROUP BY 1, 2, 3
),
evidence AS (
    SELECT o.*,
           coalesce(m.via_mqtt, false) AS first_upload_via_mqtt,
           (o.heard_by_other AND NOT coalesce(m.via_mqtt, false)) AS rf_evidenced
    FROM obs o
    LEFT JOIN mesh_packet_metrics m
      ON  m.from_node_num = o.from_node_num
      AND m.packet_id     = o.packet_id
      AND m.time         >= :since
)
```

Every signal below reads `evidence`. Three columns carry the whole
design: `rf_evidenced` is rung 4, `direct_by_other` is rung 3, and
`best_direct_snr` is the only SNR in this query that belongs to a real
link.

`direct_gateways` counts gateways, not rows, because 22 uploads from 15
gateways is one packet heard by 15 gateways.

### 4.1 `radio_isolated` — present through MQTT, not heard on the air

**Definition.** Over `W`, on preset `P`, node N:

- has at least `GAPS_MIN_PACKETS` distinct packets (default 20), and
- appears as `packet_seen.gateway_node_num` at least once, so it has an
  MQTT path of its own, and
- has zero packets with `rf_evidenced = true`, and
- is named by zero `neighbor_metrics` rows as
  `neighbor_node_num` on preset `P` in `W`, and
- appears in zero evidenced traceroute hops on preset `P` in `W`, read
  through `api/traces.py`.

Then the state is `bad`, and the phrase for the page is: **"No gateway
on this mesh has heard it over the air. Its traffic reaches us through
its own internet link."**

**State `ok`** when at least one packet is `rf_evidenced`.

**State `unknown`** when the packet count is below the floor, or when
every packet is ambiguous. Ambiguous means `heard_by_other` is true but
`first_upload_via_mqtt` is also true, so section 2.2's open hole
applies. Give the count of ambiguous packets in the evidence object.

**A node that is not a gateway can never be `radio_isolated`, and the
signal must return `ok` with the reason "not an MQTT gateway".** Its
packets reached us only because a radio heard them. This is section 2.2
read backwards, and it removes most of the mesh from the signal at no
cost.

**False positives and how they are avoided.**

| Trap | Avoided by |
|---|---|
| A relayed observation read as a direct link (`AGENTS.md` 9.5) | The signal never uses SNR and never names an observer. Rung 4 only. |
| The sender's own upload counted as a listener (`AGENTS.md` 9.5.1) | `gateway_node_num <> from_node_num` on every branch. |
| A healthy node deep in the mesh with no nearby gateway | Not possible. Its packets could not be here unless a gateway got them by some path, and that path makes `heard_by_other` true. |
| An MQTT gateway rebroadcasting MQTT traffic onto the air | `first_upload_via_mqtt` removes the packet from the evidence. Verify with section 11.1 before trusting it. |
| A node uploading under a topic that is not a preset | Preset filter, section 3. |
| A quiet node | The packet floor, and `unknown` below it. |

**How strong the claim is.** It scales with how many gateways the mesh
has. Report the number in the evidence object: `gateways_active` is the
count of distinct `packet_seen.gateway_node_num` on preset `P` in `W`.
The page then says "none of the 31 gateways active this week heard it",
which is a fact, rather than "it is isolated", which is a judgement.

### 4.2 `hears_but_is_not_heard` — the one honest asymmetry

**Definition.** N satisfies `radio_isolated`, **and** N published at
least `GAPS_MIN_NEIGHBOUR_REPORTS` (default 2) `neighbor_metrics` rows
as `node_num` on preset `P` in `W`, with at least one non-null `snr`.

Then N's receiver demonstrably works and its transmissions
demonstrably reach no gateway. That is the case the owner described,
and it is the strongest single finding this feature can produce: a bad
antenna, a bad cable, a wrong region setting, or a transmit power of
zero.

State `bad` only in that exact combination. Otherwise `unknown`, never
`ok`: the absence of neighbour reports is almost always the
NeighborInfo module being off.

### 4.3 `rf_intermittent` — sometimes gets out over the air, sometimes not

Link stability is not measurable (section 2.5). This measures something
that is.

**Definition.** Bucket `W` into hours on our clock. For each hour that
holds at least one distinct packet of N, mark the hour `rf` when at
least one of that hour's packets is `rf_evidenced`.

```
active_hours = hours with >= 1 packet
rf_hours     = active hours with >= 1 rf_evidenced packet
rf_hour_ratio = rf_hours / active_hours
```

- `unknown` when `active_hours < GAPS_MIN_ACTIVE_HOURS` (default 12).
- `bad` when `rf_hour_ratio < GAPS_RF_RATIO_BAD` (default 0.5).
- `ok` otherwise.

Read it as: "in half the hours it was awake, nothing on the air heard
it." That is an unstable connection to the mesh, stated in terms of
evidence rather than in terms of a link nobody measured.

**Traps.** Do not use the ratio of packets, because one chatty hour
would dominate. Do not call a node with a low ratio "intermittent" if
`active_hours` is small; the floor handles that. Do not compare nodes
with different broadcast intervals on `active_hours` alone, which is
why the signal is a ratio within the node and not a rate across nodes.

### 4.4 `sole_observer` — only one gateway has ever heard it directly

**Definition.** `direct_gateway_count` = distinct gateways with at
least one direct observation of N (rung 3) in `W`.

- `unknown` when the packet count is below `GAPS_MIN_PACKETS`.
- `bad` when `direct_gateway_count = 1`.
- `ok` when `direct_gateway_count >= 2`.
- When `direct_gateway_count = 0` this signal is `unknown`, and
  `radio_isolated` or `rf_intermittent` is the one to read instead. A
  well connected node three hops deep is directly heard by nobody, and
  that is normal.

**This is not a single point of failure.** The observer set is
gateways, so the signal says "one gateway can hear it", which is a
statement about our instrumentation as much as about the mesh. Name it
on the page exactly as it is: **"Only one gateway has ever heard this
node directly."** Do not call it redundancy, and do not draw a line to
that gateway.

### 4.5 `weak_best_link` — the best measured link has little margin

**Only measured readings.** Three sources, in this order:

1. `neighbor_metrics.snr` on preset `P` in `W`, in either direction.
2. Traceroute hop SNR, through `api/traces.py`: quarter dB, `-128`
   means not measured, and a hop past the end of `snr_towards` did not
   happen. See `AGENTS.md` 9.6 and 9.18.
3. `best_direct_snr` from section 4.0, which is rung 3.

**Margin.** The margin is the SNR above what the preset needs to
demodulate:

```
required_snr_db(preset) = preset.sensitivity_dbm - noise_floor_dbm(preset)
snr_margin_db           = snr - required_snr_db(preset)
```

Both terms already exist in `sonoran/radio/presets.py`. Add
`required_snr_db(preset)` there, beside `noise_floor_dbm`, so the one
preset table stays the one preset table. For Long fast the required SNR
works out near -25 dB, which is why a reported SNR of -20 dB is a
working link and not a broken one.

**Per node value.** `best_snr_margin_db` is the maximum margin over
every measured reading in `W`. The best link is the right statistic: a
node with one strong link and twenty weak ones is fine.

- `unknown` when there is no measured reading at all.
- `bad` when `best_snr_margin_db < GAPS_MARGIN_BAD_DB` (default 5).
- `ok` otherwise.

**Traps.** Never use the SNR of a relayed observation; it belongs to the
last hop (`AGENTS.md` 9.5). Never use the SNR of a self upload; it is
the node's own voice (`AGENTS.md` 9.5.1). Never mix in
`NodeFit.offset_db`: it is inferred, not reported (`AGENTS.md` 9.21),
and the live fit is currently rejected at a model bias near -41 dB, so
no correction is applied at all today.

### 4.6 `outside_predicted_usable` — the prediction does not reach it

**Definition.** Sample the current published coverage run's `usable`
layer for preset `P` and the `infrastructure` site set at the node's
position. The node is outside when the sampled level is below
`to_level(preset.sensitivity_dbm)`.

This needs a new artefact from the coverage job. Section 7 specifies
it, and it is small.

**States.**

- `unknown` when there is no published run for that preset, or the node
  has no usable position (`positions.is_usable`), or the position is
  known to be coarse. `precision_deviation_m` of 2.9 km cannot be
  placed on a 90 m grid. Report the reason
  `position_too_coarse` with the deviation, and never guess.
- `bad` when the node is outside.
- `ok` when the node is inside.

**The inverse is a finding about the map, not about the node.** A node
that is `rf_evidenced` and outside the predicted usable layer is
coverage the model missed. `tools/validate_coverage.py` measures the
same thing from outside and puts it at about 11 percent. Count those
separately, as `reached_but_unpredicted`, and show the count. It tells
a reader where the prediction is pessimistic, which matters for the
siting half in section 6.

**A diagnostic run must not feed this signal in public.** If
`Manifest.is_diagnostic` is true, the signal reads `unknown` with the
reason `diagnostic_run`, because the wider map predicts from client
nodes that move. See `AGENTS.md` 9.25 and 9.27. The gaps feature is
dashboard only in any case: see section 8.4.

### 4.7 `single_path_hop` — every known path runs through one node

**Phase 2, and rare by design.**

Only a traceroute holds the nodes a packet passed through
(`AGENTS.md` 9.20). Read every traceroute on preset `P` in `W` that
mentions N, selected by the nodes it mentions and never by recency
(`AGENTS.md` 9.19). Read it through `api/traces.py`:
`trace_endpoints` to get the request direction, `forward_path` and
`return_path` for the node lists, and `evidenced_hops` to cut the path
where the evidence stops. An unanswered request has an empty route and
evidences no link at all, which is half of all rows in live data.

Collect the set of nodes adjacent to N across every evidenced hop.

- `unknown` when there are fewer than `GAPS_MIN_TRACES` (default 3)
  evidenced traces, or fewer than 2 distinct counterparties. This will
  be the common state. Traceroutes are user initiated and sparse.
- `bad` when the adjacent set holds exactly one node.
- `ok` when it holds two or more.

When `bad`, name the node: "every path we have seen runs through
<name>". That is a true statement about the evidence and is worded as
one.

### 4.8 `mobile` — a modifier, not a fault

Compute the spread of `position_metrics` for N over `W`: the greatest
distance between any two reported positions, or the distance from the
median position to the furthest, which is cheaper. When it exceeds
`GAPS_MOBILE_SPREAD_KM` (default 1.0), mark the node `mobile`.

A mobile node is still listed per node, because a handheld that cannot
get out is a real problem for its owner. It is **excluded from the area
half**, because a footprint drawn to serve a node that moves serves
nobody tomorrow. That is the same reasoning `roles.py` uses to keep
TRACKER out of the site sets.

---

## 5. Confidence, and refusing to guess

### 5.1 Three states, and the third is loud

Every signal returns:

```json
{
  "state": "bad" | "ok" | "unknown",
  "reason": "no_gateway_heard_it",
  "value": 2.5,
  "evidence": {"packets": 412, "rf_packets": 0, "direct_gateways": 0,
               "gateways_active": 31, "ambiguous_packets": 3}
}
```

`value` is `null` unless the signal has a measured number. `reason` is
a short machine name, and the page turns it into a sentence. `evidence`
holds the counts the claim rests on, so a reader can check the claim
without opening a database.

This follows the calibration pattern in `/api/coverage/calibration`
exactly: a node with thin evidence is listed, with its counts, with
`offset_db: null` and `applied: false`. That is the precedent, and it
works.

### 5.2 No health score

There is no 0 to 100 number, and the colour of a row never comes from
a number. The row's colour comes from `worst_state`. Ranking uses, in
order:

1. `bad_count` descending.
2. A fixed severity order between signals:
   `hears_but_is_not_heard`, `radio_isolated`, `rf_intermittent`,
   `weak_best_link`, `single_path_hop`, `sole_observer`,
   `outside_predicted_usable`.
3. `packets` descending, so a node we know a lot about sorts above one
   we barely know.

A score would let two `unknown` signals and one `bad` average into
amber, and amber reads as "a bit broken" when the truth is "we cannot
tell".

### 5.3 The unknown bucket is a first class part of the answer

The summary carries three counts for every signal: `bad`, `ok`,
`unknown`. The page shows a heading such as **"Not enough evidence:
184 nodes"** with its own section, not a filter that has to be found.

A node with no `bad` signal and at least one `unknown` is not listed as
healthy. It is listed as unmeasured.

---

## 6. The area half: from weak nodes to "put one here"

### 6.1 What the demand set is, and what it is not

The demand set for one preset is the nodes with at least one `bad`
signal, excluding:

- nodes with no usable position, and nodes whose position is known to
  be coarse (they cannot be sited for),
- `mobile` nodes (section 4.8),
- nodes already inside predicted usable coverage **and** `rf_evidenced`
  and with a good margin, which is to say nodes that are fine.

Then dedupe by location. Snap each demand node to a
`GAPS_DEMAND_CELL_M` grid (default 300 m) and count one demand point
for each occupied cell, carrying the node list. Five radios in one
house must not outvote a ranch five miles out.

**The bias to state on the page.** The demand set can only hold people
who already own a node and got it partly working. It cannot see the
valley with nobody in it, or the neighbourhood where three people gave
up. A siting tool built on it will always favour places that already
half work. Say so in one sentence beside the map.

### 6.2 Clusters, which are cheap and already useful

Group demand points with a simple distance clustering:
single linkage at `GAPS_CLUSTER_LINK_KM` (default 8), implemented over
the point list with numpy, no new dependency. Keep clusters of at least
`GAPS_MIN_CLUSTER` points (default 3). A cluster of one or two is not
an area; it is a node, and the per node list already has it.

For each cluster report the point count, the node count, the bounding
box, the centroid, and the list of node IDs.

**This alone answers a good part of the request** and needs no
prediction at all. "Three neighbourhoods hold most of the struggling
nodes, and here they are" is a real answer. It ships in phase 2.

### 6.3 Candidates, in two kinds

**Kind A: upgrade a node that is already there.** Every node inside the
cluster that has a precise position is a candidate, evaluated with the
candidate radio profile instead of its own. This is the cheapest real
answer available: "if the node at this address went to 1 W on a 9 m
mast, it would bring in seven of the eleven." No new site, no land, no
permission.

**Kind B: a place on the ground.** Generated from terrain, not from a
site database, because there is no site database.

1. Take the cluster's bounding box and grow it by
   `GAPS_SEARCH_RADIUS_KM` (default 15).
2. Read the 90 m elevation for that window from the terrain pages the
   coverage job already caches, through `terrain/store.py`. Never
   re-implement the SRTM transform: `AGENTS.md` 9.13 pins it bit-exact
   and a golden test holds the hash.
3. Find local maxima: a cell that equals the maximum of a roughly 1 km
   window around it, and that stands at least
   `GAPS_MIN_PROMINENCE_M` (default 40) above the median of that
   window.
4. Thin to a minimum spacing of `GAPS_CANDIDATE_SPACING_KM`
   (default 1.5), keep the highest, and cap the count at
   `GAPS_CANDIDATES_PER_CLUSTER` (default 60).

**The candidate radio is an assumption and is named as one.** The
owner said "a 1 W node", so `GAPS_CANDIDATE_TX_POWER_DBM` defaults to
30, `GAPS_CANDIDATE_HEIGHT_M` to 9 (the "attic or roof node" that
`CLIENT_BASE` is defined for), and the antenna gain and cable loss come
from the existing default `RadioProfile` rather than from a new number.
The page prints all four values. A reader who wants a different mast
opens the planner, which is what the planner is for.

### 6.4 The pre-filter: a terrain screen that must not say no by mistake

Running SPLAT on every candidate is not affordable. Section 6.6 does
the arithmetic. So candidates are screened first with a cheap model,
and the screen has one rule: **it may pass a candidate that SPLAT
later rejects, and it may never reject a candidate that SPLAT would
have liked.** A pre-filter with false negatives silently throws away
the answer.

For each candidate and each demand point:

1. Sample the great circle profile between them from the cached terrain
   at the grid step, 1/1200 of a degree.
2. Correct for earth curvature and compute the clearance of the
   straight line above the worst obstruction.
3. Charge free space loss, plus the existing terminal clutter
   correction at both ends from `coverage/clutter.py`, plus a single
   knife edge diffraction loss for the worst obstruction and nothing
   more. One edge only, deliberately: adding more loss than that is how
   a screen starts rejecting real sites.
4. Compare against `preset.sensitivity_dbm` in both directions. The two
   directions differ by `handheld_eirp_dbm - candidate_tx_power`, which
   is the identity `coverage/sites.py` already derives. Keep the weaker
   one, per node, before anything is combined. That ordering is
   `AGENTS.md` 9.24 and it applies here for the same reason.

Score a candidate by the number of demand points it would newly serve:
predicted usable in the screen, and **not** already usable in the
published run (section 7 gives the lookup).

Cost: a 30 km profile at 90 m is about 333 samples. Sixty candidates
against forty demand points is 2,400 profiles for one cluster. In
numpy, batched over demand points, this is well under a second. Terrain
comes from the page cache that already holds 16 pages at 2.7 MB each.

**The screen is not ITM and must never be drawn on a map.** It produces
a ranking, and a ranking only.

### 6.5 SPLAT confirmation, on the top few only

Take the top `GAPS_SPLAT_PER_CLUSTER` (default 3) candidates for each
cluster and predict them with the real engine, exactly as
`jobs/coverage.py::_site_levels` does:

- One `SplatModule` and one `SplatInstance` for the process, reused for
  every candidate, closed in a `finally` (`AGENTS.md` 9.16.4, 9.16).
- Re-read every heap view after any call that can grow the heap
  (`AGENTS.md` 9.16).
- Heights in feet at the engine boundary (`AGENTS.md` 9.15), and the
  three integer arguments kept whole (`AGENTS.md` 9.16.1).
- `clutter_height_m=0.0` into the engine, with the terminal correction
  charged outside it (`AGENTS.md` 9.23).
- `combine_min(down, up)` for this one site, before anything else
  (`AGENTS.md` 9.24).
- Worker processes started with the spawn context, never fork
  (`AGENTS.md` 9.16.5).

**Score by sampling the candidate's own raster at the demand
coordinates. Never blit onto a region grid.** An Arizona region grid is
88 MB and there is no reason to build one: the answer is a few dozen
point lookups. A 25 km raster is roughly 600 by 600 cells, which is
360 KB. This is the difference between a feature that fits on the box
and one that does not.

Radius is `GAPS_CANDIDATE_RADIUS_KM` (default 25), not the 60 km the
coverage map uses. A 1 W node at 9 m talking to a 1.5 m handheld does
not reach 60 km, and cost grows with the square of the radius.

### 6.6 The compute budget, with the arithmetic shown

The measured run in `docs/COVERAGE.md` 9.1 is the baseline: 50 sites,
60 km radius, zoom 6 to 11, four cores with three workers, 307 seconds
wall, 441 MB peak.

```
307 s * 3 workers / 50 sites   = 18.4 core-seconds per site at 60 km
                                 (an upper bound: it includes tiling)
cost proportional to radius^2
18.4 * (25/60)^2               = 3.2 core-seconds per candidate at 25 km
```

Budget for one gaps run:

| | |
|---|---|
| Clusters | up to 8 |
| SPLAT predictions | 8 * 3 = 24, capped by `GAPS_MAX_PREDICTIONS` |
| Engine cost | 24 * 3.2 = 77 core-seconds |
| Tiles rendered | none |
| Extra memory | one engine instance, about 20 to 30 MB, plus the 43 MB terrain hold in that worker |
| Wall time, one niced worker | under 2 minutes |
| Against a 6 hour interval | under 0.6 percent duty of one core |

On a three core box, `GAPS_WORKERS` defaults to 1 and
`GAPS_WORKER_NICE` to 10, the same as the coverage job. The engine has
no IO to yield on, so a worker holds a core solid; niceness is what
keeps the dashboard responsive, and `docs/COVERAGE.md` 9.1 records that
somebody heard the difference on a small box.

**The scheduler detail that decides where this runs.**
`jobs/scheduler.py::service` runs tasks with `asyncio.gather`, so tasks
run **beside** each other on their own clocks. Only calibration and
coverage share one clock, in `_coverage_cycle`. A SPLAT-using gaps task
registered as its own `Task` would therefore be free to run during a
coverage build and take the box's last core.

So: the candidate prediction runs **inside the coverage cycle**, after
`coverage.run_once`, in `_coverage_cycle`. The cheap per node signals
of phase 1 may be their own `Task`, because they are only SQL.

### 6.7 What the siting half cannot know

Flag these on the page, in plain words, every time.

- Whether anybody owns, can reach, or is allowed to use the ground.
- Whether there is power, or a roof, or a pole, or a road.
- Whether there is an internet link for a gateway.
- Whether a tall building sits between the site and a street. Clutter
  is a terminal correction, not a surface model
  (`docs/COVERAGE.md` 11.3).
- Whether the person at the other end wants a node on their roof.

The tool names terrain. A human names a site. Put that sentence on the
page.

---

## 7. What the coverage job must add: the level at each node

**This is the one change to existing code that phase 1 needs, and it is
small.**

A finished run keeps no level grid. `_build_site_set` holds the region
grids in RAM, renders PNG tiles, and deletes them. Tiles are colour
ramped, saturate at `RAMP_SPAN_DB` of 60, and a tile whose coverage is
entirely below the threshold is never written at all. So the exact dBm
at a point cannot be recovered from disk after a run.

Reading it back from the tiles would give a boolean from an alpha
channel at zoom 11, which is what `tools/validate_coverage.py` does.
That is too lossy for a margin, and it would make the API read PNGs.

Instead, sample the grids while they are still in memory.

Inside `_build_site_set`, in the loop that already charges the receiver
and renders each layer, sample the level at every node the run
considered. The node list is already to hand: `select_nodes` returns
every active positioned node in region, not only the sites. Use
`Grid.holds`, `Grid.row_of` and `Grid.column_of`, which already exist.

Write one artefact for each run:

```
{coverage_cache_dir}/runs/{stamp}/coverage-at-nodes.json
```

```json
{
  "stamp": "20260918T060000Z",
  "presets": {
    "LongFast": {
      "threshold_level": 61,
      "site_sets": {
        "infrastructure": {
          "305419896": {"usable": 78, "downlink": 92, "uplink": 78}
        }
      }
    }
  }
}
```

Notes that matter:

- Sample **after** `_charge_receiver`, so the number is the number the
  map draws.
- `threshold_level` is `to_level(preset.sensitivity_dbm)`, so a reader
  needs no preset table to decide "usable".
- A level of 0 means no run reached the cell, which is
  `grid.NO_COVERAGE`. A node outside the region grid is **absent from
  the object**, and absent means unknown. It must not be written as 0.
- Node numbers are keys. No coordinates, no names. The API joins those
  from the database as every other endpoint does.
- Add `store.read_node_levels(settings)` beside `read_manifest`, and
  write the file through the same pending-then-publish path so a reader
  never sees a torn file.

Size: a few thousand nodes, two or three presets, two site sets, three
layers. Tens of kilobytes.

**A found bug, worth fixing in the same PR.**
`tools/validate_coverage.py` builds its sampler root as
`run / preset / layer` and omits the `site_set` component that
`store.tile_path` has required since the site-set work landed. The tool
therefore reads no tiles at all on a current run, and would report
every node as outside the map. Fix it to
`run / preset / "infrastructure" / layer`, or better, point it at
`coverage-at-nodes.json` and let it read exact levels.

---

## 8. Where it lives in the interface

### 8.1 Recommendation: a new page, plus two small grafts

Build **`#gaps`, "Coverage gaps"**, a new page with a nav entry. Then
add two small things to pages that already exist:

1. A **"Connection health"** panel on the node page, showing that one
   node's signals with their evidence. Somebody who lands on a node
   page is asking exactly this question about exactly that node.
2. Nothing new on the coverage page. The gaps page draws the coverage
   `usable` tiles as its own backdrop, using the same tile endpoint and
   the same picker code, so the two pages agree without being merged.

### 8.2 Why not fold it into the coverage page

The coverage page already carries three display layers, a preset
picker, a site set picker, a layer group, a view group, an assumptions
panel, an exclusions block, a calibration table, a diagnostic banner,
and a paste-ready block of coarse sites. It is full.

More to the point, the two pages answer different questions. Coverage
answers "where does the mesh reach", from prediction. Gaps answers "who
is struggling", from measurement, and it needs prose, confidence
badges, and per signal drill-down that a map layer cannot carry.
Putting a measured list inside a predicted map is also how a reader
starts to read one as the other.

### 8.3 The page, in reading order

Written for a mixed audience: the top is for somebody who joined the
mesh last week, and the detail is one click down. The house pattern for
that already exists on the graph page, where the unconfirmed and
one-way toggles hide the hard parts by default and the heading says
what is hidden.

1. **One sentence.** "On Long fast this week, 6 nodes reach us only
   through MQTT, 14 get out over the air only some of the time, and 184
   nodes have too little evidence to judge."
2. **Counts**, as stat tiles, one per signal, each showing `bad` and
   `unknown` side by side. The `unknown` number is never hidden.
3. **The map.** Coverage `usable` tiles underneath, at the same opacity
   control the coverage page uses. Struggling nodes drawn on top, shape
   and colour from their worst state. Cluster outlines in phase 2.
   Candidate pins in phase 3, in a shape that cannot be mistaken for a
   node.
4. **The table**, built with `app.js`'s `table()` helper, rows
   pre-sorted by the endpoint as every other table in this project is.
   One column per signal, showing a chip: a word, and the number when
   there is one. An em dash for `unknown`, which is the house
   convention for "not measured".
5. **A row expands** to the evidence: the counts, the window, the
   gateways active, the reason strings as sentences, and links to
   `#node/<id>` and to the existing `#link/<a>/<b>` page where a link
   is named.
6. **"Not enough evidence"**, its own section, with its own count and
   its own short explanation.
7. **What this cannot tell you.** A short list, permanently visible,
   holding section 2.5 and section 6.7 in plain words.

### 8.4 Two hard rules about the front end

- **New script before `app.js`.** `gaps.js` is a classic script that
  exports `window.SonoranGaps` and loads after `coverage.js` and before
  `app.js`, because `app.js` runs the router as its last act and a
  reload straight onto `#gaps` would otherwise fall back to the
  dashboard. `AGENTS.md` 9.14.2 and
  `test_planner_scripts_load_before_the_router` are about exactly this.
  Extend that test to cover the new file.
- **Nothing about this feature reaches the embed.** No route under
  `/api/embed`, no gaps layer on `/embed/coverage`. A list of weak
  nodes with positions is a list of houses with a reason to visit them,
  and it is a worse leak than the one `AGENTS.md` 9.25 already guards
  against. Add a test that enumerates the embed router and fails if any
  gaps path appears, in the shape of
  `test_a_diagnostic_run_can_never_widen_the_public_map`.

---

## 9. The API

Read only, GET only, plain dicts, `channel` as an optional query
parameter, windows echoed back. That is the house style and this
follows it.

### 9.1 Endpoints

```
GET /api/gaps?channel=LongFast&hours=168
GET /api/gaps/nodes?channel=LongFast&signal=radio_isolated&state=bad&limit=100
GET /api/gaps/nodes/{node_id}?channel=LongFast&hours=168
GET /api/gaps/areas?channel=LongFast                      (phase 2)
GET /api/gaps/candidates?channel=LongFast&area=3          (phase 3)
```

`channel` takes the channel name as stored, and goes through
`channels.channel_filter`. A channel that names no preset returns
`available: false` with `reason: "not_a_preset"`, because section 3
forbids guessing which preset it rides on.

`hours` is `Query(default=168, ge=1, le=720)`, the house pattern.

`limit` is `Query(default=100, ge=1, le=500)`, per `docs/API.md`.

`signal` and `state` are optional filters over the precomputed list.

### 9.2 `GET /api/gaps`

```json
{
  "available": true,
  "channel": "LongFast",
  "preset": "LongFast",
  "window_hours": 168,
  "generated_at": "2026-09-18T06:12:04Z",
  "gateways_active": 31,
  "node_count": 704,
  "assessed_count": 520,
  "coverage": {
    "stamp": "20260918T060000Z",
    "site_set": "infrastructure",
    "is_diagnostic": false,
    "available": true
  },
  "signals": {
    "radio_isolated":  {"bad": 6,  "ok": 318, "unknown": 196},
    "hears_but_is_not_heard": {"bad": 2, "ok": 0, "unknown": 518},
    "rf_intermittent": {"bad": 14, "ok": 402, "unknown": 104},
    "sole_observer":   {"bad": 31, "ok": 240, "unknown": 249},
    "weak_best_link":  {"bad": 9,  "ok": 88,  "unknown": 423},
    "outside_predicted_usable": {"bad": 57, "ok": 402, "unknown": 61}
  },
  "needs_help_count": 63,
  "not_enough_evidence_count": 184,
  "reached_but_unpredicted_count": 48,
  "caveats": ["observers_are_gateways_only", "receiving_is_not_observable",
              "demand_set_is_biased_to_existing_nodes"],
  "presets": [{"preset": "LongFast", "label": "Long fast", "node_count": 704}]
}
```

`available: false` is a working state, not an error, exactly as
`/api/coverage` treats a missing run.

### 9.3 `GET /api/gaps/nodes`

A list, pre-sorted by section 5.2, each item:

```json
{
  "node_id": "!a1b2c3d4",
  "display_name": "Dobbins Lookout",
  "role": "CLIENT",
  "preset": "LongFast",
  "latitude": 33.32, "longitude": -112.06,
  "position_confidence": "exact",
  "is_mqtt_gateway": true,
  "mobile": false,
  "packets": 412,
  "active_hours": 96,
  "worst_state": "bad",
  "bad_count": 2,
  "unknown_count": 3,
  "signals": { "...": "one object per section 5.1" }
}
```

`position_confidence` is `exact`, `coarse` or `none`, derived from
`positions.precision_deviation_m`. A `coarse` node is still listed, and
its `outside_predicted_usable` signal is `unknown`.

### 9.4 Nothing is computed per request

`jobs/gaps.py` computes the assessment and writes one artefact for each
preset:

```
{coverage_cache_dir}/gaps/index.json
{coverage_cache_dir}/gaps/{preset}.json
```

The API reads the artefact and filters it. This matters on this box:
`docs/ISSUES.md` 2.9 is an open warning about a public endpoint doing
per-row work while the map refreshes it every 15 seconds. The gaps
queries are heavier than that one.

Follow the house caching convention: JSON endpoints set no
`Cache-Control` and no `ETag`, and the route holds a module level cache
with a short life, the way `api/routes/embed.py` does with
`SUMMARY_CACHE_SECONDS`. Also note that `/api/coverage` reads its
manifest from disk on every request with no cache at all; do not copy
that.

`GAPS_INTERVAL_MINUTES` defaults to 30. The DB-only signals are cheap,
so the freshness costs little.

**No new table in phase 1.** A JSON artefact needs no migration, no new
grant, and cannot be caught by the `ON CONFLICT DO UPDATE` trap in
`AGENTS.md` 9.2. If trend history is wanted later, phase 4 adds a
hypertable and keeps the artefact as the serving path.

---

## 10. Phasing

### Phase 1 — the honest per node list. One sitting.

Highest insight for the least risk. No SPLAT, no clustering, no new
prediction.

1. `sonoran/gaps/signals.py`: the base query of section 4.0 and the
   signals 4.1, 4.3, 4.4, 4.5, 4.8. Pure functions and ORM queries.
   No new dependency.
2. `required_snr_db(preset)` added to `radio/presets.py`.
3. `sonoran/jobs/gaps.py`: compute per preset, write the artefact.
   Registered as its own `Task` in `jobs/scheduler.py` because it is
   only SQL. A `sonoran-gaps-once` console script, matching
   `sonoran-coverage-once`.
4. `api/routes/gaps.py`: `GET /api/gaps` and `GET /api/gaps/nodes`,
   registered in `api/app.py`.
5. `web/static/gaps.js` plus a `#gaps` section, a nav entry, and a
   sprite symbol in `index.html`. Counts, the table, the unknown
   section, and the limits list. The map may be a plain marker layer in
   this phase, or left to 1b.
6. The coverage job change of section 7, plus
   `store.read_node_levels`, plus the `validate_coverage.py` path fix.
   Signal 4.6 lights up by itself after the next scheduled run, within
   6 hours.
7. `docs/API.md` section, this document linked from
   `docs/COVERAGE.md`, and an entry in `docs/ISSUES.md`.
8. Tests, per section 11.

Signal 4.2, `hears_but_is_not_heard`, is two lines once 4.1 exists.
Include it: it is the most valuable single finding and it costs
nothing.

If the sitting runs short, cut in this order: the map, then the node
page panel, then signal 4.4. Do not cut the unknown bucket or the
limits list.

### Phase 1b — the node page panel

`GET /api/gaps/nodes/{node_id}` and a "Connection health" panel on the
node page. Small, and it puts the answer where people already look.

### Phase 2 — areas, and candidates without prediction

Demand points, deduping, clustering, `GET /api/gaps/areas`, cluster
outlines on the map. Kind A and Kind B candidate generation and the
terrain screen of section 6.4, served as
`GET /api/gaps/candidates` with `method: "terrain_screen"` on every
row, so nobody mistakes it for a prediction.

**Prerequisite worth doing first:** `docs/ISSUES.md` 2.6, the planner
permalink. Every candidate should carry an "open in the planner" link
with its position, power and height filled in. Upstream already encodes
a whole plan in the URL, it needs no storage and no write endpoint, and
it turns this feature's output into something a person can immediately
pull apart by hand. It is the cheapest real handoff available.

### Phase 3 — SPLAT confirmation

Section 6.5 and 6.6. Runs inside `_coverage_cycle` after
`coverage.run_once`, never as its own concurrent `Task`. Candidates
gain `method: "splat"`, a `newly_usable` node list, and the run stamp
they were scored against.

### Phase 4 — history, if it is wanted

A `gap_assessment` hypertable so a reader can ask whether a node got
better after somebody put up a mast. Only build it when somebody asks
that question out loud.

---

## 11. Tests

### 11.1 Measure these on live data before trusting any threshold

Every default in this document is a starting point, not a measurement.
Run these on the live box first, and write the answers into the
docstrings.

1. **The MQTT downlink hole, section 2.2.** How many packets have
   `mesh_packet_metrics.via_mqtt = true` and also a `packet_seen` row
   from a different gateway? If that number is near zero, the firmware
   loop protection holds and the exclusion costs nothing. If it is
   large, signal 4.1 needs rethinking before it ships.
2. **How many nodes are gateways at all?** Signal 4.1 only applies to
   them. Count distinct `packet_seen.gateway_node_num` in a week
   against the node count.
3. **How sparse is `neighbor_metrics`?** Count distinct `node_num`
   reporters in a week. Signals 4.2 and 4.5 rest on it. The dev
   database holds 16 reporters over 17 nodes, which is seeded data and
   tells us nothing about live.
4. **The distribution of `rf_hour_ratio`** across nodes, so 0.5 is a
   line somewhere useful and not in the middle of the pack.
5. **The distribution of `best_snr_margin_db`**, same reason, before
   fixing 5 dB.
6. **How many nodes are `bad` on each signal.** If a signal flags 300
   nodes it is not a finding, it is a definition problem.

The development database on this machine is the 17 node seed set
(`node` 17 rows, `neighbor_metrics` 180 rows, `mesh_packet_metrics` 0
rows, a one day window). It is enough to prove queries run. It is not
enough to set a threshold.

### 11.2 Unit tests

Build rows by hand and assert the rule, not the number.

- A packet uploaded 22 times by 15 gateways counts as **one** packet
  with 15 gateways.
- A self upload is not RF evidence, and its `rx_snr` never reaches
  `best_snr_margin_db`. `AGENTS.md` 9.5.1.
- A relayed observation is RF evidence at rung 4 and contributes **no**
  SNR. `AGENTS.md` 9.5.
- A packet whose first upload carries `via_mqtt` contributes neither
  evidence nor a fault, and increments `ambiguous_packets`.
- A node that never appears as a gateway returns `radio_isolated: ok`
  with reason `not_an_mqtt_gateway`.
- A node with 19 packets against a floor of 20 returns `unknown`, and
  the reason names the floor.
- A node with zero packets returns `unknown`, never `bad`.
- A node active on LongFast and MediumFast produces two assessments,
  and neither borrows a count from the other. `AGENTS.md` 9.7.
- A node with `role IS NULL` is treated as a client: it may be demand,
  and it may never be a candidate site. `AGENTS.md` 9.22. Note the
  inversion worth a comment in the code: the coverage map predicts from
  infrastructure because only a fixed node holds coverage open
  (`AGENTS.md` 9.26), while this feature's demand set is mostly
  clients, because clients are the people being helped.
- Traceroute readings: quarter dB divided by four, `-128` is `None` and
  not -32 dB, a hop past the end of `snr_towards` does not exist, a
  reply's endpoints are swapped, and an unanswered request evidences no
  link. Assert through `api/traces.py` and never re-implement it.
  `AGENTS.md` 9.6 and 9.18.
- Coverage sampling: a node with 13 bit precision returns
  `position_too_coarse` with the 2.9 km deviation, and never
  inside or outside. A node absent from `coverage-at-nodes.json`
  returns `unknown`, and a stored level of 0 returns `bad` and not
  `unknown`, because 0 is "the run reached this cell and found
  nothing".
- A published run with `is_diagnostic: true` makes signal 4.6
  `unknown` with reason `diagnostic_run`.
- The terrain screen passes a planted clear line of sight case, and
  rejects a case with a planted 1000 m ridge in the middle. The first
  assertion is the important one: a screen with false negatives loses
  the answer.
- `required_snr_db` is derived from the preset table and matches
  `sensitivity_dbm - noise_floor_dbm` for every one of the nine
  presets.

### 11.3 Integration tests, against a real TimescaleDB

`tests/integration/conftest.py` already provides one. Assert
behaviour, not row counts.

1. **The two routes of section 2.2.** Build node A that only ever
   uploads its own packets: assert `radio_isolated: bad`. Build node B
   whose packets arrive from a different gateway with hops consumed:
   assert `radio_isolated: ok` **and** that no link and no SNR appear
   anywhere in its assessment.
2. **The asymmetry case.** Take node A from above and add two
   `neighbor_metrics` rows where A is the reporter with a real SNR.
   Assert `hears_but_is_not_heard: bad`, and assert the phrase the API
   returns names both halves of the claim.
3. **Duplicate rows.** Insert the same packet twice in `packet`, as the
   pre-0009 history holds, plus 15 gateway observations. Assert
   `packets = 1` and `direct_gateways = 15`.
4. **Clock skew.** Insert a packet whose `rx_time` is 28 hours ahead of
   its `first_seen_at`. Assert every bucket lands on the
   `first_seen_at` hour, that the window never reports an hour that has
   not happened, and that `active_hours` does not grow.
   `AGENTS.md` 9.3, 9.4, `docs/ISSUES.md` 1.5.
5. **Preset separation.** One node, traffic on two presets, one of them
   with no RF evidence. Assert two rows, one `bad` and one `ok`, and no
   merged row anywhere.
6. **The replay trap.** Any test that re-processes a recorded fixture
   must clear the rows for that packet first, or the handlers are
   skipped and the test proves nothing. `AGENTS.md` 9.12.
7. **The coverage artefact.** Run the coverage job over a tiny region
   with one site, and assert that `coverage-at-nodes.json` holds a
   level for a node at a known position that equals the level the
   in-memory grid held at that cell, that the node outside the region
   is absent rather than zero, and that `threshold_level` equals
   `to_level(preset.sensitivity_dbm)`.
8. **The API computes nothing.** Assert the endpoint response is
   derived from the artefact alone: delete the artefact and assert
   `available: false` rather than a slow live computation.
9. **The embed cannot see any of it.** Enumerate the embed router's
   routes and fail if any path contains `gaps`.
10. **No writes.** Assert the gaps routes are GET only, as the existing
    API tests do.

---

## 12. What this design will not build, and why

1. **No link lines from gateway observations.** Not on the map, not in
   a graph, not as a "quality" figure. About 82 percent of observations
   were relayed, only about 5 percent direct, and the traffic layer
   drawing those lines is already an open issue
   (`docs/ISSUES.md` 2.3). This feature will not add a second one.
   `AGENTS.md` 9.5, 9.5.1.
2. **No topology from `relay_node_num`.** One byte, 215 distinct values
   over 694 nodes, 5.4 percent resolving to a single node. It names the
   last hop and never the path. `AGENTS.md` 9.20.
3. **No link level asymmetry, and no link stability from neighbour
   lists.** Both need "absence from an aggregated neighbour list means
   the link was silent" to be true. That assumption is exactly what
   currently blocks the calibration from being applied
   (`docs/ISSUES.md` 2.4.1, `AGENTS.md` 9.21). Prove it first, with
   the measurement that issue asks for, and then build this. Section
   4.2 gets the honest part of the answer without it.
4. **No 0 to 100 health score, and no colour derived from a score.**
   Section 5.2.
5. **No "all presets" or "whole mesh" gap view.** `AGENTS.md` 9.7.
6. **No public or embedded exposure, ever.** Section 8.4.
7. **No claim that a node cannot hear the mesh**, unless it is the
   narrow proven case in section 4.2. Section 2.5.
8. **No use of `NodeFit.offset_db` as a node fault.** It is inferred,
   not measured, the live fit is currently rejected outright, and
   `AGENTS.md` 9.21 lists the guards that exist because somebody
   reached -1830 dB.
9. **No brute force candidate grid.** A 5 km grid over the Arizona
   region is roughly 27,000 candidates, which at 18 core-seconds each
   is about six core-days. Section 6.6 shows the affordable shape.
10. **No region grid per candidate.** 88 MB each, for a few dozen point
    lookups. Section 6.5.
11. **No 30 m terrain** for the screen or the candidates.
    `docs/ISSUES.md` 2.5 measures the cost and the gain is mostly in
    close country.
12. **No alerting.** This is a report, not a monitor. The signals are
    unmeasured on live data until section 11.1 is done, and an
    unvalidated signal wired to a notification is a false alarm
    generator.
13. **No product, mast, land or vendor recommendation.** Section 6.7.
14. **No front end build step.** Plain classic script, `app.js`'s
    `table()`, the existing Leaflet setup.

---

## 13. Findings from the existing code that change the shape of this

Written down because each one cost time to find.

1. **No run keeps a level grid.** Only colour ramped PNG tiles survive,
   and a tile entirely below the threshold is never written. Section 7
   adds the small artefact that both halves need.
2. **`tools/validate_coverage.py` is broken.** Its sampler root omits
   the `site_set` path component, so it reads nothing on a current run.
   Section 7.
3. **`mesh_packet_metrics` holds the first uploader's view only**,
   because `store_mesh_packet_metrics` is called inside
   `if stored.is_new:`. So `via_mqtt` is not a per observation fact.
   Section 2.3.
4. **`route_segments` does not exist.** It was named in the brief. A
   repository-wide search finds no table, model, migration or
   reference. The tables that exist are the ones in
   `src/sonoran/db/models.py`.
5. **The jobs scheduler runs tasks concurrently**, with
   `asyncio.gather`. Only calibration and coverage share a clock. Any
   new task that uses the engine must join the coverage cycle instead
   of standing beside it. Section 6.6.
6. **`_heard_by` in `api/routes/nodes.py` already implements the
   9.5 and 9.5.1 direct rule correctly.** Reuse it. Do not write that
   join a second time. `AGENTS.md` 9.18 records what happened the last
   time three pages each held their own copy of a rule.
7. **The vendored `proto/` directory holds no `.proto` text**, only
   `UPSTREAM_REV.txt` and `update.sh`. So the `via_mqtt` semantics this
   design leans on cannot be quoted from this repository yet. Section
   2.2 makes quoting it a prerequisite.
8. **The calibration currently applies no correction at all.** The live
   fit's model bias was near -41 dB and the 20 dB guard rejected it, so
   the coverage map runs on nameplate radio profiles. Every predicted
   number in the siting half inherits that, and the page should say so
   once, in the same sentence that says the prediction is not a
   promise.
9. **The planner cannot be linked to.** `docs/ISSUES.md` 2.6. That
   makes it the natural prerequisite for phase 2, not an unrelated
   issue.

---

## 14. Settings

All new, all with defaults, all named in one block in `config.py`.

| Setting | Default | What it decides |
|---|---|---|
| `gaps_enabled` | `true` | Whether the job runs. |
| `gaps_interval_minutes` | `30` | How often the per node assessment is rebuilt. |
| `gaps_window_hours` | `168` | The measurement window. Never above retention. |
| `gaps_min_packets` | `20` | Below this a node is `unknown`. |
| `gaps_min_active_hours` | `12` | Below this `rf_intermittent` is `unknown`. |
| `gaps_rf_ratio_bad` | `0.5` | The intermittency line. Measure it first. |
| `gaps_margin_bad_db` | `5.0` | The weak margin line. Measure it first. |
| `gaps_min_neighbour_reports` | `2` | Evidence floor for section 4.2. |
| `gaps_min_traces` | `3` | Evidence floor for section 4.7. |
| `gaps_mobile_spread_km` | `1.0` | Above this a node is mobile. |
| `gaps_demand_cell_m` | `300` | Demand deduplication cell. |
| `gaps_cluster_link_km` | `8.0` | Cluster linkage distance. |
| `gaps_min_cluster` | `3` | Below this it is a node, not an area. |
| `gaps_search_radius_km` | `15.0` | How far around a cluster to look for ground. |
| `gaps_min_prominence_m` | `40` | How much a candidate must stand above its surroundings. |
| `gaps_candidate_spacing_km` | `1.5` | Minimum spacing between candidates. |
| `gaps_candidates_per_cluster` | `60` | How many candidates enter the screen. |
| `gaps_splat_per_cluster` | `3` | How many reach the engine. |
| `gaps_max_predictions` | `24` | The hard ceiling on engine runs per cycle. |
| `gaps_candidate_radius_km` | `25.0` | Prediction radius for a candidate. |
| `gaps_candidate_tx_power_dbm` | `30.0` | The "1 W node" the owner asked about. |
| `gaps_candidate_height_m` | `9.0` | A roof or attic node. |
| `gaps_workers` | `1` | Engine workers for the candidate step. |
| `gaps_worker_nice` | `10` | Same background priority as coverage. |

---

## 15. The sentence this feature exists to be able to say

> On Long fast this week, two nodes can hear the mesh and the mesh
> cannot hear them. Six more reach us only through their own internet
> link. Fourteen get out over the air in fewer than half the hours they
> are awake. Those nodes fall into three neighbourhoods. In the largest,
> a 1 W node at 9 m on the ridge at 33.41 N, 112.19 W would bring nine
> of the eleven inside usable coverage, which the engine confirms. We
> cannot tell you who owns that ridge, whether there is power on it, or
> whether anybody may stand there. For 184 other nodes we do not have
> enough evidence to say anything at all.

Every clause in that paragraph is traceable to a table, a threshold, or
an admission. That is the bar.
