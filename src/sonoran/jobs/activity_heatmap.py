from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
import shutil
import struct
import zlib

import numpy as np
import numpy.typing as npt
from sqlalchemy import select

from sonoran.config import Settings
from sonoran.coverage import store
from sonoran.coverage.grid import Grid, region_grid
from sonoran.coverage.render import tiles_for_grid, tile_latitudes, tile_longitudes
from sonoran.db.models import PacketSeen, PositionMetrics
from sonoran.logging import get_logger

logger = get_logger(__name__)

MIN_ALPHA = 40
MAX_ALPHA = 210
MAX_PACKETS_OPACITY = 100.0

def precision_deviation_m(precision_bits: int) -> float:
    """Calculate the rough deviation in meters for a given geohash precision."""
    if precision_bits >= 32:
        return 0.0
    return (180.0 / (2 ** precision_bits)) * 111320.0

def _ramp_colour(fraction: npt.NDArray[np.float32]) -> npt.NDArray[np.uint8]:
    """Map a fraction 0.0-1.0 to the coverage color ramp."""
    RAMP = np.array([
        [255, 45, 85],
        [255, 122, 0],
        [255, 230, 0],
        [0, 217, 139],
        [0, 168, 255]
    ], dtype=np.uint8)
    
    stops = len(RAMP) - 1
    scaled = fraction * stops
    index = np.clip(np.floor(scaled).astype(int), 0, stops - 1)
    remainder = (scaled - index)[..., np.newaxis]
    
    c1 = RAMP[index]
    c2 = RAMP[index + 1]
    
    blended = c1 * (1.0 - remainder) + c2 * remainder
    return blended.astype(np.uint8)

def write_png(image: npt.NDArray[np.uint8]) -> bytes:
    """Write an RGBA array to a PNG stream."""
    height, width, _ = image.shape
    
    ihdr = b"IHDR" + struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr_crc = struct.pack("!I", zlib.crc32(ihdr) & 0xFFFFFFFF)
    
    raw = np.empty((height, width * 4 + 1), dtype=np.uint8)
    raw[:, 0] = 0
    raw[:, 1:] = image.reshape(height, width * 4)
    
    idat = b"IDAT" + zlib.compress(raw.tobytes(), level=1)
    idat_crc = struct.pack("!I", zlib.crc32(idat) & 0xFFFFFFFF)
    
    iend = b"IEND"
    iend_crc = struct.pack("!I", zlib.crc32(iend) & 0xFFFFFFFF)
    
    return b"\x89PNG\r\n\x1a\n" + struct.pack("!I", len(ihdr) - 4) + ihdr + ihdr_crc + \
           struct.pack("!I", len(idat) - 4) + idat + idat_crc + \
           b"\x00\x00\x00\x00" + iend + iend_crc

async def _fetch_position_metrics(session: Any) -> list[tuple[float, float, int, float, float, float]]:
    """Fetch position metrics and calculate the three relative scores for each packet."""
    since = datetime.now(UTC) - timedelta(days=30)
    
    query = (
        select(
            PositionMetrics.latitude,
            PositionMetrics.longitude,
            PositionMetrics.precision_bits,
            PositionMetrics.packet_id,
            PacketSeen.gateway_node_num,
            PacketSeen.hop_start,
            PacketSeen.hop_limit
        )
        .join(PacketSeen, 
              (PositionMetrics.packet_id == PacketSeen.packet_id) & 
              (PositionMetrics.node_num == PacketSeen.from_node_num))
        .where(PositionMetrics.time >= since)
        .where(PositionMetrics.latitude.is_not(None))
        .where(PositionMetrics.longitude.is_not(None))
        .where((PositionMetrics.location_source != "LOC_MANUAL") | PositionMetrics.location_source.is_(None))
    )
    
    result = await session.execute(query)
    
    packets = {}
    for lat, lon, prec, pkt_id, gw_num, hop_start, hop_limit in result:
        if hop_start is None or hop_limit is None:
            continue
            
        if pkt_id not in packets:
            packets[pkt_id] = (lat, lon, prec, hop_start, {})
            
        hops_used = hop_start - hop_limit
        gateways = packets[pkt_id][4]
        
        if gw_num not in gateways or hops_used < gateways[gw_num]:
            gateways[gw_num] = hops_used
            
    final_data = []
    
    for _, (lat, lon, prec, hop_start, gateways) in packets.items():
        if not gateways:
            continue
            
        raw_count = float(len(gateways))
        
        multiplier = 5.0 / max(1, hop_start)
        multiplier_score = float(raw_count * multiplier)
        
        weighted_score = 0.0
        for hops in gateways.values():
            if hops <= 0:
                weighted_score += 10.0
            elif hops <= 2:
                weighted_score += 5.0
            elif hops <= 4:
                weighted_score += 2.0
            else:
                weighted_score += 1.0
                
        final_data.append((lat, lon, prec, raw_count, multiplier_score, weighted_score))
        
    return final_data

