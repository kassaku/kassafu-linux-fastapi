"""
SumUp Terminal Handler - Pure class without environment awareness

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
from datetime import datetime
from typing import Dict, Optional

from sumup import AsyncSumup
from sumup.readers.resource import (
    CreateReaderCheckoutBodyTotalAmountInput,
)

logger = logging.getLogger(__name__)


class SumUpTerminal:
    """Handler for SumUp Solo terminal operations"""
    
    def __init__(self):
        """
        Initialize the SumUp terminal handler with dummy/default values.
        Must call init() with proper configuration before use.
        """
        # Dummy/default values
        self.api_key = ""
        self.merchant_code = ""
        self.reader_id = None
        self.client = None
        self._is_ready = False
        
        # Configuration storage
        self.app_config = {}
        self.sumup_config = {}
        
        # Current payment tracking (for status endpoint)
        self.current_order_id = None
        self.current_transaction_id = None
        self.current_amount_cents = None
        self.current_currency = None
        self.current_status = None
        self.current_created_at = None
    
    def init(self, config: Dict) -> bool:
        """
        Initialize the terminal with configuration from JSON.
        
        Expected config structure:
        {
            "app": {"name": "KassaFu", "mode": "real"},
            "sumup": {
                "api_key": "your_sumup_api_key_here",
                "merchant_code": "MN2RA8M1",
                "reader_id": "rdr_6P0860A4S186MV3FHM2Q185AD7",
                "timeout_seconds": 30
            }
        }
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Store configuration
            self.app_config = config.get("app", {})
            self.sumup_config = config.get("sumup", {})
            
            # Extract values
            self.api_key = self.sumup_config.get("api_key", "")
            self.merchant_code = self.sumup_config.get("merchant_code", "")
            self.reader_id = self.sumup_config.get("reader_id", None)
            
            # Validate required fields
            if not self.api_key:
                logger.error("Missing sumup.api_key in configuration")
                return False
            
            if not self.merchant_code:
                logger.error("Missing sumup.merchant_code in configuration")
                return False
            
            # Initialize AsyncSumup client
            self.client = AsyncSumup(api_key=self.api_key)
            
            # Set ready flag if reader_id is provided
            if self.reader_id:
                self._is_ready = True
                logger.info(f"✅ Terminal configured with reader: {self.reader_id}")
            else:
                logger.info("No reader_id provided, auto-discovery will be used")
                self._is_ready = False
            
            logger.info(f"Terminal initialized with merchant: {self.merchant_code}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize terminal: {e}")
            return False
    
    def update_config(self, config: Dict) -> bool:
        """
        Update configuration (alias for init() that can be called after initialization).
        Useful for reconfiguring without recreating the object.
        
        Returns:
            True if update successful, False otherwise
        """
        return self.init(config)
    
    def get_config(self) -> Dict:
        """
        Get current configuration (excludes sensitive data like api_key).
        
        Returns:
            Dictionary with current configuration
        """
        return {
            "app": self.app_config,
            "sumup": {
                "merchant_code": self.merchant_code,
                "reader_id": self.reader_id,
                "timeout_seconds": self.sumup_config.get("timeout_seconds", 30)
            }
        }
    
    def clear_current_payment(self):
        """Clear the current active payment"""
        self.current_order_id = None
        self.current_transaction_id = None
        self.current_amount_cents = None
        self.current_currency = None
        self.current_status = None
        self.current_created_at = None
        logger.debug("Cleared current payment")
    
    async def discover_reader(self) -> bool:
        """
        Discover the Solo terminal from the merchant account.
        
        Returns:
            True if Solo terminal found, False otherwise
        """
        if not self.client:
            logger.error("Terminal not initialized. Call init() first.")
            return False
        
        try:
            readers = await self.client.readers.list(self.merchant_code)
            logger.info(f"Found {len(readers.items)} reader(s)")
            
            solo = next((reader for reader in readers.items if reader.device.model == "solo"), None)
            if solo:
                self.reader_id = solo.id
                self._is_ready = True
                logger.info(f"✅ Found Solo terminal: {self.reader_id}")
                return True
            else:
                logger.warning("⚠️ No Solo terminal found")
                return False
        except Exception as e:
            logger.error(f"Failed to discover Solo terminal: {e}")
            return False
    
    async def check_status(self) -> Dict:
        """
        Check if the Solo terminal is online and ready.
        
        Returns:
            Dict with status information including online status, battery level, etc.
        """
        if not self.reader_id:
            return {"online": False, "ready": False, "error": "No reader ID configured"}
        
        if not self.api_key:
            return {"online": False, "ready": False, "error": "No API key configured"}
        
        url = f"https://api.sumup.com/v0.1/merchants/{self.merchant_code}/readers/{self.reader_id}/status"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    status_data = response.json()
                    device_status = status_data.get("data", {})
                    
                    is_online = device_status.get("status") == "ONLINE"
                    is_idle = device_status.get("state") == "IDLE"
                    
                    return {
                        "online": is_online,
                        "ready": is_online and is_idle,
                        "battery": device_status.get("battery_level"),
                        "connection": device_status.get("connection_type"),
                        "firmware": device_status.get("firmware_version"),
                        "last_activity": device_status.get("last_activity"),
                        "state": device_status.get("state"),
                    }
                else:
                    return {"online": False, "ready": False, "error": f"HTTP {response.status_code}"}
            except Exception as e:
                return {"online": False, "ready": False, "error": str(e)}
    
    
    async def get_transaction_status(self, transaction_id: str) -> str:
        """
        Query the status of a transaction from SumUp API.
        Returns: "SUCCESSFUL", "FAILED", "CANCELLED", "PENDING", or "NOT_FOUND"
        """
        if not self.client:
            return "PENDING"

        url = f"https://api.sumup.com/v2.1/merchants/{self.merchant_code}/transactions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"client_transaction_id": transaction_id}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, params=params, timeout=5)

                if response.status_code == 200:
                    data = response.json()
                    
                    # The SumUp API returns either:
                    # 1. A single transaction object (when querying by client_transaction_id)
                    # 2. An array in "items" (when listing all transactions)
                    
                    # Check if this is a direct transaction object (has 'status' field)
                    if isinstance(data, dict) and "status" in data:
                        status = data.get("status")
                        logger.info(f"Transaction {transaction_id} status: {status}")
                        
                        if status == "SUCCESSFUL":
                            return "SUCCESSFUL"
                        elif status in ["FAILED", "CANCELLED"]:
                            return status
                        else:
                            return "PENDING"
                    
                    # Check for items array (list response)
                    transactions = data.get("items", []) or data.get("transactions", [])
                    if transactions and len(transactions) > 0:
                        transaction = transactions[0]
                        status = transaction.get("status")
                        logger.info(f"Transaction {transaction_id} status: {status}")
                        
                        if status == "SUCCESSFUL":
                            return "SUCCESSFUL"
                        elif status in ["FAILED", "CANCELLED"]:
                            return status
                        else:
                            return "PENDING"
                    else:
                        # No transaction found - this means checkout was created but
                        # the payment hasn't been attempted yet (still waiting for card)
                        logger.info(f"No transaction found for {transaction_id}, assuming PENDING")
                        return "PENDING"
                        
                elif response.status_code == 404:
                    # No transaction yet - payment still pending
                    logger.info(f"Transaction {transaction_id} not found (404), assuming PENDING")
                    return "PENDING"
                else:
                    logger.warning(f"Status check failed with HTTP {response.status_code}")
                    return "PENDING"
                    
            except Exception as e:
                logger.error(f"Status check error: {e}")
                return "PENDING"            
        
        
    async def process_payment(self, order_id: str, amount_cents: int, currency: str = "EUR") -> Dict:
        """
        Process a payment on the Solo terminal.
        
        Args:
            order_id: Unique order identifier
            amount_cents: Amount in cents (e.g., 10 for €0.10)
            currency: Currency code (default: EUR)
        
        Returns:
            Dict with payment result
        """
        start_time = datetime.now()
        
        # Store current payment info
        self.current_order_id = order_id
        self.current_amount_cents = amount_cents
        self.current_currency = currency
        self.current_status = "pending"
        self.current_created_at = start_time
        
        if not self.client:
            self.clear_current_payment()
            return {
                "success": False,
                "status": "failed",
                "message": "Terminal not initialized. Call init() first."
            }
        
        if not self.reader_id:
            self.clear_current_payment()
            return {
                "success": False,
                "status": "failed",
                "message": "No Solo terminal connected"
            }
        
        logger.info(f"Processing payment for order {order_id}: {amount_cents/100} {currency}")
        
        try:
            # Get timeout from config (default 30 seconds)
            timeout_seconds = self.sumup_config.get("timeout_seconds", 30)
            
            # Create amount object
            amount_obj = CreateReaderCheckoutBodyTotalAmountInput(
                value=amount_cents,
                currency=currency,
                minor_unit=2
            )
            
            # Create checkout with timeout
            checkout = await asyncio.wait_for(
                self.client.readers.create_checkout(
                    self.merchant_code,
                    self.reader_id,
                    total_amount=amount_obj,
                    description=f"Order {order_id}"
                ),
                timeout=timeout_seconds
            )
            
            self.current_transaction_id = checkout.data.client_transaction_id
            logger.info(f"✅ Checkout created: {self.current_transaction_id}")
            
            # Log transaction
            self._log_transaction(order_id, amount_cents, currency, self.current_transaction_id, start_time)
            
            return {
                "success": True,
                "transaction_id": self.current_transaction_id,
                "status": "pending",
                "message": "Payment initiated on Solo terminal"
            }
            
        except asyncio.TimeoutError:
            logger.error(f"Payment timeout after {timeout_seconds} seconds")
            self.current_status = "failed"
            return {
                "success": False,
                "status": "failed",
                "message": f"Timeout after {timeout_seconds} seconds"
            }
        except Exception as e:
            logger.error(f"Payment failed: {e}")
            self.current_status = "failed"
            return {
                "success": False,
                "status": "failed",
                "message": str(e)
            }
    
    
    async def get_reader_state(self) -> str:
        """
        Get the current state of the reader (IDLE, WAITING_FOR_CARD, etc.)
        Returns empty string if unknown or error.
        """
        if not self.reader_id or not self.api_key:
            return ""
    
        url = f"https://api.sumup.com/v0.1/merchants/{self.merchant_code}/readers/{self.reader_id}/status"
        headers = {"Authorization": f"Bearer {self.api_key}"}
    
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=5)
            
                if response.status_code == 200:
                    status_data = response.json()
                    device_status = status_data.get("data", {})
                    state = device_status.get("state", "")
                
                    # Also check if online - if offline, payment cannot succeed
                    is_online = device_status.get("status") == "ONLINE"
                    if not is_online and self.current_status == "pending":
                        logger.warning("Reader went offline during payment")
                        self.current_status = "failed"
                
                    return state
                else:
                    return ""
            except Exception as e:
                logger.error(f"Failed to get reader state: {e}")
                return ""
         

    def _log_transaction(self, order_id: str, amount_cents: int, currency: str, transaction_id: str, start_time: datetime):
        """Log transaction to file"""
        with open('transactions.log', 'a') as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "order_id": order_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "status": "pending",
                "transaction_id": transaction_id,
                "duration_sec": (datetime.now() - start_time).total_seconds()
            }) + '\n')
    
    @property
    def is_ready(self) -> bool:
        """Check if terminal is configured and ready"""
        return self._is_ready and self.reader_id is not None and self.client is not None
        
