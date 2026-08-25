import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

import httpx

from mypos_gateway import MyPOSGateway, MyPOSGatewayError, _mask_secrets

CONFIG = {
    "gateway_url": "https://demo-api-gateway.mypos.com",
    "partner": {
        "client_id": "client_integration",
        "client_secret": "secret_integration",
        "application_id": "mps-app-test",
        "partner_id": "mps-p-test",
    },
    "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
    "terminal_id": "80026232",
}


def make_gateway(handler):
    return MyPOSGateway(CONFIG, transport=httpx.MockTransport(handler))


class IntegrationTokenTests(unittest.TestCase):
    def test_fetches_integration_token(self):
        async def scenario():
            def handler(request):
                body = request.read().decode()
                self.assertEqual(request.url.path, "/api/v1/oauth/token")
                self.assertEqual(request.headers["content-type"], "application/x-www-form-urlencoded")
                self.assertIn("grant_type=client_credentials", body)
                self.assertIn("client_id=client_integration", body)
                return httpx.Response(200, json={"access_token": "tok_integration", "expires_in": 3600})

            gateway = make_gateway(handler)
            token = await gateway._get_integration_token()
            return token

        self.assertEqual(asyncio.run(scenario()), "tok_integration")

    def test_integration_token_cached(self):
        async def scenario():
            calls = []

            def handler(request):
                calls.append(1)
                return httpx.Response(200, json={"access_token": "tok_integration", "expires_in": 3600})

            gateway = make_gateway(handler)
            await gateway._get_integration_token()
            await gateway._get_integration_token()
            return len(calls)

        self.assertEqual(asyncio.run(scenario()), 1)

    def test_integration_token_refreshes_after_expiry(self):
        async def scenario():
            calls = []

            def handler(request):
                calls.append(1)
                return httpx.Response(200, json={"access_token": "tok_integration", "expires_in": 3600})

            gateway = make_gateway(handler)
            await gateway._get_integration_token()
            gateway._integration_token_expires = datetime(2000, 1, 1, tzinfo=timezone.utc)
            await gateway._get_integration_token()
            return len(calls)

        self.assertEqual(asyncio.run(scenario()), 2)

    def test_integration_token_error_raises(self):
        async def scenario():
            def handler(request):
                return httpx.Response(500, text="boom")

            gateway = make_gateway(handler)
            with self.assertRaises(MyPOSGatewayError) as ctx:
                await gateway._get_integration_token()
            return ctx.exception.status

        self.assertEqual(asyncio.run(scenario()), 500)


class SessionTests(unittest.TestCase):
    def test_fetches_session_with_merchant_credentials(self):
        async def scenario():
            seen = []

            def handler(request):
                seen.append(request.url.path)
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "tok_integration", "expires_in": 3600})
                self.assertEqual(request.url.path, "/api/v1/auth/session")
                self.assertEqual(request.headers["authorization"], "Bearer tok_integration")
                body = request.read().decode()
                self.assertIn('"client_id": "cli_merchant"', body)
                self.assertIn('"client_secret": "sec_merchant"', body)
                return httpx.Response(200, json={"session": "session_abc", "expires_in": 360})

            gateway = make_gateway(handler)
            session = await gateway._get_session()
            return session, len(seen)

        session, n = asyncio.run(scenario())
        self.assertEqual(session, "session_abc")
        self.assertEqual(n, 2)

    def test_session_cached(self):
        async def scenario():
            calls = []

            def handler(request):
                calls.append(request.url.path)
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "tok_integration", "expires_in": 3600})
                return httpx.Response(200, json={"session": "session_abc", "expires_in": 360})

            gateway = make_gateway(handler)
            await gateway._get_session()
            await gateway._get_session()
            return calls

        calls = asyncio.run(scenario())
        self.assertEqual(calls.count("/api/v1/auth/session"), 1)


