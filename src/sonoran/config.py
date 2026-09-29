"""Application settings.

This module loads settings from environment variables.
Every other module receives the Settings object as a parameter.
No other module reads os.environ directly.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The default public Meshtastic channel key (AES-128).
DEFAULT_CHANNEL_KEY = "1PG7OiApB1nwvP+rz05pAQ=="


class Settings(BaseSettings):
    """Application settings.

    All values come from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    # Database. One URL per process role.
    database_url: str = "postgresql+asyncpg://azmsh_ingest:change_me@localhost:5432/sonoran"
    database_url_api: str = "postgresql+asyncpg://azmsh_api:change_me@localhost:5432/sonoran"
    database_url_jobs: str = "postgresql+asyncpg://azmsh_jobs:change_me@localhost:5432/sonoran"

    # MQTT broker.
    mqtt_host: str = "mqtt.sonoran.net"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_use_tls: bool = False
    mqtt_keepalive: int = 60
    mqtt_topics: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["msh/US/AZ/#"])

    # Channel decryption keys. Full base64 AES keys. Tried in order.
    channel_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [DEFAULT_CHANNEL_KEY]
    )

    # The preset a page opens on when it has a choice (#177).
    #
    # MediumFast is this mesh's primary preset, and the pages used to
    # open on whichever preset happened to be first or busiest in the
    # data -- which means the landing view changed with the traffic
    # rather than with what the community actually runs.
    #
    # A setting rather than a constant because the preference belongs
    # to a deployment, not to the code: another mesh running LongFast
    # should not have to patch JavaScript to land on it. When the named
    # preset is absent from the data, the old behaviour is the
    # fallback, so nothing ends up on an empty page.
    default_preset: str = "MediumFast"

    # The channels this mesh claims as its own. A LoRa modem preset is
    # always core, so only the local names belong here. Everything else
    # is listed as extra in the channel pickers.
    core_channels: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["azmsh"])

    # mesh-graph integration.
    mesh_graph_base_url: str = "http://localhost:8080"
    # Where the API itself reaches mesh-graph, on the compose network. The
    # base URL above is the public one, for links a browser follows. The
    # API fetches trace drawings from this one and recolours them for the
    # dark site. See `sonoran/api/trace_drawing.py`.
    mesh_graph_internal_url: str = "http://mesh-graph:8080"
    mesh_graph_timeout_seconds: float = 10.0

    # Privacy switch. Text message bodies are stored only when this is true.
    store_text_messages: bool = False

    # Retention in days, per data family.
    retention_days_packet: int = 30
    retention_days_position: int = 30
    retention_days_metric: int = 90
    retention_days_traceroute: int = 90
    retention_days_text: int = 30

    # Web server.
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    web_base_path: str = ""
    web_api_base_url: str = ""

    # How long the whole-table statistics are held before they are
    # counted again.
    #
    # `/api/stats`, `/api/stats/hardware` and `/api/stats/portnums` are
    # the only answers in the API with no time window: they count every
    # row ever kept, so their cost grows with retention and not with
    # what the reader asked for. The dashboard asks for all three on
    # every load.
    #
    # Thirty seconds is chosen against what the figures are for. They
    # are a sense of scale on a dashboard, and a mesh does not change
    # its totals in a way anybody reads at second resolution.
    #
    # Zero turns the hold off and counts on every request, which is
    # what a deployment with a small database or a spare core can
    # afford.
    stats_cache_seconds: float = 30.0

    # How long one node's links and routes are held (#304).
    #
    # `/api/nodes/{id}/routes` reads every upload of the node over the
    # window. On a busy gateway that was 5 to 8 seconds on production,
    # nearly all of it one join of `packet_seen` to `packet`. Its lists
    # cover up to thirty days, and five minutes more or less of them
    # changes no row a reader looks at. Zero holds nothing.
    routes_cache_seconds: float = 300.0

    # The request budget of each API caller (`api/limits.py`). A token
    # bucket: `burst` requests at once, then `per_second` sustained.
    #
    # One dashboard page asks for 10 to 25 answers, so 300 at once is a
    # dozen pages opened together, and 3 a second is 10,800 an hour.
    # No reader reaches that. A script copying the database does.
    # Tiles have their own, larger budget, because a map fetches them
    # in hundreds. Off turns every budget off.
    api_rate_limit_enabled: bool = True
    api_rate_burst: float = 300.0
    api_rate_per_second: float = 3.0
    api_tile_rate_burst: float = 3000.0
    api_tile_rate_per_second: float = 30.0

    # The timezone every time on the page is shown in.
    #
    # Arizona does not observe daylight saving, so it sits on MST all
    # year. `America/Phoenix` carries that rule. Without a zone here the
    # browser uses its own, and a viewer outside the state reads every
    # time on the dashboard shifted by an hour or more.
    display_timezone: str = "America/Phoenix"

    # Map basemap. The tile host is added to the image sources of the CSP.
    # Set this to an empty value to hide the basemap and show nodes only.
    #
    # The OpenStreetMap tile server is fine for a mesh-sized dashboard,
    # but its usage policy asks for two things. Keep the attribution, and
    # let the browser send a Referer so the site identifies itself: a
    # request with no Referer is answered with a "blocked" placeholder
    # tile, not the map. The `Referrer-Policy` header in api/app.py is set
    # so this happens. Use one host with no `{s}` placeholder, or the CSP
    # origin cannot match it. Point this at your own tiles, or a provider
    # such as CARTO, to lean on OpenStreetMap's servers less.
    map_tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    map_tile_attribution: str = "(c) OpenStreetMap contributors"
    map_default_lat: float = 34.0
    map_default_lon: float = -111.5
    map_default_zoom: int = 7

    # The region the live map opens on (#195).
    #
    # A centre and an INTEGER zoom show a different area on every shape
    # of screen: measured at 1879x622, zoom 7 shows about 20 degrees of
    # longitude, and Arizona -- about 6 degrees wide -- filled under a
    # third of the width. A box is the thing the deployment actually
    # means, and `fitBounds` makes it fill whatever box the browser has.
    #
    # It is also the set that decides the first fit. A single node in
    # the Bay Area used to cancel the zoom-in for the whole mesh,
    # because it dragged the fit out past the configured zoom; nodes
    # outside this box are still drawn and still reachable by panning,
    # they just do not get a vote on the opening view (#114).
    #
    # The default is Arizona, because this deployment is Arizona's.
    # Another mesh sets its own four numbers and nothing in app.js
    # changes. Bounds of the state, rounded outward slightly so border
    # nodes are not clipped.
    map_home_south: float = 31.2
    map_home_west: float = -115.0
    map_home_north: float = 37.1
    map_home_east: float = -108.9

    # Address search on the coverage planner (§6.5 of the UX plan).
    #
    # **This points at a third party, and it is the only setting here
    # that sends a reader's own words off this machine.** The planner's
    # site box takes a typed address, the browser asks
    # `/api/geocode?q=...` on this origin, and `api/routes/geocode.py`
    # forwards it. A geocoder called from the browser instead would need
    # its own origin in the Content-Security-Policy and would see the
    # reader's IP address as well as what they typed; the proxy keeps
    # both here. Read that module before changing any of this.
    #
    # Nominatim is the default because this dashboard already leans on
    # OpenStreetMap for its basemap, so a deployment is not being
    # introduced to a new organisation. Its usage policy (one request a
    # second, an identifying agent, cache what you get) is honoured in
    # that module and not here.
    #
    # **Set this to empty to turn the feature off.** The endpoint then
    # answers 404, and the dashboard is told through
    # `window.SONORAN.geocode` and draws no search box at all -- rather
    # than a box that cannot work, which is the trap in `AGENTS.md` 9.9.
    #
    # Answers outside the home region above are dropped, so this cannot
    # be used as a general purpose geocoder for the whole world.
    geocode_url: str = "https://nominatim.openstreetmap.org/search"
    # How long one outbound lookup may take. Short: a reader is waiting
    # with a cursor in a box, and a slow geocoder must not hold an API
    # worker the way a slow tile source used to (see the terrain note).
    geocode_timeout_seconds: float = 8.0
    # Who this server says it is. The upstream policy requires an agent
    # that identifies the application and refuses a generic one. It
    # carries nothing about the reader.
    geocode_user_agent: str = "sonoran-dashboard (Arizona Meshtastic Community)"

    # Coverage planner terrain. Pages are made once and kept on disk.
    terrain_cache_dir: str = "/var/lib/sonoran/terrain"
    terrain_source_url: str = "https://elevation-tiles-prod.s3.amazonaws.com"
    # How long one outbound tile fetch may take.
    #
    # This was 120 seconds. A public request for an uncached in-region
    # tile makes the API hold a worker thread and an outbound
    # connection for that long, and a slow tile source is then a slow
    # API for everybody. Thirty seconds is well past a healthy fetch of
    # a few megabytes and short enough that a stuck one lets go.
    terrain_timeout_seconds: float = 30.0
    # How many tiles may be fetched from the source at once.
    #
    # The cache on disk is bounded by the region, but the work in
    # flight was not: every uncached in-region tile asked for at the
    # same time was its own connection, its own timeout, and its own
    # CPU-bound decode in a worker thread. The region holds 56 tiles,
    # so a first-warm or a cleared cache could put 56 of those in
    # flight at once on a three-core box.
    #
    # Two at a time fills a cold cache at a sensible rate and leaves
    # the thread pool to the rest of the API. A request that would be
    # the third waits its turn, which is the right answer: the page
    # treats a missing tile as sea level and asks again.
    terrain_download_concurrency: int = 2
    # Set this to false after tools/prefetch_terrain.py has filled the
    # cache. The API then makes no outbound request at all.
    terrain_allow_download: bool = True
    # The region the planner covers. Arizona is 31.33 to 37.00 north and
    # 114.82 to 109.05 west. These bounds add one degree on each side, so
    # a site near the state line still has terrain around it. A tile
    # outside these bounds is never fetched and never served.
    terrain_lat_min: int = 30
    terrain_lat_max: int = 37
    terrain_lon_min: int = -116
    terrain_lon_max: int = -109

    # Land cover. The pages say what stands on the ground, so a
    # prediction can charge the clutter loss that ITM leaves out. Make
    # them once with tools/prefetch_landcover.py. A deployment with no
    # pages predicts with no clutter, which is what the planner has
    # always done.
    landcover_cache_dir: str = "/var/lib/sonoran/landcover"

    # Coverage map. The job predicts from the selected fixed sites and
    # writes the result here, as tiles a browser can cache.
    coverage_cache_dir: str = "/var/lib/sonoran/coverage"
    coverage_enabled: bool = True
    # How often the job runs. A run costs about a second for each node,
    # so a large mesh takes minutes. It must not hold up the daily
    # snapshot, which is why the jobs process schedules them apart.
    coverage_interval_hours: int = 6
    # A node the mesh has not heard from in this long is left out. A
    # node that is gone must not hold coverage open.
    coverage_active_hours: int = 168
    # How far each node is predicted to reach, in kilometres. Past this
    # the prediction is cut, so a figure below the real reach of a tall
    # router understates the mesh.
    coverage_radius_km: float = 60.0
    # The largest number of nodes one run predicts from. The strongest
    # sites are taken first. It is a guard against a run that never
    # ends, not a limit anybody should want to reach.
    coverage_max_nodes: int = 600
    # The receiver the map assumes: a handheld with a stock antenna,
    # held about a metre and a half above the ground.
    # How coarse a position may be and still anchor a prediction, in
    # bits. Zero turns the test off. See `sonoran/positions.py`.
    #
    # Sixteen is the finest the public Meshtastic broker relays, and
    # about 365 m. On a mesh that arrives through that broker most of
    # the backbone reports 13 bits, which is 2.9 km, so most of it will
    # need a position in `config/nodes.yaml` to be a site at all. The
    # manifest counts what was left out for this reason.
    coverage_min_precision_bits: int = 16
    coverage_rx_height_m: float = 1.5
    coverage_rx_gain_dbi: float = 2.15
    # Which roles a run may predict from, as a comma separated list.
    #
    # The default is the infrastructure set, which is what a published
    # map wants. `ALL` predicts from every node, including handhelds,
    # and is a diagnostic: the manifest marks such a run, and both the
    # dashboard and the public embed label it rather than passing it
    # off as coverage. See `sonoran/roles.py`.
    coverage_site_roles: str = "ROUTER,ROUTER_LATE,REPEATER"
    # Also predict a second, wider map that includes the ordinary nodes
    # which repeat traffic: CLIENT, CLIENT_BASE and ROUTER_CLIENT.
    #
    # Off by default, and the cost is why. A run predicts from every
    # site it is given, so turning this on multiplies the work by
    # however many clients the mesh has. On the Arizona mesh that is
    # about fifty infrastructure nodes against nine hundred clients,
    # capped by COVERAGE_MAX_NODES.
    #
    # When it is on, both maps are published and the dashboard offers a
    # picker. The infrastructure map stays the default view, and it is
    # the only one the public embed will ever serve, whatever this is
    # set to. See `sonoran/roles.py` and `AGENTS.md` 9.25.
    coverage_include_clients: bool = False
    # How many worker processes predict at once. Zero means as many
    # as the machine has, less one, so the jobs process keeps a core
    # for everything else it does.
    #
    # On a small box that also serves the dashboard, set this to 1.
    # With the niceness below, a run then takes about three times as
    # long and leaves the machine responsive throughout.
    coverage_workers: int = 0
    # How much to lower the priority of each worker process.
    #
    # The engine is a solid floating point loop, so a run pins every
    # worker at 100% for minutes. On a machine that also serves the
    # dashboard and takes MQTT that is felt by everybody using it. A
    # positive niceness keeps the run off the back of anything
    # interactive: the kernel still gives it every idle cycle, and
    # hands the CPU back the moment a request arrives.
    #
    # Ten is a background batch job. Zero turns it off. It is only
    # applied where the platform has it, and never lowered, because a
    # process may not raise its own priority back.
    coverage_worker_nice: int = 10
    # The zoom levels of tile that the job writes. Level 11 is about
    # 76 m for each pixel, which is finer than the 90 m terrain, so
    # there is nothing to gain past it.
    coverage_min_zoom: int = 6
    coverage_max_zoom: int = 11

    # The public coverage embed. It is off until somebody turns it on,
    # which is the same default STORE_TEXT_MESSAGES takes: the private
    # value is the safe one.
    embed_enabled: bool = False
    # The sites that may put the embed in a frame. Anything that is not
    # an origin is dropped, and an empty list means nothing may frame
    # it. It never becomes a wildcard.
    embed_frame_ancestors: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # How far to snap a public marker, in degrees. About 0.01 degrees is
    # a kilometre, which names a hill and not a building. Zero gives the
    # exact position.
    embed_position_step: float = 0.01

    # Calibration. The job asks the mesh how far the prediction is out,
    # node by node, from the neighbour reports the nodes publish.
    calibration_enabled: bool = True
    calibration_interval_hours: int = 24
    # How far back to read neighbour reports. `neighbor_metrics` is kept
    # for RETENTION_DAYS_METRIC days, so a window past that reads
    # nothing.
    calibration_window_hours: int = 336

    # Coverage gaps. The job measures which nodes are not connected
    # well, from the packets the database already holds, and writes the
    # answer beside the coverage run. It predicts nothing.
    #
    # Every threshold below is a starting point, not a measurement.
    # `docs/design/coverage-gaps.md` 11.1 names the six figures to take
    # off live data before any of them is trusted.
    gaps_enabled: bool = True
    # How often the per node assessment is rebuilt. The signals are
    # only SQL, so freshness is cheap. The job runs on its own clock
    # and never touches the coverage engine.
    gaps_interval_minutes: int = 30
    # The measurement window. It must never exceed retention, or the
    # window reads ground that has already been deleted.
    gaps_window_hours: int = 168
    # Below this many distinct packets a node is `unknown`, never `bad`.
    # A node that says almost nothing is usually switched off.
    gaps_min_packets: int = 20
    # Below this many active hours `rf_intermittent` is `unknown`. A
    # ratio over three hours says nothing about a week.
    gaps_min_active_hours: int = 12
    # The intermittency line: the share of its awake hours in which
    # something on the air heard a node. Measure it before trusting it.
    gaps_rf_ratio_bad: float = 0.5
    # The weak margin line, in dB above what the preset needs to
    # demodulate. Measure it before trusting it.
    gaps_margin_bad_db: float = 5.0
    # How many neighbour reports a node must publish before its own
    # receiver counts as proven. See `sonoran/gaps/signals.py` 4.2.
    gaps_min_neighbour_reports: int = 2
    # How far apart two reported positions must be before a node counts
    # as mobile, in kilometres. A mobile node is still listed, because a
    # handheld that cannot get out is a real problem for its owner.
    gaps_mobile_spread_km: float = 1.0
    # A sole gateway that receives a node at least this strongly, in
    # dBm, is close to it, and `sole_observer` stops calling that a
    # fault. At 915 MHz a path loss of 90 dB is about 0.8 km in free
    # space, so -60 dBm from the 30 dBm the US band allows bounds the
    # distance to about a kilometre with plain antennas, and to a few
    # kilometres with high gain ones. Measured on the live mesh, pairs
    # that share a site read -1 to -58 dBm, and single links that
    # really are marginal read -90 to -128. See `docs/GAPS.md` 4.4.
    gaps_sole_gateway_close_rssi_dbm: float = -60.0
    # How many direct readings that median needs. One loud packet is
    # not a site.
    gaps_sole_gateway_min_readings: int = 5

    # The siting half. It answers "where would one new node help the
    # most people", and it is the only part of this feature that runs
    # the coverage engine.
    #
    # **It runs inside the coverage cycle and never beside it.** The
    # scheduler runs tasks with `asyncio.gather`, so a task registered
    # on its own clock is free to start during a coverage build. On a
    # three core box that is the last core, while the same box serves a
    # public dashboard. See `jobs/scheduler.py`.
    gaps_siting_enabled: bool = True
    # How far apart two struggling nodes must be before they count as
    # two places wanting help, in metres. Five radios in one house must
    # not outvote a ranch five miles out.
    gaps_demand_cell_m: int = 300
    # Single linkage distance for grouping demand into neighbourhoods.
    gaps_cluster_link_km: float = 8.0
    # Below this many demand points it is a node, not an area, and the
    # per node list already holds it.
    gaps_min_cluster: int = 3
    # The most areas one run reports. It bounds the engine work.
    gaps_max_clusters: int = 8
    # How far around a cluster to look for ground, in kilometres.
    gaps_search_radius_km: float = 15.0
    # How far a candidate must stand above the median of the kilometre
    # around it, in metres. The highest cell of a plain is not a site.
    gaps_min_prominence_m: float = 40.0
    # The closest two candidates may stand, in kilometres. Without it
    # one ridge fills every slot with sixty cells of itself.
    gaps_candidate_spacing_km: float = 1.5
    # How many candidates of one cluster enter the cheap terrain screen.
    gaps_candidates_per_cluster: int = 60
    # How many of them reach the engine.
    gaps_splat_per_cluster: int = 3
    # The hard ceiling on engine runs in one cycle. At the measured 3.2
    # core-seconds for a 25 km prediction this is about 77 core-seconds,
    # which is under two minutes on one niced worker.
    gaps_max_predictions: int = 24
    # The prediction radius for a candidate, in kilometres. Not the
    # 60 km the coverage map uses: a 1 W node at 9 m talking to a 1.5 m
    # handheld does not reach 60 km, and the cost grows with the square
    # of the radius.
    gaps_candidate_radius_km: float = 25.0
    # The "1 W node" the owner asked about, in dBm. It is an assumption
    # and the page prints it.
    gaps_candidate_tx_power_dbm: float = 30.0
    # A roof or attic node, in metres. The height `CLIENT_BASE` is
    # defined for. Also an assumption, also printed.
    gaps_candidate_height_m: float = 9.0
    # Engine workers for the candidate step, and their priority. One
    # niced worker on a three core box that also serves a dashboard.
    gaps_workers: int = 1
    gaps_worker_nice: int = 10

    # Radio overrides. The file names the antenna, the mast height, and
    # the power of a node, which the mesh itself never reports. It is
    # kept in the repository, so every change to it has an author and a
    # review. A file that is not there gives no overrides, which is a
    # working state.
    radio_overrides_path: str = "config/nodes.yaml"

    # The RF map (docs/design/rf-map.md). `sonoran-rf-ingest` reads what
    # the community's own receivers publish through `rf-agent`. It has a
    # broker of its own, because members' stations publish to the broker
    # they can reach, which need not be the one Meshtastic comes from.
    # An empty host means the Meshtastic broker above.
    rf_mqtt_host: str = ""
    rf_mqtt_port: int = 1883
    rf_mqtt_username: str = ""
    rf_mqtt_password: str = ""
    rf_mqtt_use_tls: bool = False
    rf_topics: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["rf/v1/#"])
    # One track point per thing per this many seconds, across every
    # station. The design's capacity arithmetic assumes 20 (5.4).
    rf_bucket_seconds: int = 20
    # A point stamped this far ahead of our clock, or this far behind it,
    # is stored with the time we received it instead (design 5.3).
    #: How far ahead of our own receipt time a NODE's timestamp may be
    #: before it is refused. Only the impossible direction is bounded:
    #: a stamp behind us is ordinary store-and-forward, a stamp ahead
    #: of us names a moment that had not happened. The slack absorbs
    #: our own clock being slightly behind, which is our fault and
    #: should not be recorded against the node. See
    #: ingest/handlers/clocks.py.
    mesh_future_slack_seconds: int = 300
    rf_future_slack_seconds: int = 60
    rf_past_slack_seconds: int = 600
    # Things never stored or shown: aircraft on the FAA LADD and PIA
    # programmes, as lower case ICAO hex. Loaded by an operator, never
    # fetched (design 8).
    rf_hidden_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # The rtl_433 model names whose readings are stored. rtl_433 decodes
    # tyre sensors, doorbells and car keys as easily as weather stations,
    # so empty means NONE pass. The agent applies its own ISM_ALLOW, and
    # this applies it again (design 8).
    rf_ism_allow: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Logging.
    log_level: str = "INFO"

    @field_validator(
        "mqtt_topics",
        "rf_topics",
        "rf_hidden_ids",
        "rf_ism_allow",
        "channel_keys",
        "core_channels",
        "embed_frame_ancestors",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: object) -> object:
        """Accept comma-separated strings for list settings."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()
