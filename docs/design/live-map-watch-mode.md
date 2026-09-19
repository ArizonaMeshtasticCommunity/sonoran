# Live map: watch mode and a new animation language

Design document. Not an implementation.

Scope: the `data-page="map"` section of the dashboard. Two halves, asked
for together by the owner:

1. A fullscreen "watch the mesh" mode, entered from the bottom right of
   the map, with overlay panels for live traffic and traceroutes that
   switch and expand.
2. A redesign of the live animation so a viewer can read direction,
   packet type and volume without being overwhelmed.

Half 2 is the centre of the work. Half 1 is a frame around it.

## 0. Citation basis

`app.js` was being edited by another agent while this review ran. It
changed three times in twenty minutes and the line numbers moved each
time. Every citation below is against one snapshot:

- `src/sonoran/web/static/app.js`, 2911 lines, sha256 begins
  `7d7557d275cae945`, taken at repo HEAD `9ddaa61`.

Verify by symbol name and by the quoted text, not by the number.

---

## 1. Honesty audit of the current animation

### 1.1 Verdict

**The endpoint is honest. The code knows the rules and says so in its
comments. The map is honest one line at a time and dishonest as a
picture. Two cells in the traffic feed are simply wrong and contradict
the packet page.**

The long form: nothing draws a line from a transmitting node to "every
node that heard it", because `/api/map/traffic` cannot return such a
thing. `packet_seen` holds MQTT uploads, so the only observer it can
name is a gateway (AGENTS.md 9.5.1), and `map.py` returns exactly one
sender and one gateway per event. The front end honours `direct`, draws
relayed observations dashed with an arrow, refuses to colour them by
SNR, and says "path not recorded" and "so this line is not the route" in
the tooltip. That is careful work and it should be said before the
criticism.

The failure is at the level of the picture, not the line. The animation
unit is the **upload**. It must be the **packet**.

### 1.2 What it draws, from what

`flashTraffic` (`app.js:719`) draws, per `packet_seen` observation:

- a `L.Polyline` from the sender's last known position to the gateway's
  last known position;
- solid, weight 2.5, coloured by `snrColour(event.snr)` when `direct`;
- dashed `6 5`, weight 1.8, neutral `--traffic-relayed` when not, plus a
  two-segment chevron at 66% of the chord (`arrowHead`, `app.js:695`);
- a text tooltip and a click handler to the packet page;
- a chain of 12 `setTimeout` fade steps (`app.js:769`) holding 7000 ms
  then fading over 2500 ms.

`animateHop` (`app.js:877`) draws one traceroute hop as a polyline
coloured by `snrColour(hop.snr)`, with 24 fade steps, held 3000 ms and
faded over 5000 ms, staggered 220 ms per hop.

`drawLinks` (`app.js:819`) draws 32 h of `neighbor_metrics` as faint
cool dashed lines. That layer is honest: a neighbour report is a node
naming a node it hears itself, which is a real radio link.

Preset discipline is correct. `PAGES.map` (`app.js:1012`) passes
`channel` to nodes, traffic, edges and traceroute-paths, and labels the
node scope (`mapNodeScope`, `app.js:1054`). AGENTS.md 9.7 is satisfied.

Clock discipline is correct. The animation orders on `event.time`, which
is `packet_seen.seen_at`, which is our receive clock. No node-supplied
time reaches the animation. AGENTS.md 9.3 and 9.4 are satisfied and the
redesign must keep it that way.

### 1.3 What is misleading, in order of size

**(a) The gateway fan reads as "heard by". This is the big one.**

`flashNewTraffic` (`app.js:787`) calls `flashTraffic` once per
observation. AGENTS.md 9.5.1 measured one live packet with **22 uploads
from 15 gateways**. So one packet fires up to 22 lines radiating out of
one node inside one refresh tick. Every one of those lines carries an
honest tooltip. Nobody hovers a tooltip at fifty events a second. The
picture says "this node was just heard by fifteen nodes at once", which
is the single reading 9.5.1 exists to forbid.

The endpoint did its job. The renderer undid it by choosing the wrong
unit. **The fix is not more wording. It is to animate packets.**

**(b) A duplicate upload draws a duplicate line.**

    app.js:790
    const key = `${event.packet_id}-${event.gateway.node_id}-${event.time}`;

The key includes the observation time, and `packet_seen` genuinely holds
several rows for the same packet and the same gateway at different
`seen_at` — 22 uploads from 15 gateways means seven of them are repeats.
Those seven draw as a second line on top of the first. Two coincident
strokes at 0.7 opacity read as one stroke at 0.91. **A pair of nodes
that happens to double-upload looks like a stronger link than a pair
that does not.** That is a false quantity, not clutter.

**(c) The key drops the sender, against AGENTS.md 9.1.**

Same line. Packet identity is `(from_node_num, packet_id)`. This key
uses `packet_id` alone. Two senders that pick the same 32-bit ID inside
one window collapse into one animation and one of the two packets never
draws. Rare, silent, and against an explicit rule. `packetHref`
(`app.js:641`) gets it right, so the file disagrees with itself.

**(d) The feed prints SNR on relayed rows. This is a bug.**

    app.js:1088
    event.snr != null ? snrCell(event.snr) : null,

No `direct` test. `snrCell` colours it good / warn / bad. `rx_snr`
belongs to the last hop into the gateway, never to the pair named in
that row (AGENTS.md 9.5, where 82% of observations were relayed). The
packet page does it correctly on the very same data:

    app.js:2766
    cell: (row) => (row.direct ? snrCell(row.rx_snr) : el('span', { class: 'muted', text: '-' }))

Two pages, two answers, from one endpoint. That is the exact failure
AGENTS.md 9.18 was written about.

**(e) The feed calls a self-upload "relayed". This is a bug.**

    app.js:1091
    text: event.direct ? 'direct' : 'relayed' }),

`direct` is false when the sender is its own gateway, by design
(`map.py`, per 9.5.1). A sender uploading its own transmission at zero
hops is therefore printed as "relayed". 9.5.1 records a live packet
where **all three** apparently-direct rows were the sender. The packet
page again gets it right and prints "its own upload" (`app.js:2763`),
with a three-way path cell at `app.js:2764`.

**(f) Unknown is drawn as known.**

`flashTraffic` styles on `direct` alone (`app.js:724`). An event with
`hops_taken == null` — which happens whenever the packet row is older
than the window plus the ten-minute lookback, so every late upload from
a reconnected gateway — is drawn identically to a measured two-hop
relay. The distinction exists only in tooltip prose (`app.js:747`).
Unknown is not a value. It must look different.

