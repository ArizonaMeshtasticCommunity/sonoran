"""SRTM elevation tiles to SPLAT! engine pages.

The coverage engine reads terrain as a "page": a 1200 x 1200 grid of
int16 elevations for one degree of latitude and one degree of longitude,
in the cell order that SPLAT! uses.

A raw SRTM tile is not in that form. The legacy site planner backend put
each tile through three steps, and the engine depends on the exact result
of all three:

1. Read the 3601 x 3601 big-endian int16 `.hgt` tile. Row 0 is the north
   edge. Column 0 is the west edge.
2. Reduce it to 1201 x 1201 with an area-weighted average. This is what
   `rasterio` does with `Resampling.average`. Cells with the SRTM no-data
   value take no part in the average.
3. Apply the `srtm2sdf` transform. This replaces each cell below zero
   with an average of its neighbours, drops the northernmost row and the
   easternmost column, and writes the cells in SPLAT! order.

This module is a port of `src/terrain/srtm.ts` from the Meshtastic Site
Planner. Do not "improve" the arithmetic. Terrain profiles depend on the
exact cell values and the exact cell order. See AGENTS.md section 9.13.

This module does no input and output. It never touches the database.
"""

import numpy as np
import numpy.typing as npt

# One arc-second tile: 3601 x 3601 samples for one degree square.
HGT_SIZE = 3601
# The tile after the area-weighted reduction.
DOWNSAMPLED_SIZE = 1201
# The engine page. One row and one column of the reduced tile are dropped.
PAGE_SIZE = 1200
# Bytes in one page on the wire: int16, little-endian.
PAGE_BYTES = PAGE_SIZE * PAGE_SIZE * 2
# The SRTM value for "no measurement here".
SRTM_NODATA = -32768
# srtm2sdf runs with this floor. Nothing below it survives.
MIN_ELEVATION = 0


def page_signed_floor_lon(min_west: int) -> int:
    """Return the signed floor longitude of a page.

    SPLAT! counts longitude west-positive from 0 to 359. This returns the
    usual signed degrees instead.
    """
    if min_west < 180:
        return -(min_west + 1)
    return 359 - min_west


def tile_name(min_north: int, min_west: int) -> str:
    """Return the SRTM tile name for an engine page reference.

    The engine reports the south-west corner of each page it needs. The
    name is the skadi form, for example `N34W112` or `S34E018`.
    """
    lon = page_signed_floor_lon(min_west)
    ns = "N" if min_north >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(min_north):02d}{ew}{abs(lon):03d}"


def tile_urls(base_url: str, name: str) -> list[str]:
    """Return the download URLs for a tile, best first.

    The v2 layout is preferred. The v1 layout is the fallback.
    """
    directory = name[:3]
    base = base_url.rstrip("/")
    return [
        f"{base}/v2/skadi/{directory}/{name}.hgt.gz",
        f"{base}/skadi/{directory}/{name}.hgt.gz",
    ]


def parse_hgt(data: bytes) -> npt.NDArray[np.int16]:
    """Read a decompressed `.hgt` tile into a 3601 x 3601 array.

    The file holds big-endian int16 values. Row 0 is the north edge.
    """
    cells = HGT_SIZE * HGT_SIZE
    if len(data) < cells * 2:
        raise ValueError(f"hgt too small: {len(data)} bytes, a 1-arcsecond tile is expected")
    values = np.frombuffer(data, dtype=">i2", count=cells)
    return np.asarray(values, dtype=np.int16).reshape(HGT_SIZE, HGT_SIZE)


