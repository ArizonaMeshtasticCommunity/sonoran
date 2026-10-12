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
        +-- climate of the site's square ->  GET /api/climate/page/N35W112
        |                                  (once: GET /api/climate/classes)
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

The model runs in the browser. The server only supplies terrain, the
climate map and the node list. **No plan made on this page is ever computed on the server,
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
and never what gets predicted. Simple predicts on the radio climate of
the site, vertical, no clutter and 30 km.

The climate is read from the site's own ground (#239, see 4.3). A line
under the site says which climate the next run will use and where it
came from, in both modes. In Advanced the climate menu opens on "From
the site", which names what it found, for example "From the site:
Continental temperate (Köppen Dsb)". Choosing another climate there
replaces it, is kept when the mode changes, and goes into a share link.

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
| Pointing which way? | degrees | empty | Directional antennas only. Clockwise from true north. See 4.4. |
| Beamwidth | degrees | empty | Only when the antenna's listing states none. See 4.4. |

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
| Radio climate | choice | From the site | Read from the site's Köppen-Geiger class. See 4.3. |
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

### 4.3 Radio climate

ITM (Longley-Rice) takes one of seven radio climates. The engine takes
them as numbers, which are the keys of `CLIMATE_CODES` in
`coverage/params.py` and `planner-params.js`:

| Code | ITM climate | Typified by (NTIA TR-82-100, Table 4) |
|---|---|---|
| 1 | Equatorial | the Congo |
| 2 | Continental subtropical | the Sudan |
| 3 | Maritime subtropical | the west coast of Africa |
| 4 | Desert | the Sahara |
| 5 | Continental temperate | large land masses in the temperate zone |
| 6 | Maritime temperate, over land | the United Kingdom and continental west coasts |
| 7 | Maritime temperate, over sea | |

The climate sets ITM's curves of variability in time. It does not move
the median loss. So it matters most at the 90 percent time fraction the
planner uses, and more with distance. Measured with this engine over
flat ground, 3 m to 1 m, at the planner's defaults: continental
temperate gives 0.5 dB less loss than desert at 10 km, 1.1 dB at 20 km
and 2.5 dB at 35 km.

#### Where the climate comes from

The source is the Köppen-Geiger map of Beck et al. (2023), version 3,
present day (1991 to 2020), at 1/120 degree, which is about 0.9 km by
0.8 km in Arizona. It is published under CC BY 4.0, which permits
redistribution with credit. `src/sonoran/climate/PROVENANCE.md` holds
the licence, the citation, the checksums and the changes made.

What ships is a crop of 30 to 38 north and 116 to 108 west, the default
terrain region: 960 x 960 cells, one byte each, 46 659 bytes
compressed. It is part of the Python package, so it needs no download
and no setting. `tools/make_climate_crop.py` makes it again from the
source.

The resolution was chosen from the data. Phoenix and Flagstaff are 200
km apart and any of the published grids separates them. The finer grid
is needed for the mountains in between, which are islands a few
kilometres across, and it costs 47 KB. These are the cells of the
shipped file:

| Place | Latitude | Longitude | Köppen | Climate used |
|---|---|---|---|---|
| Phoenix, Sky Harbor | 33.4342 | -112.0116 | BWh | Desert |
| Flagstaff, downtown | 35.1983 | -111.6513 | Dsb | Continental temperate |
| Flagstaff, Pulliam airport | 35.1385 | -111.6712 | Dsb | Continental temperate |
| Tucson, downtown | 32.2217 | -110.9265 | BWh | Desert |
| Tucson, airport | 32.1161 | -110.9410 | BSh | Desert |
| Prescott, downtown | 34.5400 | -112.4685 | Csa | Continental temperate |
| Prescott, airport | 34.6545 | -112.4196 | BSk | Desert |
| Yuma | 32.6927 | -114.6277 | BWh | Desert |
| Wickenburg | 33.9686 | -112.7296 | BWh | Desert |
| Show Low | 34.2542 | -110.0298 | Csa | Continental temperate |

Prescott shows the edge of the method: its downtown and its airport are
13 km apart and in different climates. That is the map, not a fault in
the lookup. A reader who knows better chooses in Advanced.

