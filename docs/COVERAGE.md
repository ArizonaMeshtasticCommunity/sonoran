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
| A node may be pinned entirely | `lock_calibration` |

The solver enforces the 15 dB bound during each fit round. This stops a
node with mostly silent links from pulling the other offsets away. The
stored-value reader and the radio-profile resolver enforce the same
bound again. The API shows no offset for a node that does not have
enough evidence.

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

To run one by hand:

```bash
uv run python -c "import asyncio; from sonoran.jobs.coverage import main; asyncio.run(main())"
```

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

### 9.1.1 What the accuracy rules cost in area

Measured on the development mesh, which is 17 nodes of which 4 are
routers:

| | Sites | Usable |
|---|---|---|
| Every positioned node, old clutter rule | 17 | 16,972 km² |
| Infrastructure only | 4 | 4,813 km² |
| ...and the clutter charged at both ends | 4 | 4,435 km² |
| ...and a router assumed to be on a mast | 4 | 4,908 km² |

The role test does most of it. The clutter takes off a further eight
percent here and would take off much more over a city, because Arizona
is mostly scrub and this seed is mostly not in Phoenix. The mast height
puts eleven percent back, which is the one correction that goes the
other way: a router really does reach further than a shed roof.

A map that is a third of the size is not a worse map. The area it lost
was never there.

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
