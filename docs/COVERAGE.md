# The coverage map

## 1. What it answers

The coverage planner answers one question for one hypothetical mast:
if a radio stood here, who would hear it? A person tries a site, reads
the answer, and closes the tab.

The coverage map answers the other one. Where does the mesh reach
today, from every node it hears, over the ground those nodes actually
sit on?

The two run the same engine. See `docs/PLANNER.md` 2.

## 2. Where the work happens

```
nodes.yaml ─┐
hw defaults ─┼─→ radio.resolve ──┐
calibration ─┘                   │
                                 ├─→ jobs/coverage ──→ tiles ──→ /api/coverage ──→ #coverage
terrain pages ───────────────────┤       │                              └────────→ /embed/coverage
landcover pages ─────────────────┘       │
                                         ↑
neighbor_metrics ──→ jobs/calibrate ─────┘
```

The job runs in the jobs process, on its own clock, and writes tiles to
disk. The API serves them and computes nothing: a request that needed a
prediction would take seconds and could not be cached.

The planner page keeps its own rule. Nothing a person plans on that
page is ever sent to the server. The coverage map predicts only from
the nodes the mesh already reports, so it holds no private plan.

## 3. One module holds each rule

Each is the only place that decides one thing, which is the
arrangement `sonoran/positions.py` and `sonoran/api/traces.py` already
use.

| Module | Decides |
|---|---|
| `roles.py` | Whether a node may be a site at all |
| `positions.py` | Whether a position is precise enough to predict from |
| `radio/resolve.py` | The effective power, antenna, and height of a node |
| `coverage/clutter.py` | What the last few metres at each end cost |
| `coverage/grid.py` | How a raster maps to the ground |
| `embed/sanitise.py` | What a public viewer may see |

### 3.1 The diagnostic run

`COVERAGE_SITE_ROLES` names the roles a run may predict from. The
default is the infrastructure set. Setting it to `ALL` predicts from
every node, and a named list such as `ROUTER,CLIENT_BASE` predicts from
exactly that.

An "all nodes" run is a genuinely useful thing. It answers "why is
this ridge empty — is there nothing there, or is there something there
with no role set?", and it is the only way to see what the filter is
costing on a particular mesh.

Measured against the live Arizona mesh, 931 positioned nodes in region:

| `COVERAGE_SITE_ROLES` | Sites | Left out |
|---|---|---|
| `ROUTER,ROUTER_LATE,REPEATER`, the default | 16 | 915 |
| `ROUTER,CLIENT_BASE` | 21 | 910 |
| `ALL` | 176 | 755 |

`ALL` is 176 and not 931, because a node still needs a modem preset and
a position precise enough to anchor a prediction. It is also about
eleven times the work of a default run: budget half an hour rather than
five minutes, and see 9.1 for keeping the machine usable while it
happens.

It is also not a coverage map, and its tiles look exactly like one.
So a run that can include a role outside the infrastructure set carries
`is_diagnostic` in its manifest, **and writes its tiles under a site set
named `diagnostic`**. A subset such as `ROUTER` cannot add a personal
node, so it stays safe to publish and keeps the `infrastructure` name.

The directory name matters because the site set is part of the tile
path. A `COVERAGE_SITE_ROLES=ALL` run used to be written under
`infrastructure` whatever it predicted from, so the path said "routers
and repeaters" while holding a footprint around every client node in
region. The manifest was honest and the path was not, and the tiles are
what a reader fetches.

Four things read the flag:

- The coverage page replaces its heading with the roles that were used,
  and puts a notice above the assumptions panel.
- The exclusion sentence stops claiming that only a router holds
  coverage open, because in that run it did not.
- **The public embed refuses to serve it at all.** `/api/embed/coverage`
  answers `available: false` with `reason: "diagnostic"`, and the page
  says a diagnostic is not published there.
- **The public tile route refuses it too**, in a router dependency, so
  no handler body runs and no tile is read. The JSON refusal alone was
  never enough: the tiles are the leak.

That last one is not about honesty, and a warning banner would not
have done. A diagnostic run predicts from every client node, and a
client node is usually somebody's house. Each one draws a footprint,
and a footprint has a centre. `embed/sanitise.py` already keeps the
markers back, but a stranger reading the tiles can find the middle of
a circle. The public page therefore gets nothing rather than a labelled
something.