class RequestTests(unittest.TestCase):
    def test_request_sends_all_headers_and_body(self):
        async def scenario():
            captured = {}

            def handler(request):
                captured["url"] = str(request.url)
                captured["headers"] = dict(request.headers)
                captured["body"] = request.read().decode()
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "tok_integration", "expires_in": 3600})
                if request.url.path == "/api/v1/auth/session":
                    return httpx.Response(200, json={"session": "session_abc", "expires_in": 360})
                return httpx.Response(201, json={"payment_id": "pay_123", "status": "InProgress"})

            gateway = make_gateway(handler)
            response = await gateway.create_payment({
                "reference_number": "ORD-1",
                "amount": {"value": 1500, "currency_code": "EUR"},
                "terminal_id": "80026232",
                "app_name": "KassaFu",
                "app_version": "1.0.0",
            })
            return response, captured

        response, captured = asyncio.run(scenario())
        self.assertEqual(response["payment_id"], "pay_123")
        self.assertEqual(captured["url"], "https://demo-api-gateway.mypos.com/epos/v1/payments")
        self.assertEqual(captured["headers"]["authorization"], "Bearer tok_integration")
        self.assertEqual(captured["headers"]["x-session"], "session_abc")
        self.assertEqual(captured["headers"]["x-partner-id"], "mps-p-test")
        self.assertEqual(captured["headers"]["x-application-id"], "mps-app-test")
        self.assertIn('"reference_number": "ORD-1"', captured["body"])

    def test_401_invalidates_and_retries_once(self):
        async def scenario():
            state = {"payment_attempts": 0}

            def handler(request):
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "tok_integration", "expires_in": 3600})
                if request.url.path == "/api/v1/auth/session":
                    return httpx.Response(200, json={"session": "session_abc", "expires_in": 360})
                state["payment_attempts"] += 1
                if state["payment_attempts"] == 1:
                    return httpx.Response(401, text="unauthorized")
                return httpx.Response(200, json={"payment_id": "pay_1", "status": "InProgress"})

            gateway = make_gateway(handler)
            response = await gateway.get_payment("pay_1")
            return response, state

        response, state = asyncio.run(scenario())
        self.assertEqual(response["payment_id"], "pay_1")
        self.assertEqual(state["payment_attempts"], 2)

    def test_http_400_raises_gateway_error(self):
        async def scenario():
            def handler(request):
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
                if request.url.path == "/api/v1/auth/session":
                    return httpx.Response(200, json={"session": "s", "expires_in": 360})
                return httpx.Response(400, text="bad request")

            gateway = make_gateway(handler)
            with self.assertRaises(MyPOSGatewayError) as ctx:
                await gateway.get_terminal("80026232")
            return ctx.exception.status

        self.assertEqual(asyncio.run(scenario()), 400)

    def test_get_terminals_returns_terminals_list(self):
        async def scenario():
            def handler(request):
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
                if request.url.path == "/api/v1/auth/session":
                    return httpx.Response(200, json={"session": "s", "expires_in": 360})
                return httpx.Response(200, json={
                    "pagination": {"page": 1, "page_size": 20, "total": 1},
                    "terminals": [{"terminal_id": "80026232", "serial_number": "N96N960WC15224", "model": "N96"}],
                })

            gateway = make_gateway(handler)
            return await gateway.get_terminals()

        data = asyncio.run(scenario())
        self.assertEqual(data["terminals"][0]["terminal_id"], "80026232")

    def test_cancel_payment_uses_delete(self):
        async def scenario():
            seen = {}

            def handler(request):
                seen["method"] = request.method
                seen["path"] = request.url.path
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
                if request.url.path == "/api/v1/auth/session":
                    return httpx.Response(200, json={"session": "s", "expires_in": 360})
                return httpx.Response(202, json={"request_id": "r1", "status": "InProgress"})

            gateway = make_gateway(handler)
            await gateway.cancel_payment("pay_1")
            return seen

        seen = asyncio.run(scenario())
        self.assertEqual(seen["method"], "DELETE")
        self.assertEqual(seen["path"], "/epos/v1/payments/pay_1")


class HttpDebugLoggingTests(unittest.TestCase):
    def test_mask_secrets_hides_all_credential_forms(self):
        form = "grant_type=client_credentials&client_id=client_integration&client_secret=secret_integration"
        masked = _mask_secrets(form)
        self.assertNotIn("secret_integration", masked)
        self.assertIn("client_secret=***", masked)
        self.assertIn("client_id=client_integration", masked)

        js = '{"client_id": "cli_merchant", "client_secret": "sec_merchant"}'
        masked = _mask_secrets(js)
        self.assertNotIn("sec_merchant", masked)
        self.assertIn('"client_id": "cli_merchant"', masked)

        token_body = '{"access_token": "tok_integration", "expires_in": 3600}'
        self.assertNotIn("tok_integration", _mask_secrets(token_body))

    def test_debug_hook_logs_masked_traffic_when_enabled(self):
        async def scenario():
            def handler(request):
                return httpx.Response(200, json={"access_token": "tok_integration", "expires_in": 3600})

            gateway = make_gateway(handler)
            with self.assertLogs("mypos_gateway", level="INFO") as captured:
                await gateway._get_integration_token()
            return "\n".join(captured.output)

        with mock.patch.dict(os.environ, {"KASSAFU_HTTP_DEBUG": "1"}):
            log = asyncio.run(scenario())

        self.assertIn("--> POST https://demo-api-gateway.mypos.com/api/v1/oauth/token", log)
        self.assertIn("client_secret=secret_integration", log)
        self.assertIn("content-type: application/x-www-form-urlencoded", log)
        self.assertIn("<-- HTTP 200", log)
        self.assertNotIn("tok_integration", log)

    def test_logging_disabled_by_default(self):
        async def scenario():
            def handler(request):
                return httpx.Response(200, json={"access_token": "t"})

            gateway = make_gateway(handler)
            try:
                with self.assertLogs("mypos_gateway", level="INFO") as captured:
                    await gateway._get_integration_token()
            except AssertionError:
                return ""
            return "\n".join(captured.output)

        with mock.patch.dict(os.environ):
            os.environ.pop("KASSAFU_HTTP_DEBUG", None)
            log = asyncio.run(scenario())

        self.assertNotIn("-->", log)


if __name__ == "__main__":
    unittest.main()