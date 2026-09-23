"""Connector and adapter loss, from manufacturers' datasheets (#112).

#112 asks whether "0.1 to 0.5 dB per adapter" is realistic. It is
realistic at the bottom and not at the top: **0.1 dB is the typical
figure a maker publishes across DC to 18 GHz**, and at 915 MHz — the
bottom five per cent of that span — the real loss is below it. 0.5 dB
is five times a good adapter's whole-band typical and does not describe
one.

I recorded this as unsourceable earlier in the session, after the
adapter datasheets I reached either refused automated fetches or quoted
VSWR with no insertion-loss number at all. That was a statement about
the four pages I had tried. Mini-Circuits publishes both, per part:

| part | what it is | insertion loss, DC-18 GHz typ. |
| --- | --- | --- |
| SM-SM50+ | SMA-M to SMA-M | 0.05 dB |
| SF-SF50+ | SMA-F to SMA-F | 0.1 dB |
| SF-SM50+ | SMA-F to SMA-M | 0.1 dB |
| NM-SM50+ | N-M to SMA-M | 0.1 dB |

The figures are flat across the band as published, so using them at
915 MHz is conservative rather than optimistic: SF-SM50+'s own
insertion-loss chart spans 0.00 to 0.10 dB over the whole DC-18 GHz
range, and 915 MHz sits at the left-hand edge of it.

**The mismatch correction, which I had half wrong.** I wrote in
`cables.py` that on cheap adapters the mismatch loss from a poor VSWR
is likely to dominate the insertion loss. That is true of a cheap one
and false of a good one, and the arithmetic says which is which:

    mismatch loss (dB) = -10 log10(1 - |G|^2),  G = (VSWR-1)/(VSWR+1)

    VSWR 1.12  (SM-SM50+, DC-8 GHz)   0.014 dB   -- a quarter of its
                                                    own insertion loss
    VSWR 1.30  (a typical BNC adapter) 0.073 dB
    VSWR 1.50  (a poor one)            0.177 dB   -- three times it

So "the mismatch dominates" needs the VSWR to be about 1.25 or worse.
Both terms are in `total_loss_db` rather than one, because a link
budget that carried only the published insertion loss would be
optimistic on exactly the cheap parts where it matters.

**What this does not cover.** Every figure here is one maker's
stainless-steel part. A hardware-store adapter has no datasheet, and
the honest thing to say about it is that nobody has published what it
does. `UNSPECIFIED` is here for that case: it carries no number, and
anything rendering it has to say so rather than substituting a default.

U.FL pigtails are still absent, for the reason in `cables.py`: Hirose
publishes nothing below 3 GHz for the 1.13 mm cable, and scaling the
3 GHz figure down would be a model rather than a measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Adapter:
    """One adapter, as its maker's datasheet describes it."""

    key: str
    name: str
    maker: str
    # The published typical insertion loss, in dB, and the band it is
    # published across. None where the maker publishes no figure -- see
    # UNSPECIFIED. It is not defaulted to anything.
    insertion_loss_db: float | None
    band_low_mhz: float
    band_high_mhz: float
    # The worst VSWR published for the band containing 915 MHz. None
    # where none is published.
    vswr: float | None
    url: str
    checked: str
    caveat: str = ""


ADAPTERS: tuple[Adapter, ...] = (
    Adapter(
        key="minicircuits-sm-sm50",
        name="SMA-M to SMA-M (Mini-Circuits SM-SM50+)",
        maker="Mini-Circuits",
        insertion_loss_db=0.05,
        band_low_mhz=0.0,
        band_high_mhz=18000.0,
        vswr=1.12,
        url="https://www.minicircuits.com/pdfs/SM-SM50+.pdf",
        checked="2026-09-23",
        caveat="The VSWR is the DC-8 GHz figure, which is the band 915 MHz is in.",
    ),
    Adapter(
        key="minicircuits-sf-sf50",
        name="SMA-F to SMA-F (Mini-Circuits SF-SF50+)",
        maker="Mini-Circuits",
        insertion_loss_db=0.1,
        band_low_mhz=0.0,
        band_high_mhz=18000.0,
        vswr=None,
        url="https://www.minicircuits.com/pdfs/SF-SF50+.pdf",
        checked="2026-09-23",
    ),
    Adapter(
        key="minicircuits-sf-sm50",
        name="SMA-F to SMA-M (Mini-Circuits SF-SM50+)",
        maker="Mini-Circuits",
        insertion_loss_db=0.1,
        band_low_mhz=0.0,
        band_high_mhz=18000.0,
        vswr=None,
        url="https://www.minicircuits.com/pdfs/SF-SM50+.pdf",
        checked="2026-09-23",
        caveat=(
            "Its published insertion-loss chart spans 0.00-0.10 dB over the "
            "whole DC-18 GHz range, so 0.1 dB at 915 MHz is the ceiling."
        ),
    ),
    Adapter(
        key="minicircuits-nm-sm50",
        name="N-M to SMA-M (Mini-Circuits NM-SM50+)",
        maker="Mini-Circuits",
        insertion_loss_db=0.1,
        band_low_mhz=0.0,
        band_high_mhz=18000.0,
        vswr=None,
        url="https://www.minicircuits.com/pdfs/NM-SM50+.pdf",
        checked="2026-09-23",
        caveat="The usual mast adapter: N on the cable, SMA on the board.",
    ),
)

# The adapter in somebody's drawer. It carries no figure on purpose.
#
# A default of 0.1 dB here would be the single most dangerous number in
# this file: it would make an unknown part look measured, and it is the
# unknown parts -- the ones with no datasheet -- whose VSWR is worst.
UNSPECIFIED = Adapter(
    key="unspecified",
    name="An adapter with no datasheet",
    maker="",
    insertion_loss_db=None,
    band_low_mhz=0.0,
    band_high_mhz=0.0,
    vswr=None,
    url="",
    checked="",
    caveat=(
        "No maker publishes figures for this. It is here so a budget can "
        "say an adapter is present without inventing what it costs."
    ),
)

BY_KEY: dict[str, Adapter] = {adapter.key: adapter for adapter in ADAPTERS}


def mismatch_loss_db(vswr: float) -> float:
    """Power lost to reflection at a given VSWR, in dB.

    This is the half of an adapter's cost that a datasheet's insertion
    loss does not include. A VSWR below 1 is not physical and returns
    zero rather than a complex number.
    """
    if vswr <= 1.0:
        return 0.0
    reflection = (vswr - 1.0) / (vswr + 1.0)
    return -10.0 * math.log10(1.0 - reflection**2)


def total_loss_db(adapter: Adapter) -> float | None:
    """Insertion plus mismatch, in dB, or None when nothing is published.

    None is a real answer and not an error: an adapter nobody has
    measured costs an unknown amount, and returning 0.0 would put that
    unknown into a link budget as a certainty.
    """
    if adapter.insertion_loss_db is None:
        return None
    mismatch = mismatch_loss_db(adapter.vswr) if adapter.vswr else 0.0
    return adapter.insertion_loss_db + mismatch
