#!/usr/bin/env python3
"""Shared prompt-and-encrypt helper for the create_*.py config builders."""

import getpass
import json

from encrypt_partner import encrypt_file


def _ask(prompt, secret=False, default=None):
    """Prompt once; reprompt on empty input unless a default is available."""
    while True:
        #if secret:
        #    value = getpass.getpass(prompt)
        #else:
        value = input(prompt)
        value = value.strip()
        if value:
            return value
        if default is not None:
            return default


def build_and_encrypt(questions, build_json, default_out, help_out):
    """Ask credential questions, then an encryption key and output filename.

    Writes the plaintext JSON to <out>.json and encrypts it to <out> using
    encrypt_partner.encrypt_file. questions is a list of
    (label, secret_bool, default_or_None); build_json maps the answers dict
    to the JSON payload.
    """
    print(help_out)
    answers = {}
    for label, secret, default in questions:
        prompt = label
        if default:
            prompt += f" [{default}]"
        answers[label] = _ask(prompt + ": ", secret=secret, default=default)

    key = _ask("Encryption key: ", secret=True)
    out = _ask(f"Output blob filename [{default_out}]: ", default=default_out)

    plain_path = out + ".json"
    with open(plain_path, "w", encoding="utf-8") as f:
        json.dump(build_json(answers), f, indent=2)
        f.write("\n")
    encrypt_file(plain_path, out, key)
    print(f"Wrote {plain_path} and encrypted blob {out}.")


if __name__ == "__main__":
    print("Shared helper for create_partner.py, create_mypos.py, create_sumup.py.")