**(g) Unknown signal is drawn as the brightest thing on the map.**

    app.js:77
    if (snr == null) return PALETTE.accent;

`--accent` is the brand orange, the "look here" colour. So a hop nobody
could measure is the most salient mark in the frame, and a strong
measured link is a quiet green. AGENTS.md 9.6 says an unmeasured hop is
"not measured", not a reading. It should be the dimmest mark, not the
loudest.

### 1.4 Things that are not lies but cost legibility

- **Every observation in the window is polled, then a slice is drawn.**
  `TRAFFIC_LIMIT = 2000` (`app.js:674`) against a 15-minute window. At
  the low volume case in `docs/RESEARCH.md` 5 (300,000 packets/day, so
  about 3.5 packets/s) with 15 gateway uploads each, the window holds
  roughly 47,000 observations. The cap therefore covers about the last
  **38 seconds**, `truncated` is permanently true, and the window picker
  changes the summary numbers while changing almost nothing about what
  is drawn. Nobody is lied to, but the control does not do what it looks
  like it does.
- **The bursts are partly manufactured by the poll.** `LIVE_INTERVAL_MS
  = 15000` (`app.js:2805`). Fifteen seconds of mesh activity arrives in
  one array and `flashNewTraffic` fires all of it in one synchronous
  loop. The owner's complaint that "so many nodes are hearing things and
  it's hard to tell what direction things are going" is in part an
  artefact of rendering 15 seconds of history in 16 milliseconds. This
  is the cheapest large win available and it needs no backend change.
- **`snrColour` has three buckets and no legend on the map.** The map
  legend names line kinds, not the colour ramp.

### 1.5 Performance faults that are also legibility faults

- `L.map('map', { preferCanvas: true, ... })` (`app.js:600`). With the
  canvas renderer, `setStyle` on a polyline marks a redraw region.
  Traffic lines span Arizona, so the region is effectively the whole
  canvas, so each fade step redraws every live line. Same-frame calls
  coalesce, but the 12 steps are spread over 2500 ms at different
  offsets, so the work is roughly **O(n²)** across a fade cycle. At 52
  observations per second and a 9.5-second lifetime, n is around 490.
- **Timers.** 13 per traffic line, 25 per trace hop, all through
  `mapLater` into `mapTimers` (`app.js:852`). At 52 obs/s that is about
  680 `setTimeout` per second and up to five thousand pending.
- **Object churn.** One or two `L.Polyline`, one bound tooltip and one
  click closure per observation. Over one hour at 52/s that is roughly
  190,000 Leaflet objects created and released. This is the memory
  growth the owner will meet when he watches for hours.
- `traceSeen` (`app.js:851`) is a Set pruned by slicing the first 1000
  of 2000 (`app.js:953`). That is an insertion-order prune — the exact
  bug already fixed for `trafficSeen`, whose comment at `app.js:797`
  explains why it was wrong. It survives only because traces are rare.
- **Navigating away does not stop the animation.** `stopMapAnimations`
  (`app.js:869`) is called only when the traceroute toggle goes off
  (`PAGES.map`). `route()` has no page-exit hook.
- **`.map-overlay` is dead CSS, and defined twice** (`app.css:233` and
  `app.css:259`, plus a responsive rule at `app.css:401`). Nothing in
  `index.html` or `app.js` uses the class. Watch mode gets its overlay
  styling almost free, and the duplicate should be collapsed.
- **No `prefers-reduced-motion` rule exists anywhere in `app.css`.**

### 1.6 What the data cannot support, whatever is asked for

Stated plainly, because the owner asked for some of these.

1. **The route of an ordinary packet does not exist.** AGENTS.md 9.20.
   For 82–89% of observations we know the sender, the gateway, and a hop
   count. The ground between them is recorded nowhere.
2. **`relay_node` is not the missing piece.** 9.20: one truncated byte,
   215 distinct bytes across 694 nodes, 3.2 candidates for an average
   byte, **5.4%** resolving to a single node, and it names the last hop
   only, never the path. A line drawn from it would be wrong about 95%
   of the time. This design refuses it, and so should every later phase.
3. **Latency and speed are unavailable.** Every gateway stamps its own
   `rx_time` and node clocks have been 28 hours out (9.3, 9.4). Nothing
   in the animation may encode speed, because any speed difference would
   be read as a measurement. Flight duration is therefore constant.
4. **"Nodes hearing things" is not observable.** 9.5.1: only gateways
   report. A non-gateway hearing a packet is invisible to this database.
   The animation must never suggest coverage. The phrase "heard by" is
   banned from this feature; the word is **uploaded**.
5. **SNR on a relayed observation is not a link quality.** 9.5. Colour
   only a flat line.
6. **Two presets cannot share one view.** 9.7. Watch mode therefore has
   no "everything at once" firehose. Split screen, one preset per half,
   is legitimate. A blend is not.
7. **Half of traceroute rows are unanswered requests whose implied path
   is a fiction.** 9.18 rule 3. `completed_only=true` stays the default
   in watch mode.
8. **Traceroute SNR is missing about two thirds of the time**, and
   `INT8_MIN` means not measured (9.6). Most hops will have no colour,
   and that must look deliberate rather than broken.

---

## 2. The animation language

### 2.1 Three rules, learned once

**Rule A — flatness is evidence.**
A mark that travels in a straight line between two nodes claims a radio
link. Only two things earn a straight line: a `direct` observation
(`hop_start == hop_limit` and sender ≠ gateway) and a traceroute hop.
Everything else **bows**.

**Rule B — motion means "just now, and that way". Nothing else moves.**
Role, gateway status, staleness, neighbour links, counts, positions: all
static. Motion is the loudest channel in the interface and the current
map spends it on five hundred simultaneous fades. Spending it on one
thing is what makes the picture readable.

**Rule C — the unit is the packet, not the upload.**
One packet, one emission. Its uploads are a property of it.

### 2.2 Geometry carries the hop count, so it also carries the honesty

Bow amplitude is a fraction of the on-screen chord length, perpendicular
to it, drawn as a quadratic curve:

