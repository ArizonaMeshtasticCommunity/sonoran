"""Make the radio climate data the planner and the coverage job read (#239).

The source is the Köppen-Geiger map of Beck et al. (2023), version 3,
1991 to 2020, at 1/120 degree (about 1 km). It is one GeoTIFF of the
whole world. This tool cuts out the region in `sonoran/climate/store.py`
and writes it as plain bytes, compressed. Nothing else changes: each
cell keeps the class number the source gave it.

Download the archive by hand from the publisher, into an empty
directory of its own, and check it against the checksum figshare gives:

    https://figshare.com/ndownloader/files/61012822   (koppen_geiger_tif.zip)
    md5 7fc2f5a15d4f5fe0ce59c9a9b502aa09

Then take out one file and run this tool on it:

    unzip koppen_geiger_tif.zip 1991_2020/koppen_geiger_0p00833333.tif
    uv run python -I tools/make_climate_crop.py 1991_2020/koppen_geiger_0p00833333.tif

The tool reads the file with the parser below and runs nothing that came
with the data. That is why it does not use GDAL: the parser reads only
the layout this one file has (tiled, 8 bit, LZW, no predictor), and
refuses anything else rather than guess.

See `src/sonoran/climate/PROVENANCE.md` for the licence.
"""

import argparse
import gzip
import hashlib
import struct
import sys
from pathlib import Path

import numpy as np

from sonoran.climate.store import CELLS_PER_DEGREE, CROP, DATA_FILE

# TIFF tags this tool reads.
WIDTH = 256
HEIGHT = 257
BITS = 258
COMPRESSION = 259
SAMPLES = 277
PREDICTOR = 317
TILE_WIDTH = 322
TILE_HEIGHT = 323
TILE_OFFSETS = 324
TILE_COUNTS = 325
PIXEL_SCALE = 33550
TIE_POINT = 33922

LZW = 5
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8, 16: 8}
TYPE_FORMATS = {1: "B", 2: "c", 3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}


def read_tags(data: bytes) -> dict[int, tuple[object, ...]]:
    """Return the tags of the first image of a classic TIFF."""
    if data[:4] != b"II*\x00":
        raise ValueError("not a little-endian classic TIFF")
    offset = struct.unpack_from("<I", data, 4)[0]
    count = struct.unpack_from("<H", data, offset)[0]
    tags: dict[int, tuple[object, ...]] = {}
    for index in range(count):
        tag, kind, number = struct.unpack_from("<HHI", data, offset + 2 + index * 12)
        if kind not in TYPE_FORMATS:
            continue
        size = TYPE_SIZES[kind] * number
        where = offset + 2 + index * 12 + 8
        if size > 4:
            where = struct.unpack_from("<I", data, where)[0]
        tags[tag] = struct.unpack_from("<" + TYPE_FORMATS[kind] * number, data, where)
    return tags


def lzw_decode(stream: bytes, expected: int) -> bytes:
    """Decode one TIFF LZW strip or tile.

    TIFF LZW reads codes most significant bit first, starts at nine
    bits, and widens one code early (at 511, 1023 and 2047).
    """
    out = bytearray()
    table: list[bytes] = [bytes([value]) for value in range(256)] + [b"", b""]
    width = 9
    bit = 0
    total = len(stream) * 8
    previous: bytes | None = None
    while bit + width <= total:
        byte = bit >> 3
        chunk = int.from_bytes(stream[byte : byte + 4].ljust(4, b"\x00"), "big")
        code = (chunk >> (32 - width - (bit & 7))) & ((1 << width) - 1)
        bit += width
        if code == 256:
            table = table[:258]
            width = 9
            previous = None
            continue
        if code == 257:
            break
        if previous is None:
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            table.append(previous + entry[:1])
        elif code == len(table):
            entry = previous + previous[:1]
            table.append(entry)
        else:
            raise ValueError(f"LZW code {code} is past the table")
        out += entry
        previous = entry
        if len(table) + 1 >= (1 << width) and width < 12:
            width += 1
    if len(out) < expected:
        raise ValueError(f"a tile decoded to {len(out)} bytes, not {expected}")
    return bytes(out[:expected])


