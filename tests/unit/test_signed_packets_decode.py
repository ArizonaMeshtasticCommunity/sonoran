"""A signed packet is a real packet (#252).

From 2026-09-23 22:43 UTC, packets from nodes on newer firmware were
decrypted correctly and then discarded as undecryptable. The cause was two
facts meeting:

- `_valid_data` requires the known fields of a decrypted `Data` to
  re-serialise to the exact input, because AES-CTR does not authenticate
  and that is the only guard against a wrong key producing a plausible
  message (it cut random false accepts about 800-fold);
- upstream `Data` gained field 10, `bytes xeddsa_signature`, and firmware
  that signs packets sends it. The vendored schema, from 2026-08-02, knew
  fields 1 to 9.

So every signed packet failed the round trip, no key "validated" it, and
it was stored as `no_key` with a port of 0. Measured in production:
2,995 packets from 49 senders in three days, including all of NGSP's
telemetry. Decrypted with the production keys, NGSP's rejected packets
opened cleanly with the MediumFast key and carried wire fields 1, 2, 9
and 10.

The protobufs are now generated from meshtastic/protobufs v2.8.0.
"""

import os

from sonoran.ingest.pipeline import _valid_data
from sonoran.meshtastic import mesh_pb2, portnums_pb2


def _signed(payload: bytes = b"\x0d\x00\x00\x80\x3f" * 5) -> bytes:
    data = mesh_pb2.Data()
    data.portnum = portnums_pb2.PortNum.TELEMETRY_APP
    data.payload = payload
    data.bitfield = 1
    # XEdDSA signatures are 64 bytes. The content does not matter to the
    # validator, only that the field is one the schema describes.
    data.xeddsa_signature = os.urandom(64)
    return data.SerializeToString()


def test_the_schema_knows_the_signature_field() -> None:
    """The canary. If the vendored schema is ever regenerated from an older
    source, this fails before a single real packet is lost."""
    fields = mesh_pb2.Data.DESCRIPTOR.fields_by_number
    assert 10 in fields, "Data has no field 10; signed packets will be discarded"
    assert fields[10].name == "xeddsa_signature", fields[10].name


def test_a_signed_packet_is_valid_data() -> None:
    """The exact failure: a correctly decrypted, signed Data was rejected."""
    assert _valid_data(_signed()), "a genuine signed packet is treated as a wrong key"


def test_an_unsigned_packet_is_still_valid() -> None:
    data = mesh_pb2.Data()
    data.portnum = portnums_pb2.PortNum.TELEMETRY_APP
    data.payload = b"\x0d\x00\x00\x80\x3f"
    assert _valid_data(data.SerializeToString())


def test_the_guard_against_a_wrong_key_still_holds() -> None:
    """Knowing field 10 must not reopen the door the round trip closed.

    A wrong key gives random bytes, which decode into field numbers the
    schema does not have. A field number far past anything Data defines must
    still fail, or the 800-fold improvement is gone.
    """
    genuine = _signed()
    # Append field 29, wire type 0, value 1: a field no Data has.
    forged = genuine + bytes([(29 << 3) | 0, 1])
    assert not _valid_data(forged), "an unknown field no longer fails the round trip"
