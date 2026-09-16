#!/usr/bin/env python3
"""Decrypt a KassaFu partner blob for local verification.

Usage:
    python3 decrypt.py --key "your-secret" --input partner.xml.enc
"""

import argparse
import json
import sys

from encrypt_partner import PartnerConfigError, decrypt_blob, parse_partner


def main():
    parser = argparse.ArgumentParser(
        description="Decrypt a KassaFu partner blob and print its contents"
    )
    parser.add_argument("--key", required=True, help="Decryption passphrase")
    parser.add_argument("--input", required=True, help="Encrypted blob file")
    args = parser.parse_args()

    try:
        with open(args.input, "rb") as f:
            blob = f.read()
    except OSError as exc:
        print(f"Error reading {args.input}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        plaintext = decrypt_blob(blob, args.key)
    except PartnerConfigError as exc:
        print(f"Decryption failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        print(f"Decrypted content is not valid JSON: {exc}", file=sys.stderr)
        print(plaintext.decode("utf-8", errors="replace"), file=sys.stderr)
        sys.exit(1)

    partner = data.get("partner")
    if isinstance(partner, dict):
        print("Partner credentials:")
        for k, v in partner.items():
            print(f"  {k}: {v}")
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
