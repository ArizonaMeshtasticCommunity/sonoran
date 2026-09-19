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

**State:** Fixed. The route is now
`/api/chat/conversation/{from_node}/{packet_id}` and matches on
`from_node_num` and `packet_id`, the pair `text_message` is indexed on.
Keying on the packet ID alone would have been ambiguous between senders,
so the sender joined the path rather than the fix stopping at the column.
Tapbacks are excluded from the reply list. Five integration tests cover
it; four of them failed before the change.

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

The live fit on 2026-08-21 found a network-wide model bias near -41 dB.
That is outside the 20 dB trust guard, so Sonoran applies no per-node
correction. The coverage map currently uses nameplate radio profiles.
The large bias can mean that the propagation assumptions are wrong, or
that absence from an aggregated neighbour list is not reliable evidence
that a link was silent. Do not raise the guard to make the fit apply.
Validate that evidence first.

### 2.4.2 The rejected fit is dominated by censored links

**State:** Open. Issue #3, item 3.

Three live readings of the same fault:

| Run | Links | Censored | Model bias | Scatter | Applied |
|---|---|---|---|---|---|
| 2026-08-21 | — | — | -41 dB | — | 0 |
| 2026-08-22 | 771 | — | -46.3 dB | 12.7 dB | 0 |
| 2026-09-18 | 420 | 362 (86%) | -44.62 dB | 11.17 dB | 0 |

The 2026-09-18 run is the one with a full reading. Its `summary` is
`count 420, mean_db -13.57, spread_db 17.52, censored 362`.

The solver is not the fault. `fit_offsets` is a correct EM for a Tobit
model: a censored link is filled with the conditional mean of the
truncated normal it must have come from, the offsets are refitted, and
the complete-data likelihood is quadratic, so ordinary least squares on
the filled values is the right M step. Measured against planted truth,
it recovers a zero bias to within 0.6 dB at 48 percent censoring, and a
planted -6 dB bias to within 0.5 dB.

What it cannot survive is a censored observation that is not true. The
same harness, with links that really were heard and simply never
reached the neighbour list, gives:

| Heard links left out of the list | Censored | Reported-only mean | Fitted bias |
|---|---|---|---|
| 0% | 1% | -0.03 dB | -0.17 dB |
| 25% | 26% | -0.73 dB | -7.50 dB |
| 50% | 53% | -0.11 dB | -14.80 dB |
| 75% | 74% | 0.18 dB | -21.89 dB |
| 90% | 88% | 0.13 dB | -28.79 dB |
| 98% | 98% | 3.44 dB | -38.76 dB |

The true bias in every row is zero. The fitted bias tracks the share of
false silence almost linearly, and the reported-only mean stays near
zero throughout.

**The split.** `summary.mean_db` is the mean residual over the reported
links alone, and it is also what the intercept would be with the
censored rows dropped, because with nothing else in the design the two
coincide. So the decomposition needs no model at all:

| Term | dB | Share |
|---|---|---|
| Fitted `model_bias_db` | -44.62 | 100% |
| Reported side, `summary.mean_db` | -13.57 | 30% |
| Gap opened by the censored mass | -31.05 | 70% |

Roughly a third of the rejected bias is a real error on the links the
mesh actually measured. The other two thirds is opened by rows that
record silence.

**What the bounds must have been.** Nothing stored says how far above
the sensitivity the model put a silent link, and that is the number the
whole question turns on. It can be recovered. At EM convergence the
line `bias = mean(filled - rows @ offsets)` is exactly the Tobit score
equation for the intercept:

    sum_reported (y - mu)  =  sum_censored  sigma * lambda(z),
    z = (bound - mu) / sigma,   lambda(z) = phi(z) / Phi(z)

Everything in it is live except the bounds. With 58 reported links at
-13.57, 362 censored, `mu = -44.62` and `sigma = NOISE_SIGMA_DB = 8`:

    reported pull   sum(y - mu) = 1800.9 dB
    censored push   mean lambda =   0.622   ->   mean z = 0.29
    implied mean censoring bound        = -42.29 dB

**The model put a typical silent link 42.3 dB above sensitivity.**

**How much of that silence is credible.** Judge it against the 58 links
the mesh did measure. If a silent link is drawn from the same
`N(-13.57, 17.52^2)`, then `P(residual <= -42.3) = 5.1%`. The observed
silence is 86 percent. So about 6 percent of it is credible and roughly
94 percent — some 340 of the 362 rows — is not.

