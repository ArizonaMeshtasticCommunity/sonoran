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
node list. **No plan made on this page is ever computed on the server,
and no site plan is ever sent to it.** A person may try a mast anywhere
without telling anybody where they are thinking of putting it.

That rule is about this page. It is not a rule about the engine.

The coverage map is a different feature and runs the same engine in the
jobs process, because a map of the whole mesh cannot be recomputed by
every reader and a public embed must be cacheable. It predicts from the
nodes the mesh already reports, so it holds no private plan. See
`sonoran/coverage/` and `docs/ARCHITECTURE.md` 3.6.2.

One WebAssembly file serves both. `tools/dev/engine_parity.js` and
`tests/unit/test_coverage_engine.py` pin the two to the same rasters, so
this page and the published map cannot predict different things.

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

The antenna heights, the clutter height and the range are entered in
the reader's units: feet and miles by default, metres and kilometres
when the units setting says metric. Each label names the unit its box is
in, and the label and the box change together when the setting changes.

Only the box follows the setting. Inside the page the form holds metres
and kilometres, the share link carries them (5.1), and the engine takes
feet converted from those metres. `planner-params.js` converts in both
places. Feeding metres straight through to the engine would overstate
every antenna by 3.28 times.

The conversion happens at the box and nowhere else (`UNIT_BOXES`,
`toBox`, `fromBox` and `readBox` in `planner-params.js`):

- A box shows its metric value in the reader's units, to a hundredth.
- A value the reader types is converted to metres, kept to a millionth.
  That is enough for 20 ft typed and 6.096 m typed to be the same
  number, and so the same prediction.
- A box the reader has not touched is never converted back. The page
  holds the metric value beside the text it wrote and uses that value
  until the text changes. 6 m shows as 19.69 ft, and 19.69 ft is
  6.0015 m, so reading the display back would move the antenna and
  change the link.