| `hops_taken` | bow | stroke | meaning |
|---|---|---|---|
| 0, direct | 0.00 (flat) | solid | a measured radio link |
| 1 | 0.12 | solid | one relay, ground unknown |
| 2 | 0.22 | solid | two relays |
| 3 | 0.30 | solid | three relays |
| ≥ 4 | 0.36 (clamped) | solid | four or more |
| `null` | 0.26 | stippled, 40% opacity | hop count not known |
| self-upload (sender = gateway) | n/a | no arc at all | an MQTT upload of its own voice, not a transmission across ground |

This is the whole point of the redesign. "Direct" and "flat" become the
same fact, so a viewer learns one rule and reads both. A bowed line
visibly leaves the ground, which is how every map since Minard has said
*this is a relation, not a route*. The straight lines are the only
claims about radio, and there are few of them, which is exactly right:
AGENTS.md 9.5 measured 5% direct and the map measures about 11%.

A self-upload draws only the emission pulse at the node. There is no
second place for the mark to go.

### 2.3 Packet type: shape first, colour second, never colour alone

Marks are drawn on canvas at 5–7 px. The shape features that survive
that size on a sepia basemap are fill, corner count, and elongation.
That gives about eight usable combinations, so there are seven
categories and a bucket:

| Family | Shape | Size | Hue | Relative luminance |
|---|---|---|---|---|
| `POSITION_APP` | filled circle | 5 px | `--pkt-position` `#f4703f` | 62 |
| `NODEINFO_APP` | hollow circle | 6 px | `--pkt-nodeinfo` `#a48fd0` | 62 |
| `TELEMETRY_APP` (device, environment, power, air quality) | filled square | 5 px | `--pkt-telemetry` `#46b3e6` | 68 |
| `TEXT_MESSAGE_APP` | filled capsule | 10 × 4 px | `--pkt-text` `#f6ece2` | 92 |
| `TRACEROUTE_APP` | hollow diamond | 7 px | `--pkt-trace` `#b6d94c` | 83 |
| `ROUTING_APP` | thin cross | 6 px | `--pkt-routing` `#b59c88` | 65 |
| everything else, including `UNKNOWN_APP` | 3 px tick | 3 px | `--pkt-other` `#7d6857` | 45 |

Reasoning:

- **Shape and hue are redundant.** Remove all colour and the alphabet
  still reads. That is the accessibility requirement, met by
  construction rather than by a later audit.
- **Text is the brightest and largest.** It is the rarest packet and the
  only one a human wrote. Top salience costs nothing when the thing is
  rare, and it is the mark a viewer most wants to catch.
- **The two hues that share luminance 62 (orange, violet) differ on the
  blue-yellow axis**, which deuteranopia and protanopia both retain, and
  they also differ in fill. No pair relies on the red-green axis alone.
- **Unknown is the dimmest.** This inverts `snrColour`'s current
  treatment of null and applies the same principle to portnum.
- **Seven and a bucket, not fifteen.** A viewer who needs the exact port
  reads the panel row, which already links to the full packet record.
  Compressing the tail into one dim tick is honest: the mark says "a
  packet of a kind this view does not distinguish", which is true.

These are a new `--pkt-*` group in `:root`. They must not reuse the
`--role-*` values, because those are the dots.

### 2.4 Motion versus static marks, and why

**Encoded with motion:**

- direction of travel (the mark moves origin → destination);
- recency (a mark exists at all because it just happened);
- volume at a node (halo radius, but see below).

**Encoded statically:**

- everything else: role hue, gateway ring, staleness, position
  confidence, neighbour links, hop count (geometry), packet type (shape
  and hue), signal quality (colour of flat lines only), counts.

The reason is a hard constraint, not taste: under
`prefers-reduced-motion` the motion channel disappears. So nothing may
be encoded **only** in motion. Direction therefore has a static form
too — a tapered trail, thin at the origin and thick at the destination,
with a single chevron at 62% of the chord. Taper is direction without
movement. The existing `arrowHead` already establishes the 66% idea;
keep it and draw it in the canvas instead of as two polylines.

### 2.5 Timings, and one thing they must never mean

| Mark | Duration | Easing | Note |
|---|---|---|---|
| Particle flight | **850 ms, constant** | `easeOutCubic` on the first 30%, linear after | Constant for every event. See below. |
| Emission pulse at the sender | 320 ms | radius 4 → 14 px, opacity 0.9 → 0 | fires for every packet, including self-uploads |
| Arrival pulse at the gateway | 260 ms | radius 3 → 10 px | fires when the particle lands |
| Trail decay | 1400 ms | exponential, τ = 420 ms, removed under 0.04 | replaces the 12-step `setTimeout` chain |
| Node heat halo | continuous | exponential, **half-life 20 s** | radius `6 + 10·min(1, heat/8)` px, capped 16 px |
| Traceroute hop reveal | 180 ms per hop | — | down from 220 |
| Traceroute path hold | 2600 ms | — | down from 3000 |
| Traceroute path fade | 1200 ms | — | **down from 5000** |
| Minimum drawn chord | 18 px | — | shorter than that, draw the two pulses and no particle |

**Speed is not data.** Flight duration is constant regardless of
distance or hop count, so a long arc moves faster in pixels per second
than a short one. That is deliberate. A constant pixel speed would make
distant links look slow, and a viewer would read it as latency, which
this database cannot measure (9.3, 9.4). A constant duration cannot be
mistaken for a measurement because every event takes the same time.

A traceroute path currently lives 8–10 seconds. At 1,808 traces a day
that is fine, but in watch mode with the panel beside it, 4.7 seconds
for a five-hop path is enough and stops paths from stacking.

### 2.6 The heat map, formalised

The owner loves the heat. It is currently an emergent side effect of
overlapping fades. Make it a first-class mark with a defined meaning:

- **Emission heat** is drawn as a soft halo under the node dot. `heat +=
  1` for each packet the node **originated**, decaying with a 20 s
  half-life.
- **Gateway activity** is drawn as the thickness of the node's existing
  bright gateway ring, on its own scale, with its own decay.

These two are never added together. A busy gateway uploading other
people's traffic is not a chatty node, and collapsing them into one
glow is AGENTS.md 9.5.1 reappearing as an aggregate. The legend names
both, in these words: "how much this node said" and "how much this node
uploaded".

Halos sit **under** the node dots in z-order, so identity is never
obscured by volume.

### 2.7 Aggregation: from uploads to packets

Per fetch batch, group events by `(from.node_id, packet_id)` — the
AGENTS.md 9.1 key, which also repairs fault (c). For each group compute:

- `gateway_count` — **distinct** gateway node numbers, never the row
  count (9.5.1);
