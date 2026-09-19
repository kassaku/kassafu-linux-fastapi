#!/usr/bin/env python3
"""Create and encrypt a myPOS merchant credentials blob (config.<terminal_id>)."""

from create_config import build_and_encrypt


def _build(answers):
    return {
        "app": {"name": "KassaFu"},
        "mypos": {
            "gateway_url": answers["gateway_url"],
            "merchant": {
                "client_id": answers["client_id"],
                "client_secret": answers["client_secret"],
            },
        },
    }


def main():
    build_and_encrypt(
        questions=[
            ("gateway_url", False, "https://api-gateway.mypos.com"),
            ("merchant client_id", False, None),
            ("merchant client_secret", True, None),
        ],
        build_json=_build,
        default_out="config.80581413",
        help_out="Create and encrypt a myPOS merchant credentials blob.",
    )


if __name__ == "__main__":
    main()