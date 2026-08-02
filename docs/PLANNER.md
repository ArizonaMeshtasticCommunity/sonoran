# PLANNER.md — The coverage planner

This document describes the Coverage planner page.
It uses ASD-STE100 Simplified Technical English.

## 1. What it does

The planner answers one question: if a radio stood here, who would hear
it?

It predicts the signal over the ground around a chosen point, draws the
result on a map, and then tests every node this mesh knows against it.
The last step is the reason the page exists. The Meshtastic Site Planner
already predicts coverage well, but it knows nothing about our nodes.
This page reports "reaches 14 of 285 nodes", and names them.

The prediction is not a promise. It assumes clear ground, the receiver
figures in the form, and average air. Real radios do worse.

## 2. Where the work happens

```
browser                                  this server
-------                                  -----------
form -> engine parameters
        |
        +-- worker: which pages? ----->
        |
        +-- read each page  ---------->  GET /api/terrain/page/N34W112
        |                                  cache hit  -> the page
        |                                  cache miss -> download, transform, keep
        |
        +-- 4 workers run the radials
        |   (SPLAT! ITM, WebAssembly)
        |
        +-- merge, colour, draw
        |
        +-- test every node from /api/map/nodes
```

The model runs in the browser. The server only supplies terrain and the
node list. No prediction is ever computed on the server, and no site
plan is ever sent to it.

The radials are split between up to four workers. SPLAT! computes each
point at the first radial that reaches it, so merging the workers in
radial order with "the first to set a cell wins" gives the same answer
one thread would have given.

## 3. Terrain

See `docs/ARCHITECTURE.md` section 3.8 for the page format and the
transform.

Fill the cache once after deployment:

```
uv run python tools/prefetch_terrain.py
```

For the Arizona region that is 64 tiles: about 640 MB downloaded, about
184 MB kept. Roughly two seconds per tile. The run is safe to stop and
start again.

Then set `TERRAIN_ALLOW_DOWNLOAD=false`. The API serves the cache and
makes no outbound request.

To fetch one tile only:

```
uv run python tools/prefetch_terrain.py --lat 34 --lon -112
```

The cache lives on a Docker volume. The directory must belong to the
application user: a new named volume takes the owner of the directory it
covers, so the image creates it. Without that the container downloads
each tile and then cannot keep it.

A tile the service does not hold is answered with 404. The engine reads
a page it was never given as sea level, so a run reaching past the edge
of the region draws coverage over flat ground. The page warns when that
happens, and refuses when no tile of the run is held at all.

## 4. Parameters

Antenna heights are entered in **metres**. The engine takes feet, and
`planner-params.js` converts. Feeding metres straight through would
overstate every antenna by 3.28 times.

### Transmitter

| Field | Units | Default | Notes |
|---|---|---|---|
| Site name | text | empty | A label only. |
| Latitude, Longitude | degrees | none | Click the map, or click a node. |
| Antenna height | m | 3 | Above the ground, including the mast. |
| Power | dBm | 30 | 30 dBm is 1 W. Use the figure for your region. |
| Antenna gain | dBi | 2.15 | A stock rubber antenna. |
| Frequency | MHz | 906.875 | The middle of the US 915 band. |

### Receiver

| Field | Units | Default | Notes |
|---|---|---|---|
| Modem preset | choice | Long fast | Sets the sensitivity below. |
| Sensitivity | dBm | -139 | Edit it down in town. See 4.1. |
| Height | m | 1 | A handheld radio. |
| Antenna gain | dBi | 2.15 | |
| Cable loss | dB | 2 | Applied at both ends. |

### Ground and air

| Field | Units | Default | Notes |
|---|---|---|---|
| Radio climate | choice | Desert | Right for Arizona. |
| Polarization | choice | Vertical | Meshtastic is vertical. |
| Clutter height | m | 0 | Average height of trees and buildings. |
| Range | km | 30 | The largest the engine plots is 150. |
| Ground dielectric | | 15 | Leave it. |
| Ground conductivity | S/m | 0.005 | Leave it. |
| Atmosphere bending | N-units | 301 | Leave it. |
| Situation fraction | % | 50 | Of places where the prediction holds. |
| Time fraction | % | 90 | Of the time it holds. |

### 4.1 Sensitivity by preset

| Preset | Spreading factor | Bandwidth | Sensitivity |
|---|---|---|---|
| Short turbo | SF7 | 500 kHz | -126 dBm |
| Short fast | SF7 | 250 kHz | -129 dBm |
| Short slow | SF8 | 250 kHz | -131.5 dBm |
| Medium fast | SF9 | 250 kHz | -134 dBm |
| Medium slow | SF10 | 250 kHz | -136.5 dBm |
| Long fast | SF11 | 250 kHz | -139 dBm |
| Long moderate | SF11 | 125 kHz | -142 dBm |
| Long slow | SF12 | 125 kHz | -144.5 dBm |
| Very long slow | SF12 | 62.5 kHz | -147.5 dBm |

These are the figures from the SX1262 data sheet, which is the best a
radio can do. Where the band is shared and noisy, take several dB off.

A preset is also a radio configuration, not only a sensitivity. A node
on Long fast cannot hear a node on Medium fast at all. See `AGENTS.md`
9.7. The planner predicts one preset at a time, and the nodes it counts
are every node with a position, whatever preset each one runs.

## 5. Reading the result

- The colour runs from the receiver's limit, at the dim end, to 60 dB
  above it. Ground below the limit is left clear.
- A green node is reached. A faded node is not.
- **Ground covered** is the area at or above the limit, which is not the
  same as the area a node would work in.
- **Furthest node** is the greatest distance to a node that is reached,
  not the greatest distance the signal travels.

Coverage that follows ridge lines and stops at them is the model working.
A smooth circle means the terrain did not load: look for 404 responses
from `/api/terrain/page/`.

### One link

Click a node and choose "Check this link". This runs the same model over
the single path to that node and draws the ground between the two ends.
It reports the margin above or below the receiver, the path loss, and
the bearing.

A hill that touches the straight line between the ends is the usual
reason a link does not work.

## 6. Licence

The prediction engine is the ITM / Longley-Rice model from SPLAT! by
John A. Magliacane, KD2BD, compiled to WebAssembly by the Meshtastic
Site Planner project.

- https://github.com/meshtastic/meshtastic-site-planner
- Licensed under the GNU General Public License, version 3.

`src/sonoran/web/static/vendor/splat/` holds the engine, the licence,
and the upstream commit it came from. Sonoran uses that engine, so the
Sonoran web interface is a work based on it and carries the same
licence. Do not remove the attribution.

`planner.js`, `planner-params.js` and `planner.worker.js` are written
for this project, because the upstream interface is a Vue application
with a build step and this project has none. They follow the upstream
engine sources closely, and the comments name them.

## 7. Limits

- One transmitter for each run. Merged coverage from several sites is
  not built.
- Terrain is 90 m. The engine can read 30 m, which is nine times the
  data and is not served.
- A plan cannot be saved or linked to. Nothing is stored anywhere.
- The area figure counts ground, not population and not roads.
