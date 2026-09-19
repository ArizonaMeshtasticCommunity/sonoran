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
  const TRAIL_MS = 1400;
  const TRAIL_TAU_MS = 420;
  const EMIT_PULSE_MS = 320;
  const ARRIVE_PULSE_MS = 260;
  /* A mark holds the sender's `+N` numeral for as long as its trail. */
  const ARC_LIFE_MS = FLIGHT_MS + TRAIL_MS;
  const TRACE_HOLD_MS = 2600;
  const TRACE_FADE_MS = 1200;
  const TRACE_LIFE_MS = TRACE_HOLD_MS + TRACE_FADE_MS;
  const TRACE_STEP_MS = 180;
  /* With motion reduced a mark is painted whole, held, and then gone. */
  const STATIC_LIFE_MS = 900;

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
    OTHER: { shape: 'tick', size: 3, token: 'pkt-other', fallback: '#7d6857', label: 'Other kinds' },
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
    if (!portnum) return FAMILIES.OTHER;
    return FAMILIES[portnum] || FAMILIES.OTHER;
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

    /* Marks waiting for their release time. See `enqueue`. */
    let queue = [];
    /* When a node last flashed, so a fast talker does not strobe. */
    const lastEmit = new Map();

    const stats = {
      /* Packets the batch offered, and packets actually drawn. The
       * status line prints both, because the eye cannot count marks. */
      offered: 0,
      drawn: 0,
      droppedBatch: 0,
      droppedNoRoom: 0,
      droppedThisMinute: 0,
      minuteStart: Date.now(),
      frames: 0,
      drawMs: [],
      p50: 0,
      p95: 0,
      lagMs: null,
      marksAlive: () => liveCount,
      queued: () => queue.length,
    };

    const onStats = options.onStats || null;
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
    });

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
      if (running || !pageActive) return;
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

    /** Drop every mark and every pending release. */
    function clear() {
      for (const slot of pool) slot.live = false;
      liveCount = 0;
      queue = [];
      lastEmit.clear();
      stats.lagMs = null;
      stop();
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
      start();
    }

    let tracePaths = 0;

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
        queued: queue.length,
        lagMs: inFlight ? stats.lagMs : null,
      };
    }

    function admitPacket(packet) {
      /*
       * The emission pulse fires for every packet, including a packet
       * whose only upload was the sender's own: a self-upload has no
       * second place for a mark to go, so the pulse is the whole of it.
       */
      const previous = lastEmit.get(packet.from.node_id) || 0;
      const now = Date.now();
      let admitted = false;
      if (packet.from.lat != null && packet.from.lon != null && now - previous >= EMIT_GAP_MS) {
        const slot = take();
        if (slot) {
          lastEmit.set(packet.from.node_id, now);
          slot.kind = KIND_PULSE;
          slot.born = performance.now();
          slot.life = reduced ? STATIC_LIFE_MS : ARC_LIFE_MS;
          slot.lat0 = packet.from.lat;
          slot.lng0 = packet.from.lon;
          slot.colour = colourOf(packet.portnum);
          slot.numeral = packet.extra > 0 ? packet.extra : 0;
          admitted = true;
        }
      }

      const bow = bowFor(packet);
      const family = familyOf(packet.portnum);
      for (const arc of packet.arcs) {
        const slot = take();
        if (!slot) break;
        slot.kind = KIND_ARC;
        slot.born = performance.now();
        slot.life = reduced ? STATIC_LIFE_MS : ARC_LIFE_MS;
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
        // Painted whole, held, then gone in one step. No particle and no
        // pulse, and everything the mark says is still said: the bow is
        // the hop count, the stipple is the unknown, the taper and the
        // chevron are the direction.
        const alpha = 0.85;
        trail(a.x, a.y, c.x, c.y, b.x, b.y, 1, slot.colour, alpha, slot.stipple, slot.flat);
        return;
      }

      const flightAge = Math.min(age, FLIGHT_MS);
      const head = ease(flightAge / FLIGHT_MS);
      const decay = age <= FLIGHT_MS ? 1 : Math.exp(-(age - FLIGHT_MS) / TRAIL_TAU_MS);
      if (decay < 0.04) return;

      if (chord >= MIN_CHORD_PX) {
        trail(a.x, a.y, c.x, c.y, b.x, b.y, head, slot.colour, 0.85 * decay, slot.stipple, slot.flat);
        if (age <= FLIGHT_MS) {
          const at = along(a.x, a.y, c.x, c.y, b.x, b.y, head);
          shape(slot.shape, at.x, at.y, slot.size, slot.colour, 0.95, at.angle);
        }
      }
      // The arrival pulse, on the gateway, when the particle lands.
      if (age > FLIGHT_MS && age <= FLIGHT_MS + ARRIVE_PULSE_MS) {
        const local = 1 - (age - FLIGHT_MS) / ARRIVE_PULSE_MS;
        ringPulse(b.x, b.y, 3, 10, slot.colour, 0.8 * local);
      }
    }

    function drawPulse(slot, age) {
      const a = point(slot.lat0, slot.lng0);
      if (a.x < -40 || a.x > width + 40 || a.y < -40 || a.y > height + 40) return;
      if (!reduced && age <= EMIT_PULSE_MS) {
        ringPulse(a.x, a.y, 4, 14, slot.colour, 0.9 * (1 - age / EMIT_PULSE_MS));
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
      const alpha = reduced || age <= TRACE_HOLD_MS
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

    function tick(at) {
      const started = performance.now();
      const dt = Math.min(at - lastFrameAt, MAX_DT_MS);
      lastFrameAt = at;
      void dt;

      // Release whatever is due, newest-order preserved, capped so a
      // burst cannot be spent in one frame.
      const now = Date.now();
      let released = 0;
      while (queue.length && queue[0].at <= now && released < MAX_RELEASE_PER_FRAME) {
        const item = queue.shift();
        released += 1;
        if (item.hop) {
          admitHop(item.hop);
          continue;
        }
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

      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.clearRect(0, 0, width, height);

      if (!hiddenForZoom) {
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
      stats.drawMs.push(spent);
      if (stats.drawMs.length > 120) stats.drawMs.shift();
      if (now - stats.minuteStart > 60000) {
        stats.minuteStart = now;
        stats.droppedThisMinute = 0;
        const sorted = [...stats.drawMs].sort((x, y) => x - y);
        stats.p50 = sorted[Math.floor(sorted.length * 0.5)] || 0;
        stats.p95 = sorted[Math.floor(sorted.length * 0.95)] || 0;
      }

      /*
       * Stop dead when there is nothing to draw. An idle loop still
       * wakes the compositor, and the target is no CPU at all when the
       * mesh is quiet, because a laptop is left open for hours.
       */
      if (!liveCount && !queue.length) {
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
      },
      counts: publicCounts,
      setReduced(value) {
        if (reduced === value) return;
        reduced = value;
        // Held marks were sized for the other timing, so drop them
        // rather than let a static mark linger for a flight's worth.
        for (const slot of pool) slot.live = false;
        liveCount = 0;
      },
      isReduced: () => reduced,
      /** Leaving the map page cancels the loop and empties the pool. */
      setPageActive(value) {
        pageActive = value;
        if (!value) clear();
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
      },
    };
  }

  return { create, aggregate, familyOf, FAMILIES, FAMILY_ORDER, bowFor, BOW, BOW_UNKNOWN };
})();

window.SonoranLive = SonoranLive;
