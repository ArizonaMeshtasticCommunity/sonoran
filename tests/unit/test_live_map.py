"""The live map animation and watch mode.

There is no JavaScript test runner in this project, so these tests pin the
invariants that fail silently in a browser: a script that loads in the
wrong order, a header that denies a feature with nothing in the console, a
CSS filter that inverts a palette, and a rule that a later edit could drop
without any page looking broken at a glance.

Each one is here because it either cost debugging time already or is
recorded in AGENTS.md as the kind of thing that does.
"""

from fastapi.testclient import TestClient

from sonoran.api.app import STATIC_DIR, create_app
from sonoran.config import Settings


def _client() -> TestClient:
    app = create_app(Settings(_env_file=None))
    return TestClient(app)


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_animation_scripts_load_before_the_router() -> None:
    """map-live.js and map-watch.js must come before app.js.

    app.js runs the router as its last act, and a reload straight to #map
    calls the map page immediately. If either file has not registered its
    global by then, the map page throws on the first line that uses it and
    the page renders empty.
    """
    text = _client().get("/").text
    assert text.index("static/map-live.js") < text.index("static/app.js")
    assert text.index("static/map-watch.js") < text.index("static/app.js")


def test_watch_mode_icons_are_in_the_sprite() -> None:
    """The icons are sprite symbols, like every other icon on the page.

    An inline or remote SVG would need a Content-Security-Policy exception,
    and a blocked resource shows nothing in the console. See AGENTS.md 9.9.
    """
    text = _client().get("/").text
    for symbol in ("i-fullscreen", "i-fullscreen-exit", "i-expand"):
        assert f'<symbol id="{symbol}"' in text, symbol
    assert "#i-fullscreen" in _read("map-watch.js")


def test_permissions_policy_does_not_deny_fullscreen() -> None:
    """Watch mode asks for the Fullscreen API on the map shell.

    `Permissions-Policy` denies everything it names, whatever the page
    asks for, and the browser reports nothing the user can see. Fullscreen
    is left unnamed so it keeps its default of `self`. Adding
    `fullscreen=()` to that header would break watch mode silently, which
    is the failure AGENTS.md 9.9 is about.
    """
    policy = _client().get("/").headers["Permissions-Policy"]
    assert "fullscreen" not in policy


def test_the_animation_canvas_escapes_the_basemap_filter() -> None:
    """The animation pane cancels the filter that warms the basemap.

    app.css inverts and warms the map tiles. An earlier version of that
    rule named the tile pane rather than the layer and inverted the
    coverage overlay's signal ramp with it, so the map drew its own legend
    backwards. A canvas of packet colours under that filter comes out
    inverted, and the bug looks like a palette mistake rather than a CSS
    inheritance one.
    """
    css = _read("app.css")
    assert ".leaflet-sonoranLive-pane { filter: none;" in css
    # The pane is created outside the transformed map pane, so the canvas
    # stays pinned to the container and marks are reprojected per frame.
    assert "map.createPane('sonoranLive', map.getContainer())" in _read("map-live.js")


def test_packet_identity_carries_the_sender() -> None:
    """Aggregation keys on (from_node_num, packet_id). See AGENTS.md 9.1.

    A packet ID is unique per sender only. Keying on the ID alone collapses
    two senders that picked the same 32-bit value inside one window into
    one animation, and one of the two packets never draws. Rare, silent,
    and against an explicit rule.
    """
    script = _read("map-live.js")
    assert "const key = `${event.from.node_id}/${event.packet_id}`;" in script


def test_gateway_count_is_distinct_gateways_not_rows() -> None:
    """A count of uploads is not a count of gateways. See AGENTS.md 9.5.1.

    One gateway uploads the same packet more than once: a live packet had
    22 uploads from 15 gateways. The panel shows both numbers and they are
    computed from different things.
    """
    script = _read("map-live.js")
    assert "packet.gateway_count = packet.gateways.size" in script
    assert "packet.upload_count += 1" in script


