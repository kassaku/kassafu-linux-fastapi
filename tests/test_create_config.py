import json
import os
import tempfile
import unittest
from unittest import mock

from create_config import _ask, build_and_encrypt
from encrypt_partner import decrypt_blob


class _Prompt:
    """Patch getpass/input to drain answers from a shared iterable."""

    def __init__(self, seq):
        self.seq = seq

    def __enter__(self):
        self._getpass = mock.patch(
            "getpass.getpass", side_effect=lambda *a: next(self.seq)
        )
        self._input = mock.patch(
            "builtins.input", side_effect=lambda *a: next(self.seq)
        )
        self._getpass.start()
        self._input.start()
        return self

    def __exit__(self, *exc):
        self._input.stop()
        self._getpass.stop()
        return False


class AskTests(unittest.TestCase):
    def test_returns_typed_value(self):
        with mock.patch("builtins.input", return_value="typed"):
            self.assertEqual(_ask("x: "), "typed")

    def test_uses_default_on_empty(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertEqual(_ask("x: ", default="dflt"), "dflt")

    def test_required_nonempty_reprompts(self):
        seq = iter(["", "value"])
        with _Prompt(seq):
            self.assertEqual(_ask("x: "), "value")


class BuildAndEncryptTests(unittest.TestCase):
    def test_writes_plaintext_json_and_encrypted_blob(self):
        seq = iter([
            "client_id_v", "client_secret_v", "app_v", "partner_v",
            "key_v", "config.test",
        ])
        with _Prompt(seq):
            with tempfile.TemporaryDirectory() as tmpdir:
                cwd = os.getcwd()
                os.chdir(tmpdir)
                try:
                    build_and_encrypt(
                        questions=[
                            ("client_id", False, None),
                            ("client_secret", True, None),
                            ("application_id", False, None),
                            ("partner_id", False, None),
                        ],
                        build_json=lambda a: {
                            "app": {"name": "KassaFu"},
                            "partner": {
                                "client_id": a["client_id"],
                                "client_secret": a["client_secret"],
                                "application_id": a["application_id"],
                                "partner_id": a["partner_id"],
                            },
                        },
                        default_out="config.x",
                        help_out="test",
                    )
                finally:
                    os.chdir(cwd)

                with open(os.path.join(tmpdir, "config.test.json"), encoding="utf-8") as f:
                    plain = json.load(f)
                self.assertEqual(plain["partner"], {
                    "client_id": "client_id_v",
                    "client_secret": "client_secret_v",
                    "application_id": "app_v",
                    "partner_id": "partner_v",
                })

                with open(os.path.join(tmpdir, "config.test"), "rb") as f:
                    blob = f.read()
                decrypted = json.loads(decrypt_blob(blob, "key_v").decode("utf-8"))
                self.assertEqual(decrypted["partner"]["client_id"], "client_id_v")


from create_partner import _build as build_partner
from create_mypos import _build as build_mypos
from create_sumup import _build as build_sumup


class ScriptTemplateTests(unittest.TestCase):
    def test_partner_template(self):
        self.assertEqual(build_partner({
            "client_id": "c",
            "client_secret": "s",
            "application_id": "a",
            "partner_id": "p",
        }), {
            "app": {"name": "KassaFu"},
            "partner": {
                "client_id": "c",
                "client_secret": "s",
                "application_id": "a",
                "partner_id": "p",
            },
        })

    def test_mypos_template(self):
        self.assertEqual(build_mypos({
            "gateway_url": "https://api-gateway.mypos.com",
            "client_id": "c",
            "client_secret": "s",
        }), {
            "app": {"name": "KassaFu"},
            "mypos": {
                "gateway_url": "https://api-gateway.mypos.com",
                "merchant": {"client_id": "c", "client_secret": "s"},
            },
        })

    def test_sumup_template(self):
        self.assertEqual(build_sumup({"api_key": "k", "merchant_code": "m"}), {
            "app": {"name": "KassaFu"},
            "sumup": {"api_key": "k", "merchant_code": "m"},
        })


if __name__ == "__main__":
    unittest.main()