**The embed reads the manifest flag and never the setting.**
`embed/sanitise.py` takes no settings argument at all. If it read
`COVERAGE_SITE_ROLES`, one environment variable would put every client
node on the mesh onto a public page. A test pins that:
`test_a_diagnostic_run_can_never_widen_the_public_map`.

**The dashboard keeps it, and the dashboard is not public.** The tile
route under `/api/coverage` serves a diagnostic run — that is the whole
point of the feature, because the dashboard is the audience for it.
Anybody who can reach the dashboard API can read those tiles. That
route is not part of the public surface and a proxy must not open it:
`docs/API.md` 3B.5 is the exact list of paths the embed needs. If the
dashboard itself is exposed to the open internet on a deployment, do not
leave a diagnostic run published: set `COVERAGE_SITE_ROLES` back and run
`sonoran-coverage-once`.

**This was a real defect and it is worth knowing the shape of it.** The
embed used to draw its tiles from `/api/coverage/tiles`, so publishing
the embed meant opening that path. The site set is a path segment
there, so one substitution returned the client-node map of the same
run, and a diagnostic run written under `infrastructure` was reachable
behind nothing but a stamp on a fixed six-hour cadence. The page held
the site set in a JavaScript constant, which constrained an honest
browser and nothing else. The locks now sit on the route.

## 4. Two directions, and why the default is the weaker one

A coverage map has two questions in it:

- Can I hear the mesh from here? The node transmits.
- Can the mesh hear me from here? The handheld transmits.

A node on a 30 m mast talking to a handheld at 1.5 m is not the same
link as the reverse. A carrier map shows the first, because that is
what sells telephones. Showing only that here would promise reach a
handheld cannot return.

So a run writes three layers, and the page opens on `usable`, which is
the weaker of the two.

Both come from one engine run. The path loss does not care which end
transmits, as long as the two antenna heights stay where they are.
Writing the engine field at a point as `F = EIRP_node - L`:

    down = F + G_hand - loss_hand
    up   = EIRP_hand - L + G_node - cable_node
         = F + EIRP_hand - P_node

The whole antenna of the node cancels between them, because it helps
the same amount either way, and what is left is

    up - down = P_hand - P_node

A node that shouts at 30 dBm is heard 8 dB further than it hears a
handheld that shouts at 22. See `coverage/sites.py`.

**The weaker of the two for one node, and only then the best node.**
The order matters and it is easy to get wrong. Taking the best of each
direction across every site first, and the weaker of the two
afterwards, lets one node answer for the downlink and a different node
answer for the uplink, and paints a place as usable both ways where no
single radio closes both. A tall router a handheld cannot answer,
beside a solar node the handheld can reach but which cannot be heard,
is exactly that place, and the mesh does not work there. `usable` is
therefore built in `_predict`, beside the two directions, and is not
derived from them afterwards.

## 5. One preset at a time

A node on Long fast cannot hear a node on Medium fast. Merging their
coverage draws a mesh that does not exist. See `AGENTS.md` 9.7.

So a run is keyed on the preset, and the preset is not a filter on the
display: it also sets the receiver sensitivity, which is the threshold
the whole map is drawn against.

A node whose channel is not a default preset name rides on top of one
and does not name it. Weather and PKI are the examples this mesh has.
Such a node is left out rather than guessed at.

## 6. The grid

Every raster the engine makes sits on the same lattice. The engine
works at a whole number of points for each degree and its region always
starts at a whole degree, so a cell edge is always at `k / 1200`
degrees.

A raster is therefore **placed** on the region grid at a whole cell
offset, not resampled onto it. Resampling would blur every ridge line
the model worked to find.

Levels are held the way the engine reports them: one unsigned byte,
`dBm = byte - 200`, and zero meaning no run reached the cell. A signed
byte reaches only -128 and the sensitivity of Long fast is -139 dBm.
See `AGENTS.md` 9.16.2.

### 6.1 What the page draws

The page has three independent display layers: the map, the nodes, and
the signal strength. A reader can leave only the ground, compare node
positions with the prediction, or remove the ground and inspect the
prediction by itself.

No coverage is transparent. Usable coverage is nearly opaque and runs
from hot pink at the receiver limit to bright blue at 30 dB of margin.
The terrain map does not use that ramp. The edge and the direction of
improvement therefore remain visible over roads, desert, and forest.

## 7. Clutter

