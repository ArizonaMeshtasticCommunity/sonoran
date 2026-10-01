"""Empirical activity heatmap based on position metrics and gateway reception.

Generates raster map tiles showing where position packets have successfully
reached the mesh over a rolling 30-day window, driven by ground-truth data.
Color represents maximum distance reached, and opacity represents packet count.
"""

import math
import struct
import zlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import numpy.typing as npt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings
from sonoran.coverage import store
from sonoran.coverage.grid import Grid, region_grid
from sonoran.coverage.render import tiles_for_grid, tile_latitudes, tile_longitudes
from sonoran.db.models import Node, PacketSeen, PositionMetrics
from sonoran.logging import get_logger
from sonoran.positions import precision_deviation_m

logger = get_logger(__name__)

# Constants for heatmap rendering
TILE_SIZE = 256
MAX_DISTANCE_KM = 32.0  # Approx 20 miles for max green color
MAX_PACKETS_OPACITY = 10  # Packets needed for 100% opacity
MIN_ALPHA = 51  # 20% opacity for 1 packet
MAX_ALPHA = 235 # Roughly 92% max opacity (matches COVER_ALPHA)

RAMP = (
    (0xFF, 0x2D, 0x55), # Red (0 km)
    (0xFF, 0x7A, 0x00), # Orange
    (0xFF, 0xE6, 0x00), # Yellow
    (0x00, 0xD9, 0x8B), # Light Green
    (0x00, 0xA8, 0xFF), # Blue (Max distance)
)

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance in kilometers between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def _ramp_colour(fraction: npt.NDArray[np.float32]) -> npt.NDArray[np.uint8]:
    """Return the ramp colour for each value, from 0 to 1."""
    stops = np.array(RAMP, dtype=np.float32)
    last = len(RAMP) - 1
    position = np.clip(fraction, 0.0, 1.0) * last
    lower = np.floor(position).astype(np.int32)
    upper = np.minimum(lower + 1, last)
    weight = (position - lower)[..., None]
    mixed = stops[lower] * (1.0 - weight) + stops[upper] * weight
    return mixed.astype(np.uint8)

def write_png(image: npt.NDArray[np.uint8]) -> bytes:
    """Return an RGBA image as a PNG file."""
    height, width = image.shape[0], image.shape[1]
    rows = np.concatenate(
        [np.zeros((height, 1), dtype=np.uint8), image.reshape(height, width * 4)], axis=1
    )
    body = zlib.compress(rows.tobytes(), level=6)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        head = struct.pack(">I", len(payload)) + kind
        return head + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", body) + chunk(b"IEND", b"")
    )

async def _fetch_aggregated_data(session: AsyncSession) -> list[tuple[float, float, int, float, int]]:
    """Fetch position metrics from last 30 days and calculate max distance and packet counts."""
    since = datetime.now(UTC) - timedelta(days=30)
    
    # We do a join to get packet origin and gateway destination
    # We fetch rows and calculate distance in python to avoid relying on PostGIS
    
    query = (
        select(
            PositionMetrics.latitude,
            PositionMetrics.longitude,
            PositionMetrics.precision_bits,
            Node.last_lat,
            Node.last_lon,
            PositionMetrics.packet_id
        )
        .join(PacketSeen, 
              (PositionMetrics.packet_id == PacketSeen.packet_id) & 
              (PositionMetrics.node_num == PacketSeen.from_node_num))
        .join(Node, PacketSeen.gateway_node_num == Node.node_num)
        .where(PositionMetrics.time >= since)
        .where(PositionMetrics.latitude.is_not(None))
        .where(PositionMetrics.longitude.is_not(None))
        .where(Node.last_lat.is_not(None))
        .where(Node.last_lon.is_not(None))
    )
    
    result = await session.execute(query)
    
    # Aggregate in memory: (lat, lon, precision_bits) -> dict(packet_ids: set, max_dist: float)
    agg = defaultdict(lambda: {"packets": set(), "max_dist": 0.0})
    for lat, lon, prec, g_lat, g_lon, pkt_id in result:
        key = (lat, lon, prec)
        dist = haversine(lat, lon, g_lat, g_lon)
        cell = agg[key]
        cell["packets"].add(pkt_id)
        if dist > cell["max_dist"]:
            cell["max_dist"] = dist
            
    # Return as list of (lat, lon, precision, max_dist, count)
    final_data = []
    for (lat, lon, prec), data in agg.items():
        final_data.append((lat, lon, prec or 32, data["max_dist"], len(data["packets"])))
        
    return final_data

def blur_grid(grid: npt.NDArray[np.float32], iterations: int = 2) -> npt.NDArray[np.float32]:
    """Apply a simple 3x3 box blur to soften hard edges."""
    out = grid.copy()
    for _ in range(iterations):
        padded = np.pad(out, 1, mode='edge')
        out = (
            padded[1:-1, 1:-1] * 4 +
            padded[:-2, 1:-1] +
            padded[2:, 1:-1] +
            padded[1:-1, :-2] +
            padded[1:-1, 2:]
        ) / 8.0
    return out