def test_a_self_upload_does_not_lower_the_hop_count() -> None:
    """A sender uploading its own transmission crossed no ground.

    That row carries `hop_start == hop_limit`, so it reads as zero hops.
    Folded into the minimum it made a relayed packet print "0 hops",
    which says two nodes were in range when nothing showed it. AGENTS.md
    9.5.1 records a live packet whose three apparently-direct rows were
    all the sender.
    """
    assert "event.hops_taken != null && event.from.node_id !== event.gateway.node_id" in _read(
        "map-live.js"
    )


def test_the_word_is_uploaded_never_heard_by() -> None:
    """ "Heard by" promises a coverage answer and gives a plumbing one.

    `packet_seen` records MQTT uploads, so the only observer this database
    can hold is a gateway. Every other node hears plenty and reports none
    of it, so the phrase is banned from anything a viewer reads. See
    AGENTS.md 9.5.1. The comments that explain the ban are allowed to say
    it, which is why this looks at the served page and the legend prose
    rather than at the whole source.
    """
    assert "heard by" not in _client().get("/").text.lower()
    # The legend says it in as many words, under the traffic count.
    assert "Uploads, not listeners." in _read("app.js")
    # And the map's own summary counts uploads and packets, never
    # listeners. It used to print the endpoint's word, "observations",
    # which is the same rows said in a way a reader cannot check. The
    # summary tile and the firehose column say "uploads", so this does
    # too, and the assertion follows the word rather than pinning the
    # old one.
    assert "uploads in ${traffic.window_minutes} min" in _read("app.js")


def test_only_a_direct_observation_is_drawn_flat() -> None:
    """Flatness is the map's claim that two radios heard each other.

    An ordinary packet does not carry its route (AGENTS.md 9.20), so a
    straight line between a sender and a gateway crosses ground the signal
    never took. Relayed arcs bow by their hop count, and an unknown hop
    count is stippled rather than given a weak colour.
    """
    script = _read("map-live.js")
    assert "slot.flat = arc.direct === true;" in script
    assert "slot.bow = arc.direct === true ? 0 : bow;" in script
    assert "slot.stipple = arc.hops == null && arc.direct !== true;" in script


def test_only_a_flat_line_is_coloured_by_signal() -> None:
    """On a relayed observation the SNR belongs to a different pair.

    `rx_snr` is the reading of the last hop into the gateway, not of the
    link between the two nodes the line joins. See AGENTS.md 9.5.
    """
    assert "arc.direct === true ? snrColour(arc.snr) : colourOf(packet.portnum)" in _read(
        "map-live.js"
    )


def test_the_feed_shows_no_signal_for_a_relayed_packet() -> None:
    """The panel row follows the same rule the packet page always has."""
    assert "packet.any_direct && packet.direct_snr != null ? snrCell(packet.direct_snr)" in _read(
        "app.js"
    )


def test_flight_time_is_constant() -> None:
    """Speed is not data. See AGENTS.md 9.3 and 9.4.

    Every gateway stamps its own `rx_time` and node clocks have been 28
    hours out, so latency is not measurable. A mark that took longer for a
    longer distance would be read as a measurement, so every mark takes the
    same time whatever the distance or the hop count.
    """
    script = _read("map-live.js")
    assert "const FLIGHT_MS = 850;" in script
    # Nothing may scale the flight by distance or by hops.
    assert "FLIGHT_MS *" not in script
    assert "FLIGHT_MS /" not in script


def test_the_per_mark_timer_chains_are_gone() -> None:
    """One loop, not thirteen timers per line.

    The old renderer faded each line with a chain of twelve setTimeout
    calls through `mapLater`, about 680 timers a second at load and up to
    five thousand pending. All of it is one requestAnimationFrame loop now.
    """
    script = _read("app.js")
    assert "mapLater" not in script
    assert "mapTimers" not in script
    assert "requestAnimationFrame" in _read("map-live.js")


def test_the_mark_pool_is_preallocated() -> None:
    """Zero allocation in the hot loop, so a long watch has no GC sawtooth.

    The owner watches this for hours. The old renderer made roughly 190,000
    Leaflet objects an hour at fifty observations a second.
    """
    script = _read("map-live.js")
    assert "const POOL_SIZE = 256;" in script
    assert "const MAX_LIVE = 220;" in script
    assert "const MAX_ARCS_PER_PACKET = 3;" in script


