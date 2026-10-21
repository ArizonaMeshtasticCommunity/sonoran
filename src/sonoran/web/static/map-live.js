/*
 * The live map animation: one canvas, one requestAnimationFrame loop,
 * one pool of marks.
 *
 * There is no build step. This file loads before app.js and exposes one
 * global, `SonoranLive`. Nothing here reads an app.js binding, so the
 * load order carries no risk: app.js hands over everything this needs.
 *
 * Why it exists as its own file at all: the old map drew each upload as
 * a Leaflet polyline and faded it with a chain of twelve setTimeout
 * calls. At fifty observations a second that is about 680 timers a
 * second, up to five thousand pending, and roughly 190,000 Leaflet
 * objects an hour. With `preferCanvas` a setStyle marks a redraw region,
 * and a traffic line spans Arizona, so every fade step redrew every
 * live line. The owner watches this for hours.
 *
 * Three rules from docs/design/live-map-watch-mode.md are load bearing
 * and this file is where they are kept:
 *
 *   A. Flatness is evidence. A straight line between two nodes claims a
 *      radio link, so only a `direct` observation and a traceroute hop
 *      earn one. Everything else bows, by an amount set by the hop
 *      count, and an unknown hop count is stippled.
 *   B. Motion means "just now, and that way", and nothing else.
 *   C. The unit is the packet, not the upload. See AGENTS.md 9.5.1:
 *      `packet_seen` holds MQTT uploads, so one packet arrives as many
 *      rows and drawing each one says "fifteen nodes heard this", which
 *      is the reading that section exists to forbid.
 *
 * Nothing here encodes speed. Every gateway stamps its own `rx_time`
 * and node clocks have been 28 hours out (AGENTS.md 9.3, 9.4), so
 * latency is not measurable and flight time is therefore a constant for
 * every mark. A viewer cannot read a measurement out of a number that
 * never varies.
 */

'use strict';