That 6 percent carries a caveat, and it must be carried with it.
Reported links are survivors, so their distribution is truncated above,
and a fairer distribution for the silent ones would sit lower. Judged
instead by the fit's own converged distribution, `P(r <= -42.3)` is
nearer 58 percent — but that is circular, because the fit only believes
that distribution because it assumed the silence was real. The two
answers differ by an order of magnitude. **That gap is the assumption
`AGENTS.md` 9.21 said to validate, and it is still not validated.** The
only non-circular evidence available is the 58 measured links, and they
say 6 percent.

**The alternatives, falsified.** The planted-truth harness rules out
every single-cause explanation:

| Hypothesis | Censored | Fitted bias | Verdict |
|---|---|---|---|
| Shallow margins, silence all genuine (2 dB) | 78% | -10.58 dB | bias cannot reach -44.6 |
| Shallow margins, silence all genuine (5 dB) | 73% | -11.15 dB | same |
| Shallow margins, silence all genuine (10 dB) | 61% | -11.90 dB | same |
| Deep margins (42 dB), silence all genuine | 9% | -14.24 dB | censoring cannot reach 86% |
| Reported-side error alone, -44.62 dB | 56% | -44.30 dB | the 58 links average -13.57, not -44.6 |

A bound just below zero cannot hold a mean at -44.6 dB, and a model
confident enough to place links 42 dB above sensitivity cannot have 86
percent of them fail honestly. Only a mixed cause works.

**The mixed cause reproduces the run.** Sweeping the margin
distribution, the false-silence share and the link noise, the closest
match is margins `N(36, 10^2)` dB, 84 percent false silence and 13 dB
of link noise:

| | live | synthetic |
|---|---|---|
| censored | 86% | 85% |
| reported mean | -13.57 dB | -11.82 dB |
| reported spread | 17.52 dB | 13.53 dB |
| fitted bias | -44.62 dB | -43.95 dB |
| post-fit spread | 11.17 dB | 12.17 dB |

A one-parameter sweep brackets the false-silence share at 78 to 84
percent. The loose end is the reported spread: the live reported links
are **more** scattered than the synthetic ones, which says the reported
side is noisier than modelled, not less.

**Two structural reasons the censored side is that large**, and neither
is evidence about a radio:

- `MAX_CANDIDATES` takes up to 40 silent candidates for each listener,
  against however few neighbours it actually named. 362 censored at a
  cap of 40 needs at least 10 listeners, and at exactly 10 the cap binds
  for 9 of them — 360 of the 362. The 58 reported links over those 10
  listeners is 5.8 named neighbours each. Each listener is charged with
  about 40 silences for every 5.8 things it actually said. The cap, not
  the mesh, is setting the censored count.
- The NeighborInfo module is off on most nodes, and where it is on the
  list it publishes is bounded and ages out. A node that heard a
  neighbour and did not list it is charged with silence.

**Lowering the cap is not a fix.** It is a dial. Same mesh, same truth,
same radios; only how many candidates the job bothers to enumerate:

| `MAX_CANDIDATES` | Links | Censored | Reported mean | Fitted bias |
|---|---|---|---|---|
| 40 | 443 | 89% | -12.69 dB | -52.24 dB |
| 30 | 347 | 86% | -12.69 dB | -50.25 dB |
| 20 | 247 | 81% | -12.69 dB | -46.29 dB |
| 10 | 147 | 68% | -12.69 dB | -36.26 dB |
| 5 | 97 | 52% | -12.69 dB | -26.65 dB |
| 2 | 67 | 30% | -12.69 dB | -21.59 dB |

The reported mean never moves. The mesh-wide bias moves 30 dB on a
parameter about enumeration effort, which is the definition of a number
that is not a measurement. Worse, tuning the cap walks the bias under
the 20 dB guard and starts an unvalidated fit moving the public map.
That is strictly worse than today, where it is refused and says so.

**Do not lower `MAX_CANDIDATES` to make the bias look better, and do
not raise the trust guard.** `store.calibration_offsets` and
`Calibration.is_trusted` both refused this fit and both were right.
`applied_count: 0` is the system working.

**The payoff for fixing the evidence instead.** With the false silence
removed, the same synthetic mesh fits at **-14.46 dB** — inside the
plus or minus 20 dB guard. Calibration would begin applying, and
nothing would have been weakened to let it.

**The path forward**, in this order. Instrumentation first, because the
one input nobody can see is the one the answer turns on.

1. **Instrument, then decide.** The censoring bounds had to be
   recovered by inverting the score equation above. Write them down
   instead: add the distribution of `threshold - predicted` over the
   censored links to `summary` — count, mean, median, p10 and p90 — and
   the listener count. One run then replaces every inference here with
   a measurement, and breaks the circularity in the 6 percent.