`tests/unit/test_planner_units_follow_the_setting.py` runs the engine on
the same antenna typed both ways and on a link opened in each unit
system, and asserts the same map (#246).

The cable length is feet for every reader. Cable is sold in feet and the
catalogue's figures are per 100 ft.

### Simple and Advanced

The form opens in **Simple**, which asks for the site, the two antenna
heights, the modem preset and the three pickers (your radio, your
antennas, your cable). Everything else is under **Advanced**: the
frequency and its slot, the receiver sensitivity, the gains, the power,
the cable loss, and all of Ground and air.

Nothing is removed and nothing is cleared. Simple hides the boxes with
CSS, so every value is still read, still predicted from, and still
carried in a share link. Switching mode changes what you are asked for
and never what gets predicted. Simple predicts on `desert`, vertical,
no clutter and 30 km.

A newcomer in Flagstaff is the case `desert` is wrong for. Reading the
climate from the coordinate is #239, and until that lands a default that
is openly a default is better than a lookup that is confidently wrong.

### Finding the site by name

The site box takes an address or a place name. The lookup goes to
`/api/geocode` on this server, which forwards it to the configured
geocoder; answers outside the region above are dropped. It is the only
reader-supplied text this dashboard sends anywhere, and it goes through
the server so that a geocoder never sees who asked. `GEOCODE_URL` empty
turns the feature off and the box is not drawn. See
`src/sonoran/api/routes/geocode.py`.

Nothing else changed about §2: no coordinate, no antenna and no
prediction is ever sent to the server.

### Transmitter

| Field | Units | Default | Notes |
|---|---|---|---|
| Site name | text | empty | A label only. |
| Latitude, Longitude | degrees | none | Click the map, or click a node. |
| Antenna height | ft or m | 3 m (9.84 ft) | Above the ground, including the mast. |
| Power | dBm | 30 | 30 dBm is 1 W. Use the figure for your region. |
| Antenna gain | dBi | 2.15 | A stock rubber antenna. |
| Pointing which way? | degrees | empty | Directional antennas only. Clockwise from true north. See 4.3. |
| Beamwidth | degrees | empty | Only when the antenna's listing states none. See 4.3. |

### Receiver

| Field | Units | Default | Notes |
|---|---|---|---|
| Modem preset | choice | Medium fast | Sets the sensitivity and the slot width. |
| Frequency slot | choice | 18 | `lora.channel_num` on the radio. Counts from 1. |
| Frequency | MHz | 906.375 | Slot 18 at 250 kHz. Follows the slot. |
| Sensitivity | dBm | -134 | Edit it down in town. See 4.1. |
| Height | ft or m | 1 m (3.28 ft) | A handheld radio. |
| Antenna gain | dBi | 2.15 | |
| Cable loss | dB | 2 | Applied at both ends. |

### Ground and air

| Field | Units | Default | Notes |
|---|---|---|---|
| Radio climate | choice | Desert | Right for Arizona. |
| Polarization | choice | Vertical | Meshtastic is vertical. |
| Clutter height | ft or m | 0 | Average height of trees and buildings. |
| Range | mi or km | 30 km (18.64 mi) | The largest the engine plots is 150 km. |
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

### 4.2 Preset, slot and frequency

These three are one setting said three ways, and each of them can be
edited. The band is 902 to 928 MHz, a slot is one bandwidth wide, and a
node sits in the middle of one:

```
slots  = floor((928 MHz - 902 MHz) / bandwidth)
centre = 902 MHz + bandwidth / 2 + (slot - 1) x bandwidth
```

**The slot counts from 1.** It is `lora.channel_num` on the radio, the
number azmsh.net tells a new node to set. `sonoran/radio/channels.py`
reaches the same frequencies from a zero-based index, because there the
slot comes out of a hash of the channel name. The two differ by one, and
confusing them moves a prediction by a whole slot. LongFast is the check:
slot 20, 906.875 MHz.

What each edit does:

- **preset** sets the sensitivity it implies, keeps the slot number, and
  moves the frequency, because the slots are a different width.
- **slot** sets the frequency.
- **frequency** sets the slot, or says "not on a slot" when it is between
  two. A typed frequency is never moved: `lora.override_frequency` is a
  real setting and a licensed operator may sit anywhere.

Only the frequency is in a share link. A link carrying both could carry
two that disagree, and whoever opened it would have no way to tell.

The default is slot 18 on Medium fast, which is 906.375 MHz. That is the
azmsh.net metro recommendation. It used to be 906.875 MHz, which is
LongFast's slot 20 and nothing this mesh runs.

### 4.3 Directional antennas, and which way they point

The engine is omnidirectional. `_splat_create` takes one effective
radiated power and no azimuth, and this build has no antenna-pattern
file. A Yagi handed to it unchanged would draw a map that claims the
antenna is aimed at every point on the map at once.

So the pattern is applied **after** the engine finishes, in
`static/antenna-pattern.js`. This is exact, not a fudge, and the reason
is worth writing down: in the ITM model the path loss between two points
does not depend on the transmitted power. Received level is therefore

    radiated power + gain in that direction - path loss

and the engine's raster is a linear decibel scale (a byte holding
dBm + 200). Subtracting a per-direction figure from the finished raster
is the same arithmetic the engine would have done itself if it could
take a pattern. The run is made with the antenna's **boresight** gain,
which is what the picker fills into the gain box.

**The shape.** The main lobe uses the parabolic approximation that radio
planning generally uses, and that 3GPP specifies for sector antennas:

    loss_dB = 12 * (off_axis_deg / beamwidth_deg)^2

It is used because it is pinned to the only figure the product listings
give. "Beamwidth" means the angle between the half-power points, and at
half a beamwidth off boresight the formula returns exactly 3 dB — so it
agrees with the specification by construction rather than by fitting a
curve to it.

**What is not modelled.** Side lobes and the back lobe. No product page
read for this catalogue states a front-to-back ratio, so
`front_to_back_db` is `None` on every entry and the modelled loss is
capped at **15 dB** (`MAX_MODELLED_REJECTION_DB`). The cap is modest
deliberately: assuming deep rejection would paint confident emptiness
behind the antenna, and behind the antenna is where this model knows
least. **Coverage shown behind a directional antenna is the least
trustworthy part of the map.**

**A missing beamwidth is not filled in.** The L-Com 6 dBi Yagi's listing
states no beamwidth in either plane. The catalogue records `None`, the
planner shows a box to type one, and until it is typed the map stays
omnidirectional. It does not substitute a plausible number, because a
plausible number here is indistinguishable from a sourced one once it is
on the map.

