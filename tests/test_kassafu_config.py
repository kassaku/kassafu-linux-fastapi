import unittest

import kassafu
from kassafu import _apply_runtime_config, _resolve_terminal_type
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


if __name__ == "__main__":
    unittest.main()
