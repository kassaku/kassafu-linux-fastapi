import asyncio
import os
import tempfile
import time
import unittest
from unittest import mock

import kassafu
from encrypt_partner import PartnerConfigError
from kassafu import bridge

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
        self.transaction_status = "PENDING"
        self.payments = []
        self.logged_status_updates = []

    async def process_payment(self, order_id, amount_cents, currency="EUR"):
        self.payments.append(order_id)
        return {"success": True, "status": "pending", "order_id": order_id, "error_code": 0}

    async def cancel_payment(self, order_id):
        return {"success": True}

    async def clear_display(self):
        pass

    async def check_status(self):
        return {"online": True, "ready": True, "reader_id": self.reader_id, "error_code": 0}

    async def get_transaction_status(self, transaction_id):
        return self.transaction_status

    def _log_status_update(self, order_id, transaction_id, status, message=""):
        self.logged_status_updates.append((order_id, transaction_id, status))

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

    def test_poll_returns_paid_when_transaction_successful(self):
        term = FakeTerminal()
        term.current_order_id = "O1"
        term.current_transaction_id = "T1"
        term.current_status = "pending"
        term.current_amount_cents = 1000
        term.current_currency = "EUR"
        term.current_card_scheme = "visa"
        term.current_card_last_4 = "4242"
        term.transaction_status = "SUCCESSFUL"
        kassafu.terminal = term
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "paid")
        self.assertEqual(body["amount"], 10.0)
        self.assertEqual(body["card_scheme"], "visa")
        self.assertEqual(body["card_last_4"], "4242")
        self.assertEqual(body["error_code"], 0)
        self.assertIn(("O1", "T1", "paid"), term.logged_status_updates)

    def test_poll_returns_failed_when_transaction_failed(self):
        term = FakeTerminal()
        term.current_order_id = "O1"
        term.current_transaction_id = "T1"
        term.current_status = "pending"
        term.current_amount_cents = 1000
        term.current_currency = "EUR"
        term.transaction_status = "FAILED"
        kassafu.terminal = term
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["error_code"], 108009)
        self.assertIn(("O1", "T1", "failed"), term.logged_status_updates)

    def test_queued_payment_processed_by_consumer(self):
        term = FakeTerminal()
        kassafu.terminal = term
        consumer = bridge.create_task(kassafu.process_payment_queue())
        bridge.run(kassafu.payment_queue.put({"order_id": "Q1", "amount_cents": 500, "currency": "EUR"}))
        deadline = time.time() + 5
        while time.time() < deadline and not term.payments:
            time.sleep(0.01)
        consumer.cancel()
        self.assertEqual(term.payments, ["Q1"])


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

    INTERFACE = {
        "client_url": "http://example.test/client.blob",
        "client_key": "client-key",
        "id": "80026232",
    }

    def test_get_config_without_terminal_returns_message(self):
        r = self.client.get("/config")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.get_json(), {"message": "config not available, please check tomorrow"}
        )

    def test_post_config_rejected_during_active_payment(self):
        kassafu.active_payment = True
        r = self.client.post("/config", json=self.INTERFACE)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error_code"], 108012)

    def test_post_config_non_dict_returns_400(self):
        r = self.client.post("/config", json="nope")
        self.assertEqual(r.status_code, 400)
        self.assertIn("JSON object", r.get_json()["detail"])

    def test_post_config_missing_id_returns_400(self):
        body = {"client_url": "http://example.test/c.blob", "client_key": "k"}
        r = self.client.post("/config", json=body)
        self.assertEqual(r.status_code, 400)
        self.assertIn("client_url, client_key or id", r.get_json()["detail"])

    def test_post_config_sumup_success(self):
        resolved = {
            "app": {"name": "KassaFu"},
            "sumup": {"api_key": "sup_sk_test", "merchant_code": "M1234567",
                      "reader_id": "80026232"},
        }
        with mock.patch("kassafu._resolve_remote_config", return_value=resolved):
            r = self.client.post("/config", json=self.INTERFACE)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["terminal_type"], "sumup")
        self.assertIsNotNone(kassafu.terminal)

    def test_post_config_mypos_success(self):
        resolved = {
            "app": {"name": "KassaFu"},
            "mypos": {
                "gateway_url": "https://demo-api-gateway.mypos.com",
                "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
                "terminal_id": "80026232",
                "partner": {"client_id": "ci", "client_secret": "cs",
                            "application_id": "mps-app-test", "partner_id": "mps-p-test"},
            },
        }
        with mock.patch("kassafu._resolve_remote_config", return_value=resolved):
            r = self.client.post("/config", json=self.INTERFACE)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["terminal_type"], "mypos")
        self.assertIsNotNone(kassafu.terminal)

    def test_post_config_resolution_error_returns_400(self):
        with mock.patch(
            "kassafu._resolve_remote_config",
            side_effect=PartnerConfigError("Failed to fetch client configuration"),
        ):
            r = self.client.post("/config", json=self.INTERFACE)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Failed to fetch client configuration", r.get_json()["detail"])


    def test_version_endpoint_returns_1_0_0(self):
        r = self.client.get("/version")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.get_json(),
            {"app": "KassaFu", "version": "1.0.0"},
        )


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
        body = r.get_json()
        self.assertTrue(body["online"])
        self.assertTrue(body["ready"])

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
