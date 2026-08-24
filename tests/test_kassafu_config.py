import unittest

from kassafu import _resolve_terminal_type


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


if __name__ == "__main__":
    unittest.main()
