# myPOS ePOS API Gateway Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `mypos_terminal.py` to talk to the myPOS ePOS API Gateway (OpenAPI "POS" v1), keeping the SumUp-compatible interface that `kassafu.py` consumes, via a new `mypos_gateway.py` module.

**Architecture:** New `mypos_gateway.py` owns all myPOS HTTP + dual-token auth (OAuth Bearer + `X-Session`) and raises `MyPOSGatewayError`. Rewritten `mypos_terminal.py` is a thin adapter keeping the exact `SumUpTerminal`-style contract used by `kassafu.py` and maps gateway responses/errors to the kassafu contract. `install.sh` copies the new module.

**Tech Stack:** Python 3.10+, asyncio, `httpx` (already a dependency). Tests use stdlib `unittest` + `httpx.MockTransport` — no new packages.

**Spec:** `docs/superpowers/specs/2026-08-11-mypos-epos-gateway-design.md`

---

## Working-tree warning

`git status` currently shows unrelated modified files (`ccv.py`, `git_history.py`, `sumup_terminal.py`, `loc_analyzer.py`, `kassafu.py`, `test_reader_status.py`, `install.sh`) plus the untracked `mypos_terminal.py`. **Never run `git add -A` or `git add .`.** In every commit step, stage only the explicit files listed for that task.

Run tests from the repo root:

```bash
python3 -c "import httpx" || pip install -r requirements.txt
```

If httpx is only installed in the venv:

```bash
source venv/bin/activate && python3 -m unittest <args>
```

---

### Task 1: myPOS gateway — integration token auth

**Files:**
- Create: `mypos_gateway.py`
- Test: `tests/__init__.py`, `tests/test_mypos_gateway.py`

- [ ] **Step 1: Write the failing test**

`tests/__init__.py`:
```python
```

`tests/test_mypos_gateway.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_mypos_gateway.IntegrationTokenTests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mypos_gateway'`

- [ ] **Step 3: Write minimal implementation**

`mypos_gateway.py`:
```python
"""
myPOS ePOS API Gateway client

Copyright (c) 2026 Houkes Horeca Applications

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import asyncio
import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MyPOSGatewayError(Exception):
    """Raised for myPOS gateway HTTP, transport, and timeout errors."""

    def __init__(self, status: Optional[int], detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


class MyPOSGateway:
    """HTTP client for the myPOS ePOS API Gateway.

    Owns credentials, OAuth Bearer token and merchant session caching/refresh,
    and the four required request headers.
    """

    def __init__(self, config: Dict, transport=None):
        self.gateway_url = config.get("gateway_url", "").rstrip("/")
        integration = config.get("integration", {})
        self.integration_client_id = integration.get("client_id", "")
        self.integration_client_secret = integration.get("client_secret", "")
        self.partner_id = config.get("partner_id", "")
        self.application_id = config.get("application_id", "")
        merchant = config.get("merchant", {})
        self.merchant_client_id = merchant.get("client_id", "")
        self.merchant_client_secret = merchant.get("client_secret", "")
        self._transport = transport

        self._integration_token = None
        self._integration_token_expires = None
        self._session = None
        self._session_expires = None
        self._token_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()

    def _new_client(self) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(transport=self._transport)
        return httpx.AsyncClient()

    async def _get_integration_token(self) -> str:
        async with self._token_lock:
            now = datetime.now(timezone.utc)
            if self._integration_token and self._integration_token_expires and now < self._integration_token_expires:
                return self._integration_token
            token = await self._request_integration_token()
            self._integration_token = token
            return token

    async def _request_integration_token(self) -> str:
        url = f"{self.gateway_url}/api/v1/oauth/token"
        async with self._new_client() as client:
            response = await client.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.integration_client_id,
                    "client_secret": self.integration_client_secret,
                },
                timeout=10,
            )
        if response.status_code in (200, 201):
            data = response.json()
            expires_in = data.get("expires_in", 3600)
            self._integration_token_expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
            return data.get("access_token")
        raise MyPOSGatewayError(response.status_code, f"Token request failed: HTTP {response.status_code}: {response.text[:200]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_mypos_gateway.IntegrationTokenTests -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add mypos_gateway.py tests/__init__.py tests/test_mypos_gateway.py
git commit -m "Add MyPOSGateway integration token auth"
```

