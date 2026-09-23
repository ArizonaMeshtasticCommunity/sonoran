"""Tests for the crypto module."""

import base64

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from sonoran.crypto.decrypt import (
    DecryptionError,
    KeyDecodeError,
    build_nonce,
    decode_key,
    decrypt_packet,
    decrypt_with_key,
)
from sonoran.decode.payloads import mesh_pb2
from sonoran.ingest.pipeline import _valid_data

KEY = base64.b64decode("1PG7OiApB1nwvP+rz05pAQ==")
PACKET_ID = 123456789
FROM_NODE = 2717905876


def _encrypt(plaintext: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(KEY), modes.CTR(build_nonce(PACKET_ID, FROM_NODE)))
    enc = cipher.encryptor()
    return enc.update(plaintext) + enc.finalize()


def test_decode_key_accepts_16_bytes() -> None:
    assert decode_key("1PG7OiApB1nwvP+rz05pAQ==") == KEY


def test_decode_key_accepts_32_bytes() -> None:
    key_b64 = base64.b64encode(b"x" * 32).decode()
    assert decode_key(key_b64) == b"x" * 32


def test_decode_key_rejects_bad_base64() -> None:
    with pytest.raises(KeyDecodeError):
        decode_key("not-valid-base64!!!")


def test_decode_key_rejects_wrong_length() -> None:
    key_b64 = base64.b64encode(b"short").decode()
    with pytest.raises(KeyDecodeError):
        decode_key(key_b64)


def test_nonce_layout() -> None:
    nonce = build_nonce(PACKET_ID, FROM_NODE)
    assert len(nonce) == 16
    assert int.from_bytes(nonce[0:8], "little") == PACKET_ID
    assert int.from_bytes(nonce[8:12], "little") == FROM_NODE
    assert nonce[12:16] == bytes(4)


def test_roundtrip() -> None:
    plaintext = b"\x0a\x05hello meshtastic"
    encrypted = _encrypt(plaintext)
    assert decrypt_with_key(encrypted, PACKET_ID, FROM_NODE, KEY) == plaintext


def test_decrypt_packet_empty_keys() -> None:
    with pytest.raises(DecryptionError):
        decrypt_packet(b"data", PACKET_ID, FROM_NODE, [])


def test_decrypt_packet_returns_first_key_result() -> None:
    plaintext = b"\x0a\x05hello meshtastic"
    encrypted = _encrypt(plaintext)
    result, used_key = decrypt_packet(encrypted, PACKET_ID, FROM_NODE, [KEY])
    assert result == plaintext
    assert used_key == KEY


def test_decrypt_packet_uses_validator_to_select_later_key() -> None:
    """A validator lets AES-CTR select the key that produces valid data.

    This drives the REAL validator, not an oracle (#157).

    It used to pass `validator=lambda value: value == plaintext`, which
    has a 0% false-accept rate by construction — so the multi-key path
    was never exercised against the thing that actually runs, and a
    change that made `_valid_data` less discriminating would pass here.

    The old "plaintext" was `b"\x0a\x05hello meshtastic"`, which is not
    a valid `Data` protobuf at all. The oracle was hiding that too.

    The wrong key produces `e3af8a...` from this ciphertext, which
    `_valid_data` rejects — deterministically, since the key, the nonce
    and the ciphertext are all fixed. This test cannot flake on the
    ~1-in-800 false-accept rate measured in
    `test_wrong_key_discrimination.py`.
    """
    second_key = b"x" * 16
    data = mesh_pb2.Data()
    data.portnum = 1  # TEXT_MESSAGE_APP
    data.payload = b"hello mesh"
    plaintext = bytes(data.SerializeToString())
    cipher = Cipher(
        algorithms.AES(second_key),
        modes.CTR(build_nonce(PACKET_ID, FROM_NODE)),
    )
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(plaintext) + encryptor.finalize()

    result, used_key = decrypt_packet(
        encrypted,
        PACKET_ID,
        FROM_NODE,
        [KEY, second_key],
        validator=_valid_data,
    )

    assert result == plaintext
    assert used_key == second_key
