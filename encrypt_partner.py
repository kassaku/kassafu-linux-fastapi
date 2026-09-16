#!/usr/bin/env python3
"""Encrypt/decrypt the myPOS partner credentials for remote hosting.

CLI (hand-encryption tool):

    python3 encrypt_partner.py --key "//B1a9r6t8//" --input partner.json --output partner.xml.enc

Also the importable crypto library kassafu uses at runtime (decrypt_blob + parse_partner).
"""

import argparse
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PARTNER_URL_DEFAULT = "http://www.kassaku.nl/restaurants/install/config.partner"

BLOB_MAGIC = b"KASSAFU_BLOB"
BLOB_VERSION = 1
PBKDF2_ITERATIONS = 200_000
KEY_LENGTH = 32
SALT_LENGTH = 16
NONCE_LENGTH = 12
TAG_LENGTH = 16


class PartnerConfigError(Exception):
    """Raised when the partner blob cannot be fetched, decrypted, or parsed."""


def _derive_key(key: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(key.encode("utf-8"))


def encrypt_file(input_path: str, output_path: str, key: str) -> None:
    """Read a plaintext file and write the versioned encrypted blob."""
    with open(input_path, "rb") as f:
        plaintext = f.read()

    salt = os.urandom(SALT_LENGTH)
    nonce = os.urandom(NONCE_LENGTH)
    key_bytes = _derive_key(key, salt)
    ciphertext = AESGCM(key_bytes).encrypt(nonce, plaintext, None)

    header = (
        BLOB_MAGIC
        + bytes([BLOB_VERSION])
        + salt
        + PBKDF2_ITERATIONS.to_bytes(4, "big")
        + nonce
    )
    with open(output_path, "wb") as f:
        f.write(header + ciphertext)


def decrypt_blob(blob: bytes, key: str) -> bytes:
    """Decrypt a versioned blob, raising PartnerConfigError on failure."""
    magic_len = len(BLOB_MAGIC)
    header_len = magic_len + 1 + SALT_LENGTH + 4 + NONCE_LENGTH
    if len(blob) < header_len + TAG_LENGTH:
        raise PartnerConfigError("Blob too short to be a valid KassaFu blob")

    if blob[:magic_len] != BLOB_MAGIC:
        raise PartnerConfigError("Bad blob magic: not a KassaFu blob")

    version = blob[magic_len]
    if version != BLOB_VERSION:
        raise PartnerConfigError(f"Unsupported blob version {version}")

    pos = magic_len + 1
    salt = blob[pos:pos + SALT_LENGTH]
    pos += SALT_LENGTH
    iterations = int.from_bytes(blob[pos:pos + 4], "big")
    if iterations > PBKDF2_ITERATIONS * 10:
        raise PartnerConfigError("Blob has unreasonable PBKDF2 iteration count")
    pos += 4
    nonce = blob[pos:pos + NONCE_LENGTH]
    pos += NONCE_LENGTH

    key_bytes = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=iterations,
    ).derive(key.encode("utf-8"))

    try:
        return AESGCM(key_bytes).decrypt(nonce, blob[pos:], None)
    except Exception as exc:
        raise PartnerConfigError(f"Decryption failed (wrong key or corrupted blob): {exc}")


def parse_partner(plaintext: bytes) -> dict:
    """Parse the decrypted JSON and return the partner dict."""
    try:
        data = json.loads(plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PartnerConfigError(f"Partner payload is not valid JSON: {exc}")

    if not isinstance(data, dict):
        raise PartnerConfigError("Partner payload is not a JSON object")

    partner = data.get("partner")
    if not isinstance(partner, dict):
        raise PartnerConfigError("Partner payload missing 'partner' object")
    return partner


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt the myPOS partner credentials file into a KassaFu blob"
    )
    parser.add_argument("--key", required=True, help="Encryption passphrase")
    parser.add_argument("--input", required=True, help="Plaintext JSON file")
    parser.add_argument("--output", required=True, help="Encrypted blob output file")
    args = parser.parse_args()

    encrypt_file(args.input, args.output, args.key)
    print(f"Encrypted {args.input} -> {args.output}")


if __name__ == "__main__":
    main()