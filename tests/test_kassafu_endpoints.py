import asyncio
import os
import tempfile
import unittest

import kassafu
from kassafu import bridge

SUMUP_CONFIG = {
    "sumup": {
        "api_key": "sup_sk_test",
        "merchant_code": "M1234567",
        "reader_id": "rdr_test123",
    }
}


def _reset_state():
    kassafu.config = {}
    kassafu.terminal = None
    kassafu.TERMINAL_TYPE = "sumup"
    kassafu.active_payment = False
    kassafu.payment_queue = bridge.call_in_loop(asyncio.Queue)


class FakeTerminal:
    """Async terminal stand-in so routes are exercised without live I/O."""

    def __init__(self):
        self.is_ready = True
        self.reader_id = "rdr_test123"
        self.current_order_id = None
        self.current_transaction_id = None
        self.current_amount_cents = None
        self.current_currency = None
        self.current_status = None
        self.current_card_scheme = None
        self.current_card_last_4 = None

    async def process_payment(self, order_id, amount_cents, currency="EUR"):
        return {"success": True, "status": "pending", "order_id": order_id, "error_code": 0}

    async def cancel_payment(self, order_id):
        return {"success": True}

    async def clear_display(self):
        pass

    async def check_status(self):
        return {"status": "online", "reader_id": self.reader_id, "error_code": 0}

    async def get_transaction_status(self, transaction_id):
        return "PENDING"

    def get_config(self):
        return {
            "app": {"mode": "test"},
            "sumup": {"merchant_code": "M1234567", "reader_id": self.reader_id},
        }


class PayEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_missing_required_field_returns_400(self):
        r = self.client.post("/pay", json={"order_id": "O1"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["detail"], "Missing field: amount_cents")

    def test_terminal_not_ready_returns_503(self):
        r = self.client.post(
            "/pay", json={"order_id": "O1", "amount_cents": 100, "currency": "EUR"}
        )
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["detail"], "Terminal not ready")

    def test_pay_success(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.post(
            "/pay", json={"order_id": "O1", "amount_cents": 100, "currency": "EUR"}
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["order_id"], "O1")

    def test_pay_queued_when_active_payment(self):
        kassafu.terminal = FakeTerminal()
        kassafu.active_payment = True
        r = self.client.post(
            "/pay", json={"order_id": "O1", "amount_cents": 100, "currency": "EUR"}
        )
        self.assertEqual(r.status_code, 202)
        body = r.get_json()
        self.assertEqual(body["success"], False)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["error_code"], 108012)


class PaymentStatusEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_no_terminal_returns_503(self):
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["error_code"], 108008)

    def test_idle_when_no_active_payment(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "idle")
        self.assertEqual(body["error_code"], 0)

    def test_completed_payment(self):
        term = FakeTerminal()
        term.current_order_id = "O1"
        term.current_status = "paid"
        term.current_amount_cents = 100
        term.current_currency = "EUR"
        term.current_card_scheme = "visa"
        term.current_card_last_4 = "1234"
        kassafu.terminal = term
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "paid")
        self.assertEqual(body["order_id"], "O1")
        self.assertEqual(body["error_code"], 0)

    def test_not_found_order(self):
        term = FakeTerminal()
        term.current_order_id = "O2"
        kassafu.terminal = term
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "not_found")
        self.assertEqual(body["error_code"], 108002)


class CancelEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_delete_cancel_success(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.delete("/payment/cancel?order_id=O1")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])

    def test_get_cancel_also_works(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.get("/payment/cancel?order_id=O1")
        self.assertEqual(r.status_code, 200)

    def test_missing_order_id_returns_400(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.delete("/payment/cancel")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["detail"], "Missing order_id query parameter")


class ConfigEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_get_config_without_terminal(self):
        r = self.client.get("/config")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["app"]["mode"], "sumup")

    def test_post_config_applies_sumup_config(self):
        r = self.client.post("/config", json=SUMUP_CONFIG)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["terminal_type"], "sumup")
        self.assertIsNotNone(kassafu.terminal)

    def test_post_config_rejected_during_active_payment(self):
        kassafu.active_payment = True
        r = self.client.post("/config", json=SUMUP_CONFIG)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error_code"], 108012)

    def test_post_config_non_dict_returns_400(self):
        r = self.client.post("/config", json="nope")
        self.assertEqual(r.status_code, 400)
        self.assertIn("JSON object", r.get_json()["detail"])


class HealthAndMiscEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_health_unconfigured(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "unconfigured")
        self.assertFalse(body["terminal_ready"])
        self.assertIsNone(body["mode"])

    def test_reader_status_no_terminal(self):
        r = self.client.get("/reader/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["error_code"], 108010)

    def test_reader_status_online(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.get("/reader/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "online")

    def test_payment_history_reads_log(self):
        kassafu.terminal = FakeTerminal()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write('{"order_id": "O1"}\n{"order_id": "O2"}\n')
            log_path = f.name
        try:
            original = kassafu.TRANSACTION_LOG
            kassafu.TRANSACTION_LOG = log_path
            try:
                r = self.client.get("/payment/history?limit=10")
                self.assertEqual(r.status_code, 200)
                items = r.get_json()["items"]
                self.assertEqual([i["order_id"] for i in items], ["O2", "O1"])
            finally:
                kassafu.TRANSACTION_LOG = original
        finally:
            os.unlink(log_path)


if __name__ == "__main__":
    unittest.main()
