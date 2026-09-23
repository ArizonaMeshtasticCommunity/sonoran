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
# Measured at 0.107%-0.130% today. A ceiling of 1% is far enough above
# that to never flake, and far enough below a broken validator to catch
# one: accepting "anything non-empty" would be ~100%.
CEILING = 0.01


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
        f"plaintexts ({rate:.3%}); it was 0.107%-0.130% when #157 was "
        f"filed, so something has made it much less discriminating"
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
