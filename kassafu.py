#!/usr/bin/env python3
"""
KassaFu - Payment bridge between POS and SumUp Solo terminal
"""

import asyncio
import os
import logging
import json
from datetime import datetime
from typing import Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

# SumUp SDK imports - WITH CORRECT Input suffix
from sumup import AsyncSumup
from sumup.readers.resource import (
    CreateReaderCheckoutBodyInput,
    CreateReaderCheckoutBodyTotalAmountInput,
    CreateReaderCheckoutBodyAffiliateInput
)


load_dotenv()

# Configuration
SUMUP_API_KEY = os.getenv('SUMUP_API_KEY', '')
SUMUP_MERCHANT_CODE = os.getenv('SUMUP_MERCHANT_CODE', '')
SUMUP_MODE = os.getenv('SUMUP_MODE', 'sandbox')
PORT = int(os.getenv('PORT', 8888))

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('kassafu.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global variables
payment_queue = asyncio.Queue()
active_payment = False
solo_terminal_id = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global solo_terminal_id
    
    logger.info(f"KassaFu starting in {SUMUP_MODE} mode on port {PORT}")
    
    if SUMUP_API_KEY and SUMUP_MERCHANT_CODE:
        try:
            client = AsyncSumup(api_key=SUMUP_API_KEY)
            readers = await client.readers.list(SUMUP_MERCHANT_CODE)
            
            logger.info(f"Found {len(readers.items)} reader(s)")
            
            solo = next((reader for reader in readers.items if reader.device.model == "solo"), None)
            if solo:
                solo_terminal_id = solo.id
                logger.info(f"✅ Found Solo terminal: {solo_terminal_id}")
            else:
                logger.warning("⚠️ No Solo terminal found")
        except Exception as e:
            logger.error(f"Failed to discover Solo terminal: {e}")
    else:
        logger.warning("Missing API key or merchant code")
    
    asyncio.create_task(process_payment_queue())
    yield
    logger.info("KassaFu shutting down")

app = FastAPI(lifespan=lifespan)

async def process_payment_queue():
    """Process queued payments one at a time"""
    global active_payment
    
    while True:
        payment_data = await payment_queue.get()
        active_payment = True
        try:
            await process_payment_request(payment_data)
        except Exception as e:
            logger.error(f"Error processing queued payment: {e}")
        finally:
            active_payment = False
            payment_queue.task_done()

async def process_payment_request(payment_data: Dict) -> Dict:
    """Process a single payment request on the Solo terminal"""
    start_time = datetime.now()
    order_id = payment_data.get('order_id')
    amount_cents = payment_data.get('amount_cents', 0)
    currency = payment_data.get('currency', 'EUR')
    
    logger.info(f"Processing payment for order {order_id}: {amount_cents/100} {currency}")
    
    if not solo_terminal_id:
        return {
            "success": False,
            "status": "failed",
            "message": "No Solo terminal connected"
        }
    
    try:
        client = AsyncSumup(api_key=SUMUP_API_KEY)
        merchant_code = os.getenv('SUMUP_MERCHANT_CODE')
        print("merchant code ", merchant_code)
        reader_id = os.getenv('SUMUP_READER_ID')
    
        amount_obj = CreateReaderCheckoutBodyTotalAmountInput(value=108, currency="EUR", minor_unit=2)
        checkout_body = CreateReaderCheckoutBodyInput(total_amount=amount_obj, description="Test Kassaku")
        # Other optional fields: operator_id, payment_type
    
        # Create checkout with correct Input classes
        checkout = await client.readers.create_checkout(
            merchant_code,           # 1st positional
            solo_terminal_id,        # 2nd positional
            total_amount=amount_obj, # keyword-only
            description=f"Order KASSAKU"  # keyword-only
        )              # Direct amount object, NOT wrapped in a body!
               
        transaction_id = checkout.data.client_transaction_id
        logger.info(f"✅ Checkout created: {transaction_id}")
        
        # Log transaction
        with open('kassafu.log', 'a') as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "order_id": order_id,
                "amount_cents": amount_cents,
                "status": "pending",
                "transaction_id": transaction_id,
                "duration_sec": (datetime.now() - start_time).total_seconds()
            }) + '\n')
        
        return {
            "success": True,
            "transaction_id": transaction_id,
            "status": "pending",
            "message": "Payment initiated on Solo terminal"
        }
        
    except Exception as e:
        logger.error(f"Payment failed: {e}")
        return {
            "success": False,
            "status": "failed",
            "message": str(e)
        }

@app.post("/pay")
async def pay(payment_data: dict):
    """Accept payment request from POS"""
    global active_payment
    
    required = ['order_id', 'amount_cents', 'currency']
    for field in required:
        if field not in payment_data:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
    
    if active_payment:
        logger.info(f"Queueing payment for {payment_data['order_id']}")
        await payment_queue.put(payment_data)
        return JSONResponse(
            status_code=202,
            content={
                "success": False,
                "status": "queued",
                "message": "Payment in progress, request queued"
            }
        )
    
    return await process_payment_request(payment_data)

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "mode": SUMUP_MODE,
        "solo_connected": solo_terminal_id is not None
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")