ITM treats both ends of a path as if they stood in open country. The
last few metres at each end are what a real link loses, and this is
where they are charged.

### 7.1 Not the clutter the engine takes

`splat_create` takes a clutter height, and SPLAT uses it by raising the
ground. Measured on flat ground at 906 MHz over a 20 km radius:

| clutter | tx 3 m | tx 9 m | tx 30 m |
|---|---|---|---|
| 0 m | -118.6 dB | -107.9 dB | -95.2 dB |
| 5 m | -158.8 | -109.0 | -95.2 |
| 9 m | -185.1 | -108.6 | -95.2 |
| 15 m | -189.6 | -172.5 | -95.2 |

That is a cliff. Nothing at all while the antenna clears the clutter,
then forty to seventy dB once it does not. The receiving end is charged
0.00 dB at any height, and the map is drawn for a handheld at 1.5 m.

`test_the_engine_clutter_is_a_cliff` keeps that measurement, so a
future engine that gives the value another meaning says so.

### 7.2 What is charged instead

ITU-R P.2108-1 section 3.1, the height gain terminal correction. It is
valid from 0.03 to 3 GHz and the US band sits inside it. The engine is
given no clutter at all, and the loss is taken off the field at each
end. A 1.5 m handheld pays:

| Land cover | Nominal height | Loss |
|---|---|---|
| Tree cover | 15 m | 23 dB |
| Mangroves | 10 m | 19 dB |
| Built-up | 9 m | 18 dB |
| Shrubland | 2 m | 3 dB |
| Grassland, cropland, bare, water | 1 m or less | 0 dB |

A terminal at or above the clutter pays nothing, which is the
recommendation's own boundary and the sense of it: an antenna above the
roofs sees over them. Below it the loss is a curve, so a node a metre
shorter than its neighbour does not lose its whole footprint.

The recommendation gives two forms and they are not interchangeable.
Buildings and trees are obstacles a signal bends over. Scrub and grass
are a height gain against the ground. See P.2108 Table 3.

`tools/prefetch_landcover.py` reduces the ESA WorldCover 10 m product
to the same page grid the terrain uses, one byte for each cell, holding
the most common class in it. The most common and not the average: a
class is a name, not a number, and the average of water and built-up is
not a meadow.

### 7.3 What this replaced, and why it was worse than nothing

The old rule returned a height for the engine, and returned zero when
the antenna was at least as tall as the nominal class height. The
default antenna is 3 m. Arizona is 56 percent shrubland at 2 m, 12
percent grassland and 10 percent bare ground, so over about 78 percent
of the state the answer was zero and nothing was charged. In a town it
passed 9 m to the engine and took the node off the map altogether.

The page said "buildings and trees accounted for" in both cases.

A node above the roofs still takes nothing. Set `above_clutter` in the
overrides file, or give it a mast taller than the clutter around it.

A deployment with no land cover pages predicts with no clutter, which
is what the planner has always done. The page says so rather than let a
reader believe buildings were accounted for.

## 8. Calibration

The prediction starts from a hardware model and a guess. The mesh knows
better: it hears its own links every day.

`jobs/calibrate.py` reads `neighbor_metrics`, which is a node reporting
the neighbours it hears itself. `AGENTS.md` 9.5 says to use it, and it
is right: only about five percent of gateway observations are direct
links, and `packet_seen` can only ever record MQTT gateways.

The fit gives one offset for each node, appearing at both ends of every
link it is in, because a wrong antenna helps the same amount whichever
end transmits.

Each neighbour report keeps the channel it arrived on. The calibration
uses it only when that channel and both current nodes name the same
modem preset. A node can change preset during the calibration window.
An old report must not correct its new radio configuration.

### 8.1 The part that is easy to get wrong

The mesh only reports links that worked. Fitting those alone says every
node is better than it is, and that bias draws reach that is not there.

A node that publishes a neighbour list is also telling us about the
nodes it left out. Where the model says it should have heard one, the
link is below the sensitivity of the preset and by how much is unknown.
Those are kept as censored measurements and filled in with the mean of
the truncated normal they must have come from.

`test_the_fit_recovers_planted_offsets_through_censoring` plants
offsets, hides the links below the limit, and asserts that using the
hidden ones beats ignoring them.

### 8.2 What stops it moving the map on noise

