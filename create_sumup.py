#!/usr/bin/env python3
"""Create and encrypt a SumUp merchant credentials blob (config.<reader_id>)."""

from create_config import build_and_encrypt


def _build(answers):
    return {
        "app": {"name": "KassaFu"},
        "sumup": {
            "api_key": answers["api_key"],
            "merchant_code": answers["merchant_code"],
        },
    }


def main():
    build_and_encrypt(
        questions=[
            ("api_key", True, None),
            ("merchant_code", False, None),
        ],
        build_json=_build,
        default_out="config.rdr_6P0860A4S186MV3FHM2Q185AD7",
        help_out="Create and encrypt a SumUp merchant credentials blob.",
    )


if __name__ == "__main__":
    main()