const SonoranLive = (() => {
  /* --- Timings ---------------------------------------------------- */

  /*
   * Constant for every event, whatever the distance or the hop count.
   * A long arc therefore moves faster in pixels per second than a short
   * one, which is deliberate: a constant pixel speed would make a
   * distant link look slow and a viewer would read that as latency.
   */
  const FLIGHT_MS = 850;
  const EMIT_PULSE_MS = 320;
  const ARRIVE_PULSE_MS = 260;
  /*
   * A mark flies twice, then stays solid, then fades out.
   *
   * It used to fly once and be gone in about two seconds, which is
   * shorter than a glance away from the screen. Now the particle runs
   * the arc twice, the whole line then holds solid, and it fades over a
   * few seconds rather than vanishing, so a reader who looks up late
   * still sees what just happened. Each pass takes the same constant
   * time, so flight time still says nothing about distance.
   */
  const FLIGHT_PASSES_MS = FLIGHT_MS + FLIGHT_MS;
  const HOLD_MS = 5000;
  const FADE_MS = 3000;
  /* A mark holds the sender's `+N` numeral for as long as its line. */
  const ARC_LIFE_MS = FLIGHT_PASSES_MS + HOLD_MS + FADE_MS;
  const TRAIL_MS = HOLD_MS + FADE_MS;
  const TRACE_HOLD_MS = 6000;
  const TRACE_FADE_MS = 3000;
  const TRACE_LIFE_MS = TRACE_HOLD_MS + TRACE_FADE_MS;
  const TRACE_STEP_MS = 180;
  /*
   * With motion reduced a mark is painted whole, held, and faded out.
   * It used to be gone in one step after under a second. A change of
   * opacity is not movement, so the fade stays when motion is reduced.
   */
  const STATIC_LIFE_MS = HOLD_MS + FADE_MS;

  /*
   * How long a line lasts with motion off (#222).
   *
   * The two states are meant to answer different questions. Motion on
   * says "just now, and that way" (rule B) and is deliberately brief.
   * Motion off has no movement to carry that, so its job is the lasting
   * picture: what has crossed the mesh recently.
   *
   * It did not do that job. Motion off painted a line whole, held it
   * 5 s and faded it over 3 s -- 8 s in total, against a 15 s poll, so
   * the map spent half of every cycle empty. Both states looked like
   * the same short-lived thing, which is the report.
   *
   * 30 s of hold is longer than the poll by design: the map is never
   * empty between fetches, which is the property that makes it read as
   * a picture rather than a flicker. The fade is unchanged -- opacity
   * is not movement, so it is honest in both states.
   */
  const LIVE_HOLD_MS = 30000;
  const LIVE_LIFE_MS = LIVE_HOLD_MS + FADE_MS;

  /* --- Caps ------------------------------------------------------- */

  /*
   * The pool is 256 slots and the cap is 220 live marks, so there is
   * always headroom for the pulses of a packet whose arcs were the last
   * thing admitted. Over budget, a packet is refused whole and counted:
   * the status line prints the real numbers rather than thinning the
   * picture quietly.
   */
  const POOL_SIZE = 256;
  const MAX_LIVE = 220;
  const MAX_ARCS_PER_PACKET = 3;
  const MAX_RELEASE_PER_FRAME = 60;
  const MAX_TRACE_PATHS = 12;
  /* One flash per node per 400 ms. A node talking faster than that is a
   * rate, and a rate is not something a flash can say. */
  const EMIT_GAP_MS = 400;
  /* Shorter than this on screen and there is nowhere for a particle to
   * travel, so the two pulses carry the whole event. */
  const MIN_CHORD_PX = 18;
  /* A long sleep must not step every decay to its end in one frame. */
  const MAX_DT_MS = 100;

  /* --- Heat: two quantities that are never added together --------- */

  /*
   * The owner's favourite thing about this map was the heat, and phase 1
   * took it away on purpose: the "heat" was overlapping fades of one
   * stroke per upload, so a packet uploaded by fifteen gateways glowed
   * fifteen times as hard as one uploaded by a single gateway. That is
   * AGENTS.md 9.5.1 drawn as a brightness. Grouping to packets removed
   * it, and removed the texture with it.
   *
   * So the heat comes back as two measured quantities, with the rule
   * that decides everything about how they are drawn:
   *
   *   Emission heat is how much a node SAID. One point per packet the
   *   node originated.
   *
   *   Upload heat is how much a node UPLOADED as a gateway. One point
   *   per upload row it contributed, other people's traffic included.
   *
   * They are never summed, never share a mark and never share a scale.
   * A busy gateway relaying other people's traffic is not a chatty node,
   * and a single glow that mixed the two would be 9.5.1 reappearing as
   * an aggregate — the map would once again be drawing uploads as though
   * they were something a node did. Two stores, two decays, two shapes,
   * two lines in the legend.
   *
   * Both are relative, not absolute. Neither has a unit a viewer could
   * read off, and the legend says so: the mark says "more than its
   * neighbours, just now", which is exactly what the data supports.
   */
  const EMIT_HALF_LIFE_MS = 20000;
  /*
   * The upload ring decays more slowly than the emission halo, and that
   * is the second thing keeping the two apart. A gateway's job is steady
   * and a node's voice is bursty, so a shared half-life would make the
   * two marks rise and fall together and invite exactly the reading that
   * must never be available: that one causes the other.
   */
  const UPLOAD_HALF_LIFE_MS = 30000;
  /*
   * Below this a node is forgotten entirely, so neither store can grow
   * for as long as the tab is open and the loop can reach a full stop.
   *
   * The floor belongs where the mark stops carrying information rather
   * than where it stops existing. Both scales are logarithmic to a
   * ceiling, so a value of 0.2 puts the halo 0.6 px above its minimum
   * radius and the ring 0.18 px above its minimum weight — nothing a
   * viewer can tell from a node at the bottom of the scale. Holding it
   * longer would keep the loop awake to redraw a mark that is no longer
   * saying anything, and the target is no processor cost at all when the
   * mesh is quiet.
   *
   * Measured: a flood of three hundred packets drains both stores to
   * empty and stops the loop dead, with the frame counter frozen. The
   * time is bounded by the decay, and it is the decay that has to be
   * long — a quantity with a twenty second half-life that vanished in a
   * second would be a mark that changed for no reason in the mesh.
   */
  const HEAT_FLOOR = 0.2;
  /*
   * The design puts the halo under the node dot so volume can never
   * obscure identity. A canvas pinned to the map container cannot sit
   * under the dots: Leaflet's map pane carries its own stacking context,
   * so a sibling below it is below the basemap as well. The halo is
   * therefore an annulus with a hole large enough to clear the widest
   * node dot and its stroke, which gives the same guarantee — the dot is
   * never painted over — without a second transformed canvas. The radii
   * moved with the shape; the encoding did not. Radius carries the
   * quantity, and it saturates at HEAT_FULL.
   */
  const HALO_HOLE_PX = 10;
  const HALO_MIN_PX = 14;
  const HALO_MAX_PX = 32;
  /* Steps of fill, inside out. More of them is a smoother falloff and
   * the difference between a glow and a second ring, which matters:
   * a gateway already wears a ring and the halo must not read as one. */
  const HALO_STEPS = 5;
  /* The gateway dot is radius 7 with a 2.5 px stroke. The upload ring is
   * concentric with it and grows outward, so it reads as that same ring
   * thickening rather than as a second mark. */
  const RING_RADIUS_PX = 9;
  const RING_MIN_PX = 1.4;
  const RING_GAIN_PX = 3.6;

  /*
   * Where each scale saturates, and why the mapping is logarithmic.
   *
   * These are display ceilings, not claims. Nothing reads a number off
   * either mark and the legend promises only "wider means more", so a
   * ceiling is a choice about legibility rather than a measurement being
   * asserted. That is also why it may be chosen from what the data does
   * rather than from first principles — but it has to be chosen from
   * something, so it was measured instead of guessed.
   *
   * Measured on the development seed at `tools/dev/seed.py --live`, over
   * a minute, through `SonoranMap.stats.heatValues()`:
   *
   *   emission heat across active senders   0.27 to 2.06
   *   upload heat across active gateways    0.36 to 18.4
   *
   * A linear ramp to 8 therefore spent three quarters of the halo's
   * range on values that never occur, and every node came out the same
   * size — the mark was there and said nothing. The steady state for a
   * node sending at r packets a second is about 28.9r, so emission 8 is
   * a node talking every three and a half seconds, which is genuinely
   * chatty and the right place to stop. The ceiling is kept and the ramp
   * is made logarithmic, so the resolution sits where the values are:
   * 0.3, 1 and 2 are three visibly different halos, and a node that
   * really is at 8 is still pinned at the top.
   *
   * A relative scale — sized against the busiest node on screen — was
   * the other option and is worse. A node's mark would change size
   * because a different node got busy, which is a change in the picture
   * that nothing in that node caused, and a viewer has no way to see
   * which of the two moved.
   */
  const HEAT_FULL = 8;
  const UPLOAD_FULL = 40;

  /**
   * Position on a mark's scale, in 0..1, logarithmic to the ceiling.
   *
   * Zero heat is zero, the ceiling is one, and everything between has
   * resolution where the values actually are. Monotonic, so more is
   * always bigger and the mark can never invert.
   */
  function heatScale(value, ceiling) {
    if (!(value > 0)) return 0;
    return Math.min(1, Math.log2(1 + value) / Math.log2(1 + ceiling));
  }
  /* Heat is drawn for at most this many on-screen nodes. Whatever the
   * cap refuses is counted and said, never dropped quietly. */
  const MAX_HEAT_NODES = 160;
  /* The heat order changes on a 20 s half-life, so a quarter second old
   * ordering is exact enough and costs one sort per four frames instead
   * of one per frame. */
  const HEAT_SORT_MS = 250;
  /* With motion reduced the decay is snapped to this grid, so the heat
   * steps once a second rather than gliding. */
  const HEAT_STEP_MS = 1000;

  /* --- The admission ladder --------------------------------------- */

  /*
   * Five rungs. Over budget, drop from the bottom of the design's list,
   * never from the top, and say what was refused.
   *
   *   0  everything: three arcs per packet
   *   1  two arcs
   *   2  one arc
   *   3  one arc, and none at all for a position or telemetry packet
   *      from a node already above emission heat 6 — those become heat
   *      only, which is where their volume was always going to live
   *   4  no ordinary arcs. A `direct` observation, a text message and a
   *      traceroute hop keep theirs, because they are the top three
   *      items of the keep list and a ladder that drops from the bottom
   *      cannot reach them. Everything else is heat and pulses.
   *
   * The rate table in the design names four bands and skips rung 2; the
   * frame-time governor steps one rung at a time and so visits it. The
   * rate band is therefore a floor and the governor may go finer, which
   * is the only reading of the two that does not contradict itself.
   */
  const RUNG_FULL = 0;
  const RUNG_HEAT_ONLY = 4;
  const RUNG_LABELS = [
    '',
    '2 arcs per packet',
    '1 arc per packet',
    '1 arc per packet, busy senders are heat only',
    'heat map only, arcs off',
  ];
  const RUNG_ARCS = [MAX_ARCS_PER_PACKET, 2, 1, 1, 1];
  /* A node this hot is already the loudest thing in its part of the map,
   * so its position and telemetry arcs say nothing its halo does not. */
  const RUNG3_HEAT = 6;

  function rungForRate(perSecond) {
    if (perSecond <= 6) return 0;
    if (perSecond <= 20) return 1;
    if (perSecond <= 50) return 3;
    return 4;
  }

  /*
   * Thin the arcs before the pool starts refusing packets whole (#222).
   *
   * The rate ladder and the frame governor both miss this case. A mark
   * held for 30 s instead of 8 s is alive about four times as long, so
   * the number on screen is four times the rate's worth -- and the cap
   * binds long before frames get slow, because refused packets are
   * cheap to draw. The map would sit at the cap quietly showing less.
   *
   * Pressure is measured against the cap that actually refuses, so this
   * escalates only when the pool is genuinely close to full. It is the
   * same lever the rate ladder pulls, and the rung is named in the
   * status line, so the thinning is reported rather than quiet -- which
   * is the condition the caps comment above sets for thinning at all.
   */
  const MARK_PRESSURE_RUNGS = [
    [0.95, 3],
    [0.85, 2],
    [0.70, 1],
  ];

  function rungForMarks(alive) {
    const share = alive / MAX_LIVE;
    for (const [threshold, rung] of MARK_PRESSURE_RUNGS) {
      if (share >= threshold) return rung;
    }
    return 0;
  }

  /* The frame budget is 8 ms for the whole canvas, leaving 8 ms for
   * Leaflet, the tiles and the DOM. Hysteresis in both directions, so a
   * map sitting near the threshold does not oscillate. */
  const FRAME_BUDGET_MS = 8;
  const FRAME_RECOVER_MS = 4;
  const OVER_BUDGET_SECONDS = 3;
  const UNDER_BUDGET_SECONDS = 10;
  /* The measured rate is over this many seconds of releases, so one
   * burst inside a poll does not trip the ladder on its own. */
  const RATE_WINDOW_MS = 5000;

  /* --- Geometry: the bow carries the hop count ------------------- */

  /*
   * Bow amplitude as a fraction of the on-screen chord, perpendicular to
   * it. Flat is the claim "these two radios heard each other"; a bowed
   * line visibly leaves the ground, which is how a map says "this is a
   * relation, not a route". An ordinary packet does not carry its route
   * (AGENTS.md 9.20), so the hop count is the whole of what is known and
   * the geometry is where it goes.
   */
  const BOW = [0.0, 0.12, 0.22, 0.3, 0.36];
  const BOW_UNKNOWN = 0.26;

  function bowFor(packet) {
    if (packet.any_direct) return 0;
    if (packet.min_hops == null) return BOW_UNKNOWN;
    return BOW[Math.min(packet.min_hops, BOW.length - 1)];
  }

  /* --- Packet families: shape first, colour second --------------- */

  /*
   * Seven families and a bucket. Shape and hue are redundant, so the
   * alphabet still reads with every colour removed — the accessibility
   * requirement is met by construction rather than by a later audit.
   *
   * Text is the brightest and the largest because it is the rarest
   * packet and the only one a person wrote. The bucket is the dimmest,
   * which is the same principle `snrColour` now applies to an unmeasured
   * signal: unknown is not a grade and must not outrank one.
   */
  const FAMILIES = {
    POSITION_APP: { shape: 'disc', size: 5, token: 'pkt-position', fallback: '#f4703f', label: 'Position' },
    NODEINFO_APP: { shape: 'ring', size: 6, token: 'pkt-nodeinfo', fallback: '#a48fd0', label: 'Node info' },
    TELEMETRY_APP: { shape: 'square', size: 5, token: 'pkt-telemetry', fallback: '#46b3e6', label: 'Telemetry' },
    TEXT_MESSAGE_APP: { shape: 'capsule', size: 10, token: 'pkt-text', fallback: '#f6ece2', label: 'Text message' },
    TRACEROUTE_APP: { shape: 'diamond', size: 7, token: 'pkt-trace', fallback: '#b6d94c', label: 'Traceroute' },
    ROUTING_APP: { shape: 'cross', size: 6, token: 'pkt-routing', fallback: '#b59c88', label: 'Routing' },
    OTHER: { shape: 'tick', size: 3, token: 'pkt-other', fallback: '#7d6857', label: 'Other Types' },
  };

  /* The order the legend draws them in: commonest first, bucket last. */
  const FAMILY_ORDER = [
    'POSITION_APP', 'TELEMETRY_APP', 'NODEINFO_APP', 'TEXT_MESSAGE_APP',
    'TRACEROUTE_APP', 'ROUTING_APP', 'OTHER',
  ];

  /**
   * The family of one port number.
   *
   * A port this build has never heard of, and a null port, both fall to
   * the bucket. Null is not a fault: an observation whose packet row is
   * older than the window plus the ten-minute lookback comes back with
   * no port at all, and the honest mark for it is the dim tick that says
   * "a packet of a kind this view does not distinguish".
   */
  function familyOf(portnum) {
    return FAMILIES[familyKey(portnum)];
  }

  /**
   * The key of one port number's family, with the same fall to the bucket.
   *
   * The packet filter works on keys. A port this build does not know is
   * `OTHER`, so hiding every named family can never hide a packet we
   * failed to classify without also saying so: the bucket has a chip.
   */
  function familyKey(portnum) {
    return portnum && FAMILIES[portnum] ? portnum : 'OTHER';
  }

  /* --- Aggregation: from uploads to packets ---------------------- */

  /**
   * Group observations into packets.
   *
   * The key is (`from.node_id`, `packet_id`), which is the identity
   * AGENTS.md 9.1 gives: a packet ID is unique per sender only, so two
   * senders that pick the same 32-bit value inside one window are two
   * packets and must not collapse into one.
   *
   * `gateway_count` counts distinct gateways, never rows. One live
   * packet had 22 uploads from 15 gateways (9.5.1), so the row count is
   * not a number of gateways and must never be shown as one.
   *
   * A gateway that is the sender uploaded its own voice. That is an MQTT
   * upload, not a transmission across ground, so it earns no arc — the
   * endpoint already says so in `has_line`.
   */
  function aggregate(events) {
    const byPacket = new Map();
    for (const event of events || []) {
      // A node ID is `!` and eight hex digits and a packet ID is
      // decimal, so a slash between them can never be ambiguous.
      const key = `${event.from.node_id}/${event.packet_id}`;
      let packet = byPacket.get(key);
      if (!packet) {
        packet = {
          key,
          packet_id: event.packet_id,
          from: event.from,
          portnum: event.portnum,
          channel: event.channel,
          time: event.time,
          timeMs: Date.parse(event.time) || 0,
          upload_count: 0,
          gateways: new Map(),
          any_direct: false,
          min_hops: null,
          self_upload: false,
          direct_snr: null,
        };
        byPacket.set(key, packet);
      }
      packet.upload_count += 1;
      const at = Date.parse(event.time) || 0;
      // The latest upload is the packet's time. `seen_at` is our own
      // receive clock, which is the only time in this system a client
      // may order on. See AGENTS.md 9.3 and 9.4.
      if (at > packet.timeMs) {
        packet.timeMs = at;
        packet.time = event.time;
      }
      if (packet.portnum == null && event.portnum != null) packet.portnum = event.portnum;
      if (event.from.node_id === event.gateway.node_id) packet.self_upload = true;
      if (event.direct === true) {
        packet.any_direct = true;
        // Only a direct observation measures the sender's own link. On a
        // relayed one the SNR belongs to the last hop into the gateway,
        // which is a different pair of radios. See AGENTS.md 9.5.
        if (event.snr != null && (packet.direct_snr == null || event.snr > packet.direct_snr)) {
          packet.direct_snr = event.snr;
        }
      }
      /*
       * A self-upload's hop count says nothing about the packet crossing
       * ground. The sender uploading its own transmission carries
       * `hop_start == hop_limit`, so it reads as zero hops, and folding
       * that into the minimum made a relayed packet print "0 hops" —
       * which says the two nodes were in range when nothing showed it.
       * See AGENTS.md 9.5.1, where all three apparently-direct rows of a
       * live packet turned out to be the sender.
       */
      if (event.hops_taken != null && event.from.node_id !== event.gateway.node_id) {
        packet.min_hops = packet.min_hops == null
          ? event.hops_taken
          : Math.min(packet.min_hops, event.hops_taken);
      }
      const gatewayId = event.gateway.node_id;
      const held = packet.gateways.get(gatewayId);
      if (!held) {
        packet.gateways.set(gatewayId, {
          gateway: event.gateway,
          direct: event.direct === true,
          hops: event.hops_taken,
          has_line: event.has_line === true,
          snr: event.snr,
          uploads: 1,
        });
      } else {
        held.uploads += 1;
        if (event.direct === true) held.direct = true;
        if (event.hops_taken != null && (held.hops == null || event.hops_taken < held.hops)) {
          held.hops = event.hops_taken;
        }
        if (event.has_line === true) held.has_line = true;
      }
    }

    const packets = [];
    for (const packet of byPacket.values()) {
      packet.gateway_count = packet.gateways.size;
      /*
       * At most three arcs, to the gateways that burned the fewest hops,
       * direct ones first. The rest become a numeral beside the sender
       * and an exact count in the panel, which is where precision
       * belongs: a panel row can be read and an 850 ms particle cannot.
       */
      const drawable = [...packet.gateways.values()]
        .filter((item) => item.has_line)
        .sort((a, b) => {
          if (a.direct !== b.direct) return a.direct ? -1 : 1;
          const ah = a.hops == null ? Infinity : a.hops;
          const bh = b.hops == null ? Infinity : b.hops;
          return ah - bh;
        });
      packet.arcs = drawable.slice(0, MAX_ARCS_PER_PACKET);
      /*
       * The numeral counts every distinct gateway this packet did not
       * get an arc for, which includes the ones with no position and the
       * sender's own upload as well as the ones the cap refused. All of
       * them really did upload it, so all of them belong in the count.
       */
      packet.extra = packet.gateway_count - packet.arcs.length;
      packets.push(packet);
    }
    packets.sort((a, b) => a.timeMs - b.timeMs);
    return packets;
  }

  /* --- Heat stores ------------------------------------------------ */

  /**
   * The value of one heat cell now, after its own decay.
   *
   * Exponential with a half-life, so the quantity is "how much lately"
   * and an old burst fades rather than being cut off at a window edge. A
   * window edge would make the mark jump when nothing happened, which is
   * a change in the picture that no change in the mesh caused.
   */
  function heatNow(cell, at, halfLifeMs) {
    if (!cell) return 0;
    const age = at - cell.at;
    if (age <= 0) return cell.value;
    return cell.value * 2 ** (-age / halfLifeMs);
  }

  /**
   * Add to one node's heat in one store.
   *
   * The two stores are passed in rather than reached for, because the
   * one rule this code has to keep is that no caller can ever add a
   * number from one of them to a number from the other. Separate
   * arguments make a merge something somebody would have to write on
   * purpose.
   */
  function heatAdd(store, nodeId, lat, lng, amount, halfLifeMs, at) {
    if (lat == null || lng == null) return;
    let cell = store.get(nodeId);
    if (!cell) {
      cell = { value: 0, at, lat, lng };
      store.set(nodeId, cell);
    }
    cell.value = heatNow(cell, at, halfLifeMs) + amount;
    cell.at = at;
    cell.lat = lat;
    cell.lng = lng;
  }

  /** Forget every node whose heat has fallen below what can be drawn. */
  function heatPrune(store, at, halfLifeMs) {
    for (const [nodeId, cell] of store) {
      if (heatNow(cell, at, halfLifeMs) < HEAT_FLOOR) store.delete(nodeId);
    }
  }

  /* --- The mark pool --------------------------------------------- */

  /*
   * Pre-allocated and reused, so the hot loop allocates nothing and a
   * three-hour watch has no sawtooth of garbage collection. A slot is
   * plain fields, never an object graph.
   */
  const KIND_ARC = 1;
  const KIND_PULSE = 2;
  const KIND_HOP = 3;

  function makeSlot() {
    return {
      live: false,
      kind: 0,
      born: 0,
      life: 0,
      lat0: 0, lng0: 0, lat1: 0, lng1: 0,
      bow: 0,
      stipple: false,
      flat: false,
      colour: '',
      shape: '',
      size: 0,
      numeral: 0,
      arriving: false,
      // The packet family, so a filter change can take a mark off the
      // map without waiting for it to fade. Empty for a traceroute hop.
      family: '',
    };
  }

  /* --- The engine ------------------------------------------------ */

  /**
   * Build the animation engine for one Leaflet map.
   *
   * `options.colour(token, fallback)` reads a CSS custom property, so
   * app.css stays the single source of the palette. `options.snrColour`
   * is the dashboard's own ramp, so a flat line on the map and a cell in
   * the panel cannot disagree.
   */
  function create(map, options = {}) {
    const readColour = options.colour || ((token, fallback) => fallback);
    const snrColour = options.snrColour || (() => '#ded2c6');

    const palette = {
      relayed: readColour('traffic-relayed', '#ded2c6'),
      stale: readColour('role-stale', '#7d6857'),
      /*
       * Two heat colours, and neither of them carries the meaning on its
       * own. The quantity is the radius of the halo and the thickness of
       * the ring, both of which survive being rendered in greyscale and
       * survive any colour-vision deficiency, because a size is not a
       * hue. The colours are here so the two layers read as belonging to
       * different things at a glance, not so one can be told from the
       * other by colour alone: the shapes already do that, a filled
       * annulus against a hollow ring.
       */
      emit: readColour('heat-emission', '#f4703f'),
      upload: readColour('heat-upload', '#f6ece2'),
    };
    const familyColour = new Map();
    for (const [key, family] of Object.entries(FAMILIES)) {
      familyColour.set(key, readColour(family.token, family.fallback));
    }
    const colourOf = (portnum) => {
      const name = portnum && FAMILIES[portnum] ? portnum : 'OTHER';
      return familyColour.get(name);
    };

    /*
     * A pane of its own, with the filter explicitly cancelled.
     *
     * app.css inverts and warms the basemap. An earlier version of that
     * rule named the tile pane rather than the layer, and it inverted
     * the coverage overlay's signal ramp as well, so the map drew the
     * legend backwards. A canvas of packet colours in a filtered pane
     * would come out inverted and the bug would look like a palette
     * mistake. See the comment above that rule in app.css.
     *
     * The pane is created as a direct child of the map container, not
     * inside the transformed map pane, so the canvas stays pinned to the
     * container and every mark is reprojected each frame instead of
     * riding a CSS transform.
     */
    const pane = map.createPane('sonoranLive', map.getContainer());
    pane.style.filter = 'none';
    pane.style.pointerEvents = 'none';
    pane.style.zIndex = '620';

    const canvas = document.createElement('canvas');
    canvas.className = 'live-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    pane.appendChild(canvas);
    const ctx = canvas.getContext('2d', { alpha: true, willReadFrequently: false });

    const pool = [];
    for (let index = 0; index < POOL_SIZE; index += 1) pool.push(makeSlot());
    let liveCount = 0;

    /*
     * Marks waiting for their release time. See `enqueue`.
     *
     * BOUNDED, and the bound matters because of what pausing does.
     * `setPaused(true)` cancels the animation frame, so nothing drains
     * this -- but the 15-second poll keeps calling `enqueue`. Holding
     * the buffer across a pause is deliberate and documented; holding
     * it without limit was not. Pause the map and walk away and this
     * grew for as long as you were gone, with an O(n log n) sort of
     * the whole backlog every 15 seconds and an O(n) walk on resume.
     *
     * The cap keeps the NEWEST marks and drops the oldest. On resume
     * somebody wants to see what the mesh is doing now, not a
     * fast-forward of the hour they missed, and the oldest marks in a
     * long backlog are the least interesting thing in it.
     *
     * Four times the pool because the pool is what can be on screen at
     * once; a few pool-loads of pending marks is a full-looking replay
     * and anything beyond it is never seen as motion.
     */
    const QUEUE_LIMIT = POOL_SIZE * 4;
    let queue = [];

    /** Drop the oldest pending marks when the queue is over its cap. */
    function trimQueue() {
      const over = queue.length - QUEUE_LIMIT;
      if (over > 0) queue.splice(0, over);
    }
    /* When a node last flashed, so a fast talker does not strobe. */
    const lastEmit = new Map();

    /*
     * Two stores, and nothing in this file ever reads one and writes the
     * other. See the note on EMIT_HALF_LIFE_MS: a single number holding
     * both would be "heard by" wearing a different coat.
     */
    const emitHeat = new Map();
    const uploadHeat = new Map();
    /* The on-screen draw list, rebuilt on a timer rather than per frame. */
    let heatList = { at: 0, halos: [], rings: [], hidden: 0 };

    /* --- Ladder state ------------------------------------------- */

    /* When each of the last few seconds of packets was released, so the
     * rate is measured rather than guessed. */
    let rateWindow = [];
    /* Draw times of the last second or so, for the p95. */
    let frameLog = [];
    let secondStart = 0;
    let overSeconds = 0;
    let underSeconds = 0;
    /* What the frame time alone would ask for. The rate band is a floor
     * and this may go finer; the rung in force is the higher of the two. */
    let governorRung = RUNG_FULL;
    let rung = RUNG_FULL;

    const stats = {
      /* Packets the batch offered, and packets actually drawn. The
       * status line prints both, because the eye cannot count marks. */
      offered: 0,
      drawn: 0,
      droppedBatch: 0,
      droppedNoRoom: 0,
      droppedThisMinute: 0,
      /* Arcs the ladder or the pool refused. A packet whose arcs were
       * cut is still drawn — it has a pulse and it raises heat — so this
       * is a different number from `droppedBatch` and both are said. */
      arcsDropped: 0,
      minuteStart: Date.now(),
      frames: 0,
      drawMs: [],
      p50: 0,
      p95: 0,
      lagMs: null,
      perSecond: 0,
      marksAlive: () => liveCount,
      queued: () => queue.length,
      rung: () => rung,
      heatNodes: () => emitHeat.size,
      gatewayNodes: () => uploadHeat.size,
      /*
       * The heat, as numbers, for the console.
       *
       * `window.SonoranMap` is already how this map answers questions
       * without a build step, and a quantity drawn as a size is exactly
       * the kind that cannot be checked by looking: two halos a pixel
       * apart are the same halo to the eye. So the values are readable,
       * and the scale constants are readable beside them, and anybody
       * can see whether the saturation point is the right one for this
       * mesh rather than taking the constant on trust.
       */
      heatValues: () => ({
        emission: [...emitHeat.values()]
          .map((cell) => heatNow(cell, performance.now(), EMIT_HALF_LIFE_MS))
          .sort((a, b) => b - a),
        upload: [...uploadHeat.values()]
          .map((cell) => heatNow(cell, performance.now(), UPLOAD_HALF_LIFE_MS))
          .sort((a, b) => b - a),
        saturatesAt: { emission: HEAT_FULL, upload: UPLOAD_FULL },
      }),
    };

    const onStats = options.onStats || null;
    /*
     * Told which packets a frame released, in the order they were drawn
     * (#386). The feed under the map lists a packet when its line starts,
     * not when the poll fetched it. See `enqueue`: a batch is spread over
     * the poll interval, so a list that took the whole batch at fetch time
     * showed five or six rows at once, up to fifteen seconds before their
     * lines. That is the "chunks" in the report.
     */
    const onRelease = options.onRelease || null;
    let lastStatsAt = 0;
    let frame = null;
    let running = false;
    let reduced = false;
    let hiddenForZoom = false;
    let lastFrameAt = 0;
    let scale = 1;
    let width = 0;
    let height = 0;
    let pageActive = true;
    /*
     * Paused holds the world still: marks stop ageing, heat stops
     * decaying, and the replay buffer keeps filling. A viewer watching a
     * burst wants to stop it and read what just happened, which is the
     * whole reason Space is worth a key of its own.
     */
    let paused = false;
    let pausedAt = 0;

    function resize() {
      const size = map.getSize();
      // A 3x phone gains nothing at these mark sizes and pays twice the
      // fill cost, so the render scale is capped at 2.
      scale = Math.min(window.devicePixelRatio || 1, 2);
      width = size.x;
      height = size.y;
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    }

    resize();
    map.on('resize', resize);
    /*
     * Leaflet transforms its panes during a zoom animation. This canvas
     * is pinned to the container and so receives no transform, which
     * would slide every mark for the length of the animation. Hiding it
     * for the quarter second is the honest fix, and it is what every
     * canvas overlay does.
     */
    map.on('zoomstart', () => { hiddenForZoom = true; canvas.style.visibility = 'hidden'; });
    map.on('zoomend', () => {
      hiddenForZoom = false;
      canvas.style.visibility = '';
      resize();
      if (paused) repaint();
    });
    /*
     * While paused the loop is stopped, so nothing would redraw the
     * marks after a pan and the frozen picture would slide off its
     * nodes. One draw per map movement is exactly the work the loop
     * would have done, and none of the work it would have done in
     * between. That is what keeps a paused map at no processor cost, and
     * the owner leaves this open for hours.
     */
    map.on('move', () => { if (paused) repaint(); });
    map.on('resize', () => { if (paused) repaint(); });

    /** Take a free slot, or nothing when the budget is spent. */
    function take() {
      if (liveCount >= MAX_LIVE) return null;
      for (const slot of pool) {
        if (!slot.live) {
          slot.live = true;
          liveCount += 1;
          return slot;
        }
      }
      return null;
    }

    function release(slot) {
      slot.live = false;
      liveCount -= 1;
    }

    function start() {
      if (running || !pageActive || paused) return;
      running = true;
      lastFrameAt = performance.now();
      frame = requestAnimationFrame(tick);
    }

    function stop() {
      running = false;
      if (frame != null) cancelAnimationFrame(frame);
      frame = null;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    /** Drop every mark, every pending release, and all the heat. */
    function clear() {
      for (const slot of pool) slot.live = false;
      liveCount = 0;
      queue = [];
      lastEmit.clear();
      emitHeat.clear();
      uploadHeat.clear();
      heatList = { at: 0, halos: [], rings: [], hidden: 0 };
      rateWindow = [];
      frameLog = [];
      governorRung = RUNG_FULL;
      rung = RUNG_FULL;
      overSeconds = 0;
      underSeconds = 0;
      /*
       * The pause is kept. A preset change clears the engine, and watch
       * mode can be paused at that moment with its status line saying so.
       * Un-pausing here started the replay under a "paused" label, and
       * the feed was no longer held with the map. The pause starts again
       * from now, so a resume shifts nothing that came after the clear.
       */
      if (paused) pausedAt = performance.now();
      stats.lagMs = null;
      stats.arcsDropped = 0;
      stats.perSecond = 0;
      stop();
    }

    /**
     * Stop and start the world.
     *
     * Pausing holds the buffer and keeps accumulating, so nothing that
     * arrives while a viewer is reading is lost. Resuming carries every
     * frozen age and every pending release forward by the length of the
     * pause, so the replay picks up exactly where it stopped rather than
     * firing the whole pause into one frame — which is the burst this
     * feature exists to remove. A viewer who does not want the backlog
     * has `skipToLive`, and the status line offers both.
     */
    function setPaused(value) {
      if (paused === value) return paused;
      if (value) {
        paused = true;
        pausedAt = performance.now();
        // One last frame, so the picture on screen is the picture at the
        // moment of the pause and not the one before it.
        drawFrame(performance.now());
        if (frame != null) cancelAnimationFrame(frame);
        frame = null;
        running = false;
      } else {
        const held = performance.now() - pausedAt;
        paused = false;
        for (const slot of pool) if (slot.live) slot.born += held;
        for (const item of queue) item.at += held;
        for (const store of [emitHeat, uploadHeat]) {
          for (const cell of store.values()) cell.at += held;
        }
        for (const [nodeId, at] of lastEmit) lastEmit.set(nodeId, at + held);
        rateWindow = rateWindow.map((at) => at + held);
        lastFrameAt = performance.now();
        start();
      }
      return paused;
    }

    /** Redraw the frozen picture once, after the map moved under it. */
    function repaint() {
      drawFrame(pausedAt);
    }

    /* --- Release scheduling: the replay ------------------------- */

    /**
     * Spread one batch of packets across the poll interval.
     *
     * The poll returns up to fifteen seconds of mesh activity in one
     * array, and the old renderer fired all of it in one synchronous
     * loop. The owner's complaint that "there's so many nodes hearing
     * things and it's hard to tell what direction things are going" is
     * in part an artefact of rendering fifteen seconds of history in
     * sixteen milliseconds: the burst was manufactured by the poll.
     *
     * Ordering is on `seen_at`, our own receive clock, which is the only
     * time value in this system that may be ordered on (AGENTS.md 9.3,
     * 9.4). A gateway's `rx_time` and a node's own clock may not.
     *
     * The cost is that the display runs up to one interval behind live,
     * and `lagMs` carries that so the page can say so. A watcher does
     * not care about a few seconds and does care about being able to
     * follow what happened.
     */
    function enqueue(packets, intervalMs) {
      if (!packets.length) return;
      const now = Date.now();
      const lo = packets[0].timeMs;
      const hi = packets[packets.length - 1].timeMs;
      const span = Math.max(1, hi - lo);
      // A batch wider than the interval is compressed to fit it rather
      // than clamped, so the relative order and spacing survive.
      const factor = Math.min(1, intervalMs / span);
      for (const packet of packets) {
        queue.push({ at: now + (packet.timeMs - lo) * factor, packet });
      }
      queue.sort((a, b) => a.at - b.at);
      trimQueue();
      start();
    }

    /** Queue one traceroute's hops, revealed a step apart. */
    function enqueueTrace(hops, delayMs) {
      const now = Date.now();
      let step = 0;
      for (const hop of hops) {
        queue.push({ at: now + delayMs + step * TRACE_STEP_MS, hop });
        step += 1;
      }
      queue.sort((a, b) => a.at - b.at);
      trimQueue();
      start();
    }

    let tracePaths = 0;

    /*
     * Which packet families are drawn. Null means all of them, which is
     * the default and the cheapest test.
     */
    let hiddenFamilies = null;
    const shows = (packet) => !hiddenFamilies || !hiddenFamilies.has(familyKey(packet.portnum));

    /**
     * Draw only some packet families.
     *
     * The change is immediate. Queued packets of a hidden kind are
     * dropped from the buffer, and marks of that kind already on the map
     * are taken off rather than left to fade, so the picture matches the
     * control the moment it is pressed.
     *
     * The heat is thrown away. It is one quantity summed over every
     * family, so it cannot be split after the fact, and a halo built
     * from positions would otherwise dominate a map filtered to text
     * messages for a whole half-life. It rebuilds from what arrives next.
     */
    function setFamilyFilter(hidden) {
      hiddenFamilies = hidden && hidden.size ? new Set(hidden) : null;
      queue = queue.filter((item) => item.hop || shows(item.packet));
      for (const slot of pool) {
        if (slot.live && slot.family && hiddenFamilies && hiddenFamilies.has(slot.family)) {
          release(slot);
        }
      }
      emitHeat.clear();
      uploadHeat.clear();
      heatList = { at: 0, halos: [], rings: [], hidden: 0 };
      if (paused) repaint();
    }

    /**
     * What the last batch offered, drew, dropped and still holds.
     *
     * `queued` matters as much as the rest. A packet still waiting for its
     * release time has not been dropped, and a counter that said
     * "drawing 0 of 10" while ten packets sat in the replay buffer would
     * be claiming a fault that had not happened — the same class of error
     * as sampling without saying so, pointing the other way. Only
     * `dropped` means something was refused.
     *
     * The lag is reported only while something is in flight. Once the
     * buffer has drained the last released packet's age is a fact about
     * the past, not about the picture, and leaving it on screen would say
     * the map is behind when it is idle.
     */
    function publicCounts() {
      const inFlight = queue.length > 0 || liveCount > 0;
      return {
        offered: stats.offered,
        drawn: stats.drawn,
        dropped: stats.droppedBatch,
        /* Marks on screen now: arcs, pulses and traceroute hops. */
        live: liveCount,
        queued: queue.length,
        lagMs: inFlight ? stats.lagMs : null,
        /*
         * The ladder's own numbers. `rung` is which step it is standing
         * on and `rungLabel` is that step in words, because "rung 3" is
         * not something a viewer can read. `arcsDropped` is separate
         * from `dropped`: a packet whose arcs were cut is still drawn —
         * it has a pulse and it raised heat — so the two are different
         * refusals and both get said. `heatHidden` is the nodes the heat
         * cap refused. Everything the picture leaves out has a number
         * here; nothing is thinned without being counted.
         */
        rung,
        rungLabel: RUNG_LABELS[rung] || '',
        arcsDropped: stats.arcsDropped,
        heatHidden: heatList.hidden,
        heatNodes: heatList.halos.length,
        gatewayNodes: heatList.rings.length,
        perSecond: stats.perSecond,
        p95: stats.p95,
        paused,
      };
    }

    /**
     * How many arcs this packet may draw at the rung in force.
     *
     * The ladder drops from the bottom of the design's list and never
     * from the top, so the three things it protects — a traceroute, a
     * `direct` observation and a text message — keep an arc at every
     * rung. A traceroute hop is the only true path on this map, a direct
     * observation is the only measured link, and a text message is the
     * only packet a person wrote.
     */
    function arcBudget(packet, senderHeat) {
      const protectedKind = packet.any_direct
        || packet.portnum === 'TEXT_MESSAGE_APP'
        || packet.portnum === 'TRACEROUTE_APP';
      if (rung >= RUNG_HEAT_ONLY) return protectedKind ? 1 : 0;
      if (rung === 3 && !protectedKind) {
        /*
         * A position or telemetry packet from a node that is already the
         * loudest thing in its part of the map. Its arc says nothing its
         * halo does not, so it becomes heat only — which is the one rung
         * of the ladder where the heat layer is what makes the drop
         * affordable rather than merely tolerable.
         *
         * The heat tested is the heat before this packet raised it, so
         * "already above" means what it says.
         */
        const chatty = packet.portnum === 'POSITION_APP' || packet.portnum === 'TELEMETRY_APP';
        if (chatty && senderHeat > RUNG3_HEAT) return 0;
      }
      return RUNG_ARCS[rung];
    }

    function admitPacket(packet) {
      /*
       * The emission pulse fires for every packet, including a packet
       * whose only upload was the sender's own: a self-upload has no
       * second place for a mark to go, so the pulse is the whole of it.
       */
      const previous = lastEmit.get(packet.from.node_id) || 0;
      const now = Date.now();
      const at = performance.now();

      const senderHeat = heatNow(emitHeat.get(packet.from.node_id), at, EMIT_HALF_LIFE_MS);
      const budget = arcBudget(packet, senderHeat);

      /*
       * Heat is raised whatever the ladder decided and whatever the pool
       * had room for, which is the point of having it: at the top rung
       * the arcs are gone and the heat is the whole picture, so a packet
       * that could not be drawn as a stroke is still drawn as volume. It
       * is also why heat is not gated on the pool — a halo costs a map
       * entry, not a slot.
       *
       * One point per packet the node originated, never per upload.
       */
      heatAdd(emitHeat, packet.from.node_id, packet.from.lat, packet.from.lon,
        1, EMIT_HALF_LIFE_MS, at);
      /*
       * And separately, one point per upload row, charged to the gateway
       * that made it — every gateway of this packet, not only the three
       * that got an arc. The uploads the arc cap refused are exactly the
       * thing the ring exists to hold, so they belong here rather than
       * nowhere. A gateway that is the sender raises both, because it
       * really did do both things.
       */
      for (const item of packet.gateways.values()) {
        heatAdd(uploadHeat, item.gateway.node_id, item.gateway.lat, item.gateway.lon,
          item.uploads, UPLOAD_HALF_LIFE_MS, at);
      }

      /*
       * The numeral counts every distinct gateway this packet will not
       * draw an arc for — the ones the three-arc cap refused, the ones
       * with no position, the sender's own upload, and now the ones the
       * ladder refused as well. It has to follow the rung: a numeral
       * computed for three arcs beside a packet that drew one would be a
       * count of gateways that does not add up, which is a small lie of
       * exactly the kind this map is being rebuilt to stop telling.
       */
      const willDraw = Math.min(budget, packet.arcs.length);
      const numeral = Math.max(0, packet.gateway_count - willDraw);

      let admitted = false;
      if (packet.from.lat != null && packet.from.lon != null && now - previous >= EMIT_GAP_MS) {
        const slot = take();
        if (slot) {
          lastEmit.set(packet.from.node_id, now);
          slot.kind = KIND_PULSE;
          slot.family = familyKey(packet.portnum);
          slot.born = at;
          slot.life = reduced ? LIVE_LIFE_MS : ARC_LIFE_MS;
          slot.lat0 = packet.from.lat;
          slot.lng0 = packet.from.lon;
          slot.colour = colourOf(packet.portnum);
          slot.numeral = numeral;
          admitted = true;
        }
      }

      const bow = bowFor(packet);
      const family = familyOf(packet.portnum);
      let drawnArcs = 0;
      for (const arc of packet.arcs) {
        if (drawnArcs >= budget) {
          /*
           * Never sample silently. Every arc the ladder or the pool
           * refused is counted here and printed on the status line, so
           * a thinner picture is a stated one. The `+N` numeral beside
           * the sender and the exact counts in the panel already hold
           * the gateways, so nothing the drop removed is unavailable —
           * it has only moved to where it can be read.
           */
          stats.arcsDropped += 1;
          continue;
        }
        const slot = take();
        if (!slot) {
          stats.arcsDropped += 1;
          break;
        }
        drawnArcs += 1;
        slot.kind = KIND_ARC;
        slot.family = familyKey(packet.portnum);
        slot.born = at;
        slot.life = reduced ? LIVE_LIFE_MS : ARC_LIFE_MS;
        slot.lat0 = packet.from.lat;
        slot.lng0 = packet.from.lon;
        slot.lat1 = arc.gateway.lat;
        slot.lng1 = arc.gateway.lon;
        /*
         * Rule A. Flat only for a direct observation, so a straight line
         * on this map is always the claim "these two radios heard each
         * other" and never anything else. A relayed line bows by its hop
         * count, and an unknown hop count is stippled rather than given
         * a weak colour: unknown is not a value.
         */
        slot.flat = arc.direct === true;
        slot.bow = arc.direct === true ? 0 : bow;
        slot.stipple = arc.hops == null && arc.direct !== true;
        // Colour only a flat line by signal. On a relayed observation the
        // reading belongs to a different pair of radios (AGENTS.md 9.5),
        // so the line carries the packet family's colour instead.
        slot.colour = arc.direct === true ? snrColour(arc.snr) : colourOf(packet.portnum);
        slot.shape = family.shape;
        slot.size = family.size;
        slot.arriving = false;
        admitted = true;
      }
      return admitted;
    }

    function admitHop(hop) {
      const slot = take();
      if (!slot) return false;
      slot.kind = KIND_HOP;
      slot.family = '';
      slot.born = performance.now();
      slot.life = reduced ? STATIC_LIFE_MS : TRACE_LIFE_MS;
      slot.lat0 = hop.from.lat;
      slot.lng0 = hop.from.lon;
      slot.lat1 = hop.to.lat;
      slot.lng1 = hop.to.lon;
      // A traceroute hop is the one line on this map that is a measured
      // path, so it is flat. About two thirds of reports carry no
      // reading for a hop, and INT8_MIN means "not measured" rather than
      // a weak signal (AGENTS.md 9.6), so an unread hop is stippled in
      // the dimmest colour instead of being coloured as if it were bad.
      slot.flat = true;
      slot.bow = 0;
      slot.stipple = hop.snr == null;
      slot.colour = hop.snr == null ? palette.stale : snrColour(hop.snr);
      slot.shape = 'diamond';
      slot.size = 6;
      return true;
    }

    /* --- Drawing ------------------------------------------------- */

    const point = (lat, lng) => map.latLngToContainerPoint([lat, lng]);

    /* Ease out for the first third of the flight, then linear, so a mark
     * leaves its sender sharply and arrives without a decelerating slide
     * that would read as distance. */
    function ease(progress) {
      if (progress >= 0.3) return progress;
      const local = progress / 0.3;
      return 0.3 * (1 - (1 - local) ** 3);
    }

    /** Draw one family shape, centred, at one alpha. */
    function shape(name, x, y, size, colour, alpha, angle) {
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = colour;
      ctx.fillStyle = colour;
      const half = size / 2;
      if (name === 'disc') {
        ctx.beginPath();
        ctx.arc(x, y, half, 0, Math.PI * 2);
        ctx.fill();
      } else if (name === 'ring') {
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(x, y, half, 0, Math.PI * 2);
        ctx.stroke();
      } else if (name === 'square') {
        ctx.fillRect(x - half, y - half, size, size);
      } else if (name === 'capsule') {
        // The brightest and the largest mark on the canvas, because a
        // text message is the rarest packet and the only one a person
        // wrote. Top salience costs nothing when the thing is rare.
        const long = size / 2;
        const thick = 2;
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(angle || 0);
        ctx.beginPath();
        ctx.moveTo(-long + thick, -thick);
        ctx.lineTo(long - thick, -thick);
        ctx.arc(long - thick, 0, thick, -Math.PI / 2, Math.PI / 2);
        ctx.lineTo(-long + thick, thick);
        ctx.arc(-long + thick, 0, thick, Math.PI / 2, -Math.PI / 2);
        ctx.fill();
        ctx.restore();
      } else if (name === 'diamond') {
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.moveTo(x, y - half);
        ctx.lineTo(x + half, y);
        ctx.lineTo(x, y + half);
        ctx.lineTo(x - half, y);
        ctx.closePath();
        ctx.stroke();
      } else if (name === 'cross') {
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x - half, y);
        ctx.lineTo(x + half, y);
        ctx.moveTo(x, y - half);
        ctx.lineTo(x, y + half);
        ctx.stroke();
      } else {
        // The bucket: a short tick, the dimmest thing on the canvas.
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x - half, y);
        ctx.lineTo(x + half, y);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    /*
     * The control point of the bow, perpendicular to the chord.
     *
     * The side is chosen from the endpoints rather than at random, so a
     * pair of nodes always bows the same way and a viewer is not shown a
     * shape that changes while the relation does not.
     */
    function control(ax, ay, bx, by, amount, side) {
      const mx = (ax + bx) / 2;
      const my = (ay + by) / 2;
      if (!amount) return { x: mx, y: my };
      const dx = bx - ax;
      const dy = by - ay;
      const length = Math.hypot(dx, dy) || 1;
      const lift = length * amount * side;
      return { x: mx - (dy / length) * lift, y: my + (dx / length) * lift };
    }

    /** A point on the quadratic curve, and its tangent angle. */
    function along(ax, ay, cx, cy, bx, by, t) {
      const u = 1 - t;
      const x = u * u * ax + 2 * u * t * cx + t * t * bx;
      const y = u * u * ay + 2 * u * t * cy + t * t * by;
      const tx = 2 * (u * (cx - ax) + t * (bx - cx));
      const ty = 2 * (u * (cy - ay) + t * (by - cy));
      return { x, y, angle: Math.atan2(ty, tx) };
    }

    /*
     * A tapered trail plus one chevron, so direction has a static form
     * as well as a moving one.
     *
     * This matters beyond taste: with motion reduced the moving channel
     * disappears, so nothing may be encoded in motion alone. Taper is
     * direction without movement, and the chevron at 62% of the chord is
     * the same idea the old arrow head established.
     */
    function trail(ax, ay, cx, cy, bx, by, head, colour, alpha, stipple, flat) {
      const steps = 12;
      ctx.strokeStyle = colour;
      ctx.lineCap = 'round';
      if (stipple) ctx.setLineDash([2, 3]);
      for (let index = 0; index < steps; index += 1) {
        const t0 = (index / steps) * head;
        const t1 = ((index + 1) / steps) * head;
        if (t1 <= 0) continue;
        const p0 = along(ax, ay, cx, cy, bx, by, t0);
        const p1 = along(ax, ay, cx, cy, bx, by, t1);
        // Thin at the origin, thick at the destination.
        const grow = 0.35 + 0.65 * (t1 / Math.max(head, 0.001));
        ctx.globalAlpha = alpha * (stipple ? 0.4 : 1) * (0.35 + 0.65 * grow);
        ctx.lineWidth = (flat ? 2.4 : 1.8) * grow;
        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      if (head >= 0.62) {
        const at = along(ax, ay, cx, cy, bx, by, 0.62);
        const size = 6;
        const spread = 0.45;
        ctx.globalAlpha = alpha * (stipple ? 0.5 : 0.9);
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(at.x - size * Math.cos(at.angle + spread), at.y - size * Math.sin(at.angle + spread));
        ctx.lineTo(at.x, at.y);
        ctx.lineTo(at.x - size * Math.cos(at.angle - spread), at.y - size * Math.sin(at.angle - spread));
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    function ringPulse(x, y, from, to, colour, alpha) {
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = colour;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(x, y, from + (to - from) * (1 - alpha), 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    /* --- Heat ---------------------------------------------------- */

    /**
     * Rebuild the two heat draw lists.
     *
     * On a timer rather than per frame. The quantity moves on a twenty
     * second half-life, so a quarter of a second of staleness in the
     * ordering is below anything a viewer could see, and it turns one
     * sort of several hundred entries per frame into one per four.
     *
     * Off-screen nodes are culled before the cap, so panning to a quiet
     * corner does not spend the budget on nodes nobody is looking at.
     * Whatever the cap then refuses is counted, because a heat map that
     * quietly showed the top hundred and sixty would be the same failure
     * as a sampled animation that does not say it is sampled.
     */
    function buildHeat(at) {
      const halos = [];
      const rings = [];
      const margin = 40;
      const onScreen = (cell) => {
        const p = point(cell.lat, cell.lng);
        if (p.x < -margin || p.x > width + margin) return null;
        if (p.y < -margin || p.y > height + margin) return null;
        return p;
      };
      for (const cell of emitHeat.values()) {
        const value = heatNow(cell, at, EMIT_HALF_LIFE_MS);
        if (value < HEAT_FLOOR) continue;
        const p = onScreen(cell);
        if (p) halos.push({ x: p.x, y: p.y, value });
      }
      for (const cell of uploadHeat.values()) {
        const value = heatNow(cell, at, UPLOAD_HALF_LIFE_MS);
        if (value < HEAT_FLOOR) continue;
        const p = onScreen(cell);
        if (p) rings.push({ x: p.x, y: p.y, value });
      }
      halos.sort((a, b) => b.value - a.value);
      rings.sort((a, b) => b.value - a.value);
      const hidden = Math.max(0, halos.length - MAX_HEAT_NODES)
        + Math.max(0, rings.length - MAX_HEAT_NODES);
      heatList = {
        at,
        halos: halos.slice(0, MAX_HEAT_NODES),
        rings: rings.slice(0, MAX_HEAT_NODES),
        hidden,
      };
    }

    /**
     * How much this node said: an annulus around the dot, radius by heat.
     *
     * Three steps of fill rather than a radial gradient, because a
     * gradient is an allocation and this runs for a few hundred nodes
     * sixty times a second — the object churn that phase 1 removed from
     * the arcs would come straight back in the heat. Three fills read as
     * a soft glow and cost nothing.
     *
     * The outer edge is stroked so the extent of the halo is readable
     * when the fill is faint, and the quantity is the radius, which is a
     * size rather than a hue. Render the canvas in greyscale and the
     * halo still says which node is talking most, which is the whole
     * accessibility requirement met by construction.
     */
    /*
     * How much of the heat is left to show above the floor. A node is
     * dropped when its heat falls under `HEAT_FLOOR`, and drawing it at
     * full strength until then made the halo and the ring vanish in one
     * step. This fades them out over the last stretch instead, so the
     * mark is already gone when the node is dropped.
     */
    function aboveFloor(value) {
      return Math.max(0, Math.min(1, (value - HEAT_FLOOR) / HEAT_FLOOR));
    }

    function halo(x, y, value) {
      const full = heatScale(value, HEAT_FULL);
      const fading = aboveFloor(value);
      const outer = HALO_MIN_PX + (HALO_MAX_PX - HALO_MIN_PX) * full;
      /*
       * Each step is an annulus from its own radius down to the hole, so
       * they stack: five layers over the innermost band and one at the
       * rim. That is a falloff, bright near the node and fading outward,
       * built out of plain fills. It has to look like a glow and not
       * like a ring, because a gateway wears a ring already and the two
       * say different things.
       */
      const alpha = (0.06 + 0.06 * full) * fading;
      ctx.fillStyle = palette.emit;
      ctx.strokeStyle = palette.emit;
      for (let step = 0; step < HALO_STEPS; step += 1) {
        const radius = HALO_HOLE_PX + (outer - HALO_HOLE_PX) * (1 - step / HALO_STEPS);
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        // The hole clears the node dot, its stroke and the widest the
        // upload ring can ever be, so neither the node's identity nor
        // its other quantity is ever painted over. That is the guarantee
        // the design asked a z-order for.
        ctx.arc(x, y, HALO_HOLE_PX, 0, Math.PI * 2, true);
        ctx.fill();
      }
      /*
       * One faint line at the true extent. A falloff fades out before it
       * ends, so without this the size a viewer reads is the size of the
       * visible part rather than of the quantity — and in greyscale, or
       * on a bright basemap, those two are different amounts.
       */
      ctx.globalAlpha = Math.min(1, alpha * 3.4);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(x, y, outer, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    /**
     * How much this node uploaded: the gateway ring, thicker.
     *
     * Concentric with the bright ring a gateway already wears, growing
     * outward, so it reads as that ring thickening rather than as a
     * second mark competing with it. It is never added to the halo and
     * never shares its scale: a gateway uploading other people's traffic
     * is not a node with a lot to say, and one glow holding both would
     * be AGENTS.md 9.5.1 returning as an aggregate.
     *
     * Hollow against the halo's fill, so the two are told apart by shape
     * before colour is consulted at all.
     */
    function uploadRing(x, y, value) {
      const full = heatScale(value, UPLOAD_FULL);
      const weight = RING_MIN_PX + RING_GAIN_PX * full;
      ctx.globalAlpha = (0.45 + 0.4 * full) * aboveFloor(value);
      ctx.strokeStyle = palette.upload;
      ctx.lineWidth = weight;
      ctx.beginPath();
      ctx.arc(x, y, RING_RADIUS_PX + weight / 2, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    function drawArc(slot, age) {
      const a = point(slot.lat0, slot.lng0);
      const b = point(slot.lat1, slot.lng1);
      const chord = Math.hypot(b.x - a.x, b.y - a.y);
      // Both endpoints off screen by a margin: nothing to draw.
      const margin = 80;
      if (Math.max(a.x, b.x) < -margin || Math.min(a.x, b.x) > width + margin) return;
      if (Math.max(a.y, b.y) < -margin || Math.min(a.y, b.y) > height + margin) return;
      // The side is stable for a pair of nodes, so the shape of a
      // relation does not change while the relation does not.
      const side = (a.x + a.y) <= (b.x + b.y) ? 1 : -1;
      const c = control(a.x, a.y, b.x, b.y, slot.bow, side);

      if (reduced) {
        // Painted whole, held, then faded. No particle and no pulse, and
        // everything the mark says is still said: the bow is the hop
        // count, the stipple is the unknown, the taper and the chevron
        // are the direction.
        const alpha = 0.85 * holdThenFade(age);
        if (alpha <= 0.02) return;
        trail(a.x, a.y, c.x, c.y, b.x, b.y, 1, slot.colour, alpha, slot.stipple, slot.flat);
        return;
      }

      const flying = age < FLIGHT_PASSES_MS;
      // The first pass draws the line as the particle goes; the second
      // runs the particle over the whole line again.
      const firstPass = age < FLIGHT_MS;
      const passAge = firstPass ? age : age - FLIGHT_MS;
      const head = flying ? ease(Math.min(passAge, FLIGHT_MS) / FLIGHT_MS) : 1;
      const alpha = 0.85 * (flying ? 1 : holdThenFade(age - FLIGHT_PASSES_MS));
      if (alpha <= 0.02) return;

      if (chord >= MIN_CHORD_PX) {
        trail(a.x, a.y, c.x, c.y, b.x, b.y, firstPass ? head : 1, slot.colour, alpha, slot.stipple, slot.flat);
        if (flying) {
          const at = along(a.x, a.y, c.x, c.y, b.x, b.y, head);
          shape(slot.shape, at.x, at.y, slot.size, slot.colour, 0.95, at.angle);
        }
      }
      // The arrival pulse, on the gateway, each time the particle lands.
      const landed = firstPass ? -1 : age < FLIGHT_PASSES_MS ? age - FLIGHT_MS : age - FLIGHT_PASSES_MS;
      if (landed >= 0 && landed <= ARRIVE_PULSE_MS) {
        ringPulse(b.x, b.y, 3, 10, slot.colour, 0.8 * (1 - landed / ARRIVE_PULSE_MS));
      }
    }

    /** Full strength for the hold, then a straight fade to nothing. */
    function holdThenFade(age) {
      if (age <= HOLD_MS) return 1;
      return Math.max(0, 1 - (age - HOLD_MS) / FADE_MS);
    }

    function drawPulse(slot, age) {
      const a = point(slot.lat0, slot.lng0);
      if (a.x < -40 || a.x > width + 40 || a.y < -40 || a.y > height + 40) return;
      // The sender pulses as each pass leaves it.
      const sent = age < FLIGHT_MS ? age : age - FLIGHT_MS;
      if (!reduced && age < FLIGHT_PASSES_MS && sent <= EMIT_PULSE_MS) {
        ringPulse(a.x, a.y, 4, 14, slot.colour, 0.9 * (1 - sent / EMIT_PULSE_MS));
      }
      /*
       * `+N`: the gateways that uploaded this packet and did not get an
       * arc. The word for them is "uploaded", never "heard by": only a
       * gateway reports, every other node hears plenty and reports none
       * of it, so a count of them is a plumbing answer and not a
       * coverage one. See AGENTS.md 9.5.1.
       */
      if (slot.numeral > 0) {
        const fade = 1 - age / slot.life;
        ctx.globalAlpha = Math.max(0, Math.min(1, fade * 1.6));
        ctx.fillStyle = slot.colour;
        ctx.font = '600 11px system-ui, -apple-system, "Segoe UI", sans-serif';
        ctx.textBaseline = 'middle';
        // fillText on a number we computed, never an assembled string
        // from a node's own display name. See AGENTS.md 4.6 in the
        // design and the `createTextNode` comment in app.js.
        ctx.fillText(`+${slot.numeral}`, a.x + 9, a.y - 9);
        ctx.globalAlpha = 1;
      }
    }

    function drawHop(slot, age) {
      const a = point(slot.lat0, slot.lng0);
      const b = point(slot.lat1, slot.lng1);
      // Held, then faded, with motion reduced as well: it used to stay
      // at full strength and then vanish in one step.
      const alpha = age <= TRACE_HOLD_MS
        ? 0.95
        : 0.95 * (1 - (age - TRACE_HOLD_MS) / TRACE_FADE_MS);
      if (alpha <= 0.02) return;
      ctx.strokeStyle = slot.colour;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = 3;
      if (slot.stipple) ctx.setLineDash([3, 4]);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    /* --- The loop ------------------------------------------------ */

    /**
     * Paint one frame at one instant.
     *
     * Taken out of `tick` so a paused map can be redrawn after a pan
     * without the clock moving: the argument is the instant to draw, not
     * "now". Nothing in here advances any state except the retirement of
     * a mark that has outlived its own life.
     */
    function drawFrame(started) {
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.clearRect(0, 0, width, height);
      if (hiddenForZoom) return;

      /*
       * With motion reduced the heat is snapped to a one-second grid, so
       * it steps rather than glides. The layer does not vanish: it is a
       * quantity, not an animation, and something that carries meaning
       * may never be available only to a viewer who can take movement.
       */
      const heatAt = reduced
        ? Math.floor(started / HEAT_STEP_MS) * HEAT_STEP_MS
        : started;
      const stale = reduced
        ? heatList.at !== heatAt
        : started - heatList.at > HEAT_SORT_MS || heatList.at > started;
      if (stale) buildHeat(heatAt);

      /*
       * The heat goes down first so the live marks are over it, and the
       * upload rings go down after the halos, because they are two
       * different statements about a node and the ring is the one that
       * has to stay legible under traffic.
       */
      for (const item of heatList.halos) halo(item.x, item.y, item.value);
      for (const item of heatList.rings) uploadRing(item.x, item.y, item.value);

      for (const slot of pool) {
        if (!slot.live) continue;
        const age = started - slot.born;
        if (age >= slot.life) {
          release(slot);
          continue;
        }
        if (slot.kind === KIND_ARC) drawArc(slot, age);
        else if (slot.kind === KIND_PULSE) drawPulse(slot, age);
        else if (slot.kind === KIND_HOP) drawHop(slot, age);
      }
    }

    /**
     * The measured rate, and the measured frame time, decide the rung.
     *
     * Both, not either: a slow machine at a low rate needs the same
     * relief as a fast one in a storm, and a fast machine at a high rate
     * still must not draw fifty arcs out of one node. The rate band is
     * the floor, the frame-time governor may ask for one rung finer, and
     * the rung in force is the higher of the two.
     *
     * Hysteresis in both directions, and on different lengths: three
     * seconds over budget to step down and ten seconds under it to step
     * back up. A map sitting on the threshold therefore settles rather
     * than flapping, and the asymmetry is deliberate — going down is a
     * response to a problem and going up is a claim that the problem is
     * gone, and the second deserves more evidence than the first.
     */
    function governor(at) {
      if (!secondStart) secondStart = at;
      if (at - secondStart < 1000) return;
      secondStart = at;

      const sorted = frameLog.map((entry) => entry.ms).sort((x, y) => x - y);
      stats.p50 = sorted.length ? sorted[Math.floor(sorted.length * 0.5)] : 0;
      stats.p95 = sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] : 0;

      if (!sorted.length) return;
      if (stats.p95 > FRAME_BUDGET_MS) {
        overSeconds += 1;
        underSeconds = 0;
      } else if (stats.p95 < FRAME_RECOVER_MS) {
        underSeconds += 1;
        overSeconds = 0;
      } else {
        overSeconds = 0;
        underSeconds = 0;
      }
      if (overSeconds >= OVER_BUDGET_SECONDS && governorRung < RUNG_HEAT_ONLY) {
        governorRung += 1;
        overSeconds = 0;
      } else if (underSeconds >= UNDER_BUDGET_SECONDS && governorRung > RUNG_FULL) {
        governorRung -= 1;
        underSeconds = 0;
      }
    }

    function tick(at) {
      const started = performance.now();
      /*
       * A long sleep resumes with an enormous delta. Clamped, or every
       * mark jumps to its end state and the heat decays to nothing in
       * one step — which would look exactly like a mesh that went quiet
       * while the viewer was away, and it did not.
       */
      const dt = Math.min(at - lastFrameAt, MAX_DT_MS);
      lastFrameAt = at;
      void dt;

      // Release whatever is due, newest-order preserved, capped so a
      // burst cannot be spent in one frame.
      const now = Date.now();
      let released = 0;
      const releasedPackets = [];
      while (queue.length && queue[0].at <= now && released < MAX_RELEASE_PER_FRAME) {
        const item = queue.shift();
        released += 1;
        if (item.hop) {
          if (!admitHop(item.hop)) stats.droppedBatch += 1;
          continue;
        }
        // A packet of a hidden kind was queued before the filter
        // changed. It is not a drop: the viewer asked not to see it.
        if (!shows(item.packet)) continue;
        rateWindow.push(started);
        // Told whether or not it found room. A packet the pool refused is
        // counted as dropped from the picture, and the feed is where its
        // numbers can still be read.
        releasedPackets.push(item.packet);
        const ok = admitPacket(item.packet);
        if (ok) {
          stats.drawn += 1;
          stats.lagMs = Math.max(0, now - item.packet.timeMs);
        } else {
          stats.droppedBatch += 1;
          stats.droppedNoRoom += 1;
          stats.droppedThisMinute += 1;
        }
      }

      if (onRelease && releasedPackets.length) onRelease(releasedPackets);

      /*
       * The rate the ladder reads is measured over the last few seconds
       * of releases, not guessed from the size of a batch. A batch is
       * whatever the poll happened to return; the rate is what the map
       * is actually being asked to draw.
       */
      const rateFloor = started - RATE_WINDOW_MS;
      while (rateWindow.length && rateWindow[0] < rateFloor) rateWindow.shift();
      stats.perSecond = rateWindow.length / (RATE_WINDOW_MS / 1000);
      governor(started);
      // Three inputs, whichever is worst: the release rate, the frame
      // governor, and how full the pool is (#222).
      rung = Math.max(rungForRate(stats.perSecond), governorRung, rungForMarks(liveCount));

      drawFrame(started);

      /*
       * Tell the page what the numbers are, from inside the loop.
       *
       * The replay backlog and the lag are live quantities: they change
       * every frame and a status line written once per fetch would show a
       * number that was true fifteen seconds ago. Reporting a stale lag is
       * the one lie this feature is most able to tell, so it is driven
       * from here rather than from the poll, and it costs no timer because
       * the loop stops when there is nothing to say.
       */
      if (onStats && now - lastStatsAt > 250) {
        lastStatsAt = now;
        onStats(publicCounts());
      }

      stats.frames += 1;
      const spent = performance.now() - started;
      /*
       * The percentile is over the last second and a bit, because the
       * governor asks a question about the last three seconds and a
       * percentile over a whole minute cannot answer it. The list is
       * pruned by time rather than by length so it is the same window
       * whatever the frame rate is.
       */
      frameLog.push({ at: started, ms: spent });
      while (frameLog.length && frameLog[0].at < started - 1200) frameLog.shift();
      stats.drawMs.push(spent);
      if (stats.drawMs.length > 240) stats.drawMs.shift();
      if (now - stats.minuteStart > 60000) {
        stats.minuteStart = now;
        stats.droppedThisMinute = 0;
      }

      /*
       * Stop dead when there is nothing to draw. An idle loop still
       * wakes the compositor, and the target is no CPU at all when the
       * mesh is quiet, because a laptop is left open for hours.
       *
       * Heat keeps the loop alive while it is still visible, which is
       * about a minute and a half after the last packet. Both stores are
       * pruned here rather than only being read, so a node that has gone
       * quiet leaves the map rather than sitting in it below the
       * threshold for as long as the tab is open.
       */
      heatPrune(emitHeat, started, EMIT_HALF_LIFE_MS);
      heatPrune(uploadHeat, started, UPLOAD_HALF_LIFE_MS);
      if (!liveCount && !queue.length && !emitHeat.size && !uploadHeat.size) {
        stop();
        return;
      }
      frame = requestAnimationFrame(tick);
    }

    /* --- The interface app.js uses ------------------------------- */

    return {
      /** Aggregate, then schedule. Returns what it offered and took. */
      push(packets, intervalMs) {
        stats.offered += packets.length;
        enqueue(packets, intervalMs);
      },
      /** Queue one traceroute path, hop by hop, capped at 12 alive. */
      pushTrace(hops, index) {
        if (tracePaths >= MAX_TRACE_PATHS) tracePaths = 0;
        tracePaths += 1;
        enqueueTrace(hops, index * 320);
      },
      /** Reset the honesty counters at the start of a fetch cycle. */
      beginBatch() {
        stats.offered = 0;
        stats.drawn = 0;
        stats.droppedBatch = 0;
        stats.arcsDropped = 0;
      },
      counts: publicCounts,
      /**
       * The keys of the packets still waiting for their release time.
       *
       * The feed leaves these out, so it never lists a packet before
       * its line is on the map (#386). The queue is the one record of
       * what is still to come. A packet that leaves it any other way --
       * the cap, the filter, `skipToLive` -- is then listed at once,
       * because nothing is waiting for it any more.
       */
      pendingKeys() {
        const keys = new Set();
        for (const item of queue) if (item.packet) keys.add(item.packet.key);
        return keys;
      },
      setFamilyFilter,
      setReduced(value) {
        if (reduced === value) return;
        reduced = value;
        /*
         * Keep the lines already on screen (#222).
         *
         * This used to drop every live mark, so the toggle blanked the
         * map -- which is most of why switching "felt broken". A mark is
         * evidence that a packet crossed the mesh; that does not stop
         * being true because the reader changed how it is drawn.
         *
         * What does change is how long it should last, so each mark's
         * remaining life is rescaled into the new timing rather than
         * left as it was. Without this, a mark born with motion on
         * would linger for a flight's worth after the flight stopped
         * being drawn -- which was the original reason for dropping
         * them, and is a reason to convert rather than to discard.
         */
        const nowAt = performance.now();
        const target = reduced ? LIVE_LIFE_MS : ARC_LIFE_MS;
        for (const slot of pool) {
          // Traceroute hops keep their own timing, which #222 does not
          // change. `KIND_HOP`, not an invented name: an undefined
          // constant here would read as `undefined` and silently
          // rescale the hops too.
          if (!slot.live || slot.kind === KIND_HOP) continue;
          const age = nowAt - slot.born;
          const left = Math.max(0, slot.life - age);
          const fraction = slot.life > 0 ? left / slot.life : 0;
          // Born now, with the share of its life it had left.
          slot.born = nowAt;
          slot.life = Math.max(1, target * fraction);
        }
        /*
         * The heat survives the switch. It is a quantity rather than an
         * animation, so it means the same thing in both states and
         * throwing it away would make the toggle look like it had
         * silenced part of the mesh. Only its clock changes: stepped
         * once a second with motion reduced, continuous without.
         */
        heatList = { at: 0, halos: [], rings: [], hidden: 0 };
        if (paused) repaint();
        else if (emitHeat.size || uploadHeat.size) start();
      },
      isReduced: () => reduced,
      /**
       * Hold the world still, or let it go again.
       *
       * Returns the state it settled in, so the caller can say which it
       * is rather than assume.
       */
      setPaused,
      togglePaused: () => setPaused(!paused),
      isPaused: () => paused,
      /**
       * Give up the backlog and rejoin live.
       *
       * The other half of the choice the design asks to be shown on
       * resume. Returns how many packets were given up, because a
       * buffer thrown away without a number is a gap in the record that
       * the viewer has no way to notice.
       */
      skipToLive() {
        const held = queue.length;
        queue = [];
        stats.lagMs = null;
        return held;
      },
      /** Leaving the map page cancels the loop and empties the pool. */
      setPageActive(value) {
        pageActive = value;
        if (!value) {
          // Leaving the page is not a pause. The next visit starts live.
          paused = false;
          clear();
        }
      },
      /** Throw away a buffer that is no longer about now. */
      discardQueue() {
        const held = queue.length;
        queue = [];
        stats.lagMs = null;
        return held;
      },
      clear,
      resize,
      stats,
      constants: {
        FLIGHT_MS, TRAIL_MS, ARC_LIFE_MS, POOL_SIZE, MAX_LIVE,
        MAX_ARCS_PER_PACKET, MAX_TRACE_PATHS, MIN_CHORD_PX, MAX_DT_MS,
        EMIT_HALF_LIFE_MS, UPLOAD_HALF_LIFE_MS, HEAT_FULL, UPLOAD_FULL,
        MAX_HEAT_NODES, FRAME_BUDGET_MS, RATE_WINDOW_MS, RUNG_LABELS,
      },
    };
  }

  return {
    create, aggregate, familyOf, familyKey, FAMILIES, FAMILY_ORDER, bowFor, BOW, BOW_UNKNOWN,
    /* The ladder and the heat, exposed so the legend can name them in
     * the same words the engine uses and a console can check them. */
    heatNow, rungForRate, RUNG_LABELS, EMIT_HALF_LIFE_MS, UPLOAD_HALF_LIFE_MS,
  };
})();

window.SonoranLive = SonoranLive;
