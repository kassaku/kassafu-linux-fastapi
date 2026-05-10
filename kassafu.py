#!/usr/bin/env python3
"""
KassaFu - Payment bridge between POS and SumUp Solo terminal

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
import os
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

from sumup_terminal import SumUpTerminal

load_dotenv()

# Configuration from environment
SUMUP_API_KEY = os.getenv('SUMUP_API_KEY', '')
SUMUP_MERCHANT_CODE = os.getenv('SUMUP_MERCHANT_CODE', '')
SUMUP_READER_ID = os.getenv('SUMUP_READER_ID', '')  # Optional
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
terminal: Optional[SumUpTerminal] = None
payment_queue = asyncio.Queue()
active_payment = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global terminal
    
    logger.info(f"KassaFu starting in {SUMUP_MODE} mode on port {PORT}")
    
    # Validate configuration
    if not SUMUP_API_KEY:
        logger.error("Missing SUMUP_API_KEY in environment")
        raise RuntimeError("SUMUP_API_KEY is required")
    
    if not SUMUP_MERCHANT_CODE:
        logger.error("Missing SUMUP_MERCHANT_CODE in environment")
        raise RuntimeError("SUMUP_MERCHANT_CODE is required")
    
    # Initialize terminal with environment values
    terminal = SumUpTerminal(
        api_key=SUMUP_API_KEY,
        merchant_code=SUMUP_MERCHANT_CODE,
        reader_id=SUMUP_READER_ID if SUMUP_READER_ID else None
    )
    
    # Discover reader if not manually specified
    if not terminal.reader_id:
        logger.info("No reader ID provided, discovering...")
        await terminal.discover_reader()
    else:
        terminal._is_ready = True
        logger.info(f"✅ Using configured Solo terminal: {terminal.reader_id}")
    
    # Start payment queue processor
    asyncio.create_task(process_payment_queue())
    
    yield
    
    logger.info("KassaFu shutting down")


app = FastAPI(lifespan=lifespan)


async def process_payment_queue():
    """Process queued payments one at a time"""
    global active_payment, terminal
    
    while True:
        payment_data = await payment_queue.get()
        active_payment = True
        try:
            result = await terminal.process_payment(
                order_id=payment_data['order_id'],
                amount_cents=payment_data['amount_cents'],
                currency=payment_data.get('currency', 'EUR')
            )
            logger.info(f"Payment result: {result}")
        except Exception as e:
            logger.error(f"Error processing queued payment: {e}")
        finally:
            active_payment = False
            payment_queue.task_done()


@app.post("/pay")
async def pay(payment_data: dict):
    """Accept payment request from POS"""
    global active_payment, terminal
    
    # Validate required fields
    required = ['order_id', 'amount_cents', 'currency']
    for field in required:
        if field not in payment_data:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
    
    # Check if terminal is ready
    if not terminal or not terminal.is_ready:
        raise HTTPException(status_code=503, detail="Terminal not ready")
    
    # Queue if active payment in progress
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
    
    # Process payment immediately
    result = await terminal.process_payment(
        order_id=payment_data['order_id'],
        amount_cents=payment_data['amount_cents'],
        currency=payment_data.get('currency', 'EUR')
    )
    
    return result


@app.get("/health")
async def health():
    """Health check endpoint"""
    if not terminal:
        return {
            "status": "initializing",
            "mode": SUMUP_MODE,
            "terminal_ready": False
        }
    
    return {
        "status": "healthy",
        "mode": SUMUP_MODE,
        "terminal_ready": terminal.is_ready,
        "reader_id": terminal.reader_id
    }


@app.get("/reader/status")
async def get_reader_status():
    """Check if the Solo terminal is online and ready"""
    if not terminal or not terminal.reader_id:
        return {
            "status": "error",
            "message": "No Solo terminal configured"
        }
    
    status = await terminal.check_status()
    return status


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")

