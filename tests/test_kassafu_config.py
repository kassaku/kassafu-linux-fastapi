import unittest
from unittest import mock

import kassafu
from encrypt_partner import PARTNER_URL_DEFAULT, PartnerConfigError
from kassafu import _apply_runtime_config, _resolve_remote_config, _resolve_terminal_type
from mypos_terminal import MyPOSTerminal
from sumup_terminal import SumUpTerminal

SUMUP_CONFIG = {
    "sumup": {
        "api_key": "sup_sk_test",
        "merchant_code": "M1234567",
        "reader_id": "rdr_test123",
    }
}

MYPOS_CONFIG = {
    "mypos": {
        "gateway_url": "https://demo-api-gateway.mypos.com",
        "partner": {
            "client_id": "ci",
            "client_secret": "cs",
            "application_id": "mps-app-test",
            "partner_id": "mps-p-test",
        },
        "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
        "terminal_id": "80026232",
    }
}


class ResolveTerminalTypeTests(unittest.TestCase):
    def test_explicit_terminal_type_wins_over_sections(self):
        config = {"app": {"terminal_type": "mypos"}, "sumup": {"api_key": "k"}}
        self.assertEqual(_resolve_terminal_type(config), "mypos")

    def test_explicit_terminal_type_is_case_insensitive(self):
        config = {"app": {"terminal_type": "MyPOS"}, "sumup": {"api_key": "k"}}
        self.assertEqual(_resolve_terminal_type(config), "mypos")

    def test_explicit_unknown_terminal_type_falls_back_to_sumup(self):
        config = {"app": {"terminal_type": "sandbox"}}
        self.assertEqual(_resolve_terminal_type(config), "sumup")

    def test_mypos_only_section_detected(self):
        config = {"mypos": {"gateway_url": "https://demo-api-gateway.mypos.com"}}
        self.assertEqual(_resolve_terminal_type(config), "mypos")

    def test_sumup_only_section_detected(self):
        config = {"sumup": {"api_key": "k"}}
        self.assertEqual(_resolve_terminal_type(config), "sumup")

    def test_both_sections_default_to_sumup(self):
        config = {
            "sumup": {"api_key": "k"},
            "mypos": {"gateway_url": "https://demo-api-gateway.mypos.com"},
        }
        self.assertEqual(_resolve_terminal_type(config), "sumup")

    def test_no_sections_defaults_to_sumup(self):
        self.assertEqual(_resolve_terminal_type({}), "sumup")


class ApplyRuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = (kassafu.config, kassafu.terminal, kassafu.TERMINAL_TYPE)
        kassafu.config = {}
        kassafu.terminal = None
        kassafu.TERMINAL_TYPE = None

    def tearDown(self):
        kassafu.config, kassafu.terminal, kassafu.TERMINAL_TYPE = self._saved

    def test_apply_on_empty_state_creates_sumup_terminal(self):
        ok, detail = _apply_runtime_config(SUMUP_CONFIG)
        self.assertTrue(ok)
        self.assertEqual(detail, "sumup")
        self.assertIsInstance(kassafu.terminal, SumUpTerminal)
        self.assertEqual(kassafu.TERMINAL_TYPE, "sumup")
        self.assertEqual(kassafu.config, SUMUP_CONFIG)

    def test_apply_mypos_config_creates_mypos_terminal(self):
        ok, detail = _apply_runtime_config(MYPOS_CONFIG)
        self.assertTrue(ok)
        self.assertEqual(detail, "mypos")
        self.assertIsInstance(kassafu.terminal, MyPOSTerminal)
        self.assertEqual(kassafu.TERMINAL_TYPE, "mypos")

    def test_live_swap_from_sumup_to_mypos(self):
        _apply_runtime_config(SUMUP_CONFIG)
        ok, detail = _apply_runtime_config(MYPOS_CONFIG)
        self.assertTrue(ok)
        self.assertEqual(detail, "mypos")
        self.assertIsInstance(kassafu.terminal, MyPOSTerminal)

        ok, detail = _apply_runtime_config(SUMUP_CONFIG)
        self.assertTrue(ok)
        self.assertEqual(detail, "sumup")
        self.assertIsInstance(kassafu.terminal, SumUpTerminal)

    def test_invalid_config_keeps_previous_terminal(self):
        _apply_runtime_config(SUMUP_CONFIG)
        previous = kassafu.terminal

        broken = {
            "mypos": {
                k: v for k, v in MYPOS_CONFIG["mypos"].items() if k != "partner"
            }
        }
        ok, detail = _apply_runtime_config(broken)
        self.assertFalse(ok)
        self.assertIn("Failed to initialize", detail)
        self.assertIs(kassafu.terminal, previous)
        self.assertEqual(kassafu.TERMINAL_TYPE, "sumup")
        self.assertEqual(kassafu.config, SUMUP_CONFIG)

    def test_non_dict_config_rejected(self):
        ok, detail = _apply_runtime_config("nope")
        self.assertFalse(ok)
        self.assertIn("JSON object", detail)