def _build_grids(
    settings: Settings, 
    data: list[tuple[float, float, int, float, int]]
) -> tuple[Grid, npt.NDArray[np.float32], npt.NDArray[np.int32]]:
    """Build the region grids for distance and packet count."""
    grid = region_grid(
        settings.terrain_lat_min,
        settings.terrain_lat_max,
        settings.terrain_lon_min,
        settings.terrain_lon_max
    )
    
    dist_grid = np.zeros((grid.height, grid.width), dtype=np.float32)
    count_grid = np.zeros((grid.height, grid.width), dtype=np.float32)
    
    for lat, lon, prec, dist, count in data:
        # Convert lat/lon to grid row/col
        row = grid.row_of(lat)
        col = grid.column_of(lon)
        
        if row < 0 or row >= grid.height or col < 0 or col >= grid.width:
            continue
            
        # Determine deviation in meters based on precision bits
        dev_m = precision_deviation_m(prec)
        # 1 degree lat is approx 111320 meters. Grid is 1200 cells/deg.
        # So 1 cell is approx 111320 / 1200 = 92.7 meters.
        cell_size_m = 111320.0 / grid.cells_per_degree
        radius_cells = max(0, int(round((dev_m or 0) / cell_size_m)))
        
        r_start = max(0, row - radius_cells)
        r_end = min(grid.height, row + radius_cells + 1)
        c_start = max(0, col - radius_cells)
        c_end = min(grid.width, col + radius_cells + 1)
        
        # We take the max distance across overlaps, and sum the packet counts
        block_dist = dist_grid[r_start:r_end, c_start:c_end]
        np.maximum(block_dist, dist, out=block_dist)
        
        block_count = count_grid[r_start:r_end, c_start:c_end]
        block_count += count
        
    # Soften edges
    dist_grid = blur_grid(dist_grid, iterations=2)
    count_grid = blur_grid(count_grid, iterations=2)
        
    return grid, dist_grid, count_grid

def sample_heatmap_tile(
    dist_grid: npt.NDArray[np.float32], 
    count_grid: npt.NDArray[np.float32], 
    grid: Grid, 
    tile
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Sample the grids for a specific web mercator tile."""
    latitudes = tile_latitudes(tile)
    longitudes = tile_longitudes(tile)

    rows = np.floor((grid.north - latitudes) * grid.cells_per_degree).astype(np.int64)
    columns = np.floor((longitudes - grid.west) * grid.cells_per_degree).astype(np.int64)

    inside_rows = (rows >= 0) & (rows < grid.height)
    inside_columns = (columns >= 0) & (columns < grid.width)

    safe_rows = np.clip(rows, 0, grid.height - 1)
    safe_columns = np.clip(columns, 0, grid.width - 1)

    patch_dist = dist_grid[safe_rows[:, None], safe_columns[None, :]]
    patch_count = count_grid[safe_rows[:, None], safe_columns[None, :]]
    inside = inside_rows[:, None] & inside_columns[None, :]
    
    return (
        np.where(inside, patch_dist, 0.0).astype(np.float32),
        np.where(inside, patch_count, 0.0).astype(np.float32)
    )

def _render_tile(dist: npt.NDArray[np.float32], count: npt.NDArray[np.float32]) -> npt.NDArray[np.uint8]:
    """Render a patch of distance and count into an RGBA tile."""
    height, width = dist.shape
    image = np.zeros((height, width, 4), dtype=np.uint8)
    
    active = count > 0.1
    if not active.any():
        return image
        
    # Scale distance to [0.0, 1.0] for the color ramp
    fraction = np.clip(dist / MAX_DISTANCE_KM, 0.0, 1.0)
    image[..., :3] = _ramp_colour(fraction)
    
    # Scale count to alpha
    # 1 packet = MIN_ALPHA, MAX_PACKETS_OPACITY packets = MAX_ALPHA
    alpha_fraction = np.clip((count - 1.0) / max(1.0, MAX_PACKETS_OPACITY - 1.0), 0.0, 1.0)
    alpha = MIN_ALPHA + alpha_fraction * (MAX_ALPHA - MIN_ALPHA)
    
    image[..., 3] = np.where(active, alpha.astype(np.uint8), 0)
    return image

async def run_once(session: AsyncSession, settings: Settings) -> None:
    """Generate the empirical heatmap tiles."""
    logger.info("activity heatmap: starting")
    start = datetime.now(UTC)
    
    # 1. Fetch data
    data = await _fetch_aggregated_data(session)
    logger.info(f"activity heatmap: fetched {len(data)} unique aggregated positions")
    
    if not data:
        logger.info("activity heatmap: no data found")
        return

    # 2. Build grids
    grid, dist_grid, count_grid = _build_grids(settings, data)
    
    # 3. Render and write tiles
    cache_dir = Path(settings.coverage_cache_dir)
    layer = "empirical_heatmap"
    preset = "all"
    site_set = "all"
    written = 0
    
    for zoom in range(settings.coverage_min_zoom, settings.coverage_max_zoom + 1):
        for tile in tiles_for_grid(grid, zoom):
            patch_dist, patch_count = sample_heatmap_tile(dist_grid, count_grid, grid, tile)
            image = _render_tile(patch_dist, patch_count)
            if not image[..., 3].any():
                continue
            store.write_tile(
                cache_dir, preset, site_set, layer, tile.zoom, tile.x, tile.y, write_png(image)
            )
            written += 1
            
    took = (datetime.now(UTC) - start).total_seconds()
    logger.info("activity heatmap: wrote %s tiles in %.1fs", written, took)

def run() -> None:
    """Console script entry point for running once manually."""
    from sonoran.config import get_settings
    from sonoran.db.session import make_engine, make_session_factory
    from sonoran.logging import configure_logging
    import asyncio

    settings = get_settings()
    configure_logging(settings.log_level)

    async def main() -> None:
        engine = make_engine(settings.database_url_jobs)
        factory = make_session_factory(engine)
        try:
            async with factory() as session:
                await run_once(session, settings)
        finally:
            await engine.dispose()

    asyncio.run(main())