---

### Task 2: myPOS gateway — merchant session

**Files:**
- Modify: `mypos_gateway.py`
- Test: `tests/test_mypos_gateway.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mypos_gateway.py` (before the `if __name__` block):
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_mypos_gateway.SessionTests -v`
Expected: FAIL with `AttributeError: 'MyPOSGateway' object has no attribute '_get_session'`

- [ ] **Step 3: Write minimal implementation**

Append methods to `MyPOSGateway` in `mypos_gateway.py`:
```python
    async def _get_session(self) -> str:
        token = await self._get_integration_token()
        async with self._session_lock:
            now = datetime.now(timezone.utc)
            if self._session and self._session_expires and now < self._session_expires:
                return self._session
            session = await self._request_session(token)
            self._session = session
            return session

    async def _request_session(self, token: str) -> str:
        url = f"{self.gateway_url}/api/v1/auth/session"
        async with self._new_client() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "client_id": self.merchant_client_id,
                    "client_secret": self.merchant_client_secret,
                },
                timeout=10,
            )
        if response.status_code in (200, 201):
            data = response.json()
            expires_in = data.get("expires_in", 360)
            self._session_expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 30)
            return data.get("session")
        raise MyPOSGatewayError(response.status_code, f"Session request failed: HTTP {response.status_code}: {response.text[:200]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_mypos_gateway.SessionTests -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add mypos_gateway.py tests/test_mypos_gateway.py
git commit -m "Add MyPOSGateway merchant session auth"
```

---

### Task 3: myPOS gateway — request() with headers, 401 retry, endpoint methods

**Files:**
- Modify: `mypos_gateway.py`
- Test: `tests/test_mypos_gateway.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mypos_gateway.py` (before the `if __name__` block):
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_mypos_gateway.RequestTests -v`
Expected: FAIL with `AttributeError: 'MyPOSGateway' object has no attribute 'request'`

- [ ] **Step 3: Write minimal implementation**

Append methods to `MyPOSGateway` in `mypos_gateway.py`:
```python
    def _invalidate_tokens(self):
        self._integration_token = None
        self._integration_token_expires = None
        self._session = None
        self._session_expires = None

    async def request(self, method: str, path: str, body: dict = None, params: dict = None) -> dict:
        for attempt in range(2):
            token = await self._get_integration_token()
            session = await self._get_session()
            headers = {
                "Authorization": f"Bearer {token}",
                "X-Session": session,
                "X-Partner-Id": self.partner_id,
                "X-Application-Id": self.application_id,
                "Content-Type": "application/json; x-api-version=1",
            }
            url = f"{self.gateway_url}{path}"
            try:
                async with self._new_client() as client:
                    response = await client.request(
                        method, url, headers=headers, json=body, params=params, timeout=15
                    )
            except httpx.TimeoutException as e:
                raise MyPOSGatewayError(None, f"Timeout: {e}") from e
            except httpx.HTTPError as e:
                raise MyPOSGatewayError(None, f"Transport error: {e}") from e

            if response.status_code == 401 and attempt == 0:
                self._invalidate_tokens()
                continue
            if response.status_code >= 400:
                raise MyPOSGatewayError(response.status_code, response.text[:200])
            if not response.content:
                return {}
            return response.json()
        raise MyPOSGatewayError(401, "Unauthorized after token refresh")

    async def get_terminals(self, page: int = 1, size: int = 20, terminal_id: str = None, serial_number: str = None, model: str = None) -> dict:
        params = {"page": page, "size": size}
        if terminal_id:
            params["terminal_id"] = terminal_id
        if serial_number:
            params["serial_number"] = serial_number
        if model:
            params["model"] = model
        return await self.request("GET", "/pos/v1/terminals", params=params)

    async def get_terminal(self, terminal_id: str) -> dict:
        return await self.request("GET", f"/pos/v1/terminals/{terminal_id}")

    async def create_payment(self, payload: dict) -> dict:
        return await self.request("POST", "/epos/v1/payments", body=payload)

    async def get_payment(self, payment_id: str) -> dict:
        return await self.request("GET", f"/epos/v1/payments/{payment_id}")

    async def cancel_payment(self, payment_id: str) -> dict:
        return await self.request("DELETE", f"/epos/v1/payments/{payment_id}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_mypos_gateway -v`
Expected: all 9 tests PASS (3 IntegrationToken + 2 Session + 5 Request)

- [ ] **Step 5: Commit**

```bash
git add mypos_gateway.py tests/test_mypos_gateway.py
git commit -m "Add MyPOSGateway request and endpoint methods"
```

---

### Task 4: myPOS terminal adapter — init/update/get_config, status mapping

**Files:**
- Rewrite: `mypos_terminal.py`
- Test: `tests/test_mypos_terminal.py`

- [ ] **Step 1: Write the failing test**

`tests/test_mypos_terminal.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_mypos_terminal -v`
Expected: FAIL — the old `mypos_terminal.py` has no gateway-based `get_transaction_status` behavior matching snake_case API (several tests fail on `AssertionError` / wrong mapping).

- [ ] **Step 3: Write minimal implementation**

Rewrite `mypos_terminal.py` in full:
```python
"""
myPOS Terminal Handler - ePOS API Gateway integration for KassaFu

Copyright (c) 2026 Houkes Horeca Applications

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import logging
import json
from datetime import datetime
from typing import Dict, Optional

from mypos_gateway import MyPOSGateway, MyPOSGatewayError

logger = logging.getLogger(__name__)


class MyPOSTerminal:
    """Handler for myPOS ePOS Gateway terminal operations.

    Presents the same interface as SumUpTerminal so kassafu.py can use either.
    """

    def __init__(self):
        self.gateway_url = ""
        self.integration_client_id = ""
        self.integration_client_secret = ""
        self.partner_id = ""
        self.application_id = ""
        self.merchant_client_id = ""
        self.merchant_client_secret = ""
        self.terminal_id = None
        self.gateway: Optional[MyPOSGateway] = None
        self._is_ready = False

        self.app_config = {}
        self.mypos_config = {}

        self.current_order_id = None
        self.current_transaction_id = None
        self.current_amount_cents = None
        self.current_currency = None
        self.current_status = None
        self.current_created_at = None
        self.current_card_scheme = None
        self.current_card_last_4 = None

    def init(self, config: Dict) -> bool:
        try:
            self.app_config = config.get("app", {})
            self.mypos_config = config.get("mypos", {})

            self.gateway_url = self.mypos_config.get("gateway_url", "").rstrip("/")
            integration = self.mypos_config.get("integration", {})
            self.integration_client_id = integration.get("client_id", "")
            self.integration_client_secret = integration.get("client_secret", "")
            self.partner_id = self.mypos_config.get("partner_id", "")
            self.application_id = self.mypos_config.get("application_id", "")
            merchant = self.mypos_config.get("merchant", {})
            self.merchant_client_id = merchant.get("client_id", "")
            self.merchant_client_secret = merchant.get("client_secret", "")
            self.terminal_id = self.mypos_config.get("terminal_id", None)

            if not self.gateway_url:
                logger.error("Missing mypos.gateway_url in configuration")
                return False
            if not self.integration_client_id or not self.integration_client_secret:
                logger.error("Missing mypos.integration.client_id or client_secret")
                return False
            if not self.partner_id or not self.application_id:
                logger.error("Missing mypos.partner_id or application_id")
                return False
            if not self.merchant_client_id or not self.merchant_client_secret:
                logger.error("Missing mypos.merchant.client_id or client_secret")
                return False

            self.gateway = MyPOSGateway({
                "gateway_url": self.gateway_url,
                "integration": {
                    "client_id": self.integration_client_id,
                    "client_secret": self.integration_client_secret,
                },
                "partner_id": self.partner_id,
                "application_id": self.application_id,
                "merchant": {
                    "client_id": self.merchant_client_id,
                    "client_secret": self.merchant_client_secret,
                },
            })

            if self.terminal_id:
                self._is_ready = True
                logger.info(f"myPOS configured with terminal: {self.terminal_id}")
            else:
                logger.info("No terminal_id provided, will auto-discover")
                self._is_ready = False

            logger.info(f"myPOS initialized with gateway: {self.gateway_url}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize myPOS terminal: {e}")
            return False

    def update_config(self, config: Dict) -> bool:
        return self.init(config)

    def get_config(self) -> Dict:
        return {
            "app": self.app_config,
            "mypos": {
                "gateway_url": self.gateway_url,
                "partner_id": self.partner_id,
                "application_id": self.application_id,
                "terminal_id": self.terminal_id,
            }
        }

    def clear_current_payment(self):
        self.current_order_id = None
        self.current_transaction_id = None
        self.current_amount_cents = None
        self.current_currency = None
        self.current_status = None
        self.current_created_at = None
        self.current_card_scheme = None
        self.current_card_last_4 = None

    def _map_error_code(self, status: Optional[int]) -> int:
        if status is None:
            return 108001
        if status == 400:
            return 108007
        if status in (401, 403):
            return 108003
        if status == 404:
            return 108002
        if status >= 500:
            return 108011
        return 108001

    async def get_transaction_status(self, transaction_id: str) -> str:
        try:
            data = await self.gateway.get_payment(transaction_id)
            status = data.get("status", "InProgress")
            if status == "Success":
                self.current_card_scheme = data.get("card_qualifier")
                pan = data.get("pan") or ""
                self.current_card_last_4 = pan[-4:] if len(pan) >= 4 else pan
                return "SUCCESSFUL"
            elif status in ("Failed", "Rejected"):
                return "FAILED"
            elif status in ("Canceled", "Reversed"):
                return "CANCELLED"
            return "PENDING"
        except MyPOSGatewayError as e:
            logger.warning(f"Status check failed for {transaction_id}: {e.detail}")
            return "PENDING"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_mypos_terminal.InitTests tests.test_mypos_terminal.TransactionStatusTests -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add mypos_terminal.py tests/test_mypos_terminal.py
git commit -m "Rewrite MyPOSTerminal as gateway adapter with status mapping"
```

---

### Task 5: myPOS terminal adapter — discover_reader, check_status

**Files:**
- Modify: `mypos_terminal.py`
- Test: `tests/test_mypos_terminal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mypos_terminal.py` (before the `if __name__` block):
```python
class DiscoverTests(unittest.TestCase):
    def test_discover_sets_first_terminal(self):
        t = MyPOSTerminal()
        t.init({**CONFIG, "mypos": {**CONFIG["mypos"], "terminal_id": None}})
        t.gateway = FakeGateway()
        self.assertFalse(t.is_ready)

        async def scenario():
            return await t.discover_reader()

        self.assertTrue(asyncio.run(scenario()))
        self.assertEqual(t.terminal_id, "80026232")
        self.assertTrue(t.is_ready)


class CheckStatusTests(unittest.TestCase):
    def test_active_terminal_is_online(self):
        t = make_terminal()

        async def scenario():
            return await t.check_status()

        status = asyncio.run(scenario())
        self.assertTrue(status["online"])
        self.assertTrue(status["ready"])
        self.assertEqual(status["state"], "Active")
        self.assertEqual(status["device_currency"], "EUR")

    def test_missing_terminal_id(self):
        t = MyPOSTerminal()
        t.init({**CONFIG, "mypos": {**CONFIG["mypos"], "terminal_id": None}})

        async def scenario():
            return await t.check_status()

        status = asyncio.run(scenario())
        self.assertEqual(status["error_code"], 108010)
        self.assertFalse(status["online"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_mypos_terminal.DiscoverTests tests.test_mypos_terminal.CheckStatusTests -v`
Expected: FAIL with `AttributeError: 'MyPOSTerminal' object has no attribute 'discover_reader'`

- [ ] **Step 3: Write minimal implementation**

Append methods to `MyPOSTerminal` in `mypos_terminal.py`:
```python
    async def discover_reader(self) -> bool:
        try:
            result = await self.gateway.get_terminals()
            terminals = result.get("terminals", [])
            if terminals:
                self.terminal_id = terminals[0].get("terminal_id")
                self._is_ready = True
                logger.info(f"Discovered myPOS terminal: {self.terminal_id}")
                return True
            logger.warning("No myPOS terminals found")
            return False
        except MyPOSGatewayError as e:
            logger.warning(f"Failed to discover terminals: {e.detail}")
            return False

    async def check_status(self) -> Dict:
        if not self.terminal_id:
            return {"online": False, "ready": False, "error": "No terminal ID configured", "error_code": 108010}
        try:
            data = await self.gateway.get_terminal(self.terminal_id)
            is_active = data.get("status") == "Active"
            return {
                "online": is_active,
                "ready": is_active,
                "state": data.get("status"),
                "terminal_id": self.terminal_id,
                "terminal_name": data.get("terminal_name"),
                "model": data.get("model"),
                "serial_number": data.get("serial_number"),
                "device_currency": data.get("device_currency"),
            }
        except MyPOSGatewayError as e:
            return {"online": False, "ready": False, "error": e.detail, "error_code": self._map_error_code(e.status)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_mypos_terminal.DiscoverTests tests.test_mypos_terminal.CheckStatusTests -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add mypos_terminal.py tests/test_mypos_terminal.py
git commit -m "Add myPOS terminal discovery and status check"
```

---

### Task 6: myPOS terminal adapter — process_payment

**Files:**
- Modify: `mypos_terminal.py`
- Test: `tests/test_mypos_terminal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mypos_terminal.py` (before the `if __name__` block):
```python
class ProcessPaymentTests(unittest.TestCase):
    def test_builds_snake_case_payload(self):
        t = make_terminal()

        async def scenario():
            return await t.process_payment("ORD-1", 1500, "EUR")

        result = asyncio.run(scenario())
        payload = t.gateway.payment_requests[0]
        self.assertEqual(payload["reference_number"], "ORD-1")
        self.assertEqual(payload["amount"], {"value": 1500, "currency_code": "EUR"})
        self.assertEqual(payload["terminal_id"], "80026232")
        self.assertEqual(payload["app_name"], "KassaFu")
        self.assertEqual(payload["app_version"], "1.0.0")
        self.assertNotIn("operator_code", payload)
        self.assertTrue(result["success"])
        self.assertEqual(result["transaction_id"], "pay_123")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(t.current_transaction_id, "pay_123")

    def test_includes_operator_code_when_configured(self):
        t = make_terminal()
        t.mypos_config["operator_code"] = "0123"

        async def scenario():
            return await t.process_payment("ORD-2", 100, "EUR")

        asyncio.run(scenario())
        self.assertEqual(t.gateway.payment_requests[0]["operator_code"], "0123")

    def test_missing_terminal_fails(self):
        t = MyPOSTerminal()
        t.init({**CONFIG, "mypos": {**CONFIG["mypos"], "terminal_id": None}})

        async def scenario():
            return await t.process_payment("ORD-1", 100, "EUR")

        result = asyncio.run(scenario())
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], 108010)

    def test_gateway_error_maps_error_code(self):
        t = make_terminal()
        t.gateway.create_payment_error = MyPOSGatewayError(400, "bad request")

        async def scenario():
            return await t.process_payment("ORD-1", 100, "EUR")

        result = asyncio.run(scenario())
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], 108007)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_mypos_terminal.ProcessPaymentTests -v`
Expected: FAIL with `AttributeError: 'MyPOSTerminal' object has no attribute 'process_payment'`

- [ ] **Step 3: Write minimal implementation**

Append methods + `_log_transaction`/`_log_status_update` to `MyPOSTerminal` in `mypos_terminal.py`:
```python
    async def process_payment(self, order_id: str, amount_cents: int, currency: str = "EUR") -> Dict:
        start_time = datetime.now()

        self.current_order_id = order_id
        self.current_amount_cents = amount_cents
        self.current_currency = currency
        self.current_status = "pending"
        self.current_created_at = start_time

        if not self.terminal_id:
            self.clear_current_payment()
            return {"success": False, "status": "failed", "message": "No myPOS terminal configured", "error_code": 108010}

        logger.info(f"Processing myPOS payment for order {order_id}: {amount_cents/100} {currency}")

        payload = {
            "reference_number": order_id,
            "amount": {"value": amount_cents, "currency_code": currency},
            "terminal_id": self.terminal_id,
            "app_name": self.app_config.get("name", "KassaFu"),
            "app_version": "1.0.0",
        }
        operator_code = self.mypos_config.get("operator_code")
        if operator_code:
            payload["operator_code"] = operator_code

        try:
            data = await self.gateway.create_payment(payload)
            payment_id = data.get("payment_id")
            self.current_transaction_id = payment_id
            logger.info(f"myPOS payment initiated: {payment_id}")
            self._log_transaction(order_id, amount_cents, currency, payment_id or "", start_time)
            return {
                "success": True,
                "transaction_id": payment_id,
                "status": "pending",
                "message": "Payment initiated on myPOS terminal",
                "error_code": 0,
            }
        except MyPOSGatewayError as e:
            self.current_status = "failed"
            self._log_status_update(order_id, self.current_transaction_id or "", "failed", e.detail)
            return {
                "success": False,
                "status": "failed",
                "message": e.detail,
                "error_code": self._map_error_code(e.status),
            }

    def _log_transaction(self, order_id: str, amount_cents: int, currency: str, transaction_id: str, start_time: datetime):
        with open('transactions.log', 'a') as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "order_id": order_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "status": "pending",
                "transaction_id": transaction_id,
                "card_scheme": self.current_card_scheme,
                "card_last_4": self.current_card_last_4,
                "duration_sec": (datetime.now() - start_time).total_seconds()
            }) + '\n')

    def _log_status_update(self, order_id: str, transaction_id: str, status: str, message: str = ""):
        with open('transactions.log', 'a') as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "order_id": order_id,
                "transaction_id": transaction_id,
                "status": status,
                "message": message,
                "card_scheme": self.current_card_scheme,
                "card_last_4": self.current_card_last_4
            }) + '\n')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_mypos_terminal.ProcessPaymentTests -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add mypos_terminal.py tests/test_mypos_terminal.py
git commit -m "Add myPOS process payment with snake_case payload"
```

---

### Task 7: myPOS terminal adapter — cancel_payment, clear_display, is_ready

**Files:**
- Modify: `mypos_terminal.py`
- Test: `tests/test_mypos_terminal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mypos_terminal.py` (before the `if __name__` block):
```python
class CancelPaymentTests(unittest.TestCase):
    def test_cancels_active_payment_via_delete(self):
        t = make_terminal()

        async def scenario():
            await t.process_payment("ORD-1", 100, "EUR")
            return await t.cancel_payment("ORD-1")

        result = asyncio.run(scenario())
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(t.gateway.cancel_requests, ["pay_123"])

    def test_no_active_payment(self):
        t = make_terminal()

        async def scenario():
            return await t.cancel_payment("ORD-1")

        result = asyncio.run(scenario())
        self.assertEqual(result["status"], "not_found")
        self.assertFalse(result["success"])

    def test_wrong_order_id(self):
        t = make_terminal()

        async def scenario():
            await t.process_payment("ORD-1", 100, "EUR")
            return await t.cancel_payment("ORD-2")

        result = asyncio.run(scenario())
        self.assertEqual(result["status"], "not_found")


class ClearDisplayTests(unittest.TestCase):
    def test_clear_display_is_noop(self):
        t = make_terminal()

        async def scenario():
            await t.clear_display()

        asyncio.run(scenario())  # must not raise


class ReadyTests(unittest.TestCase):
    def test_is_ready_false_without_terminal(self):
        t = MyPOSTerminal()
        t.init({**CONFIG, "mypos": {**CONFIG["mypos"], "terminal_id": None}})
        self.assertFalse(t.is_ready)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_mypos_terminal.CancelPaymentTests tests.test_mypos_terminal.ClearDisplayTests tests.test_mypos_terminal.ReadyTests -v`
Expected: FAIL with `AttributeError: 'MyPOSTerminal' object has no attribute 'cancel_payment'`

- [ ] **Step 3: Write minimal implementation**

Append methods to `MyPOSTerminal` in `mypos_terminal.py`:
```python
    async def cancel_payment(self, order_id: str) -> Dict:
        if not self.current_order_id:
            return {"success": False, "status": "not_found", "message": "No active payment", "error_code": 108002}
        if self.current_order_id != order_id:
            return {"success": False, "status": "not_found", "message": f"No payment for order {order_id}", "error_code": 108002}
        if self.current_status in ("paid", "failed", "cancelled"):
            return {"success": True, "status": self.current_status, "message": f"Already {self.current_status}", "error_code": 0}

        if self.current_transaction_id:
            try:
                await self.gateway.cancel_payment(self.current_transaction_id)
                self.current_status = "cancelled"
                self._log_status_update(order_id, self.current_transaction_id, "cancelled")
                logger.info(f"myPOS payment for order {order_id} cancelled")
                return {"success": True, "status": "cancelled", "message": "Payment cancelled", "error_code": 0}
            except MyPOSGatewayError as e:
                logger.warning(f"Cancel failed on gateway: {e.detail}")

        self.current_status = "cancelled"
        return {"success": True, "status": "cancelled", "message": "Payment cancelled (local)", "error_code": 0}

    async def clear_display(self):
        pass

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self.terminal_id is not None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_mypos_terminal -v`
Expected: all 14 tests PASS (4 Init + 2 TransactionStatus + 3 Discover/CheckStatus + 4 ProcessPayment + 3 Cancel + 1 ClearDisplay + 1 Ready)

- [ ] **Step 5: Commit**

```bash
git add mypos_terminal.py tests/test_mypos_terminal.py
git commit -m "Add myPOS cancel, clear display, and ready state"
```

---

### Task 8: install.sh — ship the new module

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Add the copy line**

In `install.sh`, directly after the existing `cp "$SCRIPT_DIR/mypos_terminal.py" "$INSTALL_DIR/"` (currently line 25), add:

```bash
cp "$SCRIPT_DIR/mypos_gateway.py" "$INSTALL_DIR/"
```

- [ ] **Step 2: Verify**

Run: `grep mypos_gateway install.sh`
Expected: the new `cp` line is shown

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "Ship mypos_gateway.py in installer"
```

---

### Task 9: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python3 -m unittest tests.test_mypos_gateway tests.test_mypos_terminal -v`
Expected: 23 PASS, 0 failures/errors (9 gateway + 14 terminal)

- [ ] **Step 2: Byte-compile all modules**

Run: `python3 -m py_compile mypos_gateway.py mypos_terminal.py kassafu.py`
Expected: no output, exit code 0

- [ ] **Step 3: Confirm the interface contract**

Run: `python3 -c "from mypos_terminal import MyPOSTerminal; print([m for m in dir(MyPOSTerminal) if not m.startswith('__')])"`
Expected output includes: `cancel_payment`, `check_status`, `clear_current_payment`, `clear_display`, `discover_reader`, `get_config`, `get_transaction_status`, `init`, `is_ready`, `process_payment`, `update_config`

- [ ] **Step 4: Verify git status shows only intended files**

Run: `git status --short`
Expected: modified `install.sh`, `mypos_terminal.py`; new `mypos_gateway.py`, `tests/`; unrelated pre-existing modifications to `ccv.py`, `git_history.py`, `sumup_terminal.py`, `loc_analyzer.py`, `kassafu.py`, `test_reader_status.py` remain untouched.

---

## Self-Review

**Spec coverage:**
- Auth flow (Task 1-3): `POST /api/v1/oauth/token`, `POST /api/v1/auth/session`, four required headers, cache + refresh-before-expiry, 401 invalidation + single retry. ✓
- Endpoints (Task 3, 5, 6, 7): create payment, get payment, cancel (DELETE), terminals list, terminal details. ✓
- Status mapping (Task 4): Success/Failed/Rejected/Canceled/Reversed/InProgress → SUCCESSFUL/FAILED/CANCELLED/PENDING; card_qualifier + pan to card info. ✓
- Config unchanged + new required fields (Task 4 InitTests). ✓
- Error mapping 400/401/403/404/5xx/transport → 108007/108003/108002/108011/108001; timeout → MyPOSGatewayError(status=None). ✓
- install.sh ships module (Task 8). ✓
- kassafu.py, test scripts, config schema, requirements unchanged (no task touches them). ✓

**Placeholder scan:** no TBD/TODO; every code step contains full code and every run step has expected output.

**Type consistency:** `MyPOSGateway` constructor takes `(config, transport=None)`; adapter passes a creds dict, tests pass `httpx.MockTransport`. Endpoint method names (`get_terminals`, `get_terminal`, `create_payment`, `get_payment`, `cancel_payment`) are identical across gateway, FakeGateway, and adapter calls. `MyPOSGatewayError(status, detail)` used consistently. Error-code mapping helper named `_map_error_code` in every task that uses it.