#### Outside the data

A site outside the crop, or on a cell the map gives no class (open
water, such as the Gulf of California), has no climate. The planner
then predicts on `desert`, which is what it always did, and says "the
climate is not known here, using desert". It never guesses a class.

#### How the page reads it, without telling the server where

The planner never sends a site to the server (2). So there is no
endpoint that answers a point. The page asks for the climate page of
the one degree square around the site, the same square it asks terrain
for, and reads the cell itself. It reads the Köppen to ITM table from
`/api/climate/classes`, so the page holds no copy of it. Both endpoints
are GET only, and the page endpoint serves the configured region only,
like the terrain endpoint. See `docs/API.md` 11.4 and 11.5.

The coverage map uses the same lookup for each site, and the
calibration uses it for each node it fits. See `docs/COVERAGE.md` 11.

#### The Köppen to ITM table

ITM's climates are not on any map. NTIA TR-82-100 section 5 says the
CCIR climates "have not been mapped out as various zones throughout the
world", and gives a rule: use continental temperate "unless there are
clear indications to choose another". It adds that "for land-mobile
services in the United States, the Continental Temperate climate is
nearly always chosen".

This table applies that rule. The clear indications are a dry class,
which is the Sahara's group; a wet tropical class, which is the
Congo's; and a tropical class with a long dry season, which is the
Sudan's savanna. Every other class is continental temperate.

**No class is given a maritime climate.** The maritime climates are for
places where "prevailing winds carry moist maritime air inland"
(TR-82-100 section 5). A Köppen class does not say how far a place is
from the sea: Csb is the coast of California and also Mount Lemmon. The
crop is inland everywhere. A deployment on a coast needs a second input
and must not reuse this table as it stands.

`src/sonoran/climate/koppen.py` is the source of this table, and
`tests/unit/test_climate.py` checks that this copy agrees with it, row
by row. The cells column is how many of the 921 600 cells of the
shipped crop hold the class.

