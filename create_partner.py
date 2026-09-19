#!/usr/bin/env python3
"""Create and encrypt the myPOS partner credentials blob (config.partner)."""

from create_config import build_and_encrypt


def _build(answers):
    return {
        "app": {"name": "KassaFu"},
        "partner": {
            "client_id": answers["client_id"],
            "client_secret": answers["client_secret"],
            "application_id": answers["application_id"],
            "partner_id": answers["partner_id"],
        },
    }


def main():
    build_and_encrypt(
        questions=[
            ("provider client_id", False, None),
            ("provider client_secret", True, None),
            ("application_id", False, None),
            ("partner_id", False, None),
        ],
        build_json=_build,
        default_out="config.partner",
        help_out="Create and encrypt the myPOS partner credentials blob.",
    )


if __name__ == "__main__":
    main()