def test_the_page_says_when_it_is_not_drawing_everything() -> None:
    """Never sample silently. The eye cannot count marks.

    The counter is only ever written when something really was refused: a
    packet still in the replay buffer has not been dropped, and reporting
    it as a shortfall would be the same fault pointing the other way.
    """
    script = _read("app.js")
    assert "drawing ${count(counts.offered - counts.dropped)} of" in script
    assert "counts.dropped" in script


def test_the_replay_lag_is_stated() -> None:
    """A replay presented as instantaneous is the one lie this could tell.

    Each batch is spread across the poll interval instead of being fired in
    one frame, so the display runs about one interval behind live.
    """
    assert "replaying, about ${Math.max(1, Math.round(counts.lagMs / 1000))} s behind" in _read(
        "app.js"
    )


def test_the_replay_orders_on_our_own_clock() -> None:
    """`seen_at` is the only time a client may order on.

    A gateway's `rx_time` and a node's own clock may not: node clocks have
    been seen nearly 28 hours ahead. See AGENTS.md 9.3 and 9.4.
    """
    script = _read("map-live.js")
    assert "packets.sort((a, b) => a.timeMs - b.timeMs);" in script
    assert "Date.parse(event.time)" in script


def test_the_packet_palette_is_its_own_group() -> None:
    """A role is what a node is; a family is what a packet was.

    Both are drawn in the same frame, so the two palettes must not share
    values. The dots are roles and the moving marks are families.
    """
    css = _read("app.css")
    families = {
        "--pkt-position": "#f4703f",
        "--pkt-nodeinfo": "#a48fd0",
        "--pkt-telemetry": "#46b3e6",
        "--pkt-text": "#f6ece2",
        "--pkt-trace": "#b6d94c",
        "--pkt-routing": "#b59c88",
        "--pkt-other": "#7d6857",
    }
    for token, value in families.items():
        assert f"{token}: {value};" in css, token


def test_every_packet_family_has_a_shape_as_well_as_a_colour() -> None:
    """Remove all colour and the alphabet must still read.

    Meaning is never in hue alone: the accessibility requirement is met by
    construction rather than by a later audit.
    """
    script = _read("map-live.js")
    shapes = {"disc", "ring", "square", "capsule", "diamond", "cross", "tick"}
    for shape in shapes:
        assert f"shape: '{shape}'" in script, shape
    # Seven families and a bucket, in a fixed legend order.
    assert script.count("token: 'pkt-") == len(shapes)


def test_reduced_motion_has_a_path_and_a_toggle() -> None:
    """The system setting is the default of a toggle, not a lock.

    A viewer whose system says reduce may still want the animation here,
    and a viewer whose system says nothing may want it off. Nothing on the
    map is encoded in motion alone, so both states say the same things.
    """
    assert "prefers-reduced-motion: reduce" in _read("app.css")
    assert "prefers-reduced-motion: reduce" in _read("app.js")
    assert "data-map-motion" in _client().get("/").text
    # The toggle must not trigger a refetch: it changes how the page is
    # drawn, not what it asked for.
    assert "data-no-refresh" in _read("index.html")


def test_the_map_overlay_class_is_defined_once() -> None:
    """It used to be defined twice, with different values, and used by
    nothing. Watch mode is what it was waiting for."""
    css = _read("app.css")
    assert css.count("\n.map-overlay {") == 1


def test_watch_mode_chrome_stays_hidden_outside_watch_mode() -> None:
    """`display: flex` beats the browser's own `[hidden]` rule.

    `[hidden] { display: none }` is a plain element rule at lower
    specificity, so without an explicit rule the whole overlay draws over
    the ordinary map page.
    """
    css = _read("app.css")
    assert ".watch-bar[hidden]" in css
    assert ".watch-panel[hidden]" in css
    assert ".watch-legend[hidden]" in css


