# Köppen-Geiger climate data

`koppen_1991_2020.u8.gz` is a crop of a published map. It is not
Sonoran's own work.

## Attribution

Beck, H. E., T. R. McVicar, N. Vergopolan, A. Berg, N. J. Lutsko,
A. Dufour, Z. Zeng, X. Jiang, A. I. J. M. van Dijk, and D. G. Miralles.
High-resolution (1 km) Köppen-Geiger maps for 1901–2099 based on
constrained CMIP6 projections. *Scientific Data* 10, 724 (2023).
https://doi.org/10.1038/s41597-023-02549-6

## Licence

Creative Commons Attribution 4.0 International (CC BY 4.0).
https://creativecommons.org/licenses/by/4.0/

The licence is recorded on the figshare record of the data
(`license: CC BY 4.0`) and on the authors' page,
https://www.gloh2o.org/koppen/, which says: "The data and code are
provided under the Creative Commons Attribution 4.0 International".
CC BY 4.0 permits redistribution and adaptation, with credit, a link to
the licence, and a statement of the changes. This file is all three.

The licence covers this data file only. It does not change the licence
of the code around it.

## Source

- Record: https://doi.org/10.6084/m9.figshare.21789074, version 2,
  published 2026-01-14. This is the map's version 3, which corrects a
  small calculation error in the first 2023 release.
- Archive: `koppen_geiger_tif.zip`, https://figshare.com/ndownloader/files/61012822,
  130 618 411 bytes, md5 `7fc2f5a15d4f5fe0ce59c9a9b502aa09` (the
  checksum figshare publishes; the download matched it).
- File used: `1991_2020/koppen_geiger_0p00833333.tif`, sha256
  `2130f0071dfb2904947d8ec3a0d807fac71004df76e769262004f1602e4d6a13`.
  The present-day map, 1991 to 2020, at 1/120 degree.
- Retrieved: 2026-10-09.

## Changes made

1. Cropped to 30 to 38 north and 116 to 108 west, which is the default
   terrain region in `sonoran/config.py`. 960 by 960 cells.
2. Written as plain bytes, one byte for each cell, row 0 north and
   column 0 west, and compressed with gzip.

No cell value was changed. Each one is still the class number of the
source `legend.txt` (1 = Af to 30 = EF), and 0 where the source has no
class. The uncompressed crop has sha256
`6faf6dac19b55173b36799b1d06ea8cc707d933b5a497fe194577c9c0cebfb88`.

`tools/make_climate_crop.py` made the file, and makes it again from the
same source. It reads the GeoTIFF with its own parser and runs nothing
that came with the data.

## What Sonoran adds

The mapping from a Köppen class to an ITM radio climate is Sonoran's
own judgement, not the authors'. It is in `koppen.py` and in
`docs/PLANNER.md` 4.3.
