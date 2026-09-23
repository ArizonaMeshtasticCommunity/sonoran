"""What the real validator does with the output of a wrong key (#157).

`_valid_data` is the only integrity check on a decrypted packet. AES-CTR
has no authentication, so a wrong key produces uniformly random
plaintext, and the validator asks only "does this parse as a non-empty
`Data` protobuf" — which random bytes sometimes do.

Measured in this repo's virtualenv, 48-byte random plaintexts:

    52/40000 = 0.130%
    46/40000 = 0.115%
    43/40000 = 0.107%

So roughly **1 in 800 to 1 in 1,000** foreign packets is accepted by the
wrong key and stored with a fabricated port number, sender and payload,
and the rate scales with the number of keys configured.

`test_crypto.py` exercised the multi-key path with
`validator=lambda value: value == plaintext` — an oracle with a 0%
false-accept rate — so the real validator's discrimination was never
exercised by any test, and a change that made it worse would pass.

These tests do not fix the defect. Whether to accept it, corroborate
against known nodes, or weigh by key is a decision recorded on #157.
What they do is make the rate visible and bound it, so a change that
makes it *worse* is caught. The seed is fixed, so the numbers are the
same on every run and a failure means the validator changed.
"""

import random

from sonoran.decode.payloads import mesh_pb2
from sonoran.ingest.pipeline import _valid_data


def _a_real_data_packet() -> bytes:
    """A genuine `Data`, built rather than written out by hand.

    The old multi-key test used `b"\x0a\x05hello meshtastic"` as its
    "plaintext". That is not a valid `Data` at all — `_valid_data`
    rejects it — which is precisely why that test needed a fake oracle
    and could never have exercised the real validator.
    """
    data = mesh_pb2.Data()
    data.portnum = 1  # TEXT_MESSAGE_APP
    data.payload = b"hello mesh"
    return bytes(data.SerializeToString())


SAMPLES = 40_000
PLAINTEXT_BYTES = 48
# FIXED in #157. The validator now also requires that the known fields
# alone reproduce the input, so random bytes decoding into unknown
# field numbers no longer pass. Re-measured over the same 40,000 draws:
#
#     12 bytes  2.025% -> 0.0025%     810x fewer
#     24 bytes  0.427% -> 0.0000%
#     48 bytes  0.130% -> 0.0025%
#     64 bytes  0.102% -> 0.0025%
#
# The ceiling moves from 1% to 0.1% with it. Leaving it at 1% would
# have kept passing while the rate went back up twenty-fold, which is
# the whole failure mode a ceiling exists to catch.
CEILING = 0.001


def _false_accepts(seed: int) -> int:
    """How many random plaintexts the validator calls a real packet."""
    rng = random.Random(seed)
    return sum(
        1
        for _ in range(SAMPLES)
        if _valid_data(bytes(rng.getrandbits(8) for _ in range(PLAINTEXT_BYTES)))
    )


def test_the_validator_rejects_almost_all_random_bytes() -> None:
    """The bound. Not a fix — a tripwire under one."""
    accepted = _false_accepts(seed=20260923)
    rate = accepted / SAMPLES
    assert rate < CEILING, (
        f"the wrong-key validator accepted {accepted}/{SAMPLES} random "
        f"plaintexts ({rate:.4%}); after #157 it was 0.0025%, so the "
        f"discard-unknown-fields round trip has been weakened or removed"
    )


def test_it_does_reject_most_of_them() -> None:
    """The other direction, and the control.

    A validator that rejected everything would pass the test above while
    throwing away every real packet. This asserts the measurement is of
    a working validator, not a broken one.
    """
    assert _false_accepts(seed=20260923) < SAMPLES // 2


def test_a_real_data_payload_is_still_accepted() -> None:
    """The positive control the rate tests need to mean anything.

    Without it, a validator that rejected everything would satisfy every
    bound above. The first draft of this file used the old test's
    "plaintext" here and failed, which is how the hand-written bytes
    turned out not to be a `Data` at all.
    """
    assert _valid_data(_a_real_data_packet())


def test_empty_bytes_are_not_a_packet() -> None:
    assert not _valid_data(b"")


def test_the_rate_is_stable_across_seeds() -> None:
    """One lucky seed is not a measurement.

    Three independent draws, so the bound is not an artefact of the one
    sequence the first test happens to use.
    """
    for seed in (1, 2, 3):
        rate = _false_accepts(seed) / SAMPLES
        assert rate < CEILING, f"seed {seed} gave {rate:.3%}"


# ------------------------------------------- how long the packet was

# Measured here, 40,000 random plaintexts per length, seed 20260923:
#
#       8 bytes   1.847%      48 bytes   0.152%
#      12 bytes   2.090%      64 bytes   0.115%
#      16 bytes   1.080%      96 bytes   0.105%
#      24 bytes   0.410%     128 bytes   0.110%
#      32 bytes   0.198%     200 bytes   0.010%
#
# The "roughly 1 in 800" in this file's header, and on #157, is the
# 48-to-64 byte figure. It is not a constant: a 12-byte plaintext is
# accepted **eighteen times more often** than a 64-byte one, because
# there is far less room for a byte that fails to parse.
#
# That matters for what #157 decides, because the encrypted traffic
# that is short is not a rare case -- acknowledgements, routing and
# telemetry are the small packets, and a foreign mesh sends mostly
# those. The exposure of a given deployment therefore depends on the
# LENGTH DISTRIBUTION of the packets it cannot read, which is exactly
# what `tools/portnum_zero_census.py` reports.
SHORT_BYTES = 12
LONG_BYTES = 64


def _false_accepts_at(length: int, seed: int) -> int:
    rng = random.Random(seed)
    return sum(
        1 for _ in range(SAMPLES) if _valid_data(bytes(rng.getrandbits(8) for _ in range(length)))
    )


def test_no_plaintext_length_is_a_soft_spot_any_more() -> None:
    """The length dependence was the finding; its absence is the fix.

    Before #157 this asserted that short plaintexts were accepted
    EIGHTEEN TIMES more often than long ones -- 2.025% at 12 bytes
    against 0.102% at 64 -- because a short string has less room for a
    byte that fails to parse. That mattered: acks, routing and
    telemetry are the small packets, so the common case was the weak
    one.

    The discard-unknown-fields round trip removed the gap rather than
    narrowing it. Both ends now sit at or below 1 acceptance in 40,000,
    and asserting an ORDERING between two numbers that small would be
    asserting noise -- on the measured seed they come out 1 and 2.

    So what is checked is the property that has to hold however the
    counts land: no length is a soft spot.
    """
    worst = max(_false_accepts_at(length, seed=20260923) for length in (12, 16, 24, 48, 64))
    assert worst <= SAMPLES // 4000, (
        f"the worst length now accepts {worst}/{SAMPLES} random plaintexts. "
        f"After #157 no length exceeded 1. A length-dependent soft spot has "
        f"come back, which is what made the old rate 18x worse on exactly "
        f"the packets a foreign mesh sends most"
    )


def test_the_short_packet_rate_is_bounded_too() -> None:
    """The tripwire, at the length where it matters most.

    The 1% ceiling above is measured at 48 bytes, where the rate is
    0.15%. At 12 bytes the real rate is 2.09%, so that ceiling would
    not catch a regression here at all.
    """
    rate = _false_accepts_at(SHORT_BYTES, seed=20260923) / SAMPLES
    assert rate < 0.05, (
        f"short-plaintext false accepts are now {rate:.3%}, against 2.09% when #157 was measured"
    )