def test_watch_mode_is_a_state_of_the_map_not_a_page() -> None:
    """The fragment is where this dashboard keeps state, on purpose.

    A `Referer` never carries a fragment, so watch mode persists across a
    reload, is shareable, and leaks nothing. See AGENTS.md 9.9.1.
    """
    script = _read("map-watch.js")
    assert "['map', 'watch', tab, height]" in script
    # And it is not a new route.
    assert '"watch"' not in _read("app.js").replace("'watch'", '"watch"').replace(
        'PAGES["watch"]', ""
    ) or "PAGES.watch" not in _read("app.js")


def test_fullscreen_falls_back_to_a_css_class() -> None:
    """iOS Safari does not grant `requestFullscreen` on an element.

    Both paths end with the same class on the same element, so there is one
    layout code path and one set of CSS rules.
    """
    script = _read("map-watch.js")
    assert "requestFullscreen" in script
    assert "document.body.classList.add('watch-mode')" in script
    assert "body.watch-mode .map-shell.watch" in _read("app.css")


def test_the_preset_and_the_scope_never_hide() -> None:
    """A viewer must never forget which mesh they are watching.

    One graph per modem preset: a node on LongFast cannot hear a node on
    MediumFast. In fullscreen there is no page head to say which preset is
    drawn, so the strip that carries it is always on screen. AGENTS.md 9.7.
    """
    text = _client().get("/").text
    assert "data-watch-preset" in text
    assert "data-watch-scope" in text
    assert "mapPresetLabel = (chosen && chosen.label) || linkChannel" in _read("app.js")


def test_the_expanded_table_adds_no_signal_to_a_relayed_row() -> None:
    """It adds hops, gateways, uploads and channel, which the response
    already carried and the renderer threw away. It does not add SNR to a
    relayed row, because that reading is of a different pair of radios."""
    script = _read("app.js")
    assert "label: 'Gateways'" in script
    assert "label: 'Uploads'" in script
    assert "label: 'Hops'" in script
    assert "row.any_direct && row.direct_snr != null" in script


def test_the_slow_endpoints_are_cached() -> None:
    """`api/graph/channels` runs three 24-hour GROUP BY aggregates and was
    paid for on every map refresh, four times a minute per open tab. The
    node list is 700-900 rows that change slowly and was refetched just as
    often."""
    script = _read("app.js")
    assert "const CHANNELS_TTL_MS = 600000;" in script
    assert "const NODES_TTL_MS = 120000;" in script


def test_the_seed_can_produce_live_traffic() -> None:
    """The seeded window is fixed at the moment the seed ran, so a few
    minutes later the map has nothing new to animate. Watching the
    animation at all needs traffic that keeps arriving."""
    from pathlib import Path

    seed = Path("tools/dev/seed.py").read_text(encoding="utf-8")
    assert "async def live() -> None:" in seed
    assert '"--live" in sys.argv' in seed
    # The fan-out and the hop mix follow the measurements, not convenience.
    assert "UNMEASURED_SNR = -128" in seed
    assert "def _burned(rng: random.Random) -> int:" in seed


# --- Phase 2: the heat, the ladder, and watching for hours -------------


def test_the_two_heat_layers_are_never_merged() -> None:
    """Emission heat and upload heat are two quantities, not one.

    A halo is how much a node said: one point for each packet it
    originated. A ring is how much it uploaded as a gateway: one point
    for each upload row, of anybody's traffic. Adding them would be
    AGENTS.md 9.5.1 returning as an aggregate — the map would be drawing
    uploads as though they were something the node did, which is the
    reading the whole redesign exists to remove.

    So there are two stores with two half-lives, and `heatAdd` takes the
    store as an argument rather than reaching for one, which makes a
    merge something somebody would have to write on purpose.
    """
    script = _read("map-live.js")
    assert "const emitHeat = new Map();" in script
    assert "const uploadHeat = new Map();" in script
    assert "const EMIT_HALF_LIFE_MS = 20000;" in script
    assert "const UPLOAD_HALF_LIFE_MS = 30000;" in script
    assert "heatAdd(emitHeat" in script
    assert "heatAdd(uploadHeat" in script
    # The legend names both, separately, in the design's own terms.
    app = _read("app.js")
    assert "how much this node said" in app
    assert "how much this node uploaded" in app
    assert "never added together" in app