| Guard | Value |
|---|---|
| The fit as a whole is ignored above this model bias | 20 dB |
| The fit as a whole is ignored above this scatter | 20 dB |
| A node is ignored above this scatter | 20 dB |
| A node needs this many links | 6 |
| A node needs this many counterparties | 3 |
| A node needs this many links that really worked | 2 |
| An offset is clamped at | 15 dB |
| A node may be pinned at zero inside the fit | `lock_calibration` |

The solver enforces the 15 dB bound during each fit round. This stops a
node with mostly silent links from pulling the other offsets away. The
stored-value reader and the radio-profile resolver enforce the same
bound again. The API shows no offset for a node that does not have
enough evidence.

### 8.2.1 A pinned node is pinned inside the fit

`lock_calibration` in `config/nodes.yaml` says the radio facts of a
node are already known to be right. The fit therefore holds that node
at zero **while it solves**. It is not a parameter the solver has, so
every link the node is in charges the whole of its residual to the
other end and to the model bias.

It used to be fitted like any other node and only dropped on the way to
the map. That is not the same answer. A free offset on a pinned node
absorbs evidence that belongs elsewhere, and a node whose build somebody
has measured came out of a live fit at +2.77 dB.

A pinned node is also the anchor. The zero-sum rule exists only to
remove the one freedom the model has — adding a constant to every offset
and taking twice it off the bias predicts the same thing — and a node
held at zero removes that freedom already. So the fit re-centres nothing
when anything is pinned, and **the model bias it reports is then measured
against the pinned radios** rather than against the average of every
guess. That is the point of pinning: a mesh-wide number that means
something needs a reference somebody measured.

The 15 dB bound still applies to every node that is not pinned. The
bound used to be enforced by the same projection that held the sum at
zero, and a pinned fit does not run that projection, so the bound is
applied on its own. `test_pinning_a_node_still_bounds_the_others` pins
it, because dropping it would give back the unbounded estimate that
`AGENTS.md` 9.21 exists about.

Three places refuse to apply a pinned offset, and each one is cheap:
the fit writes zero, `store.calibration_offsets` skips any node the file
marks `locked`, and `radio/resolve.py` ignores the offset of a locked
node whatever it holds. The middle one matters for a file written before
a lock was added.

A model bias is one error over the whole mesh. A value past 20 dB says
the propagation model or the silent-link assumption does not describe
the current evidence. Sonoran then uses no per-node correction.

The scatter is measured on the reported links only. A filled in link
was invented from the fit, so counting it would flatter the fit with
its own guesses.

## 9. Running it

The job runs on a timer in the jobs process. When calibration is due,
it finishes before coverage starts. The coverage run then reads the
new calibration file.

To run one by hand, now, instead of waiting for the timer:

```bash
sonoran-coverage-once                      # on the host
docker compose exec jobs sonoran-coverage-once   # in the image
```

It writes into the same cache and publishes the same way, so the
schedule carries on from where it left off. That is the answer to
"make sure this is one time and updates on a schedule": the timer is
the schedule, and this is the one time.

Fill the caches once:

```bash
uv run python tools/prefetch_terrain.py
uv pip install "rasterio>=1.3"
uv run python tools/prefetch_landcover.py
```

`rasterio` is needed only by that tool. The API and the jobs read the
plain byte pages it writes, with numpy.

### 9.1 What a run costs

The engine is a tight loop of floating point and takes a few seconds
for each node, so the work is split across worker processes.
`COVERAGE_WORKERS` is zero by default, which means as many as the
machine has, less one.

**A run is niced, and on a small box it should also be narrowed.** The
engine has no IO to yield on, so a worker holds its core solid for
minutes. On a machine that also serves the dashboard and takes MQTT
that is felt by everybody using it — the first person to try this on a
small-form-factor box reported it audibly. `COVERAGE_WORKER_NICE` is 10
by default, which is a background batch job: the kernel still gives the
run every idle cycle and hands the CPU straight back the moment a
request arrives.

For the smallest deployment, `COVERAGE_WORKERS=1` with the default
niceness is one low priority worker. A fifty site run then takes about
fifteen minutes instead of five, against an interval of six hours, and
the machine stays responsive throughout.

The niceness is applied in the worker initialiser and never in the
jobs process. A process cannot raise its own priority back afterwards,
and the jobs process also runs the snapshot and the calibration. For
the same reason a negative value is refused rather than acted on, and
one worker is still a worker process: a run inside the jobs process
could not be niced without slowing every other job down for good.