**The bearing box.** It is shown only for an antenna that has to be
aimed, and it is not marked Advanced, so Simple shows it too. Empty
means "not aimed", never 0: 0 is due north. A run with a directional
antenna in the picker and no bearing is refused and asks for one, in
the same way as an empty picker (#314). Choosing an omni empties both
aiming boxes, because a hidden bearing must not shape the map. A width
that the catalogue filled in for one antenna is not kept for the next.
A share link carries the bearing and the width but not the antenna, so
a link with a bearing shows both boxes.

**The far end does not get a bearing.** A coverage map answers "who can
hear this site", so the receiver is every point on the map at once and
has no single direction it faces. Choosing a directional antenna for the
far end therefore assumes it is aimed straight at the site — its best
case — and the page says so in words. Modelling a misaimed receiver
would need a bearing per cell, which is a different question than this
page asks.

**Two numbers that are not comparable.** The 12 dBi Yagi claims a
32-degree vertical beamwidth, wider than the 10 dBi omni's 12 degrees.
That is not a transcription error. An omni buys gain only by flattening
its pattern, so for omnis more gain always means a narrower one; a Yagi
buys gain in azimuth as well, so the same relation does not hold across
the two kinds. The catalogue's tests enforce the ordering for omnis
only, for exactly this reason.

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

## 5.1 Sharing a plan

"Copy link" makes a URL that carries the form. Somebody who opens it
gets the same site, the same settings, and the prediction run again.

```
https://example.org/#planner?v=1&site_name=Shaw%20Butte&lat=33.5905&lon=-112.0865&tx_height=6&ran=2026-09-22
```

The prediction itself is not in the link. It is raster data made in the
browser by the WebAssembly engine, far too large for a URL, and the API
is GET only against a read-only role (`AGENTS.md` section 4), so there
is nowhere on the server to keep it. The same settings over the same
terrain give the same map, so the page that opens a link runs the model
again. A link with a site on it runs by itself; a link without one fills
the form and waits.

### What the link holds

| Key | Meaning |
|---|---|
| `v` | The format version. It is `1`. A link that names another version is still read, and the page says it did not know the number. |
| `ran` | The day the prediction behind the link was made, as `YYYY-MM-DD`. The page that opens the link prints it, because terrain and the node list move. |

Then any of the form fields, spelled as they are in
`DEFAULTS` in `planner-params.js`: `site_name`, `lat`, `lon`,
`tx_height`, `tx_power`, `tx_gain`, `tx_azimuth`, `tx_beamwidth`,
`frequency_mhz`, `preset`,
`sensitivity`, `rx_height`, `rx_gain`, `system_loss`, `radio_climate`,
`polarization`, `clutter_height`, `radius`, `ground_dielectric`,
`ground_conductivity`, `atmosphere_bending`, `situation_fraction`,
`time_fraction`.

Units are the form's, not the engine's. `radius` is in kilometres and
the heights are in metres. **They are metric whatever the reader's units
setting says**, and whatever units the boxes show: a link that changed
meaning with the setting of whoever opened it would predict two
different things. A reader in feet who types 20 writes `tx_height=6.096`,
and a metric reader who opens that link sees 6.096 m. See 4.

The **frequency slot is not in the link**. It is the frequency and the
preset's bandwidth said another way, so a link could carry two numbers
that disagree, and whoever received it could not tell which was meant.
The page works the slot out from the frequency. See 4.2.

Only what differs from the default is written. A link for a site with
one field changed is 115 characters; the same link with all 21 fields
in it is 478. `sensitivity` is left out when it is still the figure its
preset implies, and the page that opens the link puts it back from the
preset, so a link to Long fast arrives on Long fast's -139 dBm and not
on the form default.

Nothing goes in the link but what the reader typed. A site name and a
pair of coordinates are their own words.

### A link that has been edited

Every number is held to a sensible range, an unknown choice falls back
to the default, and an unknown key is dropped. Whatever was changed is
printed on the page rather than applied quietly:

```
#planner?v=9&radius=99999&tx_height=abc&preset=NOT_A_PRESET&nonsense=1
```

opens on a 150 km range, the default antenna height, the default
preset, and a line saying the version was not known, that the range was
held, that the height was not a number, and that `nonsense` was
ignored.

The address bar follows the form as settings are committed, so it is
always a link worth copying. It is rewritten with `history.replaceState`,
which fires no `hashchange`, so the page is not re-drawn and the back
button is not filled with one entry per edit.

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
- A plan can be linked to but not saved. The link carries the settings
  and the prediction is made again from them, so a plan opened later is
  drawn from the terrain and the node list as they are then. Nothing is
  stored on the server.
- The area figure counts ground, not population and not roads.