def test_emission_counts_packets_and_upload_counts_uploads() -> None:
    """The two stores are fed different things, which is the whole point.

    Emission takes one point for each packet the node originated. Upload
    takes `item.uploads` — rows — for every gateway of the packet, not
    only the three that got an arc, because the uploads the arc cap
    refused are exactly what the ring exists to hold. A count of rows is
    not a count of gateways and neither is a count of listeners
    (AGENTS.md 9.5.1).
    """
    script = _read("map-live.js")
    assert "1, EMIT_HALF_LIFE_MS, at);" in script
    assert "item.uploads, UPLOAD_HALF_LIFE_MS, at);" in script
    # Every gateway, not only the drawn arcs.
    assert "for (const item of packet.gateways.values()) {" in script


def test_a_halo_can_never_paint_over_a_node_dot() -> None:
    """Volume must never obscure identity.

    The design puts the halo under the node dots in z-order. A canvas
    pinned to the map container cannot sit under them — Leaflet's map
    pane carries its own stacking context, so a sibling below it is below
    the basemap too — so the halo is an annulus with a hole instead, and
    the hole has to clear the widest dot, its stroke, and the widest the
    upload ring can ever be.

    The gateway dot is radius 7 with a 2.5 px stroke, so its outer edge
    is at 8.25.
    """
    script = _read("map-live.js")
    assert "const HALO_HOLE_PX = 10;" in script
    assert "ctx.arc(x, y, HALO_HOLE_PX, 0, Math.PI * 2, true);" in script
    # The node style the hole has to clear, unchanged.
    app = _read("app.js")
    assert "radius: node.is_mqtt_gateway ? 7 : 5," in app


def test_heat_is_a_size_not_a_hue() -> None:
    """Meaning is never in colour alone, and this is the layer most at
    risk of it: a glow is the kind of mark that wants to say things with
    colour.

    The emission quantity is a radius and the upload quantity is a
    thickness. Both are sizes, so both survive a greyscale render and any
    colour-vision deficiency. The two layers are told apart by shape — a
    soft filled annulus against a hard hollow ring — before colour is
    consulted at all.
    """
    script = _read("map-live.js")
    assert "const outer = HALO_MIN_PX + (HALO_MAX_PX - HALO_MIN_PX) * full;" in script
    assert "const weight = RING_MIN_PX + RING_GAIN_PX * full;" in script
    css = _read("app.css")
    # A third palette group. A role is what a node is, a family is what a
    # packet was, heat is how much there has been; all three are in one
    # frame and none may borrow another's value. The one exception is
    # written down: the upload ring is the gateway ring's own colour,
    # because it is that ring getting thicker.
    assert "--heat-emission: #e8a33d;" in css
    assert "--heat-upload: #f6ece2;" in css
    assert "--pkt-position: #f4703f;" in css


def test_the_heat_ceilings_were_measured_not_guessed() -> None:
    """A constant that decides what a viewer sees is a claim.

    A linear ramp to the design's ceiling of 8 put every node at the
    bottom of the scale and the mark said nothing. The values were
    measured through `SonoranMap.stats.heatValues()` before the ramp was
    changed, and the measurement is written beside the constant so the
    next person can check it rather than take it on trust.
    """
    script = _read("map-live.js")
    assert "const HEAT_FULL = 8;" in script
    assert "const UPLOAD_FULL = 40;" in script
    assert "0.27 to 2.06" in script
    assert "0.36 to 18.4" in script
    # Monotonic and logarithmic, so more is always bigger and the
    # resolution sits where the values are.
    assert "Math.log2(1 + value) / Math.log2(1 + ceiling)" in script
    # And the numbers are readable from the console, because a quantity
    # drawn as a size cannot be checked by looking at it.
    assert "heatValues: () => ({" in script