The cost is roughly linear in the number of nodes and grows with the
square of `COVERAGE_RADIUS_KM`. A radius below the real reach of a tall
router understates the mesh, and one far above it costs time for
coverage nobody has.

A measured run, on four cores with three workers, at the default 60 km
radius and zoom 6 to 11:

| | |
|---|---|
| Sites | 284, over two presets |
| Time | 1931 s, which is 32 minutes |
| Rate | 25 sites every 165 s, and it did not slow down |
| Tiles written | 3309 |
| Memory | About 1 GB for the whole run, flat |

The rate held from the first quarter to the last, which is what a
bounded working set looks like. See 9.2.

That is well inside `COVERAGE_INTERVAL_HOURS`, which is 6 by default.
The scheduler waits for a task to finish and only then counts the
delay, so a run that took longer than its interval would push the next
one out rather than start beside it. At the `COVERAGE_MAX_NODES` cap of
600 the same machine would take about 70 minutes, which still fits.

The machine this was measured on held 24 of the 64 terrain tiles the
run wanted, so part of it predicted over flat ground. A deployment with
the whole cache is slower than this, not faster.

The figure that matters for a deployment is the whole Arizona mesh at
the defaults. Fifty sites, a 60 km radius, zoom 6 to 11, on four cores
with three workers:

| | |
|---|---|
| Time | 307 s |
| Peak memory | 441 MB |
| Duty cycle against `COVERAGE_INTERVAL_HOURS` of 6 | 1.4% |

The role test is what made that possible. The same machine took 1931 s
over 284 sites before it, and a run of every positioned node was ended
by the memory killer at 4.7 GB in each worker.

### 9.1.1 What the accuracy rules cost in area

Measured on the development mesh, which is 17 nodes of which 4 are
routers:

| | Sites | Usable |
|---|---|---|
| Every positioned node, old clutter rule | 17 | 16,972 km² |
| Infrastructure only | 4 | 4,813 km² |
| ...and the clutter charged at both ends | 4 | 4,435 km² |
| ...and a router assumed to be on a mast | 4 | 4,908 km² |

The role test does most of it. The mast height puts eleven percent
back, which is the one correction that goes the other way: a router
really does reach further than a shed roof.

**The clutter figure understates it, and the reason is worth knowing.**
That machine held one land cover page, N33W112, out of the eighty one
degrees the region covers. Clutter was charged around Phoenix and
nowhere else. A deployment that has run `tools/prefetch_landcover.py`
for the whole region will see a larger reduction, concentrated in the
built-up degrees. `has_landcover` is true only when every degree has a
page, and the manifest names the ones that do not, so the page cannot
claim buildings were accounted for when they were not.

A map that is a third of the size is not a worse map. The area it lost
was never there.

### 9.1.2 What the live mesh actually looks like

Measured against the Arizona mesh, 2,381 nodes of which 931 report a
position:

| Role | Nodes | |
|---|---|---|
| CLIENT | 370 | 39.7% |
| CLIENT_MUTE | 260 | 27.9% |
| No role reported | 158 | 17.0% |
| CLIENT_BASE | 89 | 9.6% |
| ROUTER_LATE | 35 | 3.8% |
| ROUTER | 15 | 1.6% |
| TRACKER | 4 | 0.4% |

**Fifty nodes of 931 are infrastructure.** That is the number the role
test exists for.

Position precision is the harder half. Of those 50:

| Precision | Deviation | Nodes |
|---|---|---|
| 13 bits | 2.9 km | 24 |
| 14 bits | 1459 m | 7 |
| 15 bits | 729 m | 3 |
| 17 bits | 182 m | 4 |
| 18 bits | 91 m | 3 |
| 32 bits | exact | 9 |

So `COVERAGE_MIN_PRECISION_BITS` at 16 keeps **16 of the 50**, and the
other 34 need a position in `config/nodes.yaml`.

That is a real cost and it is the right default. A run of the whole
mesh at both settings:

| | Sites | Usable |
|---|---|---|
| 16 bits, the default | 16 | 11,065 km² |
| 0, trusting the broker | 50 | 21,001 km² |

Half the coverage in the second row rests on positions rounded to
between 2.9 and 23 km, over terrain that is 90 m across. A node can sit
on either side of a ridge at that distance. The map would claim ground
nobody can use, which is the failure this whole page is about.

