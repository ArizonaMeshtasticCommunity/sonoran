"""Why a stored packet's payload could not be read (#157).

`portnum = 0` is the sentinel this pipeline writes when it cannot read
a packet, and **0 is also a real Meshtastic port number**, `UNKNOWN_APP`.
Nothing else was stored to tell them apart, so a single row with
`portnum = 0` was any of four different events, and the traffic chart,
`/api/stats`, `/api/nodes` and the map all called every one of them
`UNKNOWN_APP`.

The census in `sonoran.ingest.census`, run against production over a
168 h window, measured the mix:

    pki_to_one_recipient   8342   91.7%
    opaque_no_key_opened    743    8.2%
    decoded_with_payload      7    0.1%
    decoded_empty_payload     1    0.0%

So that bucket was about 99.9% mislabelled. An operator reading it
concluded the mesh was full of unknown application traffic; it is full
of direct messages nobody running this instance could ever read.

This module holds the vocabulary for the answer. The value is recorded
at ingest, where it is **known rather than inferred** -- the pipeline
has three separate paths and each one corresponds to exactly one state,
so nothing here guesses from the shape of a row.

Not a boolean, and not named like one. The plan for this change called
the column `payload_readable`, which would have put a three-valued
answer behind a two-valued name -- the same class of mistake as the
label it exists to fix, and the same one #149 made when it called an
unmeasured link a weak one.
"""

from __future__ import annotations

from enum import StrEnum


class PayloadState(StrEnum):
    """What happened when ingest tried to read a packet's payload.

    Stored as text rather than an integer. These values are read by
    people -- in `psql`, in a chart's legend -- and a row that says
    `pki` explains itself where a row that says `2` needs this file.
    """

    #: A channel key opened it and the `Data` inside parsed. The port
    #: number on the row is the port the packet really carried, so a
    #: `portnum` of 0 here is a genuine `UNKNOWN_APP`.
    READABLE = "readable"

    #: Encrypted on a channel this instance holds no key for. The port
    #: number sits inside the encrypted part and is not recoverable, so
    #: the row's `portnum` of 0 means "not known", not `UNKNOWN_APP`.
    NO_KEY = "no_key"

    #: Encrypted to one recipient with their public key. No channel key
    #: could ever open it and only the recipient could -- so unlike
    #: `NO_KEY`, this is not a configuration gap that adding a key would
    #: close. It is the single largest group.
    PKI = "pki"


#: Rows written before this was recorded carry NULL, and NULL is not a
#: fourth state -- it means nobody asked the question at the time.
#:
#: There is deliberately no backfill. The answer for an old row lives
#: in `raw_bytes` and needs a decryption attempt per row against the
#: current key list, which is `tools/portnum_zero_census.py`, not a
#: migration: it is slow, it needs keys a migration does not have, and
#: it would write today's key configuration onto packets ingested under
#: a different one. Anything reading this column must treat NULL as
#: unknown and say so, rather than folding it into the commonest value.
UNRECORDED = None