def test_the_heat_stores_cannot_grow_for_as_long_as_the_tab_is_open() -> None:
    """The owner leaves this open for hours.

    Both stores are pruned every frame against the same floor that
    decides whether a mark is still saying anything, so a node that has
    gone quiet leaves the map rather than sitting in it below the
    threshold for ever. The loop's stop condition reads them, so an empty
    mesh stops the animation dead rather than redrawing nothing at 60 Hz.
    """
    script = _read("map-live.js")
    assert "heatPrune(emitHeat, started, EMIT_HALF_LIFE_MS);" in script
    assert "heatPrune(uploadHeat, started, UPLOAD_HALF_LIFE_MS);" in script
    assert "if (!liveCount && !queue.length && !emitHeat.size && !uploadHeat.size) {" in script


def test_reduced_motion_steps_the_heat_rather_than_removing_it() -> None:
    """Heat is a quantity, not an animation.

    It means the same thing whether or not a viewer can take movement, so
    it may not be a thing only some viewers get. With motion reduced its
    clock is snapped to a one-second grid, so it steps rather than
    glides, and the toggle does not throw it away — a toggle that
    silenced part of the mesh would look like a fault.
    """
    script = _read("map-live.js")
    assert "const HEAT_STEP_MS = 1000;" in script
    assert "Math.floor(started / HEAT_STEP_MS) * HEAT_STEP_MS" in script
    # setReduced drops the marks, which were sized for the other timing,
    # and keeps the heat, which was not.
    assert "The heat survives the switch." in script


def test_the_admission_ladder_follows_the_measured_rate() -> None:
    """The rate bands are the design's, and they are measured.

    The rate is counted over the last five seconds of releases rather
    than inferred from the size of a batch: a batch is whatever the poll
    happened to return, and the rate is what the map is being asked to
    draw.
    """
    script = _read("map-live.js")
    assert "if (perSecond <= 6) return 0;" in script
    assert "if (perSecond <= 20) return 1;" in script
    assert "if (perSecond <= 50) return 3;" in script
    assert "const RATE_WINDOW_MS = 5000;" in script
    # The rungs protect the top of the design's keep list at every step:
    # a traceroute, a direct observation and a text message.
    assert "packet.portnum === 'TEXT_MESSAGE_APP'" in script
    assert "packet.portnum === 'TRACEROUTE_APP'" in script
    assert "if (rung >= RUNG_HEAT_ONLY) return protectedKind ? 1 : 0;" in script


def test_the_frame_time_governor_has_hysteresis_in_both_directions() -> None:
    """Three seconds over budget to step down, ten under it to step up.

    The asymmetry is deliberate. Stepping down is a response to a problem
    and stepping up is a claim that the problem is gone, and the second
    deserves more evidence. Without hysteresis a map sitting on the
    threshold flaps between rungs, and a picture that changes density
    twice a second is worse than either density.
    """
    script = _read("map-live.js")
    assert "const FRAME_BUDGET_MS = 8;" in script
    assert "const FRAME_RECOVER_MS = 4;" in script
    assert "const OVER_BUDGET_SECONDS = 3;" in script
    assert "const UNDER_BUDGET_SECONDS = 10;" in script
    # The percentile is over the last second and a bit, because a
    # governor asking about three seconds cannot be answered by a
    # percentile over a whole minute.
    assert "frameLog.push({ at: started, ms: spent });" in script
    assert "frameLog[0].at < started - 1200" in script
    # Both drive it: the rate band is a floor and the governor may go
    # finer, so the rung in force is the higher of the two.
    assert "rung = Math.max(rungForRate(stats.perSecond), governorRung);" in script


def test_the_ladder_never_drops_anything_silently() -> None:
    """Whatever the ladder refuses appears in the counter.

    The arcs are a separate refusal from the packets: a packet whose arcs
    were cut is still on the map, because it has an emission pulse and it
    raised its sender's heat. So the two are counted separately and both
    are printed, rather than folded into one number that would be true of
    neither. The heat has its own cap and its own count.

    The eye cannot count marks. A thinner picture that does not say it is
    thinner is the pixel form of sampling without saying so.
    """
    script = _read("map-live.js")
    assert "stats.arcsDropped += 1;" in script
    assert "arcsDropped: stats.arcsDropped," in script
    assert "heatHidden: heatList.hidden," in script
    # And the rung is named in words, because "rung 3" is not something a
    # viewer can read.
    assert "'heat map only, arcs off'," in script
    app = _read("app.js")
    assert "arcs not drawn" in app
    assert "quieter nodes not shown" in app
    assert "data-watch-rung" in _client().get("/").text


