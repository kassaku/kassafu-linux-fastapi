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