- `upload_count` — rows, for the panel only;
- `min_hops` — the fewest `hops_taken` across uploads, ignoring nulls;
- `any_direct`;
- `portnum`, `channel`, latest `seen_at`.

Then draw:

- one emission pulse at the sender, always;
- **at most three arcs**, to the three distinct gateways with the fewest
  hops, `direct` ones first;
- when `gateway_count > 3`, a small numeral `+N` beside the sender dot
  for the trail's lifetime;
- the exact `gateway_count` and `upload_count` in the panel row.

This one change removes roughly 70–85% of the strokes, deletes fault
(a), deletes fault (b) for free (dedupe is now per packet and gateway,
with time excluded from the key), and makes the panel the place where
precision lives — which is where precision belongs, because a panel row
can be read and a 900 ms particle cannot.

Keep the time-based prune of the seen map (`app.js:797`–`804`) exactly
as it is, including the comment. It was already fixed once and it is
correct. Convert `traceSeen` to the same shape.

### 2.8 Legend

Watch mode carries a collapsed legend that expands on `?` or a click. It
must name, in these terms:

- flat line = a measured radio link; bowed line = a relation whose route
  is not recorded; bow height = hops burned;
- stipple = not measured, for both hop counts and SNR;
- shape and colour per packet family, with the shapes drawn, not
  described;
- halo = how much this node said; ring = how much it uploaded;
- the preset name, permanently, never in the collapsed state;
- "uploads, not listeners" as a single line of prose under the traffic
  count.

---

## 3. Legibility under load

### 3.1 The numbers this is designed against

From `docs/RESEARCH.md` 5 and the measurements in AGENTS.md 9.5 / 9.5.1:

| Quantity | Low case | High case |
|---|---|---|
| Packets per day, whole mesh | 300,000 | several million |
| Packets per second | 3.5 | 23–60 |
| Uploads per packet | ~15 distinct gateways, ~22 rows | same |
| Observations per second | ~52 | ~350–900 |
| Traceroutes per day | 1,808 (1.25/min) | — |
| Direct share of observations | 5% (9.5) to 11% (ISSUES 2.3) | — |

One preset filtered is lower than the whole-mesh figure. Design for the
low case being comfortable and the high case being honest.

### 3.2 Time-dilated replay

Each fetch returns events from a known interval. Do not fire them at
once. Buffer the batch and release each event at

    releaseAt = batchStart + (event.seen_at - windowStart)

so a 5-second batch replays over the following 5 seconds in true
relative order. `seen_at` is our clock, so this ordering is sound
(9.3, 9.4) — and it is the only time value in the system that is.

Cost: the display runs one interval plus a little behind live. That must
be said on screen, in the status line: "replaying, about 7 s behind".
Never present it as instantaneous. A watcher does not care about seven
seconds and does care about being able to follow what happened.

This is the single largest legibility improvement in the document and it
requires no backend change.

### 3.3 Caps

- **220** concurrent animated marks (particles plus trails).
- **3** arcs per packet.
- **60** new packet events released per animation tick.
- **12** traceroute paths alive at once; a 13th replaces the oldest.
- **1** emission pulse per node per 400 ms; a node transmitting faster
  than that raises its heat instead of flashing.

### 3.4 The admission ladder

When over budget, drop from the bottom. Never from the top.

1. Keep: traceroute hops. Rarest, and the only true paths on the map.
2. Keep: `direct` observations. The only measured links.
3. Keep: `TEXT_MESSAGE_APP`. Written by a person.
4. Keep: the first arc of every packet.
5. Drop: the 2nd and 3rd arcs. The count moves to the `+N` numeral and
   the panel.
6. Drop: relayed arcs for position and telemetry from nodes already
   above heat 6. They become heat only.
7. Drop: arcs entirely. Heat, emission pulses and the panel remain, and
   the status line says the map is now a heat map.

Driven by measured rate, not by guesswork:

| Packets/s | Behaviour |
|---|---|
| ≤ 6 | draw everything |
| 6 – 20 | 2 arcs per packet |
| 20 – 50 | 1 arc per packet; direct, text and traceroute only |
| > 50 | rungs 1–4 only; arcs off; banner |

Also driven by measured frame time: if p95 draw time exceeds 8 ms for 3
consecutive seconds, step down one rung; if it stays under 4 ms for 10
seconds, step back up. Hysteresis in both directions so it does not
oscillate.

### 3.5 Never sample silently

Whenever the ladder drops anything, the status line prints the real
numbers: **"drawing 84 of 312 packets"**. The eye cannot count marks, so
the count must be written. This is the pixel form of the project's own
rule that an absence must be evidence rather than a blank.

### 3.6 Z-order, bottom to top

1. basemap tiles
2. coverage overlay, if on
3. neighbour links
4. heat halos
5. trails and arcs
6. node dots and gateway rings
7. particles
8. pulses
9. the `+N` numerals and any labels

Node dots above trails so identity is never lost under traffic.
Particles above dots because they are the subject.

### 3.7 The panel under load

- `replace()` of the whole feed every refresh (`app.js:1079` onward)
  destroys scroll position and any text selection. In watch mode the
  panel is taller and the loss is worse. Use keyed prepend and trim to
  40 rows, with a 120 ms highlight on new rows.
- **Coalesce repeats.** Consecutive rows with the same sender and the
  same portnum inside 60 s collapse to one row with a count badge.
  Otherwise one tracker posting a position every 30 seconds owns the
  panel.
- The summary keeps the word "observations" (`app.js:1079` already gets
  this right) and gains "from N packets".

---

## 4. Accessibility, taste and the frame budget

### 4.1 Colour vision

Meaning is never in hue alone. Every packet family pairs a hue with a
shape; every line semantic pairs a colour with geometry (bow) or with
stroke (stipple). The palette is separated in luminance as well as hue,
and the one same-luminance pair is separated on the blue-yellow axis and
by fill. Test by rendering the canvas through a greyscale filter: the
alphabet must still read.

### 4.2 The basemap filter trap

`app.css:287` applies `invert(1) hue-rotate(180deg) …` to
`.leaflet-tile-pane .basemap-tiles`. The comment above it records that
an earlier pane-level version of this rule inverted the coverage
overlay's signal ramp, so the map drew the legend backwards. **A new
animation canvas must live in its own Leaflet pane with an explicit
`filter: none`, and must not be a tile layer.** Anything else and every
packet colour comes out inverted, and the bug will look like a palette
mistake rather than a CSS inheritance one.

