import unittest
from copy import deepcopy
from unittest import mock

import kassafu
from encrypt_partner import PARTNER_URL_DEFAULT, PartnerConfigError
from kassafu import _apply_runtime_config, _merge_partner, _resolve_terminal_type
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


MYPOS_CONFIG_NO_PARTNER = {
    "mypos": {
        "gateway_url": "https://demo-api-gateway.mypos.com",
        "partner_url": "http://example.test/partner.xml",
        "partner_key": "test-key",
        "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
        "terminal_id": "80026232",
    }
}

FAKE_PARTNER = {
    "client_id": "ci",
    "client_secret": "cs",
    "application_id": "app",
    "partner_id": "pi",
}


class MergePartnerTests(unittest.TestCase):
    def setUp(self):
        self._saved_key = kassafu.KASSAFU_PARTNER_KEY
        kassafu.KASSAFU_PARTNER_KEY = None

    def tearDown(self):
        kassafu.KASSAFU_PARTNER_KEY = self._saved_key

    def test_non_mypos_returns_same_object(self):
        cfg = SUMUP_CONFIG
        self.assertIs(_merge_partner(cfg), cfg)

    def test_injects_fetched_partner(self):
        cfg = deepcopy(MYPOS_CONFIG_NO_PARTNER)
        with mock.patch("kassafu.fetch_partner", return_value=FAKE_PARTNER) as fetch:
            merged = _merge_partner(cfg)
        fetch.assert_called_once_with(
            "http://example.test/partner.xml", "test-key", "partner.xml.enc"
        )
        self.assertEqual(merged["mypos"]["partner"], FAKE_PARTNER)
        self.assertNotIn("partner", cfg["mypos"])

    def test_default_url_used_when_absent(self):
        cfg = deepcopy(MYPOS_CONFIG_NO_PARTNER)
        del cfg["mypos"]["partner_url"]
        with mock.patch("kassafu.fetch_partner", return_value=FAKE_PARTNER) as fetch:
            _merge_partner(cfg)
        self.assertEqual(fetch.call_args[0][0], PARTNER_URL_DEFAULT)

    def test_cli_key_fallback(self):
        kassafu.KASSAFU_PARTNER_KEY = "cli-key"
        cfg = deepcopy(MYPOS_CONFIG_NO_PARTNER)
        del cfg["mypos"]["partner_key"]
        with mock.patch("kassafu.fetch_partner", return_value=FAKE_PARTNER) as fetch:
            _merge_partner(cfg)
        self.assertEqual(fetch.call_args[0][1], "cli-key")

    def test_missing_key_raises(self):
        cfg = deepcopy(MYPOS_CONFIG_NO_PARTNER)
        del cfg["mypos"]["partner_key"]
        with self.assertRaises(PartnerConfigError):
            _merge_partner(cfg)

    def test_non_dict_returns_same_object(self):
        self.assertIs(_merge_partner("nope"), "nope")


if __name__ == "__main__":
    unittest.main()