def test_the_numeral_follows_the_rung() -> None:
    """A `+N` computed for three arcs beside a packet that drew one is a
    count of gateways that does not add up."""
    script = _read("map-live.js")
    assert "const willDraw = Math.min(budget, packet.arcs.length);" in script
    assert "const numeral = Math.max(0, packet.gateway_count - willDraw);" in script


def test_space_pauses_and_the_buffer_keeps_filling() -> None:
    """A viewer watching a burst wants to stop it and read what happened.

    Pausing holds the buffer and keeps accumulating, so nothing that
    arrives while somebody is reading is lost. Resuming carries every
    frozen age and every pending release forward by the length of the
    pause, so the replay picks up where it stopped rather than firing the
    whole pause into one frame — which is the manufactured burst this
    feature exists to remove.

    The other half of the choice is offered rather than decided, because
    the right answer depends on why the viewer paused.
    """
    watch = _read("map-watch.js")
    assert "if (key === ' ' || key === 'Spacebar') {" in watch
    assert "ctx.onPause()" in watch
    assert "ctx.onSkipToLive()" in watch
    live = _read("map-live.js")
    assert "for (const slot of pool) if (slot.live) slot.born += held;" in live
    assert "for (const item of queue) item.at += held;" in live
    assert "for (const cell of store.values()) cell.at += held;" in live
    app = _read("app.js")
    assert "paused - Space resumes from here, L skips to live" in app
    # Space is a watch-mode key, so leaving must not strand a paused map.
    assert "onLeavePaused" in app


def test_a_paused_map_costs_no_processor_time() -> None:
    """The loop stops rather than redrawing a still picture at 60 Hz.

    One draw per map movement is exactly the work the loop would have
    done, and none of the work it would have done in between. The owner
    leaves this open for hours, and a paused map is a state he will leave
    it in.
    """
    script = _read("map-live.js")
    assert "map.on('move', () => { if (paused) repaint(); });" in script
    assert "if (running || !pageActive || paused) return;" in script


def test_trace_seen_is_pruned_by_time_not_by_insertion_order() -> None:
    """The bug that was already found and fixed for traffic.

    Slicing off the first thousand keys of two thousand drops the oldest
    *keys*, which after one pass are the newest *traces*, and the map
    then redraws paths it had already drawn. It survived in the trace
    path only because a traceroute arrives about 1.25 times a minute, so
    the trim almost never ran. Rare is not fixed.
    """
    script = _read("app.js")
    assert "const traceSeen = new Map();" in script
    assert "traceSeen.set(key, Date.parse(trace.time) || Date.now());" in script
    assert "for (const [key, seenAt] of traceSeen) {" in script
    # The insertion-order trim is gone.
    assert "[...traceSeen].slice(0, 1000)" not in script


def test_the_watchdog_can_go_red() -> None:
    """A monitor that can only go green is not a monitor.

    `getAll` turns a failed request into null rather than throwing, so a
    traffic fetch that fails leaves the page rendering happily with the
    last picture under a green dot. The animation would go on replaying
    its last buffer as though the mesh were still talking, and a viewer
    watching for hours could not tell a quiet mesh from a broken pipe.
    """
    script = _read("app.js")
    assert "mapState.failures = traffic ? 0 : (mapState.failures || 0) + 1;" in script
    assert "if (mapState.failures >= 3) {" in script
    assert "traffic requests are failing, the map has stopped" in script


