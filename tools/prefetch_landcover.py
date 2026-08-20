"""Fill the land cover cache.

The terrain model says where the ground is. It does not say what stands
on it, and ITM has no clutter model of its own. This tool makes the
pages that let a prediction charge the clutter loss of ITU-R P.2108.

The source is the ESA WorldCover 10 m product, which is a set of cloud
optimised GeoTIFF files in three degree squares on a public S3 bucket.
Each is reduced here to the same 1200 by 1200 page grid the terrain
uses, one byte for each cell, holding the most common class in it.

That reduction is why this is a tool and not a service. Reading a
GeoTIFF needs `rasterio`, and `rasterio` needs GDAL. Nothing in the
running system reads one: the API and the jobs read the plain byte
pages this writes, with numpy. It is the same arrangement the terrain
cache uses.

The product is fixed, so this is run once:

    uv pip install "rasterio>=1.3"
    uv run python tools/prefetch_landcover.py

Arizona is nine source tiles and about 60 degrees of page. Expect a
few minutes and a few hundred megabytes of download for about 90 MB
kept.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from sonoran.config import get_settings
from sonoran.landcover.store import PAGE_SIZE, is_tile_name, page_path, tile_name
from sonoran.logging import configure_logging, get_logger

logger = get_logger(__name__)

# Where the product lives. It is on the AWS open data registry, so it
# needs no credentials.
SOURCE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"

# The source squares are three degrees on a side.
SOURCE_STEP = 3


def source_url(latitude: int, longitude: int) -> str:
    """Return the URL of the square that holds a whole degree."""
    south = latitude - (latitude % SOURCE_STEP)
    west = longitude - (longitude % SOURCE_STEP)
    north_south = "N" if south >= 0 else "S"
    east_west = "E" if west >= 0 else "W"
    name = f"{north_south}{abs(south):02d}{east_west}{abs(west):03d}"
    return f"{SOURCE}/ESA_WorldCover_10m_2021_v200_{name}_Map.tif"


def reduce_to_page(block: np.ndarray) -> bytes:
    """Return one degree of land cover as a page of classes.

    The source is 10 m and a page is 90 m, so about nine source cells
    fall in each page cell. The most common class wins.

    The most common and not the average. A class is a name, not a
    number: the average of water and built-up is not a meadow.
    """
    if block.shape[0] < PAGE_SIZE or block.shape[1] < PAGE_SIZE:
        raise ValueError(f"the source block is {block.shape}, too small for a page")

    factor_y = block.shape[0] // PAGE_SIZE
    factor_x = block.shape[1] // PAGE_SIZE
    trimmed = block[: PAGE_SIZE * factor_y, : PAGE_SIZE * factor_x]
    grouped = trimmed.reshape(PAGE_SIZE, factor_y, PAGE_SIZE, factor_x).transpose(0, 2, 1, 3)
    flat = grouped.reshape(PAGE_SIZE, PAGE_SIZE, factor_y * factor_x)

    # A count for each class, then the class with the most.
    counts = np.zeros((PAGE_SIZE, PAGE_SIZE, 256), dtype=np.uint8)
    for index in range(flat.shape[2]):
        np.add.at(
            counts,
            (np.arange(PAGE_SIZE)[:, None], np.arange(PAGE_SIZE)[None, :], flat[:, :, index]),
            1,
        )
    return counts.argmax(axis=2).astype(np.uint8).tobytes()


def fetch_one(reader: object, latitude: int, longitude: int, out: Path) -> str:
    """Read one degree out of an open source file. Return what happened."""
    import rasterio
    from rasterio.windows import from_bounds

    assert isinstance(reader, rasterio.DatasetReader)
    if out.exists():
        return "cached"
    window = from_bounds(
        longitude, latitude, longitude + 1, latitude + 1, transform=reader.transform
    )
    block = reader.read(1, window=window)
    page = reduce_to_page(block)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(f".{out.name}.tmp")
    temporary.write_bytes(page)
    temporary.replace(out)
    return "written"


def main() -> int:
    """Fill the cache for the configured region."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=int, help="one degree of latitude only")
    parser.add_argument("--lon", type=int, help="one degree of longitude only")
    parser.add_argument("--dry-run", action="store_true", help="say what would be fetched")
    arguments = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    if (arguments.lat is None) != (arguments.lon is None):
        logger.error("give both --lat and --lon, or neither")
        return 1

    if arguments.lat is not None:
        wanted = [(arguments.lat, arguments.lon)]
    else:
        wanted = [
            (latitude, longitude)
            for latitude in range(settings.terrain_lat_min, settings.terrain_lat_max + 1)
            for longitude in range(settings.terrain_lon_min, settings.terrain_lon_max + 1)
        ]

    if arguments.dry_run:
        for latitude, longitude in wanted:
            print(f"{tile_name(latitude, longitude)}  {source_url(latitude, longitude)}")
        return 0

    try:
        import rasterio
    except ImportError:
        logger.error(
            "this tool needs rasterio, which the running system does not. "
            'Install it with: uv pip install "rasterio>=1.3"'
        )
        return 1

    # One source file covers nine degrees, so open each one once.
    by_source: dict[str, list[tuple[int, int]]] = {}
    for latitude, longitude in wanted:
        by_source.setdefault(source_url(latitude, longitude), []).append((latitude, longitude))

    written = cached = failed = 0
    for url, degrees in sorted(by_source.items()):
        try:
            with rasterio.open(url) as reader:
                for latitude, longitude in degrees:
                    name = tile_name(latitude, longitude)
                    if not is_tile_name(name):
                        continue
                    out = page_path(settings, name)
                    try:
                        what = fetch_one(reader, latitude, longitude, out)
                    except Exception as error:
                        logger.error("%s failed: %s", name, error)
                        failed += 1
                        continue
                    if what == "written":
                        written += 1
                        logger.info("%s written", name)
                    else:
                        cached += 1
        except Exception as error:
            logger.error("%s could not be opened: %s", url, error)
            failed += len(degrees)

    logger.info("done: %s written, %s already cached, %s failed", written, cached, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
