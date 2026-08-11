import asyncio
import unittest

from mypos_gateway import MyPOSGatewayError
from mypos_terminal import MyPOSTerminal

CONFIG = {
    "app": {"name": "KassaFu", "mode": "sandbox"},
    "mypos": {
        "gateway_url": "https://demo-api-gateway.mypos.com",
        "integration": {"client_id": "client_integration", "client_secret": "secret_integration"},
        "partner_id": "mps-p-test",
        "application_id": "mps-app-test",
        "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
        "terminal_id": "80026232",
    },
}


class FakeGateway:
    def __init__(self):
        self.terminals_result = {"terminals": [{"terminal_id": "80026232", "serial_number": "N96N960WC15224", "model": "N96"}]}
        self.terminal_result = {"status": "Active", "terminal_name": "Demo Ultra", "model": "N96", "serial_number": "N96N960WC15224", "device_currency": "EUR"}
        self.payment_result = {}
        self.payment_requests = []
        self.cancel_requests = []
        self.create_payment_error = None

    async def get_terminals(self, **kwargs):
        return self.terminals_result

    async def get_terminal(self, terminal_id):
        return self.terminal_result

    async def create_payment(self, payload):
        self.payment_requests.append(payload)
        if self.create_payment_error:
            raise self.create_payment_error
        return {"payment_id": "pay_123", "status": "InProgress"}

    async def get_payment(self, payment_id):
        return self.payment_result

    async def cancel_payment(self, payment_id):
        self.cancel_requests.append(payment_id)
        return {}


def make_terminal():
    t = MyPOSTerminal()
    assert t.init(CONFIG)
    t.gateway = FakeGateway()
    return t


class InitTests(unittest.TestCase):
    def test_init_fails_without_gateway_url(self):
        t = MyPOSTerminal()
        config = {"mypos": {"integration": {"client_id": "x", "client_secret": "y"}}}
        self.assertFalse(t.init(config))

    def test_init_fails_without_merchant_credentials(self):
        t = MyPOSTerminal()
        config = {"mypos": {"gateway_url": "https://demo-api-gateway.mypos.com", "integration": {"client_id": "x", "client_secret": "y"}}}
        self.assertFalse(t.init(config))

    def test_init_ready_with_terminal_id(self):
        t = make_terminal()
        self.assertTrue(t.is_ready)
        self.assertEqual(t.terminal_id, "80026232")

    def test_get_config_excludes_secrets(self):
        t = make_terminal()
        cfg = t.get_config()
        mypos = cfg["mypos"]
        self.assertNotIn("integration", mypos)
        self.assertNotIn("merchant", mypos)
        self.assertEqual(mypos["terminal_id"], "80026232")


class TransactionStatusTests(unittest.TestCase):
    def test_maps_spec_statuses(self):
        cases = [
            ("Success", "SUCCESSFUL"),
            ("Failed", "FAILED"),
            ("Rejected", "FAILED"),
            ("Canceled", "CANCELLED"),
            ("Reversed", "CANCELLED"),
            ("InProgress", "PENDING"),
        ]
        for spec_status, expected in cases:
            t = make_terminal()
            t.gateway.payment_result = {"status": spec_status, "pan": "****6693", "card_qualifier": "VISA"}

            async def scenario():
                return await t.get_transaction_status("pay_1")

            self.assertEqual(asyncio.run(scenario()), expected, msg=spec_status)

    def test_success_sets_card_info(self):
        t = make_terminal()
        t.gateway.payment_result = {"status": "Success", "pan": "****6693", "card_qualifier": "VISA"}

        async def scenario():
            return await t.get_transaction_status("pay_1")

        asyncio.run(scenario())
        self.assertEqual(t.current_card_scheme, "VISA")
        self.assertEqual(t.current_card_last_4, "6693")


if __name__ == "__main__":
    unittest.main()