def _axis_weights(
    src_size: int,
    dst_size: int,
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
    """Return the source window and weights for one axis.

    Each output cell covers a range of input cells. The first and the
    last input cell of that range are usually covered in part only, so
    they carry a weight below one.

    The result is the first source index of each window, and a weight for
    each offset in the window. Offsets past the end of a window carry a
    weight of zero.
    """
    ratio = src_size / dst_size
    lo = np.empty(dst_size, dtype=np.int64)
    hi = np.empty(dst_size, dtype=np.int64)
    lo_weight = np.empty(dst_size, dtype=np.float64)
    hi_weight = np.empty(dst_size, dtype=np.float64)
    for d in range(dst_size):
        start = d * ratio
        end = (d + 1) * ratio
        first = int(np.floor(start))
        last = min(int(np.ceil(end)), src_size)
        lo[d] = first
        hi[d] = last
        lo_weight[d] = min(first + 1, end) - start
        hi_weight[d] = end - max(last - 1, start)

    width = int((hi - lo).max())
    weights = np.zeros((dst_size, width), dtype=np.float64)
    for offset in range(width):
        index = lo + offset
        inside = index < hi
        weights[:, offset] = np.where(inside, 1.0, 0.0)
        # The first cell of a window wins over the last. A window of one
        # cell therefore takes the leading weight, as the source does.
        last = inside & (index == hi - 1)
        weights[last, offset] = hi_weight[last]
        if offset == 0:
            weights[inside, offset] = lo_weight[inside]
    return lo, weights


def _round_half_away_from_zero(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Round like GDAL does when it writes a float back to an integer."""
    return np.where(values >= 0, np.floor(values + 0.5), np.ceil(values - 0.5))


def downsample_average(
    src: npt.NDArray[np.int16],
    src_size: int = HGT_SIZE,
    dst_size: int = DOWNSAMPLED_SIZE,
    nodata: int = SRTM_NODATA,
) -> npt.NDArray[np.int16]:
    """Reduce a tile with an area-weighted average.

    This reproduces `Resampling.average` in GDAL 3.3 and later for a
    ratio that is not a whole number. No-data cells take no part in the
    average. An output cell with no valid input is no-data itself.

    This step is not bit-exact against GDAL, and it cannot be. GDAL and
    this code disagree on about 6 cells in 100000, always by one metre,
    on cells whose true average falls within 1e-4 of a half metre. The
    site planner has the same disagreement and accepts it: its own test
    asks for 99.9 percent exact and a largest error of one metre. This
    port measures 99.994 percent exact against the same tile.

    The `srtm2sdf` step that follows is a different matter. That one is
    bit-exact and must stay so.
    """
    lo, weights = _axis_weights(src_size, dst_size)
    valid = (src != nodata).astype(np.float64)
    measured = np.where(src == nodata, 0.0, src).astype(np.float64)
    width = weights.shape[1]
    last = src_size - 1

    total = np.zeros((dst_size, dst_size), dtype=np.float64)
    weight = np.zeros((dst_size, dst_size), dtype=np.float64)
    for dy in range(width):
        rows = np.minimum(lo + dy, last)
        row_values = measured[rows, :]
        row_valid = valid[rows, :]
        weight_y = weights[:, dy, None]
        for dx in range(width):
            columns = np.minimum(lo + dx, last)
            cell_weight = weight_y * weights[None, :, dx]
            total += row_values[:, columns] * cell_weight
            weight += row_valid[:, columns] * cell_weight

    with np.errstate(invalid="ignore", divide="ignore"):
        average = _round_half_away_from_zero(total / weight)
    out = np.where(weight == 0, nodata, average)
    return out.astype(np.int16)


def _average_terrain(grid: npt.NDArray[np.int32], y: int, x: int, page_size: int) -> None:
    """Replace one sub-zero cell with an average of its neighbours.

    This is `average_terrain()` from `srtm2sdf.c`. Two details matter:

    - Only neighbours above the bad value take part. When none does, the
      value of the last neighbour that was read is used instead. That is
      the behaviour of the C code, not an accident of this port.
    - The grid is changed as the caller walks it, so a later cell can see
      a value this call wrote.
    """
    mpi = page_size - 1
    bad_value = int(grid[y, x])
    accum = 0
    count = 0
    temp = 0

    def consider(yy: int, xx: int) -> None:
        nonlocal accum, count, temp
        temp = int(grid[yy, xx])
        if temp > bad_value:
            accum += temp
            count += 1

    if y >= 2:
        consider(y - 1, x)
    if y <= mpi:
        consider(y + 1, x)
    if y >= 2 and x <= mpi - 1:
        consider(y - 1, x + 1)
    if x <= mpi - 1:
        consider(y, x + 1)
    if x <= mpi - 1 and y <= mpi:
        consider(y + 1, x + 1)
    if x >= 1 and y >= 2:
        consider(y - 1, x - 1)
    if x >= 1:
        consider(y, x - 1)
    if y <= mpi and x >= 1:
        consider(y + 1, x - 1)

    if count != 0:
        temp = int(np.trunc(accum / count + 0.5))
    grid[y, x] = temp if temp > MIN_ELEVATION else MIN_ELEVATION


def srtm2sdf_transform(
    grid: npt.NDArray[np.int16], page_size: int = PAGE_SIZE
) -> npt.NDArray[np.int16]:
    """Apply the `srtm2sdf` transform to a reduced tile.

    The input is a (page_size + 1) square with row 0 on the north edge.
    The output is a page_size square in SPLAT! cell order.

    `WriteSDF` walks latitude from south to north and longitude from east
    to west, which is why the window is read backwards on both axes.
    """
    n = page_size + 1
    if grid.shape != (n, n):
        raise ValueError(f"expected a {n} x {n} grid, got {grid.shape}")

    srtm = np.clip(grid.astype(np.int64), -32768, 32767).astype(np.int32)
    # The walk reads y from 1 to page_size and x from 0 to page_size - 1.
    # `average_terrain` stays inside the same window, so a window with no
    # sub-zero cell cannot change and needs no walk.
    window = srtm[1:n, 0:page_size]
    if bool((window >= MIN_ELEVATION).all()):
        return np.ascontiguousarray(window[::-1, ::-1]).astype(np.int16)

    out = np.empty(page_size * page_size, dtype=np.int16)
    index = 0
    for y in range(page_size, 0, -1):
        for x in range(page_size - 1, -1, -1):
            if srtm[y, x] < MIN_ELEVATION:
                _average_terrain(srtm, y, x, page_size)
            out[index] = srtm[y, x]
            index += 1
    return out.reshape(page_size, page_size)


def page_from_hgt(data: bytes) -> bytes:
    """Turn a decompressed `.hgt` tile into an engine page.

    The result is `PAGE_BYTES` of little-endian int16, ready to send to
    the browser and hand straight to the engine.
    """
    reduced = downsample_average(parse_hgt(data))
    page = srtm2sdf_transform(reduced)
    return page.astype("<i2").tobytes()
