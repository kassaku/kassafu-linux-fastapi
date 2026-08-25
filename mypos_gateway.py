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
import json
import logging
import os
import re
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _mask_secrets(text: str) -> str:
    text = re.sub(r'(?i)(client_secret["\s=:]+)[^&"\s]+', r"\1***", text)
    text = re.sub(r'"access_token"\s*:\s*"[^"]*"', '"access_token": "***"', text)
    text = re.sub(r'"session"\s*:\s*"[^"]*"', '"session": "***"', text)
    text = re.sub(r"Bearer\s+[^\"\s]+", "Bearer ***", text)
    return text


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
        partner = config.get("partner", {})
        self.partner_client_id = partner.get("client_id", "")
        self.partner_client_secret = partner.get("client_secret", "")
        self.partner_id = partner.get("partner_id", "")
        self.application_id = partner.get("application_id", "")
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
        hooks = None
        if os.environ.get("KASSAFU_HTTP_DEBUG"):
            hooks = {"request": [self._log_request], "response": [self._log_response]}
        if self._transport is not None:
            return httpx.AsyncClient(transport=self._transport, event_hooks=hooks)
        return httpx.AsyncClient(event_hooks=hooks)

    async def _log_request(self, request: httpx.Request):
        body = _mask_secrets(request.read().decode(errors="replace")) if request.content else ""
        logger.info(f"--> {request.method} {request.url} {body}")

    async def _log_response(self, response: httpx.Response):
        await response.aread()
        body = _mask_secrets(response.text[:500]) if response.content else ""
        logger.info(f"<-- HTTP {response.status_code} {response.request.url} {body}")

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
        try:
            async with self._new_client() as client:
                response = await client.post(
                    url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.partner_client_id,
                        "client_secret": self.partner_client_secret,
                    },
                    timeout=10,
                )
        except httpx.TimeoutException as e:
            raise MyPOSGatewayError(None, f"Timeout: {e}") from e
        except httpx.HTTPError as e:
            raise MyPOSGatewayError(None, f"Transport error: {e}") from e
        if response.status_code in (200, 201):
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                raise MyPOSGatewayError(response.status_code, f"Malformed token response: {e}") from e
            access_token = data.get("access_token")
            if not access_token:
                raise MyPOSGatewayError(response.status_code, 'Token response missing "access_token"')
            expires_in = data.get("expires_in", 3600)
            self._integration_token_expires = datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in - 60))
            return access_token
        raise MyPOSGatewayError(response.status_code, f"Token request failed: HTTP {response.status_code}: {response.text[:200]}")

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
        payload = {
            "client_id": self.merchant_client_id,
            "client_secret": self.merchant_client_secret,
        }
        try:
            async with self._new_client() as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    content=json.dumps(payload),
                    timeout=10,
                )
        except httpx.TimeoutException as e:
            raise MyPOSGatewayError(None, f"Timeout: {e}") from e
        except httpx.HTTPError as e:
            raise MyPOSGatewayError(None, f"Transport error: {e}") from e
        if response.status_code in (200, 201):
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                raise MyPOSGatewayError(response.status_code, f"Malformed session response: {e}") from e
            session = data.get("session")
            if not session:
                raise MyPOSGatewayError(response.status_code, 'Session response missing "session"')
            expires_in = data.get("expires_in", 360)
            self._session_expires = datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in - 30))
            return session
        raise MyPOSGatewayError(response.status_code, f"Session request failed: HTTP {response.status_code}: {response.text[:200]}")

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
            kwargs = {}
            if body is not None:
                kwargs["content"] = json.dumps(body)
            try:
                async with self._new_client() as client:
                    response = await client.request(
                        method, url, headers=headers, params=params, timeout=15, **kwargs
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