CLIENT_SUMUP = {"sumup": {"api_key": "sup_sk_test", "merchant_code": "M1234567"}}
CLIENT_MYPOS = {"mypos": {"gateway_url": "https://demo-api-gateway.mypos.com",
                          "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"}}}
PARTNER_OBJ = {"client_id": "ci", "client_secret": "cs",
               "application_id": "mps-app-test", "partner_id": "mps-p-test"}


class RemoteResolveTests(unittest.TestCase):
    def test_sumup_client_resolves_with_id(self):
        interface = {"client_url": "http://c/sumup.blob", "client_key": "k",
                     "id": "rdr_123"}
        with mock.patch("kassafu._fetch_blob_json", return_value=CLIENT_SUMUP) as fetch:
            resolved = _resolve_remote_config(interface)
        fetch.assert_called_once_with("http://c/sumup.blob", "k", "client")
        self.assertEqual(resolved["sumup"]["reader_id"], "rdr_123")
        self.assertNotIn("partner", resolved)

    def test_sumup_does_not_fetch_partner(self):
        interface = {"client_url": "http://c/s.blob", "client_key": "k", "id": "r"}
        with mock.patch("kassafu._fetch_blob_json", return_value=CLIENT_SUMUP) as fetch:
            _resolve_remote_config(interface)
        self.assertEqual(fetch.call_count, 1)

    def test_mypos_resolves_and_injects_partner(self):
        def fake_fetch(url, key, what):
            return CLIENT_MYPOS if what == "client" else {"partner": PARTNER_OBJ}

        interface = {"partner_url": "http://p/partner.blob", "partner_key": "pk",
                     "client_url": "http://c/m.blob", "client_key": "ck", "id": "80581413"}
        with mock.patch("kassafu._fetch_blob_json", side_effect=fake_fetch) as fetch:
            resolved = _resolve_remote_config(interface)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(resolved["mypos"]["terminal_id"], "80581413")
        self.assertEqual(resolved["mypos"]["partner"], PARTNER_OBJ)

    def test_mypos_uses_default_partner_url_when_absent(self):
        def fake_fetch(url, key, what):
            return CLIENT_MYPOS if what == "client" else {"partner": PARTNER_OBJ}

        interface = {"partner_key": "pk", "client_url": "http://c/m.blob",
                     "client_key": "ck", "id": "80581413"}
        with mock.patch("kassafu._fetch_blob_json", side_effect=fake_fetch) as fetch:
            _resolve_remote_config(interface)
        self.assertEqual(fetch.call_args_list[1][0][0], PARTNER_URL_DEFAULT)

    def test_missing_client_url_raises(self):
        with self.assertRaises(PartnerConfigError):
            _resolve_remote_config({"client_key": "k", "id": "1"})

    def test_missing_client_key_raises(self):
        with self.assertRaises(PartnerConfigError):
            _resolve_remote_config({"client_url": "http://c/b", "id": "1"})

    def test_missing_id_raises(self):
        with self.assertRaises(PartnerConfigError):
            _resolve_remote_config({"client_url": "http://c/b", "client_key": "k"})

    def test_mypos_missing_partner_key_raises(self):
        interface = {"client_url": "http://c/m.blob", "client_key": "ck", "id": "1"}
        with mock.patch("kassafu._fetch_blob_json", return_value=CLIENT_MYPOS):
            with self.assertRaises(PartnerConfigError):
                _resolve_remote_config(interface)

    def test_client_missing_both_sections_raises(self):
        interface = {"client_url": "http://c/b", "client_key": "k", "id": "1"}
        with mock.patch("kassafu._fetch_blob_json", return_value={"app": {"name": "KassaFu"}}):
            with self.assertRaises(PartnerConfigError):
                _resolve_remote_config(interface)

    def test_client_missing_required_keys_raises(self):
        interface = {"client_url": "http://c/b", "client_key": "k", "id": "1"}
        with mock.patch("kassafu._fetch_blob_json", return_value={"sumup": {"api_key": "only"}}):
            with self.assertRaises(PartnerConfigError):
                _resolve_remote_config(interface)

    def test_partner_object_missing_fields_raises(self):
        interface = {"partner_key": "pk", "client_url": "http://c/m.blob",
                     "client_key": "ck", "id": "1"}
        with mock.patch(
            "kassafu._fetch_blob_json",
            side_effect=lambda url, key, what: (
                CLIENT_MYPOS if what == "client" else {"partner": {"client_id": "only"}}
            ),
        ):
            with self.assertRaises(PartnerConfigError):
                _resolve_remote_config(interface)


if __name__ == "__main__":
    unittest.main()