The way to have both is the overrides file. An operator knows where
their own router is, and a position given there is used as exact.

**And the page names them, not just the count.** "Give each one a
latitude and longitude in config/nodes.yaml" is not something anybody
can act on without knowing which ones. The manifest carries
`coarse_sites` — up to `COARSE_REPORT_LIMIT` of them, coarsest first —
and the coverage page renders a block ready to paste into
`config/nodes.yaml`, with the rounded position filled in as a starting
point and the deviation in the comment beside each name.

The rounded position names the area and not the mast, so each one
still has to be corrected by somebody who knows the site. It saves the
looking up, not the knowing. A test pins that the block the page
writes is the shape `parse_overrides` reads, because the two are in
different languages and nothing else connects them.

`COVERAGE_MIN_PRECISION_BITS` may be set to zero by a deployment that
reads its own broker, where every position arrives at full precision.

### 9.1.2.2 Predicting from the nodes that repeat

The map predicts from routers and repeaters because only a node that
stays where it is can hold coverage open. That is the right default and
it is not the only question. A mesh also carries traffic on ordinary
nodes, and "why does my neighbourhood work when no router covers it" is
a question about those.

`COVERAGE_INCLUDE_CLIENTS=true` makes a run publish a second map beside
the first, predicted from the roles that repeat traffic without being
infrastructure. The dashboard then offers a picker, and the
infrastructure map stays the view a reader gets without choosing
anything.

Which roles, and why, quoted from `meshtastic/config.proto`:

| Role | In | Why |
|---|---|---|
| `ROUTER`, `ROUTER_LATE`, `REPEATER` | yes | The infrastructure set. Unchanged. |
| `CLIENT` | yes | The default role. `CLIENT_MUTE` is defined as the one that does not forward, which leaves this one that does. |
| `CLIENT_BASE` | yes | "Used for stronger attic/roof nodes to distribute messages more widely." A roof node that stays on the roof. |
| `ROUTER_CLIENT` | yes | "Combination of both ROUTER and CLIENT." Deprecated, still set on live nodes. |
| `CLIENT_MUTE` | no | "Device that does not forward packets from other devices." |
| `CLIENT_HIDDEN` | no | Rebroadcasts "local only", and its stated purpose is stealth. |
| `TRACKER`, `TAK_TRACKER` | no | Mobile by definition. |
| `SENSOR`, `TAK`, `LOST_AND_FOUND` | no | The proto never says whether they forward, so nothing is asserted. |
| no role | no | See `AGENTS.md` 9.22. NULL is a client or an unintroduced node. |

**The cost is the reason it is off by default.** A run predicts from
every site it is given, and a mesh has far more clients than routers:
on the Arizona mesh about fifty infrastructure nodes against nine
hundred clients, capped by `COVERAGE_MAX_NODES`.

**It is a diagnostic and the public embed never serves it.** A client
is usually somebody's house, and a footprint has a centre. The public
tile route takes no site set at all, so there is nowhere to ask for
this map: see `AGENTS.md` 9.25 and 9.27 for each lock and why it is
load-bearing.

Read the wider map for what it is. A handheld that crossed town once
still draws a footprint where it stood, and the mesh will not be there
tomorrow. The infrastructure map is the one to publish.

### 9.1.3 Is the map right?

A prediction can be self consistent and still be wrong. The one test
that means anything is whether the map contains the nodes the mesh
demonstrably reaches.

`tools/validate_coverage.py` does it. It reads a node list from a
MeshMonitor instance, samples the tiles of the current run at each
node, and reports how many agree:

```bash
uv run python tools/validate_coverage.py https://mesh.example.org
```

Against the live Arizona mesh, 16 sites, the `usable` layer:

| | Inside the map |
|---|---|
| All 826 nodes reached over the radio | 88.9% |
| Heard directly, no hops | 92.3% |
| One hop away | 94.8% |
| Two hops or more | 88.0% |

A hundred percent is neither expected nor wanted. A node reached over
four hops can sit well outside any one site and still work, which is
what the mesh is for. The figure to watch is the one for nodes heard
directly: those are inside one site's footprint by definition, so the
map should contain them.

A number that falls is a warning. A number near a hundred across every
hop count means the map has stopped saying no to anything.

The test says nothing about the ground between the nodes, because
nothing has ever stood there with a radio. It bounds the map from one
side only.

### 9.2 What a run holds in memory