### 4.3 Reduced motion

`prefers-reduced-motion: reduce` is the **default** of a visible "Motion"
toggle, not a lock. A viewer whose system setting says reduce may still
want the animation on this one page, and a viewer whose system says
nothing may want it off on a train.

With motion reduced:

- no particles, no pulses, no halo animation;
- each event paints its **static tapered arc with a chevron**, held 900
  ms, then removed in one step;
- heat still renders but recomputes once per tick, so it steps rather
  than glides;
- traceroute paths appear whole rather than hop by hop.

Everything in section 2 remains readable, because nothing was encoded in
motion alone.

### 4.4 Frame budget

**8 ms per frame at 60 Hz for the whole animation canvas**, leaving 8 ms
for Leaflet, tiles and the DOM.

How to stay inside it:

- **One canvas, one `requestAnimationFrame` loop, one clear, one draw
  pass.** Not Leaflet layers. This is the change that fixes the O(n²)
  `setStyle` behaviour described in 1.5.
- **Object pool** of 256 mark slots, reused. Zero allocation in the hot
  loop, so no GC sawtooth over a long watch.
- **Reproject per frame** from lat/lng to container points. That is 220
  cheap transforms, far less than one canvas fill.
- **Hide the canvas between `zoomstart` and `zoomend`.** Leaflet applies
  a CSS transform to its panes during the zoom animation; a
  container-pinned canvas does not receive it, so marks would slide.
  Hiding for ~250 ms is the honest fix and it is what every canvas
  overlay does.
- **Render at `min(devicePixelRatio, 2)`.** On a 3× phone that halves
  the fill cost with no visible loss at these mark sizes.
- **Stop the loop completely** when the live set is empty, when
  `document.hidden`, or when the map page is not active.
  `cancelAnimationFrame`, and restart on the next release. Target **0%
  CPU when the mesh is quiet**, which matters on a laptop left open for
  hours. `requestAnimationFrame` throttles in a background tab but an
  idle loop still wakes the compositor.
- **No SVG, no per-mark DOM, no `box-shadow` halos, no CSS transitions
  on hundreds of elements.**
- `getContext('2d', { alpha: true, willReadFrequently: false })`.

### 4.5 Self-auditing

`window.SonoranMap` already exists for console inspection
(`app.js:434`). Extend it with `stats`: marks alive, marks dropped this
minute, current ladder rung, p50 and p95 draw time, frames drawn,
allocations. That is how the frame budget gets verified without a build
step, and it is in keeping with how the map already exposes itself.

### 4.6 Tooltips and node names

`app.js:787` uses `document.createTextNode` deliberately, because a
display name is whatever a node's owner typed into their radio. On
canvas the equivalent rule is: draw names with `fillText` on a truncated
string, never assemble HTML. The panel keeps the existing `el()` helper,
which sets `text`, not `innerHTML`.

---

## 5. Fullscreen watch mode

### 5.1 Entry, exit, and where the control lives

An `L.Control` at `position: 'bottomright'`, which is where the owner
asked for it and which keeps it inside the map rather than in the page
chrome that watch mode hides. Icon from the existing inline Material
Design sprite in `index.html`: add `#i-fullscreen` and
`#i-fullscreen-exit` symbols. That is the established pattern here and
it keeps the strict CSP free of exceptions.

Label: "Watch mode", accesskey-free, `aria-pressed`, `title` "Watch mode
(F)".

### 5.2 Fullscreen API or CSS: use both, API first

**Recommendation: request the Fullscreen API on `.map-shell`, and fall
back to a CSS class.**

Why the API:

- It hides the browser's own chrome. That is the whole point of sitting
  and watching, and CSS cannot do it.
- Escape is handled by the browser, and `fullscreenchange` gives a
  single place to sync state — including when the user leaves fullscreen
  by a route the page did not initiate.
- A button click is already a user gesture, so the permission model
  costs nothing.

Why a fallback is mandatory: iOS Safari does not grant
`requestFullscreen` on arbitrary elements. So `requestFullscreen()` is
called inside a try, and on rejection or absence the code adds
`body.watch-mode`, which does `position: fixed; inset: 0; z-index: 900`
on `.map-shell`. **Same DOM in both paths**, so there is one layout code
path and one set of CSS.

