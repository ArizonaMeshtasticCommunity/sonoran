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

    # The channels this mesh claims as its own. A LoRa modem preset is
    # always core, so only the local names belong here. Everything else
    # is listed as extra in the channel pickers.
    core_channels: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["azmsh"])

    # mesh-graph integration.
    mesh_graph_base_url: str = "http://localhost:8080"

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

    # Coverage planner terrain. Pages are made once and kept on disk.
    terrain_cache_dir: str = "/var/lib/sonoran/terrain"
    terrain_source_url: str = "https://elevation-tiles-prod.s3.amazonaws.com"
    terrain_timeout_seconds: float = 120.0
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

    # Logging.
    log_level: str = "INFO"

    @field_validator("mqtt_topics", "channel_keys", "core_channels", mode="before")
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