2. **Make silence provable before it counts.** Censor only where
   absence is informative: the listener's NeighborInfo module is on, its
   list is not saturated, and the candidate actually transmitted inside
   the window. A link the listener could not have listed is not a link
   it failed to hear.
3. **Charge the listener's receive gain**, which is 2.4.3. Correctness,
   and it belongs in the same work, but it is not the cause and must
   not lead.
4. **Then** take the remaining -13.57 dB on its own. A LoRa SNR reading
   saturates near +12 dB, so a strong close link reads far lower than
   the model predicts, and the harness shows that cap alone producing a
   -20 dB bias with nothing censored at all. `noise_floor_dbm` also
   assumes thermal noise, and a band with interference in it puts every
   derived power below the truth.

**What the excluded nodes do not change.** `coarse_sites` lists 31
nodes held back at 13, 14 and 15 precision bits — 2900 m, 1459 m and
729 m of deviation — and `config/nodes.yaml` holds no real entries.
`read_peers` drops a coarse node from the fit entirely, so those 31 are
neither listeners nor candidates. That is deliberate and right: a
silence about a node that may be 2.9 km from where it says means
nothing. It changes no number above. The score-equation inversion uses
only the four summary figures; the cap arithmetic is arithmetic on the
live counts; the credibility figure comes from the links that did get
in. It explains the small sample — 10 listeners and 420 links on a mesh
this size — and giving those 31 real positions would grow the evidence
without changing any conclusion here. It also confirms 2.4.3 exactly:
with no override entries, every node takes the stock antenna gain.

### 2.4.3 The fit charges no receive antenna gain at the listener

**State:** Open. Found while reading 2.4.2. Quantified against the
2026-09-18 run.

`jobs/calibrate.py::_fill` recovers a path loss with
`listener_eirp - link.dbm` and then predicts the far end with
`peer.effective_eirp_dbm - loss_db`. Nothing adds the gain of the
antenna the listener received on, although the coverage job does exactly
that for its handheld through `params.received_dbm`.

**The term is exactly 2.15 dB, and it is uniform.** Every entry in
`radio/hardware.py` carries `STOCK_ANTENNA_GAIN_DBI`, which is 2.15 —
the figures that vary in that table are transmit powers, not gains.
`DEFAULT_CABLE_LOSS_DB` is 0.0, and `config/nodes.yaml` holds no real
entries, so no node takes a written antenna. A uniform gain is an exact
translation of every residual and every censoring bound alike, which was
confirmed on the harness: the fitted bias moved by -2.15 dB and not a
hundredth more.

**It moves the bias the wrong way.** Charging the gain makes the model
predict more signal, so measurement sits further below it:

| | now | with the gain charged |
|---|---|---|
| Reported side | -13.57 dB | -15.72 dB |
| Fitted bias | -44.62 dB | -46.77 dB |

It is 16 percent of the reported-side error **in the direction that
deepens it**. It also admits slightly more censored rows, because
`elif predicted > threshold` takes more candidates once `predicted` is
correctly higher.

So nobody should later read this entry and mistake it for the cause of
2.4.2. It explains none of the -13.57 and makes the headline figure
marginally worse. It is a real defect, worth fixing for correctness,
and it is step 3 of the path in 2.4.2 rather than the lead.

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

### 2.10 Every coverage gap threshold is unmeasured

`docs/GAPS.md` ships with seven thresholds and **not one of them has been
measured on live data**. They are starting points that work on the 17
node seed, which proves the queries run and proves nothing about where a
line belongs.

`docs/design/coverage-gaps.md` 11.1 names the six measurements to take on
the live box first:

1. How many packets carry `mesh_packet_metrics.via_mqtt = true` **and**
   have a `packet_seen` row from a different gateway. If that is near
   zero the firmware loop protection holds and the exclusion costs
   nothing. If it is large, `radio_isolated` needs rethinking before it
   is trusted. Until this is done a `via_mqtt` packet counts as no
   evidence either way, which is the conservative branch.
2. How many nodes are MQTT gateways at all. `radio_isolated` applies to
   nobody else.
3. How sparse `neighbor_metrics` is: distinct reporters in a week.
   `hears_but_is_not_heard` and `weak_best_link` both rest on it.
4. The distribution of `rf_hour_ratio`, so 0.5 is a line somewhere useful
   and not in the middle of the pack.
5. The distribution of `best_snr_margin_db`, before 5 dB is fixed.
6. How many nodes each signal flags. **If a signal flags 300 nodes it is
   not a finding, it is a definition problem.**