def box_blur(grid: npt.NDArray[np.float32], radius: int) -> npt.NDArray[np.float32]:
    """Fast 2D box blur using integral images (O(N) independent of radius)."""
    if radius <= 0:
        return grid
        
    # Y-axis blur
    padded_y = np.pad(grid, ((radius, radius), (0, 0)), mode='edge')
    integral_y = np.cumsum(padded_y, axis=0)
    integral_y = np.vstack([np.zeros((1, grid.shape[1]), dtype=integral_y.dtype), integral_y])
    
    W = 2 * radius + 1
    out_y = (integral_y[W:] - integral_y[:-W]) / W
    
    # X-axis blur
    padded_x = np.pad(out_y, ((0, 0), (radius, radius)), mode='edge')
    integral_x = np.cumsum(padded_x, axis=1)
    integral_x = np.hstack([np.zeros((out_y.shape[0], 1), dtype=integral_x.dtype), integral_x])
    
    out_xy = (integral_x[:, W:] - integral_x[:, :-W]) / W
    
    return out_xy

def blur_grid(grid: npt.NDArray[np.float32], radius: int = 15, iterations: int = 3) -> npt.NDArray[np.float32]:
    """Apply multiple passes of a box blur to approximate a Gaussian blur."""
    out = grid
    for _ in range(iterations):
        out = box_blur(out, radius)
    return out