Memory, not time, is what stops a large run. A three hundred node run
was ended by the memory killer with each worker at 4.7 GB, and the
first build was wrong in two ways at once.

**The engine heap.** A worker made a new engine instance for every
site. An instance owns a WebAssembly linear memory, and a dropped
instance never gives it back. See `AGENTS.md` 9.16.4. This was the
large one. A worker now makes one instance when it starts and uses it
for every site it takes, which is what the browser worker has always
done.

**The terrain.** The parent read every page the run wanted and sent the
whole set to each worker through the pool. Each process now reads the
pages it needs from the disk cache and holds `PAGE_CACHE_SIZE` of them.
One engine run at a 60 km radius reads about nine pages, and the sites
are predicted one after another over ground that mostly repeats, so the
hold serves nearly every read.

| What | Cost |
|---|---|
| One engine instance, reused | About 20 MB at a 20 km radius, and it stays flat |
| One terrain page | 2.7 MB |
| The terrain hold in one process | 43 MB, whatever the size of the region |
| One region grid of Arizona | 88 MB |
| A preset being built | Two grids, and a third while it is rendered |

`_build` releases the grids of a preset before it starts the next one.

A worker that dies still takes the whole pool with it. That now costs
time and not the run: the preset is predicted again in the jobs process
alone, from empty grids, so no site is counted twice.

## 10. The public embed

`/embed/coverage` is a page for somebody else's website. It is off
until `EMBED_ENABLED` is true.

It is its own document. The dashboard carries `serial=(self)` so the
config checker can read a node over USB, and framing that page would
take Web Serial onto a third party site.

That path alone sends no `X-Frame-Options` and sets `frame-ancestors`
from `EMBED_FRAME_ANCESTORS`. Every other path keeps `DENY` and
`'none'`, and the tests still assert exactly that.

It shows routers, repeaters, and MQTT gateways, with positions snapped
to a grid before they leave the process. A client node is usually a
person, often at home, and never appears.

### 10.1 What a proxy opens

`docs/API.md` 3B.5 holds the exact list, and it is short: the embed
document, three `/api/embed/` endpoints — one of them the tiles — and
three static files the page loads.

**Never `/api/coverage` by prefix.** The embed's tiles used to come
from `/api/coverage/tiles`, which is the dashboard's route: it takes
the site set from the path, carries no `EMBED_ENABLED` dependency, and
serves a diagnostic run. Opening that prefix also publishes
`/api/coverage`, whose `coarse_sites` and `presets[].nodes` carry node
names and positions, and `/api/coverage/calibration`, which names what
each node measured.

The public tiles are `/api/embed/tiles/{stamp}/{preset}/{layer}/...`.
No site set in the URL, the stamp must be the published run, and a
diagnostic run answers 404 before a handler runs.

### 10.2 Before turning it on

`EMBED_ENABLED` defaults to false, and the switch is the owner's to
throw. What it opens is the list above and nothing else. Set
`EMBED_FRAME_ANCESTORS` to the sites that may frame the page: an empty
list means nobody may, and a value that is not an origin is dropped
rather than widened.

## 11. Limits

1. The map is drawn against one receiver: a handheld with a stock
   antenna, at `COVERAGE_RX_HEIGHT_M`. A radio in a pocket or a car
   does worse.
2. Terrain is 90 m. See `docs/ISSUES.md` 2.5.
3. Clutter is a terminal correction, not a surface model. A single
   tall building between two nodes is not in it.
4. The calibration reads neighbour reports only. See
   `docs/ISSUES.md` 2.4.1.
5. Only a router, a router late, or a repeater is a site. A client
   node moves, and a footprint drawn around it promises reach that
   nobody can use tomorrow. A node with no role is a client: the
   firmware numbers `CLIENT` as zero and the ingest stores a zero enum
   as NULL, so the two cannot be told apart. See `sonoran/roles.py`.
6. A position the public broker fuzzed cannot anchor a prediction. The
   broker sends between 10 and 16 bits, which is 23 km to 365 m, and
   the terrain under a prediction is 90 m across. A node that never
   said its precision counts as exact, because that is the ordinary
   case for a node heard over the radio.
7. `coverage_max_nodes` caps a run. The strongest sites are kept, and
   the manifest says how many were left out.
8. The manifest counts every node left out, by role and by the
   coarseness of its position, and the page shows both. A map that
   drops nine nodes in ten must say so.
