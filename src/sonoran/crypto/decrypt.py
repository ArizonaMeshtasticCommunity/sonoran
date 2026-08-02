"""Meshtastic packet decryption.

Meshtastic encrypts the Data payload with AES-CTR.
The key is the channel pre-shared key (16 or 32 bytes).
The nonce is 16 bytes: the packet ID as 64-bit little-endian, the sender
node number as 32-bit little-endian, and four zero bytes.
"""

import base64
import binascii
from collections.abc import Callable

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class DecryptionError(Exception):
    """Raised when no key can decrypt the packet."""


class KeyDecodeError(ValueError):
    """Raised when a configured key is not valid base64 of 16 or 32 bytes."""


def decode_key(key_b64: str) -> bytes:
    """Decode one base64 channel key.

    Returns the raw key bytes.
    Raises KeyDecodeError when the key is not 16 or 32 bytes.
    """
    try:
        raw = base64.b64decode(key_b64, validate=True)
    except binascii.Error as exc:
        raise KeyDecodeError(f"key is not valid base64: {exc}") from exc
    if len(raw) not in (16, 32):
        raise KeyDecodeError(f"key must decode to 16 or 32 bytes, got {len(raw)}")
    return raw


def build_nonce(packet_id: int, from_node: int) -> bytes:
    """Build the 16-byte AES-CTR nonce for a packet."""
    return packet_id.to_bytes(8, "little") + from_node.to_bytes(4, "little") + bytes(4)


def decrypt_with_key(encrypted: bytes, packet_id: int, from_node: int, key: bytes) -> bytes:
    """Decrypt one payload with one key.

    AES-CTR does not authenticate. The caller must validate the result
    by parsing it as a Data protobuf.
    """
    cipher = Cipher(algorithms.AES(key), modes.CTR(build_nonce(packet_id, from_node)))
    decryptor = cipher.decryptor()
    return decryptor.update(encrypted) + decryptor.finalize()


def decrypt_packet(
    encrypted: bytes,
    packet_id: int,
    from_node: int,
    keys: list[bytes],
    validator: Callable[[bytes], bool] | None = None,
) -> tuple[bytes, bytes]:
    """Try each key in order and return the first valid (plaintext, key).

    AES-CTR has no authentication. Pass a validator that parses the result
    when more than one key is configured. Without a validator, the first
    key result is returned for compatibility with one-key callers.

    Raises DecryptionError when the key list is empty or no key is valid.
    """
    if not keys:
        raise DecryptionError("no channel keys configured")
    for key in keys:
        plaintext = decrypt_with_key(encrypted, packet_id, from_node, key)
        if validator is None or validator(plaintext):
            return plaintext, key
    raise DecryptionError("no channel key produced a valid payload")