| Value | Köppen | Name | ITM climate | Cells | Reason |
|---|---|---|---|---|---|
| 1 | Af | Tropical, rainforest | Equatorial | 0 | Hot and wet all year: the Congo. |
| 2 | Am | Tropical, monsoon | Equatorial | 0 | Hot and wet with a short dry season. Nearer the Congo than the Sudan. |
| 3 | Aw | Tropical, savannah | Continental subtropical | 0 | Hot with a long dry season: the savanna of the Sudan belt. |
| 4 | BWh | Arid, desert, hot | Desert | 276 727 | Dry: the Sahara's group. Phoenix, Yuma. |
| 5 | BWk | Arid, desert, cold | Desert | 79 437 | Dry. Winslow, Tuba City, Page. |
| 6 | BSh | Arid, steppe, hot | Desert | 101 475 | **Judgement call.** Less dry than desert, and the Sahel between the Sahara and the Sudan is BSh. Desert, because Köppen still calls it dry. Tucson airport. |
| 7 | BSk | Arid, steppe, cold | Desert | 292 904 | **Judgement call.** The temperature swings of continental temperate and the dryness of desert. Desert, because dryness is what Köppen classifies it by. Holbrook, Sedona, Sierra Vista, Prescott airport. |
| 8 | Csa | Temperate, dry summer, hot summer | Continental temperate | 48 866 | **Judgement call.** Mediterranean, which the CCIR names and ITM has no curves for. Maritime on a coast, which Köppen cannot tell. Inland, as at Prescott, Payson, Show Low and Williams. |
| 9 | Csb | Temperate, dry summer, warm summer | Continental temperate | 16 459 | As Csa. Mount Lemmon. |
| 10 | Csc | Temperate, dry summer, cold summer | Continental temperate | 0 | As Csa. |
| 11 | Cwa | Temperate, dry winter, hot summer | Continental temperate | 77 | No clear indication of another climate. |
| 12 | Cwb | Temperate, dry winter, warm summer | Continental temperate | 27 | No clear indication of another climate. |
| 13 | Cwc | Temperate, dry winter, cold summer | Continental temperate | 0 | No clear indication of another climate. |
| 14 | Cfa | Temperate, no dry season, hot summer | Continental temperate | 275 | No clear indication of another climate. |
| 15 | Cfb | Temperate, no dry season, warm summer | Continental temperate | 3 270 | No clear indication. Maritime on a west coast, which Köppen cannot tell. |
| 16 | Cfc | Temperate, no dry season, cold summer | Continental temperate | 0 | No clear indication of another climate. |
| 17 | Dsa | Cold, dry summer, hot summer | Continental temperate | 10 875 | Cold winters and warm summers on a large land mass: TR-82-100's "extremes of temperature". |
| 18 | Dsb | Cold, dry summer, warm summer | Continental temperate | 24 611 | As Dsa. Flagstaff, Alpine, Greer. |
| 19 | Dsc | Cold, dry summer, cold summer | Continental temperate | 117 | As Dsa. The San Francisco Peaks. |
| 20 | Dsd | Cold, dry summer, very cold winter | Continental temperate | 0 | As Dsa. |
| 21 | Dwa | Cold, dry winter, hot summer | Continental temperate | 0 | As Dsa. |
| 22 | Dwb | Cold, dry winter, warm summer | Continental temperate | 0 | As Dsa. |
| 23 | Dwc | Cold, dry winter, cold summer | Continental temperate | 0 | As Dsa. |
| 24 | Dwd | Cold, dry winter, very cold winter | Continental temperate | 0 | As Dsa. |
| 25 | Dfa | Cold, no dry season, hot summer | Continental temperate | 1 357 | As Dsa. |
| 26 | Dfb | Cold, no dry season, warm summer | Continental temperate | 25 228 | As Dsa. |
| 27 | Dfc | Cold, no dry season, cold summer | Continental temperate | 1 205 | As Dsa. |
| 28 | Dfd | Cold, no dry season, very cold winter | Continental temperate | 0 | As Dsa. |
| 29 | ET | Polar, tundra | Continental temperate | 3 | The CCIR describes a polar climate with no curves, so TR-82-100's default applies. |
| 30 | EF | Polar, frost | Continental temperate | 0 | As ET. |

38 687 cells hold no class. They are the Gulf of California.

The judgement calls that move most ground are BSh and BSk, 43 percent
of the crop between them. Continental temperate is the defensible
alternative for BSk. Desert was chosen because it is what Köppen calls
the class, and because it is what every site here already predicted
on, so a doubtful class changes nothing. The ground constants
(`ground_dielectric`, `ground_conductivity`) and the surface
refractivity (`atmosphere_bending`, 301, which is TR-82-100's figure
for continental temperate) do not follow the climate. They are a
separate question, outside #239.

### 4.4 Directional antennas, and which way they point

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
https://example.org/#planner?v=2&site_name=Shaw%20Butte&lat=33.5905&lon=-112.0865&tx_height=6&ran=2026-10-09
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
| `v` | The format version. It is `2`. Version `1` is still read (see below). A link that names another version is still read, and the page says it did not know the number. |
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

### A link made before the climate was read from the site

`radio_climate` defaults to `auto`, "read it from the site", so a link
leaves it out unless somebody chose a climate. A climate chosen by
hand, desert included, is written and comes back as chosen.

Before #239 the default was `desert`, and a link left that out instead.
So a version 1 link, or a link with no `v`, that names no climate meant
desert. It still does: the page puts the desert back and says "This
link was made before the planner read the climate from the site, so it
keeps desert, as it predicted then." A Flagstaff link made in September
therefore predicts in October what it predicted in September. Passed on
again, it is written as version 2 with `radio_climate=desert`.

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

The climate map is the work of Beck et al. (2023) and is used under
CC BY 4.0. See `src/sonoran/climate/PROVENANCE.md`. The mapping from
its classes to ITM climates is this project's own (4.3).

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
- One climate for each run: the site's own. A path from Flagstaff down
  into the desert is predicted on continental temperate for its whole
  length.
- The climate map covers 30 to 38 north and 116 to 108 west. Outside
  it the planner uses desert and says so.
