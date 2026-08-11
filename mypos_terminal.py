"""
myPOS Terminal Handler - ePOS API integration for KassaFu

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
import json
import httpx
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MyPOSTerminal:
    """Handler for myPOS ePOS terminal operations"""

    def __init__(self):
        self.gateway_url = ""
        self.integration_client_id = ""
        self.integration_client_secret = ""
        self.partner_id = ""
        self.application_id = ""
        self.merchant_client_id = ""
        self.merchant_client_secret = ""
        self.terminal_id = None
        self._is_ready = False

        self.app_config = {}
        self.mypos_config = {}

        self._integration_token = None
        self._integration_token_expires = None
        self._merchant_token = None
        self._merchant_token_expires = None
        self._token_lock = asyncio.Lock()

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

    async def _get_integration_token(self) -> Optional[str]:
        async with self._token_lock:
            now = datetime.now(timezone.utc)
            if self._integration_token and self._integration_token_expires and now < self._integration_token_expires:
                return self._integration_token
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.gateway_url}/oauth/token",
                        data={
                            "grant_type": "client_credentials",
                            "client_id": self.integration_client_id,
                            "client_secret": self.integration_client_secret,
                        },
                        timeout=10,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        self._integration_token = data.get("access_token")
                        expires_in = data.get("expires_in", 3600)
                        import datetime as dt
                        self._integration_token_expires = now + dt.timedelta(seconds=expires_in - 60)
                        return self._integration_token
                    else:
                        logger.error(f"Failed to get integration token: HTTP {response.status_code}")
                        return None
            except Exception as e:
                logger.error(f"Integration token error: {e}")
                return None

    async def _get_merchant_token(self) -> Optional[str]:
        integration_token = await self._get_integration_token()
        if not integration_token:
            return None

        async with self._token_lock:
            now = datetime.now(timezone.utc)
            if self._merchant_token and self._merchant_token_expires and now < self._merchant_token_expires:
                return self._merchant_token
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.gateway_url}/oauth/session",
                        headers={"Authorization": f"Bearer {integration_token}"},
                        json={
                            "clientId": self.merchant_client_id,
                            "clientSecret": self.merchant_client_secret,
                        },
                        timeout=10,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        self._merchant_token = data.get("sessionToken") or data.get("access_token")
                        expires_in = data.get("expiresIn", 300)
                        import datetime as dt
                        self._merchant_token_expires = now + dt.timedelta(seconds=expires_in - 30)
                        return self._merchant_token
                    else:
                        logger.error(f"Failed to get merchant token: HTTP {response.status_code}")
                        return None
            except Exception as e:
                logger.error(f"Merchant token error: {e}")
                return None

    async def _api_request(self, method: str, path: str, json_body: dict = None) -> Dict:
        token = await self._get_merchant_token()
        if not token:
            return {"success": False, "error_code": 108008, "message": "Authentication failed"}

        url = f"{self.gateway_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if self.partner_id:
            headers["X-Partner-ID"] = self.partner_id
        if self.application_id:
            headers["X-Application-ID"] = self.application_id

        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, headers=headers, json=json_body, timeout=15)
                if response.status_code in (200, 201):
                    return {"success": True, "data": response.json(), "error_code": 0}
                elif response.status_code == 404:
                    return {"success": False, "error_code": 108002, "message": "Not found"}
                elif response.status_code == 401:
                    self._merchant_token = None
                    self._merchant_token_expires = None
                    return {"success": False, "error_code": 108003, "message": "Unauthorized"}
                else:
                    body = response.text
                    return {"success": False, "error_code": 108011, "message": f"HTTP {response.status_code}: {body[:200]}"}
        except Exception as e:
            return {"success": False, "error_code": 108001, "message": str(e)}

    async def discover_reader(self) -> bool:
        result = await self._api_request("GET", "/epos/terminals")
        if result.get("success"):
            terminals = result.get("data", {}).get("items", [])
            if terminals:
                self.terminal_id = terminals[0].get("terminalId")
                self._is_ready = True
                logger.info(f"Discovered myPOS terminal: {self.terminal_id}")
                return True
            logger.warning("No myPOS terminals found")
            return False
        logger.warning(f"Failed to discover terminals: {result.get('message')}")
        return False

    async def check_status(self) -> Dict:
        if not self.terminal_id:
            return {"online": False, "ready": False, "error": "No terminal ID configured", "error_code": 108010}

        result = await self._api_request("GET", f"/epos/terminals/{self.terminal_id}")
        if result.get("success"):
            data = result["data"]
            is_online = data.get("status") == "ONLINE"
            battery = data.get("batteryLevel")
            return {
                "online": is_online,
                "ready": is_online,
                "battery": battery,
                "state": data.get("status"),
            }
        return {"online": False, "ready": False, "error": result.get("message"), "error_code": result.get("error_code", 108001)}

    async def get_transaction_status(self, transaction_id: str) -> str:
        result = await self._api_request("GET", f"/epos/payments/{transaction_id}")
        if result.get("success"):
            data = result["data"]
            status = data.get("status", "PENDING")
            if status == "SUCCESSFUL":
                card = data.get("card", {})
                self.current_card_scheme = card.get("type") or card.get("scheme")
                self.current_card_last_4 = card.get("last4") or card.get("last_4_digits")
                return "SUCCESSFUL"
            elif status in ("FAILED", "CANCELLED", "REVERSED"):
                return status
            return "PENDING"
        return "PENDING"

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

        result = await self._api_request("POST", "/epos/payments", {
            "amount": {
                "value": amount_cents,
                "currencyCode": currency,
            },
            "terminalId": self.terminal_id,
            "appName": "KassaFu",
            "appVersion": "1.0.0",
        })

        if result.get("success"):
            data = result["data"]
            self.current_transaction_id = data.get("paymentId")
            logger.info(f"myPOS payment initiated: {self.current_transaction_id}")
            self._log_transaction(order_id, amount_cents, currency, self.current_transaction_id or "", start_time)
            return {
                "success": True,
                "transaction_id": self.current_transaction_id,
                "status": "pending",
                "message": "Payment initiated on myPOS terminal",
                "error_code": 0,
            }
        else:
            self.current_status = "failed"
            self._log_status_update(order_id, self.current_transaction_id or "", "failed", result.get("message", ""))
            return {
                "success": False,
                "status": "failed",
                "message": result.get("message", "Payment failed"),
                "error_code": result.get("error_code", 108001),
            }

    async def cancel_payment(self, order_id: str) -> Dict:
        if not self.current_order_id:
            return {"success": False, "status": "not_found", "message": "No active payment", "error_code": 108002}
        if self.current_order_id != order_id:
            return {"success": False, "status": "not_found", "message": f"No payment for order {order_id}", "error_code": 108002}
        if self.current_status in ("paid", "failed", "cancelled"):
            return {"success": True, "status": self.current_status, "message": f"Already {self.current_status}", "error_code": 0}

        if self.current_transaction_id:
            result = await self._api_request("POST", f"/epos/payments/{self.current_transaction_id}/reverse", {
                "description": "Cancelled by POS",
            })
            if result.get("success"):
                self.current_status = "cancelled"
                self._log_status_update(order_id, self.current_transaction_id or "", "cancelled")
                logger.info(f"myPOS payment for order {order_id} cancelled")
                return {"success": True, "status": "cancelled", "message": "Payment cancelled", "error_code": 0}

        self.current_status = "cancelled"
        return {"success": True, "status": "cancelled", "message": "Payment cancelled (local)", "error_code": 0}

    async def clear_display(self):
        pass

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

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self.terminal_id is not None
