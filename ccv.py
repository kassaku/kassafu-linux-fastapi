"""
CCV Cloud Connect (Attended) Terminal Handler
Gebaseerd op CCV VPOS PSP API v2.2

Copyright (c) 2026 Houkes Horeca Applications
"""

import asyncio
import logging
import json
import base64
import uuid
import httpx
from datetime import datetime
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
import uvicorn
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class CCVCloudConnect:
    """
    Handler voor CCV Cloud Connect (Attended) interface.
    Implementeert VPOS PSP API v2.2
    """
    
    def __init__(self):
        """Initialize de CCV Cloud Connect handler."""
        # Configuratie
        self.api_key = ""
        self.environment = "test"  # test of production
        self.base_url = ""
        
        # Terminal configuratie (verplicht volgens API)
        self.terminal_id = None      # TMS Terminal ID (10 chars)
        self.management_system_id = None  # "GrundmasterNL" of "GrundmasterBE"
        self.access_protocol = "OPI_NL"
        
        self._is_ready = False
        
        # Huidige payment tracking
        self.current_reference = None
        self.current_order_id = None
        self.current_amount = None
        self.current_currency = None
        self.current_status = None
        self.current_created_at = None
        
        # Timeout settings (API spec: 6 minuten max)
        self.transaction_timeout = 360  # 6 minuten
        
    def init(self, config: Dict) -> bool:
        """
        Initialiseer met configuratie volgens API spec.
        
        Verwacht config formaat:
        {
            "app": {"name": "KassaFu"},
            "ccv": {
                "api_key": "l_your_live_key_of t_your_test_key",
                "environment": "test",  # of "production"
                "terminal_id": "J4S009",  # TMS TID van de pinterminal
                "management_system_id": "GrundmasterNL-ThirdPartyTest",  # Test
                "access_protocol": "OPI_NL"
            }
        }
        """
        try:
            self.app_config = config.get("app", {})
            self.ccv_config = config.get("ccv", {})
            
            self.api_key = self.ccv_config.get("api_key", "")
            self.environment = self.ccv_config.get("environment", "test")
            self.terminal_id = self.ccv_config.get("terminal_id")
            self.management_system_id = self.ccv_config.get("management_system_id")
            self.access_protocol = self.ccv_config.get("access_protocol", "OPI_NL")
            
            # Bepaal base URL volgens API spec
            if self.environment == "production":
                self.base_url = "https://api.psp.ccv.eu/api/v1"
            else:  # test
                self.base_url = "https://vpos-test.jforce.be/vpos/api/v1"
            
            # Validatie volgens API spec
            if not self.api_key:
                logger.error("Missing ccv.api_key in configuratie")
                return False
            
            if not self.terminal_id:
                logger.error("Missing ccv.terminal_id (TMS TID)")
                return False
            
            if not self.management_system_id:
                logger.error("Missing ccv.management_system_id")
                return False
            
            # Check of API key type matcht met environment
            if self.environment == "production" and not self.api_key.startswith("l_"):
                logger.error("Production environment requires LIVE key (starting with 'l_')")
                return False
            elif self.environment == "test" and self.api_key.startswith("l_"):
                logger.info("Using LIVE key in test environment (real test terminal)")
            elif self.environment == "test" and self.api_key.startswith("t_"):
                logger.info("Using TEST key in test environment (simulated terminal)")
            
            self._is_ready = True
            logger.info(f"✅ CCV Cloud Connect geconfigureerd")
            logger.info(f"   Environment: {self.environment}")
            logger.info(f"   Base URL: {self.base_url}")
            logger.info(f"   Terminal ID: {self.terminal_id}")
            logger.info(f"   Management System: {self.management_system_id}")
            return True
            
        except Exception as e:
            logger.error(f"Initialisatie mislukt: {e}")
            return False
    
    def _get_auth_header(self) -> Dict:
        """Genereer Basic Authentication header (API spec section 5.2)."""
        # username = API key, password = leeg
        credentials = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}
    
    def _generate_idempotency_reference(self) -> str:
        """
        Genereer Idempotency-Reference (API spec section 5.2.1).
        Minimum 6 karakters, UUID wordt aangeraden.
        """
        return str(uuid.uuid4())
    
    async def create_payment(self, order_id: str, amount_cents: int, 
                            currency: str = "EUR",
                            return_url: str = None,
                            webhook_url: str = None,
                            merchant_language: str = "NLD") -> Dict:
        """
        CreateNewTransactionRequest voor Sale (API spec section 5.6.1.1).
        
        Args:
            order_id: Uniek ordernummer (wordt merchantOrderReference)
            amount_cents: Bedrag in centen (wordt omgezet naar decimalen)
            currency: Valuta (EUR, GBP, etc.)
            return_url: URL voor redirect na betaling
            webhook_url: URL voor webhook notificaties
            merchant_language: Taal voor cashier (NLD, ENG, DEU, FRA)
        """
        # Converteer centen naar decimaal formaat (API spec: "0.10")
        amount_decimal = amount_cents / 100
        amount_str = f"{amount_decimal:.2f}".replace(",", ".")
        
        if not return_url:
            return_url = f"http://localhost:8080/return?order={order_id}"
        if not webhook_url:
            webhook_url = "http://localhost:8080/webhook"
        
        # Bouw request volgens API spec section 5.6.1.1
        payload = {
            "currency": currency.lower(),
            "amount": amount_str,  # String formaat met punt!
            "method": "terminal",
            "language": "nld",  # Cardholder taal
            "returnUrl": return_url,
            "webhookUrl": webhook_url,
            "details": {
                "operatingEnvironment": "ATTENDED",  # Voor cashier bediening
                "merchantLanguage": merchant_language,  # Taal voor cashier
                "managementSystemId": self.management_system_id,
                "terminalId": self.terminal_id,
                "accessProtocol": self.access_protocol
            }
        }
        
        # Idempotency header (API spec 5.2.1)
        idempotency_ref = self._generate_idempotency_reference()
        
        logger.info(f"CreateNewTransactionRequest voor order {order_id}")
        logger.info(f"  Amount: {amount_str} {currency}")
        logger.info(f"  Terminal: {self.terminal_id}")
        logger.info(f"  Idempotency-Reference: {idempotency_ref}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/payment",
                    headers={
                        **self._get_auth_header(),
                        "Content-Type": "application/json",
                        "Idempotency-Reference": idempotency_ref,
                        "User-Agent": "CCVTerminalHandler/1.0"  # Verplicht!
                    },
                    json=payload
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # API spec section 5.6.2
                    self.current_reference = data.get("reference")
                    self.current_order_id = order_id
                    self.current_amount = amount_decimal
                    self.current_currency = currency
                    self.current_status = data.get("status", "pending")
                    self.current_created_at = datetime.now()
                    
                    logger.info(f"✅ Transaction created: {self.current_reference}")
                    logger.info(f"   Status: {self.current_status}")
                    logger.info(f"   PayURL: {data.get('payUrl')}")
                    
                    return {
                        "success": True,
                        "status": data.get("status"),
                        "reference": self.current_reference,
                        "pay_url": data.get("payUrl"),
                        "type": data.get("type"),
                        "amount": data.get("amount"),
                        "currency": data.get("currency"),
                        "message": "Transaction initiated on CCV terminal",
                        "error_code": 0
                    }
                else:
                    # Error handling volgens API spec 5.4
                    error_data = response.json() if response.text else {}
                    logger.error(f"CreateNewTransaction failed: {response.status_code}")
                    logger.error(f"  Type: {error_data.get('type')}")
                    logger.error(f"  Message: {error_data.get('message')}")
                    logger.error(f"  FailureCode: {error_data.get('failureCode')}")
                    
                    return {
                        "success": False,
                        "status": "failed",
                        "message": error_data.get("message", f"HTTP {response.status_code}"),
                        "error_code": 108011
                    }
                    
        except httpx.TimeoutException:
            logger.error("Request timeout")
            return {
                "success": False,
                "status": "failed",
                "message": "Connection timeout",
                "error_code": 108005
            }
        except Exception as e:
            logger.error(f"CreateNewTransaction error: {e}")
            return {
                "success": False,
                "status": "failed",
                "message": str(e),
                "error_code": 108001
            }
    
    async def get_transaction_status(self, reference: str) -> Dict:
        """
        ReadTransactionRequest (API spec section 5.6.4).
        Poll de status van een transactie.
        """
        if not reference:
            return {"status": "PENDING", "message": "No reference provided", "error_code": 108002}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/transaction",
                    headers={
                        **self._get_auth_header(),
                        "User-Agent": "CCVTerminalHandler/1.0"
                    },
                    params={"reference": reference}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")
                    
                    logger.info(f"ReadTransactionResponse for {reference}: {status}")
                    
                    # Update local status
                    if reference == self.current_reference:
                        self.current_status = status
                    
                    # Parse response volgens API spec 5.6.5
                    result = {
                        "status": status.upper() if status else "PENDING",
                        "reference": data.get("reference"),
                        "type": data.get("type"),
                        "amount": data.get("amount"),
                        "currency": data.get("currency"),
                        "error_code": 0,
                    }
                    
                    # Voeg receipt informatie toe indien beschikbaar
                    details = data.get("details", {})
                    if details.get("customerReceipt"):
                        result["customer_receipt"] = json.loads(details["customerReceipt"])
                    if details.get("merchantReceipt"):
                        result["merchant_receipt"] = json.loads(details["merchantReceipt"])
                    if details.get("journalReceipt"):
                        result["journal_receipt"] = json.loads(details["journalReceipt"])
                    if details.get("eJournal"):
                        result["ejournal"] = details["eJournal"]
                    if details.get("printCustomerReceipt"):
                        result["print_customer_receipt"] = details["printCustomerReceipt"]
                    if details.get("askCustomerSignature"):
                        result["ask_customer_signature"] = details["askCustomerSignature"]
                    if details.get("askCustomerIdentification"):
                        result["ask_customer_identification"] = details["askCustomerIdentification"]
                    
                    return result
                    
                elif response.status_code == 404:
                    logger.info(f"Transaction {reference} not found")
                    return {"status": "PENDING", "reference": reference, "error_code": 108002}
                else:
                    logger.warning(f"Status check failed: {response.status_code}")
                    return {"status": "PENDING", "reference": reference, "error_code": 108011}
                    
        except Exception as e:
            logger.error(f"ReadTransactionRequest error: {e}")
            return {"status": "PENDING", "reference": reference, "error_code": 108001}
    
    async def create_refund(self, original_reference: str, amount_cents: int = None,
                           return_url: str = None, webhook_url: str = None) -> Dict:
        """
        Refund transaction (API spec section 5.6.1.2).
        
        Args:
            original_reference: Reference van originele payment
            amount_cents: Bedrag in centen (optioneel, volledig bedrag als None)
        """
        amount_decimal = amount_cents / 100 if amount_cents else None
        amount_str = f"{amount_decimal:.2f}".replace(",", ".") if amount_decimal else None
        
        if not return_url:
            return_url = f"http://localhost:8080/return?refund={original_reference}"
        if not webhook_url:
            webhook_url = "http://localhost:8080/webhook"
        
        payload = {
            "reference": original_reference,  # Referentie van originele transactie
            "returnUrl": return_url,
            "webhookUrl": webhook_url,
            "details": {
                "operatingEnvironment": "ATTENDED",
                "merchantLanguage": "NLD",
                "managementSystemId": self.management_system_id,
                "terminalId": self.terminal_id,
                "accessProtocol": self.access_protocol
            }
        }
        
        if amount_str:
            payload["amount"] = amount_str  # Gedeeltelijke refund
        
        idempotency_ref = self._generate_idempotency_reference()
        
        logger.info(f"Refund transaction voor {original_reference}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/refund",
                    headers={
                        **self._get_auth_header(),
                        "Content-Type": "application/json",
                        "Idempotency-Reference": idempotency_ref,
                        "User-Agent": "CCVTerminalHandler/1.0"
                    },
                    json=payload
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "reference": data.get("reference"),
                        "original_reference": data.get("originalReference"),
                        "status": data.get("status"),
                        "pay_url": data.get("payUrl"),
                        "error_code": 0
                    }
                else:
                    error_data = response.json() if response.text else {}
                    return {
                        "success": False,
                        "message": error_data.get("message", f"HTTP {response.status_code}"),
                        "error_code": 108011
                    }
                    
        except Exception as e:
            logger.error(f"Refund error: {e}")
            return {"success": False, "message": str(e), "error_code": 108001}
    
    async def check_status(self) -> Dict:
        """Check of de API beschikbaar is."""
        if not self.api_key:
            return {"online": False, "ready": False, "error": "Geen API key", "error_code": 108003}
        
        return {
            "online": self._is_ready,
            "ready": self._is_ready,
            "environment": self.environment,
            "terminal_id": self.terminal_id,
            "error_code": 0
        }
    
    @property
    def is_ready(self) -> bool:
        return self._is_ready


# ============================================================
# FastAPI Server
# ============================================================

terminal = CCVCloudConnect()
config = {}


def load_config():
    """Laad configuratie uit config.json."""
    global config
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            return terminal.init(config)
    except FileNotFoundError:
        logger.warning("config.json niet gevonden")
        return False
    except Exception as e:
        logger.error(f"Configuratie error: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starten CCV Cloud Connect handler op poort 8080...")
    if load_config():
        logger.info("✅ Configuratie geladen")
    else:
        logger.warning("⚠️ Geen configuratie")
    yield
    logger.info("Stoppen...")


app = FastAPI(title="CCV Cloud Connect Terminal Handler", lifespan=lifespan)


@app.get("/")
async def root():
    return {
        "service": "CCV Cloud Connect",
        "api_version": "2.2",
        "status": "running",
        "terminal_ready": terminal.is_ready,
        "error_code": 0
    }


@app.post("/payment")
async def process_payment(request: Dict):
    """Start een nieuwe betaling."""
    result = await terminal.create_payment(
        order_id=request.get("order_id"),
        amount_cents=request.get("amount_cents"),
        currency=request.get("currency", "EUR"),
        return_url=request.get("return_url"),
        webhook_url=request.get("webhook_url")
    )
    
    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=500, detail=result["message"])


@app.get("/payment/{reference}")
async def payment_status(reference: str):
    """Query status van een betaling."""
    return await terminal.get_transaction_status(reference)


@app.post("/refund")
async def process_refund(request: Dict):
    """Start een refund transactie."""
    result = await terminal.create_refund(
        original_reference=request.get("original_reference"),
        amount_cents=request.get("amount_cents")
    )
    
    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=500, detail=result["message"])


@app.post("/webhook")
async def webhook(request: Dict):
    """Webhook endpoint voor CCV status updates."""
    reference = request.get("id")
    logger.info(f"Webhook ontvangen voor transaction: {reference}")
    
    # Haal volledige status op
    if reference:
        status = await terminal.get_transaction_status(reference)
        logger.info(f"Transaction {reference} status: {status.get('status')}")
    
    return {"received": True}


@app.get("/health")
async def health():
    return {"status": "healthy", "error_code": 0}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)