def local_max_pool(grid: npt.NDArray[np.float32], radius_cells: int = 177) -> npt.NDArray[np.float32]:
    """Find the local maximum over a given radius using block downsampling."""
    block_size = max(1, (radius_cells * 2) // 10)
    
    h, w = grid.shape
    pad_h = (block_size - (h % block_size)) % block_size
    pad_w = (block_size - (w % block_size)) % block_size
    
    padded = np.pad(grid, ((0, pad_h), (0, pad_w)), mode='constant', constant_values=0)
    ph, pw = padded.shape
    
    coarse = padded.reshape(ph // block_size, block_size, pw // block_size, block_size).max(axis=(1, 3))
    
    window = 10
    offset = window // 2
    coarse_padded = np.pad(coarse, offset, mode='edge')
    coarse_max = np.zeros_like(coarse)
    
    for i in range(window):
        for j in range(window):
            coarse_max = np.maximum(coarse_max, coarse_padded[i:i+coarse.shape[0], j:j+coarse.shape[1]])
            
    upsampled = np.repeat(np.repeat(coarse_max, block_size, axis=0), block_size, axis=1)[:h, :w]
    
    # Smooth the step-function block edges so colors transition cleanly
    smoothed = box_blur(upsampled, radius=block_size)
    smoothed = box_blur(smoothed, radius=block_size)
    
    return np.maximum(smoothed, 1.0)

def _build_grids(
    settings: Settings, 
    data: list[tuple[float, float, int, float, float, float]]
) -> tuple[Grid, dict[str, npt.NDArray[np.float32]], npt.NDArray[np.float32]]:
    """Build the region grids and return normalized grids for each model."""
    grid = region_grid(
        settings.terrain_lat_min,
        settings.terrain_lat_max,
        settings.terrain_lon_min,
        settings.terrain_lon_max
    )
    
    models = ["raw", "multiplier", "weighted"]
    score_grids = {m: np.zeros((grid.height, grid.width), dtype=np.float32) for m in models}
    count_grid = np.zeros((grid.height, grid.width), dtype=np.float32)
    
    for lat, lon, prec, raw_s, mul_s, w_s in data:
        row = grid.row_of(lat)
        col = grid.column_of(lon)
        
        if row < 0 or row >= grid.height or col < 0 or col >= grid.width:
            continue
            
        for g_name, score in zip(models, [raw_s, mul_s, w_s]):
            score_grids[g_name][row, col] = max(score_grids[g_name][row, col], score)
            
        # Inject enough count mass so the blur spreads it visibly.
        # With blur radius=15 and 3 iterations the peak drops by ~1000x,
        # so injecting MAX_PACKETS_OPACITY keeps the blurred peak above
        # the active threshold.
        count_grid[row, col] = min(count_grid[row, col] + MAX_PACKETS_OPACITY, MAX_PACKETS_OPACITY)
        
    count_grid = blur_grid(count_grid)
    relative_grids = {}
    for g_name in models:
        raw_s = score_grids[g_name]
        mask = (raw_s > 0).astype(np.float32)
        
        blurred_s = blur_grid(raw_s)
        blurred_mask = blur_grid(mask)
        
        # Normalize the blurred score so colors extend outward without dropping to 0
        s_grid = np.divide(blurred_s, blurred_mask, out=np.zeros_like(blurred_s), where=blurred_mask > 0.001)
        
        local_potential = local_max_pool(s_grid, radius_cells=177)
        relative = np.divide(s_grid, local_potential, out=np.zeros_like(s_grid), where=local_potential > 0.001)
        relative_grids[g_name] = np.clip(relative, 0.0, 1.0)
        
    return grid, relative_grids, count_grid

def sample_heatmap_tile(
    rel_grid: npt.NDArray[np.float32], 
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

    patch_rel = rel_grid[safe_rows[:, None], safe_columns[None, :]]
    patch_count = count_grid[safe_rows[:, None], safe_columns[None, :]]
    inside = inside_rows[:, None] & inside_columns[None, :]
    
    return (
        np.where(inside, patch_rel, 0.0).astype(np.float32),
        np.where(inside, patch_count, 0.0).astype(np.float32)
    )

def _render_tile(rel_score: npt.NDArray[np.float32], count: npt.NDArray[np.float32]) -> npt.NDArray[np.uint8]:
    """Render a patch of relative score and count into an RGBA tile."""
    height, width = rel_score.shape
    image = np.zeros((height, width, 4), dtype=np.uint8)
    
    active = count > 0.01
    if not active.any():
        return image
        
    image[..., :3] = _ramp_colour(rel_score)
    
    alpha_high = MIN_ALPHA + np.clip((count - 1.0) / max(1.0, MAX_PACKETS_OPACITY - 1.0), 0.0, 1.0) * (MAX_ALPHA - MIN_ALPHA)
    alpha_low = count * MIN_ALPHA
    alpha = np.where(count >= 1.0, alpha_high, alpha_low)
    
    image[..., 3] = np.where(active, alpha.astype(np.uint8), 0)
    return image

async def run_once(session: Any, settings: Settings) -> None:
    """Entry point for the scheduled job."""
    start = datetime.now(UTC)
    
    data = await _fetch_position_metrics(session)
    if not data:
        logger.info("activity heatmap: no data found in the last 30 days")
        return

    grid, relative_grids, count_grid = _build_grids(settings, data)
    
    cache_dir = Path(settings.coverage_cache_dir)
    preset = "all"
    site_set = "all"
    written = 0
    
    for layer in relative_grids.keys():
        layer_dir = cache_dir / preset / site_set / f"empirical_heatmap_{layer}"
        if layer_dir.exists():
            shutil.rmtree(layer_dir, ignore_errors=True)
            
    for layer, rel_grid in relative_grids.items():
        layer_name = f"empirical_heatmap_{layer}"
        for zoom in range(settings.coverage_min_zoom, settings.coverage_max_zoom + 1):
            for tile in tiles_for_grid(grid, zoom):
                patch_rel, patch_count = sample_heatmap_tile(rel_grid, count_grid, grid, tile)
                image = _render_tile(patch_rel, patch_count)
                if not image[..., 3].any():
                    continue
                store.write_tile(
                    cache_dir, preset, site_set, layer_name, tile.zoom, tile.x, tile.y, write_png(image)
                )
                written += 1
            
    took = (datetime.now(UTC) - start).total_seconds()
    logger.info("activity heatmap: wrote %s tiles across 3 models in %.1fs", written, took)

def run() -> None:
    """Console script entry point for running once manually."""
    from sonoran.config import get_settings
    from sonoran.db.session import make_engine, make_session_factory
    from sonoran.logging import configure_logging
    import asyncio

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)

    async def main() -> None:
        try:
            async with factory() as session:
                await run_once(session, settings)
        finally:
            await engine.dispose()

    asyncio.run(main())