def test_the_sparkline_is_raw_and_says_its_sample_interval() -> None:
    """A smoothed rate line hides the bursts, and the bursts are the
    phenomenon the owner wants to watch.

    It counts packets rather than uploads, for the same reason everything
    else on this page does: a chart of rows would rise when one gateway
    reconnected and uploaded a backlog, and read as the mesh getting
    busier when nothing about the mesh had changed (AGENTS.md 9.5.1).

    A second the returned window does not cover is left out rather than
    drawn as a zero. A row limit is not evidence that nothing happened
    (AGENTS.md 9.19), and a zero bar is exactly that claim.
    """
    script = _read("app.js")
    assert "const SPARK_SECONDS = 60;" in script
    assert "Packets a second, 1 s samples, last ${SPARK_SECONDS} s" in script
    assert "is not drawn rather than drawn as nothing." in script
    # The gap is a gap.
    assert "if (!known[index]) continue;" in script
    assert "data-traffic-spark" in _client().get("/").text


def test_the_feed_is_updated_in_place_and_coalesced() -> None:
    """`replace()` of the whole list destroys the scroll position.

    In watch mode the panel is tall and the panel is where the exact
    numbers live, so a viewer reading a row halfway down lost it four
    times a minute — which makes the panel useless for the one thing it
    is for. And without coalescing, one tracker posting a position every
    thirty seconds owns the whole feed.
    """
    script = _read("app.js")
    assert "function coalesceFeed(packets)" in script
    assert "const COALESCE_MS = 60000;" in script
    assert "function updateFeed(list, rows, emptyText)" in script
    assert "updateFeed($('[data-traffic-feed]', page), newest," in script
    # Only a consecutive run collapses, so the order is still the order
    # things happened in and a gap in the middle is still a gap.
    assert "const last = rows[rows.length - 1];" in script


def test_the_watch_chrome_sits_above_the_animation_canvas() -> None:
    """`#map` does not open a stacking context, so the panes inside it
    compete with the chrome beside it.

    The animation pane is at 620, which is where it has to be to clear
    Leaflet's marker pane at 600. Chrome numbered in the five hundreds
    therefore lost, and heat halos painted over the traffic table — found
    in a screenshot of the expanded panel, with a halo sitting on a row's
    SNR cell. The chrome is raised above 620 and stays below Leaflet's
    control container at 800, which keeps the way out of watch mode on
    top where it belongs.
    """
    import re

    css = _read("app.css")

    def z_index(selector: str) -> int:
        """The `z-index` of one rule, read from the rule rather than from
        a line of text.

        These were three literal one-line matches, which broke the moment
        the offsets became `calc()` expressions over the safe-area insets
        and had to go on separate lines. The numbers are the invariant;
        how they are spelt is not.
        """
        match = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S)
        assert match, f"no rule for {selector}"
        found = re.search(r"z-index:\s*(\d+)", match.group(1))
        assert found, f"{selector} has no z-index"
        return int(found.group(1))

    # Above the animation pane at 620, and below Leaflet's control
    # container at 800, which holds the way out of watch mode.
    for selector in (".watch-bar", ".watch-panel", ".watch-legend"):
        assert 620 < z_index(selector) < 800, selector
    # And the strip stays above the panel, which stays above nothing else
    # in the overlay: the legend is the topmost of the three.
    assert z_index(".watch-legend") > z_index(".watch-bar") > z_index(".watch-panel")
    assert "pane.style.zIndex = '620';" in _read("map-live.js")


def test_the_page_says_what_it_skipped_after_a_sleep() -> None:
    """A tab hidden for three hours comes back to a map of three hours
    ago under a stale "Updated HH:MM" with no warning at all.

    The buffer is discarded rather than replayed — playing out forty
    minutes of sleep would manufacture exactly the burst this change
    removed — and what was skipped is said.
    """
    script = _read("app.js")
    assert "resumed, skipped ${count(minutes)} min" in script
    assert "mapState.hiddenAt = Date.now();" in script


def test_the_phone_ticker_does_not_run_where_it_cannot_be_seen() -> None:
    """A timer that writes into a `display: none` element for hours.

    CSS shows the ticker below 47.9 rem and at the peek height alone, and
    the timer ran in watch mode at any width — so a desktop watching for
    three hours woke a timer five thousand times to do nothing visible.
    The page is meant to hold two timers and a frame loop.
    """
    script = _read("app.js")
    assert "getComputedStyle(ticker).display !== 'none'" in script
    assert "!SonoranWatch.isOn() || !visible" in script
