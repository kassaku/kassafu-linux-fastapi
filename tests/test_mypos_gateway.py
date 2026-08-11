import asyncio
import unittest

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
                self.assertEqual(request.url.path, "/api/v1/oauth/token")
                self.assertEqual(request.headers["content-type"], "application/x-www-form-urlencoded")
                self.assertIn("grant_type=client_credentials", request.read().decode())
                self.assertIn("client_id=client_integration", request.read().decode())
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

    def test_integration_token_error_raises(self):
        async def scenario():
            def handler(request):
                return httpx.Response(500, text="boom")

            gateway = make_gateway(handler)
            with self.assertRaises(MyPOSGatewayError) as ctx:
                await gateway._get_integration_token()
            return ctx.exception.status

        self.assertEqual(asyncio.run(scenario()), 500)


if __name__ == "__main__":
    unittest.main()