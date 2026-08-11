import asyncio
import unittest
from datetime import datetime, timezone

import httpx

from mypos_gateway import MyPOSGateway, MyPOSGatewayError

CONFIG = {
    "gateway_url": "https://demo-api-gateway.mypos.com",
    "integration": {"client_id": "client_integration", "client_secret": "secret_integration"},
    "partner_id": "mps-p-test",
    "application_id": "mps-app-test",
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


if __name__ == "__main__":
    unittest.main()