There is no alerting on any of this, and there must not be until those
numbers exist. It is a report, not a monitor.

### 2.11 The `via_mqtt` semantics cannot be quoted from this repository

`docs/GAPS.md` 2.2 leans on the firmware never re-uploading a packet it
took from MQTT. The vendored `proto/` directory holds only
`UPSTREAM_REV.txt` and `update.sh`, so the `via_mqtt` and
`TransportMechanism` field comments are not in the repository and cannot
be quoted. This project does not assert what the vendor did not state, so
the conservative branch runs and such packets are reported as
`ambiguous_packets`.

Vendoring the `.proto` text, or at least those field comments, closes it.

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

### 3.5 ingest and jobs have no liveness probe

**State:** Open.

`timescaledb` and `api` are the only services with a healthcheck, so
`ingest` and `jobs` can sit wedged behind a `Up` status indefinitely.
Neither serves HTTP, so a probe has to read something they write.

The honest shape is a heartbeat: ingest touches a file, or records a
timestamp, each time it stores a packet; jobs does the same at the end of
a cycle. A probe then asserts the timestamp is recent. Until they write
one, adding a healthcheck would only assert that a process exists, which
is the state that already looks healthy and is not.

### 3.6 No memory or CPU ceiling on any service

**State:** Open. Needs a decision, not a guess.

`docker-compose.yml` sets no `mem_limit` and no `cpus`. Measured on the
shared dev box, which has 3 cores and 3,398 MB of RAM:

| Service | RSS |
|---|---|
| timescaledb | 788 MiB |
| jobs | 259 MiB |
| mesh-graph | 76 MiB |
| ingest | 53 MiB |
| api | 24 MiB |

About 1.2 GB of 3.4 GB at rest. The figure that makes a ceiling awkward
is the coverage job: `docs/COVERAGE.md` 9.2 records one Arizona region
grid at 88 MB, a preset holding two and a third while rendering, and an
unbounded 300-node run killed by the OOM killer at 4.7 GB per worker
before the engine was fixed to one instance per process.

So a `mem_limit` low enough to protect the box is close enough to the
coverage job's real peak to risk killing a run that would have finished.
Setting one is a judgement about which failure is preferable, on a host
shared with another account, and it belongs to whoever operates the box.
The measurements above are here so that decision starts from numbers.

### 3.7 CI's `test` job fails intermittently on a migration

**State:** Open. Mechanism understood, fix not verified.

`tests/integration/test_migrations.py::test_revision_downgrade_and_upgrade`
fails in GitHub Actions with:

    psycopg.errors.InternalError_: tuple concurrently updated

It hit `main` itself and three pull requests in one evening, and passed on
several others, so it is intermittent rather than a regression. Coverage
passes in the same run (82.79%), so the job fails only on this test.

The likely mechanism: the test runs four `downgrade`/`upgrade` cycles
against a session-scoped TimescaleDB container. TimescaleDB runs
background workers that touch the same catalog rows the DDL is rewriting,
and a catalog tuple updated by two backends at once produces exactly this
error. Starting the test container with
`-c timescaledb.max_background_workers=0` would remove the competing
writer.

**Not applied, because it could not be verified.** The flake does not
reproduce locally: 12 consecutive runs of the module pass, and CI's exact
whole-suite command with coverage passes with 656 passed / 3 skipped. A
mitigation whose failing state has never been observed here is a guess,
and a guess that silences an intermittent failure is worse than the
failure, because it removes the signal without proving the cause. It
needs one run that fails with the setting in place, or the same failure
reproduced on a runner.

### 3.8 The land cover cache has never been filled

**State:** Open, and it is a decision rather than a task. See issue #3.

`has_landcover` is `false` on every published run, so no prediction
charges the clutter loss of ITU-R P.2108.

`tools/prefetch_landcover.py` works. Measured end to end against the real
ESA WorldCover bucket, one page at a time:

| | |
|---|---|
| Pages for the configured region | 64 |
| Distinct source GeoTIFFs | 9, about 60 MB each |
| Time per page | 28 s |
| Bytes kept per page | 1,440,000 |
| Total time | roughly 30 minutes |
| Total kept | about 88 MB |

The tool needs the `landcover` extra (`rasterio`, which brings GDAL) and a
writable `LANDCOVER_CACHE_DIR`; it does not need credentials.

Why it is a decision and not simply a chore: filling the cache changes
what every subsequent prediction says, and those predictions are what the
public embed publishes. On a shared box it also installs GDAL into an
account other people use. Both of those belong to whoever operates the
deployment, not to whoever happens to notice the flag is false.

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