def crop(path: Path) -> np.ndarray:
    """Return the crop of `CROP` from the source file, row 0 north."""
    data = path.read_bytes()
    tags = read_tags(data)
    if tags[BITS] != (8,) or tags[SAMPLES] != (1,) or tags[COMPRESSION] != (LZW,):
        raise ValueError("this tool reads 8 bit, one sample, LZW files only")
    if tags.get(PREDICTOR, (1,)) != (1,):
        raise ValueError("this tool reads files with no predictor only")
    width, height = tags[WIDTH][0], tags[HEIGHT][0]
    tile_w, tile_h = tags[TILE_WIDTH][0], tags[TILE_HEIGHT][0]
    scale = tags[PIXEL_SCALE]
    tie = tags[TIE_POINT]
    step = 1.0 / CELLS_PER_DEGREE
    if abs(float(scale[0]) - step) > 1e-12 or abs(float(scale[1]) - step) > 1e-12:  # type: ignore[arg-type]
        raise ValueError(f"the cell size is {scale[:2]}, not 1/{CELLS_PER_DEGREE} degree")
    if tie[3:5] != (-180.0, 90.0):
        raise ValueError(f"the grid starts at {tie[3:5]}, not at 180 W 90 N")
    assert isinstance(width, int) and isinstance(height, int)
    assert isinstance(tile_w, int) and isinstance(tile_h, int)

    row0 = (90 - CROP.north) * CELLS_PER_DEGREE
    col0 = (CROP.west + 180) * CELLS_PER_DEGREE
    rows = (CROP.north - CROP.south) * CELLS_PER_DEGREE
    cols = (CROP.east - CROP.west) * CELLS_PER_DEGREE
    tiles_across = -(-width // tile_w)
    out = np.zeros((rows, cols), dtype=np.uint8)
    for tile_row in range(row0 // tile_h, (row0 + rows - 1) // tile_h + 1):
        for tile_col in range(col0 // tile_w, (col0 + cols - 1) // tile_w + 1):
            index = tile_row * tiles_across + tile_col
            start = int(tags[TILE_OFFSETS][index])  # type: ignore[call-overload]
            length = int(tags[TILE_COUNTS][index])  # type: ignore[call-overload]
            raw = lzw_decode(data[start : start + length], tile_w * tile_h)
            tile = np.frombuffer(raw, dtype=np.uint8).reshape(tile_h, tile_w)
            top, left = tile_row * tile_h, tile_col * tile_w
            r0, r1 = max(top, row0), min(top + tile_h, row0 + rows)
            c0, c1 = max(left, col0), min(left + tile_w, col0 + cols)
            out[r0 - row0 : r1 - row0, c0 - col0 : c1 - col0] = tile[
                r0 - top : r1 - top, c0 - left : c1 - left
            ]
    return out


def main() -> int:
    """Write the crop beside the climate package."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="1991_2020/koppen_geiger_0p00833333.tif")
    parser.add_argument("--out", type=Path, default=DATA_FILE)
    arguments = parser.parse_args()

    grid = crop(arguments.source)
    if grid.max() > 30:
        print(f"a cell holds class {grid.max()}, which the legend has not got", file=sys.stderr)
        return 1
    # mtime=0 so the same source gives the same bytes on every run.
    packed = gzip.compress(grid.tobytes(), compresslevel=9, mtime=0)
    arguments.out.write_bytes(packed)
    source_sha = hashlib.sha256(arguments.source.read_bytes()).hexdigest()
    classes, counts = np.unique(grid, return_counts=True)
    print(f"source sha256 {source_sha}")
    print(f"wrote {arguments.out}: {grid.shape[0]} x {grid.shape[1]} cells, {len(packed)} bytes")
    print(f"crop sha256 {hashlib.sha256(grid.tobytes()).hexdigest()}")
    for value, number in zip(classes, counts, strict=True):
        print(f"  class {int(value):2d}: {int(number)} cells")
    return 0


if __name__ == "__main__":
    sys.exit(main())
