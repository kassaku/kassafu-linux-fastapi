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

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self.terminal_id is not None

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