import json
import os
import tempfile
import unittest

from encrypt_partner import (
    PARTNER_URL_DEFAULT,
    PartnerConfigError,
    decrypt_blob,
    encrypt_file,
    parse_partner,
)

PLAIN = json.dumps({
    "app": {"name": "KassaFu", "mode": "mypos"},
    "partner": {
        "client_id": "client_test",
        "client_secret": "secret_test",
        "application_id": "mps-app-test",
        "partner_id": "mps-p-test",
    },
}).encode("utf-8")


def _make_blob(tmpdir, key="test-key"):
    src = os.path.join(tmpdir, "src.json")
    dst = os.path.join(tmpdir, "dst.blob")
    with open(src, "wb") as f:
        f.write(PLAIN)
    encrypt_file(src, dst, key)
    with open(dst, "rb") as f:
        return f.read()


class EncryptDecryptTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = _make_blob(tmpdir)
            self.assertEqual(decrypt_blob(blob, "test-key"), PLAIN)

    def test_wrong_key_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = _make_blob(tmpdir)
            with self.assertRaises(PartnerConfigError):
                decrypt_blob(blob, "wrong-key")

    def test_corrupted_blob_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = bytearray(_make_blob(tmpdir))
            blob[-1] ^= 0xFF
            with self.assertRaises(PartnerConfigError):
                decrypt_blob(bytes(blob), "test-key")

    def test_unknown_version_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = bytearray(_make_blob(tmpdir))
            blob[12] = 0x63
            with self.assertRaises(PartnerConfigError):
                decrypt_blob(bytes(blob), "test-key")

    def test_bad_magic_raises(self):
        blob = b"NOTKASSAFU_BLOB" + b"\x00" * 64
        with self.assertRaises(PartnerConfigError):
            decrypt_blob(blob, "test-key")

    def test_default_url(self):
        self.assertEqual(
            PARTNER_URL_DEFAULT,
            "http://www.kassaku.nl/restaurants/install/config.partner",
        )


class ParsePartnerTests(unittest.TestCase):
    def test_returns_partner_dict(self):
        self.assertEqual(parse_partner(PLAIN)["client_id"], "client_test")

    def test_rejects_bad_json(self):
        with self.assertRaises(PartnerConfigError):
            parse_partner(b"{not json")

    def test_rejects_missing_partner(self):
        with self.assertRaises(PartnerConfigError):
            parse_partner(b'{"app": {"name": "KassaFu"}}')

    def test_rejects_non_dict_top_level(self):
        with self.assertRaises(PartnerConfigError):
            parse_partner(b"[1,2,3]")

    def test_rejects_invalid_utf8(self):
        with self.assertRaises(PartnerConfigError):
            parse_partner(b"\xff\xfe")


if __name__ == "__main__":
    unittest.main()