Do not re-parent the map element. Fullscreen `.map-shell` in place.
Re-parenting a Leaflet container forces a resize dance the code already
performs twice (`PAGES.map`, and the packet page's `positionMap`). One
`map.invalidateSize()` on `fullscreenchange`, and on the fallback's
`transitionend`, is all that is needed.

State goes in the URL fragment, for example `#map/watch/traffic/tall`.
AGENTS.md 9.9.1 records that the fragment is deliberately where this
dashboard keeps state, because a `Referer` never carries it — so this
persists across reload and is shareable and leaks nothing. Watch mode is
therefore **not a new page**; a link to it is a link to the map.

### 5.3 Keyboard

One `keydown` listener on `document`, active only when the map page is
active and the focus is not in an input or select.

| Key | Action |
|---|---|
| `F` | toggle watch mode |
| `Escape` | exit (native in API mode; handled in fallback mode) |
| `Space` | pause and resume the animation, and freeze the replay buffer |
| `T` | switch the overlay tab |
| `1` `2` `3` | select a tab directly |
| `E` | cycle the panel height: peek → normal → expanded |
| `?` | toggle the legend |

`Space` is worth more than it looks. A viewer watching a burst will want
to stop it and read what just happened. Pause holds the buffer and keeps
accumulating; resume replays from the pause point or skips to live, with
the choice shown.

### 5.4 What hides, and what must never hide

Hidden: the sidebar, the page head (`h2` and `.sub`), the role legend
(moves into the collapsible legend), and the two panels below the map
(they become the overlay). The `.controls` row collapses into a slim
top-right bar holding the preset picker, the traffic window and the live
dot.

**Always visible:**

- the **preset name**. AGENTS.md 9.7 — a viewer must never forget which
  mesh they are watching, and in fullscreen there is no page head to
  tell them;
- the node-scope label (`mapNodeScope`), for the same reason;
- the "drawing N of M packets" honesty counter;
- the replay lag;
- the OpenStreetMap attribution. It is a condition of the tiles and
  9.9.1 is the story of what happens when tile policy is treated
  casually.

### 5.5 Switch or side by side: switch. Tabs, with a badge.

**Recommendation: one panel at the bottom left, with a two-tab header
`Traffic · Traceroutes`, and an unread badge on the inactive tab.**

Reasons, in order:

1. **Traceroutes arrive at about 1.25 per minute.** A permanently
   visible traceroute panel is empty most of the time, and a region of
   the screen that is usually empty trains the eye to stop looking at
   it. The badge does the opposite: it pulls attention exactly when
   something lands.
2. **The map is the product.** Two panels at the bottom left consume
   about 52 rem of a 1280 px viewport. One consumes 26.
3. **The two feeds are read at different tempos.** Traffic is a river
   you skim; a traceroute is an event you read. Side by side asks for
   both attentions at once and gets neither.

The badge is what side-by-side was actually trying to buy, at a tenth of
the cost in screen.

A third tab, `Heat` (top talkers in the window, with the emission and
upload columns kept separate), is a phase 2 addition.

### 5.6 Layout by width

**Desktop, ≥ 1280 px.** Panel bottom left, three snap heights:

| Height | Size | Contents |
|---|---|---|
| peek | ~5 rem | summary line plus one row |
| normal | 14 rem, 26 rem wide | the current two-line rows |
| expanded | 34 rem wide, full map height less 4 rem | a table: time, sender, portnum, hops, gateways, uploads, SNR *only when direct*, channel, plus a 60-second packets-per-second sparkline |

Expanded is the "expand those boxes to show better data" the owner
asked for. Note what it adds and what it does not: it adds `hops`,
`gateway_count`, `upload_count` and `channel`, all of which exist today
in the response and are thrown away by the renderer. It does **not** add
SNR to relayed rows.

**Tablet, 768–1279 px.** The panel becomes a bottom sheet, full width,
same three heights, map above. The existing responsive rule at
`app.css:401` already turns `.map-overlay` static at 60 rem; extend that
idea rather than fighting it.

**Phone, < 768 px.** Be honest: fullscreen on a phone in portrait is a
poor watch experience and a nine-column table is worse. Watch mode on a
phone gives the map, a **one-line ticker** at the bottom cycling one
event every 2 s, and a pull-up sheet for the full feed. Do not attempt
the table. Landscape phone gets the tablet layout.

### 5.7 Expansion behaviour

A drag handle on the panel's top edge, a chevron button, and the `E`
key — three ways in, because this is the control the owner named.

**Three discrete snap heights, no free drag.** Free drag on a map
overlay is fiddly with a mouse, hostile with a finger, and creates a
persistence problem (what exactly is stored, and what happens when the
window resizes). Snaps store as one of three words in the fragment.

Expanding does not pause the animation and does not change what is
drawn. It changes what is tabulated. A viewer who expands to read
something can press `Space` to stop the world.

### 5.8 No new framework

Everything above is: one `L.Control`, one `<canvas>` in a custom Leaflet
pane, one `requestAnimationFrame` loop, two sprite symbols, a set of CSS
classes, and a handful of functions in `app.js`. Alpine.js is loaded but
the map page does not use it; this is not the place to start. There is no
build step and this design does not need one.

---

## 6. Data and transport

### 6.1 What the current endpoints already give

Enough for phase 1. `/api/map/traffic` returns `packet_id`,
`from`, `gateway`, `hops_taken`, `hop_start`, `hop_limit`, `direct`,
`portnum`, `channel`, `snr`, `rssi`, `has_line` and `time`. Grouping
uploads into packets, bowing by hop count, and time-dilating the replay
are all client-side. **Phase 1 needs no API change**, which is why it
ships in one sitting.

### 6.2 What is missing, and what it costs

**(1) An incremental cursor.** Today the map re-requests the whole
window every 15 s. Add `since=<iso8601>` (or an opaque cursor) to
`/api/map/traffic` so a tick fetches only new rows. A read-only GET
gaining a filter parameter is the smallest possible change and matches
`docs/API.md` rule 1.

**(2) A way to skip the counters.** This is the big one.
`docs/REVIEW.md` 2.1 and `docs/ISSUES.md` 2.9: the window counts run one
correlated probe into the `packet` hypertable **per `packet_seen` row in
the window**. At `minutes=1440` that is hundreds of thousands of index
probes on a public, unauthenticated endpoint that the map calls every 15
seconds per open tab. Add `counts=false` (defaulting true for
compatibility) so watch mode asks for events only. **This is the single
largest cost reduction available anywhere in this design**, and it is
one parameter.

**(3) `/api/graph/channels` is refetched on every map refresh.**
`linkChannelOptions` calls `api/graph/channels?hours=24` at
`app.js:972`, and that endpoint runs three 24-hour `GROUP BY` aggregates
over `packet_seen`, `neighbor_metrics` and `traceroute`
(`graph.py`, `_channel_link_counts` and `_channel_packet_counts`). It
answers a question that changes hourly and it is paid four times a
minute. **Cache it client-side for 10 minutes.** Cheap, and the second
biggest win.

**(4) `/api/map/nodes` is refetched on every refresh** (`app.js:1034`),
700–900 rows that change slowly. Fetch on entry, then every 120 s.

**(5) `portnum` nulls need a rendering rule, not a backend fix.** An
observation whose packet row predates the window plus the ten-minute
lookback returns `portnum: null`, `hop_start: null`, `direct: false`.
That is correct and documented. It must render as the dim "other" tick
with a `null`-hops stippled arc, never as a confident "relayed". This is
fault (f) from section 1.

**(6) Nothing is needed for the fullscreen panels themselves.** Every
column the expanded table wants already exists in the response and is
discarded by the renderer.

### 6.3 Polling or SSE: poll now, SSE at phase 3, never WebSocket

**Phase 1 and 2: keep polling. Change the cadence and the payload.**

Move the map's live tick to **5 s** and dilate each batch across the
following 5 s. A 5-second pipeline delay is invisible to a human
watching a mesh; 15 seconds of history fired in one frame is not. With
`since` and `counts=false` each request is far cheaper than today's.

Per-viewer request budget in watch mode, steady state:

| Call | Interval | Per minute |
|---|---|---|
| `/api/map/traffic?since=…&counts=false` | 5 s | 12 |
| `/api/map/traceroute-paths` | 15 s | 4 |
| `/api/map/nodes` | 120 s | 0.5 |
| `/api/map/edges` | off by default | 0 |
| `/api/graph/channels` | 600 s | 0.1 |
| **Total** | | **≈ 17 req/min, ≈ 1,020/hour** |

That is slightly more requests than today's 16–20 per minute, and each
one is far cheaper because the correlated count is gone. Net server cost
falls. State the trade honestly rather than claiming a win on both axes.

**Phase 3: SSE.** `GET /api/map/live`, `text/event-stream`.

Why SSE and not WebSocket, decisively:

1. **CSP.** `EventSource` is governed by `connect-src`, which
   `sonoran/api/app.py` already builds from settings and which already
   contains `'self'`. **SSE needs no CSP change.** A WebSocket needs a
   `ws:`/`wss:` source added to `connect-src` or it fails with nothing in
   the console — which is precisely AGENTS.md 9.9 waiting to happen
   again.
2. **The API is documented GET-only** (`docs/API.md` rule 1). SSE is a
   GET. A WebSocket upgrade is not.
3. **Nothing flows upstream.** There is no message for the client to
   send.
4. **Reconnect and resume are free** with `Last-Event-ID` and `retry:`.
   A WebSocket reconnect has to be written and tested.

Why SSE is worth doing at all: **cost becomes O(1) in viewers.** One
broadcaster in the API process runs one query every 2 s and fans the
result to every connected client. At ten viewers that is 0.5 queries per
second instead of five. On a three-core box also serving a public embed,
that is the argument.

Why it is phase 3 and not phase 1, and the constraints it must respect:

- **The broadcaster owns exactly one `AsyncSession`.** `db/session.py`
  calls `create_async_engine(database_url, pool_pre_ping=True)` with no
  `pool_size`, so the pool is the SQLAlchemy default of 5 with 10
  overflow — **15 connections**. A design that holds a session per SSE
  connection exhausts the pool at fifteen viewers and takes the public
  embed down with it. One session, in the broadcaster, never per client.
- **Cap concurrent streams**, say 24, and answer the 25th with `503`
  plus `Retry-After`, so a crowd can never starve the embed. The client
  must fall back to polling on any SSE failure, including that 503.
- `sonoran-api` runs **one uvicorn worker** (`app.py`, `run()` calls
  `uvicorn.run` with no `workers`), so an in-process broadcaster is
  correct today. If anyone ever adds `--workers`, each worker gets its
  own broadcaster and each client gets one copy — silently fine, but the
  query cost multiplies. Leave a comment and a test that asserts the
  single-worker assumption, or detect it.
- The API and the ingest are **separate containers** (`docker-compose.yml`:
  `api` and `ingest`), so there is no in-process event source to
  subscribe to. The broadcaster polls the database. Postgres
  `LISTEN`/`NOTIFY` from the ingest would be lower latency and is a
  later option; it is not needed to get O(1) in viewers, which is the
  whole benefit.

### 6.4 Watching for hours

The owner said hours explicitly. Each item below is a present defect or
a specific guard.

**Memory.**

- Today: ~190,000 `L.Polyline` objects with bound tooltips and click
  closures per hour at 52 obs/s. After: **zero objects per event**. Marks
  are slots in a pre-allocated pool of 256.
- `trafficSeen` is pruned by time and is correct. Keep it, comment and
  all.
- `traceSeen` is pruned by insertion order (`app.js:953`) — the bug that
  was already fixed for traffic. Convert it to a time-keyed Map with a
  cutoff prune.
- Cap the panel at 40 rows by trimming, not by rebuilding.
- `mapState.lastNodes` holds one array. Fine.

**Timers.**

- Today: 13 per traffic line, 25 per trace hop, up to ~5,000 pending.
- After: **two timers for the whole page** — the fetch interval and a
  watchdog — plus one `requestAnimationFrame` handle. That is the number
  to check in a console audit.

**Page exit.**

- `route()` has no exit hook, so leaving the map leaves fades running.
  Add one: cancel the rAF loop, clear the pool, stop the fetch interval.

**Sleep and wake.** Concretely:

1. `setInterval` fires once on wake, not N times, so there is no request
   storm. Good today, keep it.
2. All pending `setTimeout` fades fire in one clump on wake. After the
   redesign there are none, so this disappears.
3. The rAF loop resumes with an enormous `dt`. **Clamp `dt` to 100 ms
   per frame**, or every mark jumps to its end state and the heat decays
   to zero in a single step.
4. On `visibilitychange → visible`, **discard the replay buffer and
   refetch**. Do not replay 40 minutes of sleep.
5. Print what happened: "resumed, skipped 38 min". A tab hidden for
   three hours currently shows stale content under a stale
   "Updated HH:MM" with no warning at all.
6. `document.hidden` already gates the poll. Keep it, and add the
   `visibilitychange` handler, which does not exist.

**Watchdog.** If three consecutive fetches fail, the live dot goes to
`down`, the animation stops, and the panel says so. It must not keep
replaying the last buffer as if the mesh were still talking. A monitor
that can only go green is not a monitor.

### 6.5 One thing worth saying about rate limiting

There is no rate-limiting middleware. `/api/map/traffic` is public,
unauthenticated, accepts `minutes=1440` and `limit=2000`, and runs the
correlated count described in `docs/REVIEW.md` 2.1. Watch mode will
increase traffic to it. Fixing 2.9 matters more than it did, and a
modest per-IP cap on that one endpoint is worth considering alongside
`counts=false`. Out of scope for this design; in scope for whoever
merges it.

---

## 7. Phasing

### Phase 1 — one sitting, four to six hours, no API change

Every item is independently valuable and the whole is visibly better.

1. **Fix the two feed bugs.** Gate SNR on `direct`; print "its own
   upload" for sender = gateway. Copy the packet page's cells exactly,
   so the two pages stop disagreeing.
2. **Aggregate to packets.** Key on `(from.node_id, packet_id)`, group
   uploads, draw at most three arcs, show `+N` beside the sender. Fixes
   faults (a), (b) and (c) in one change and removes 70–85% of strokes.
3. **Time-dilated replay** across the poll interval, ordered by
   `seen_at`, with the lag stated on screen.
4. **One canvas, one rAF loop, one mark pool**, in a dedicated Leaflet
   pane with `filter: none`. Delete the per-line `setTimeout` chains.
5. **Bow relayed arcs by hop count**; flat stays direct; stipple for
   `null` hops; no arc for a self-upload.
6. `snrColour(null)` → dimmest, not `--accent`.
7. **Cache `/api/graph/channels` for 10 min; fetch `/api/map/nodes`
   every 120 s.**
8. **Fullscreen.** `L.Control` bottom right, Fullscreen API with the CSS
   fallback, Escape and `F`, chrome hiding, and the two existing panels
   folded into one tabbed overlay reusing `.map-overlay` — which
   currently styles nothing, so the class is free. Collapse its
   duplicate definition while there.
9. **`prefers-reduced-motion` path plus the Motion toggle.**
10. **The "drawing N of M" counter** and the replay-lag line.

All of it lands in `app.js`, `app.css` and two sprite symbols in
`index.html`. `OVERNIGHT-PLAN.md` flags those files as a collision risk
— **sequence this work, do not parallelise it**, and expect the line
numbers in section 0 to have moved.

### Phase 2 — a few days

- The full particle alphabet: seven shapes, the `--pkt-*` palette.
- Node heat with the 20 s half-life, and the gateway ring kept
  separate from it.
- The admission ladder, the rate thresholds, the p95 frame-time
  governor, and the honesty banner.
- Panel expand with the wide table and the packets-per-second sparkline.
- Feed row coalescing and keyed updates in place of `replace()`.
- Backend: `since` and `counts=false` on `/api/map/traffic`, documented
  in `docs/API.md`.
- Poll at 5 s; sleep and wake handling; the watchdog.
- The keyboard map, including `Space` to pause.
- Fragment-persisted tab and panel height.
- Convert `traceSeen` to a time-pruned Map. Add the `route()` exit hook.

### Phase 3 — about a week, honestly

- `GET /api/map/live` as SSE: one in-process broadcaster owning one
  session, a 2 s tick, `Last-Event-ID` resume, a hard cap with `503` and
  `Retry-After`, and a client that falls back to polling on any failure.
- The `docs/ISSUES.md` 2.9 / `docs/REVIEW.md` 2.1 query rewrite. The
  counters are what make any of this expensive.
- Tests that matter: one proving the client falls back when SSE answers
  503 (**test the failing state, not only the green one**); one proving
  the broadcaster holds one session with twenty clients attached; one
  pinning the single-worker assumption.

The week is the broadcaster, the backpressure, the query rewrite and the
tests. It is not the animation. The animation is phases 1 and 2.

### Phase 4 — optional, and the good one

- **A 60-second scrub-back buffer.** Pause, then rewind and replay the
  last minute, entirely client-side, at zero server cost. This is the
  one genuinely delightful thing left, and it is the natural reward for
  having built a replay buffer in phase 1.
- Split screen, one preset per half, which 9.7 permits and a blend does
  not.
- "Follow this node": centre on it, dim everything it did not touch.

---

## 8. What I would not build, and why

1. **Anything drawn from `relay_node`.** 5.4% of observations resolve to
   a single node (9.20). A line that is wrong 95% of the time is worse
   than no line, and it would look authoritative.
2. **Inferred routes.** Shortest path through the neighbour graph to
   "fill in" a relayed packet's journey would be the most beautiful
   thing on the page and it would be fiction. AGENTS.md 9.21 is the
   record of what happens when an inferred number gets displayed beside
   measured ones: it gets read as a measurement. The neighbour graph is
   32 hours of reports about a mesh that changes.
3. **WebSocket.** Nothing to send upstream, breaks the GET-only rule,
   and needs a CSP change that fails silently (9.9).
4. **Sound.** Genuinely tempting for a watch mode, and wrong here:
   autoplay policy makes it unreliable, it has no reduced-motion
   equivalent, and it encodes volume in a channel that cannot be
   screenshotted, reviewed, or audited.
5. **A 3D or globe view, or deck.gl / WebGL.** New dependency, no build
   step, and the payoff is aesthetic rather than informational. The
   2D canvas budget in 4.4 is not close to exhausted.
6. **A "heard by" count anywhere on the map.** Both the name and the
   number are wrong (9.5.1).
7. **Smoothed rate charts.** A smoothed packets-per-second line hides
   the bursts, and the bursts are the phenomenon the owner wants to
   watch. Raw, with a visible sample interval.
8. **Free-drag resizable panels.** Snap heights only.
9. **An "all presets" firehose.** 9.7. Not a preference — the lines
   cannot exist.
10. **Server-rendered video or pre-baked animation tiles.** Three shared
    cores, and a public embed to protect.
11. **A new page or route for watch mode.** It is a state of the map, in
    the fragment.
12. **Animated telemetry on the nodes** — temperature drifting, battery
    bars filling. That is state, not an event. Rule B.
13. **Neighbour links on by default in watch mode.** 1,500 static dashed
    lines under a live animation is the "standing mat of old lines" the
    existing comments already fought off once. Off by default, one
    keypress on.

---

## 9. AGENTS.md traps that shaped this design

| Trap | How it constrained the design |
|---|---|
| 9.1 packet identity is `(from_node_num, packet_id)` | The dedupe key must carry the sender; today it does not |
| 9.3 every gateway stamps its own `rx_time` | The animation clock is `seen_at`, nothing else |
| 9.4 node clocks are wrong, sometimes badly | No latency, no speed, constant flight duration |
| 9.5 a gateway observation is usually not a direct link | Flat lines only for `direct`; colour only on flat lines |
| 9.5.1 "heard by" is a list of uploads | The unit is the packet; `gateway_count`, not row count; emission heat and upload ring never merged |
| 9.6 traceroute SNR needs care | `null` means not measured; stipple, not a weak colour; most hops have none |
| 9.7 one graph per modem preset | No blended firehose; the preset name never leaves the screen |
| 9.8 mesh-graph keys a trace on the request ID | Panel rows link with `id`, not `trace_id` |
| 9.9 the CSP is built from configuration | SSE over WebSocket; `connect-src` already covers `EventSource` |
| 9.9.1 the tiles need a Referer | Attribution stays visible in fullscreen; fragment state leaks nothing |
| 9.18 a traceroute row is not a path | `completed_only` stays true; one reading of a row, in `api/traces.py` |
| 9.19 a row limit must never decide what evidence exists | The 2000-row cap is named on screen, not hidden behind a window picker |
| 9.20 an ordinary packet does not carry its route | Bowed arcs; `relay_node` refused outright |
| 9.21 a calibration estimate is not a radio reading | No inferred paths; inferred and measured never share an encoding |
| 9.22 a role of NULL is a client | The role legend and node colours stay as they are; NULL is not "unknown" |

Open project items this design touches: `docs/ISSUES.md` 2.3 (the
relayed lines this design finally answers, by bowing them rather than
deleting them), 2.9 and `docs/REVIEW.md` 2.1 (the correlated count,
which phase 2's `counts=false` sidesteps and phase 3 should fix).
