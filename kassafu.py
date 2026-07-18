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
import json
import sys
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from sumup_terminal import SumUpTerminal

# Configuration file
CONFIG_FILE = "config.json"

# Load configuration from JSON file
def load_config_from_file(config_path: str = CONFIG_FILE) -> dict:
    """Load configuration from JSON file"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"✅ Loaded configuration from {config_path}")
        return config
    except FileNotFoundError:
        logger.error(f"❌ Config file {config_path} not found")
        logger.error(f"   Please create {config_path} with your SumUp credentials")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"❌ Invalid JSON in {config_path}: {e}")
        sys.exit(1)

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

# Load configuration
config = load_config_from_file()

# Extract configuration values
APP_MODE = config.get("app", {}).get("mode", "real")
SUMUP_API_KEY = config.get("sumup", {}).get("api_key", "")
SUMUP_MERCHANT_CODE = config.get("sumup", {}).get("merchant_code", "")
SUMUP_READER_ID = config.get("sumup", {}).get("reader_id", "")
PORT = 8888

# Global variables
terminal: Optional[SumUpTerminal] = None
payment_queue = asyncio.Queue()
active_payment = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global terminal
    
    logger.info(f"KassaFu starting in {APP_MODE} mode on port {PORT}")
    
    # Validate configuration
    if not SUMUP_API_KEY:
        logger.error("Missing sumup.api_key in configuration")
        logger.error("Please edit config.json and add your SumUp API key")
        raise RuntimeError("SUMUP_API_KEY is required")
    
    if not SUMUP_MERCHANT_CODE:
        logger.error("Missing sumup.merchant_code in configuration")
        logger.error("Please edit config.json and add your merchant code")
        raise RuntimeError("SUMUP_MERCHANT_CODE is required")
    
    # Initialize terminal (no constructor parameters!)
    terminal = SumUpTerminal()
    
    # Initialize with configuration
    if not terminal.init(config):
        logger.error("Failed to initialize terminal with configuration")
        raise RuntimeError("Terminal initialization failed")
    
    # Discover reader if not manually specified
    if not terminal.reader_id:
        logger.info("No reader ID provided, discovering...")
        await terminal.discover_reader()
        if not terminal.reader_id:
            logger.warning("⚠️ No Solo terminal found. Please check your SumUp account.")
    
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
                "message": "Payment in progress, request queued",
                "error_code": 108012
            }
        )
    
    # Process payment immediately
    result = await terminal.process_payment(
        order_id=payment_data['order_id'],
        amount_cents=payment_data['amount_cents'],
        currency=payment_data.get('currency', 'EUR')
    )
    
    return result


TRANSACTION_LOG = "transactions.log"


@app.get("/payment/history")
async def get_payment_history(limit: int = 20):
    """Return the last N transactions from the transaction log"""
    try:
        with open(TRANSACTION_LOG, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {"items": [], "error_code": 0}

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entries.append(entry)
            if len(entries) >= limit:
                break
        except json.JSONDecodeError:
            continue

    return {"items": entries, "error_code": 0}


@app.get("/payment/status")
async def get_payment_status(order_id: str):
    """
    Get payment status for an order.
    POS calls this every few seconds to check if payment is complete.
    """
    global terminal
    
    if not terminal:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Terminal not ready", "error_code": 108008}
        )
    
    # Check if terminal has a current payment
    if not terminal.current_order_id:
        return {
            "status": "idle",
            "message": "No active payment",
            "error_code": 0
        }
    
    # If this order_id doesn't match current payment
    if terminal.current_order_id != order_id:
        return {
            "status": "not_found",
            "message": f"No payment found for order {order_id}",
            "error_code": 108002
        }
    
    # If payment already completed or failed, return cached status
    if terminal.current_status in ["paid", "failed", "cancelled"]:
        return {
            "status": terminal.current_status,
            "order_id": terminal.current_order_id,
            "amount": terminal.current_amount_cents / 100,
            "currency": terminal.current_currency,
            "message": "Payment completed" if terminal.current_status == "paid" else "Payment failed",
            "error_code": 0 if terminal.current_status == "paid" else 108009
        }
    
    # Check transaction status with SumUp API
    if terminal.current_transaction_id:
        transaction_status = await terminal.get_transaction_status(terminal.current_transaction_id)
        
        if transaction_status == "SUCCESSFUL":
            terminal.current_status = "paid"
            terminal._log_status_update(order_id, terminal.current_transaction_id or "", "paid")
            logger.info(f"✅ Payment for order {order_id} completed")
            return {
                "status": "paid",
                "order_id": terminal.current_order_id,
                "amount": terminal.current_amount_cents / 100,
                "currency": terminal.current_currency,
                "message": "Payment completed successfully",
                "error_code": 0
            }
        
        elif transaction_status in ["FAILED", "CANCELLED"]:
            terminal.current_status = "failed"
            terminal._log_status_update(order_id, terminal.current_transaction_id or "", "failed")
            
            # Determine specific error message
            # Try to get more details from the transaction if available
            error_message = "Card rejected - please try another payment method"
            
            # You can enhance this by checking the actual API response
            # For now, use a generic message
            logger.warning(f"❌ Payment for order {order_id} {transaction_status}")
            
            return {
                "status": "failed",
                "order_id": terminal.current_order_id,
                "amount": terminal.current_amount_cents / 100,
                "currency": terminal.current_currency,
                "message": error_message,
                "error_code": 108009
            }
        
        else:
            # Still pending
            return {
                "status": "pending",
                "order_id": terminal.current_order_id,
                "amount": terminal.current_amount_cents / 100,
                "currency": terminal.current_currency,
                "error_code": 0
            }
    
    # No transaction ID yet - still pending
    return {
        "status": "pending",
        "order_id": terminal.current_order_id,
        "amount": terminal.current_amount_cents / 100,
        "currency": terminal.current_currency,
        "error_code": 0
    }


@app.api_route("/payment/cancel", methods=["GET", "DELETE"])
async def cancel_payment(order_id: str):
    global terminal

    if not terminal:
        return JSONResponse(status_code=503, content={"status": "error", "message": "Terminal not ready", "error_code": 108008})

    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order_id query parameter")

    result = await terminal.cancel_payment(order_id)

    if terminal:
        await terminal.clear_display()

    if not result.get("success"):
        return JSONResponse(status_code=404 if result.get("status") == "not_found" else 200, content=result)

    logger.info(f"Payment for order {order_id} cancelled via API")
    return result


@app.get("/health")
async def health():
    """Health check endpoint"""
    if not terminal:
        return {
            "status": "initializing",
            "mode": APP_MODE,
            "terminal_ready": False,
            "error_code": 0
        }
    
    return {
        "status": "healthy",
        "mode": APP_MODE,
        "terminal_ready": terminal.is_ready,
        "reader_id": terminal.reader_id,
        "error_code": 0
    }


@app.get("/reader/status")
async def get_reader_status():
    """Check if the Solo terminal is online and ready"""
    if not terminal or not terminal.reader_id:
        return {
            "status": "error",
            "message": "No Solo terminal configured",
            "error_code": 108010
        }
    
    status = await terminal.check_status()
    return status


@app.get("/config")
async def get_config():
    """Return the current runtime configuration (API key excluded)"""
    if not terminal:
        return {"app": {"mode": APP_MODE}, "sumup": {}}
    cfg = terminal.get_config()
    cfg["app"]["mode"] = APP_MODE
    return cfg


@app.post("/config")
async def update_config(new_config: dict):
    """Update configuration at runtime (in-memory only, does not persist across restarts)"""
    global APP_MODE, SUMUP_API_KEY, SUMUP_MERCHANT_CODE, SUMUP_READER_ID, config

    if "app" in new_config:
        config["app"].update(new_config["app"])
        APP_MODE = config["app"].get("mode", "real")

    if "sumup" in new_config:
        config["sumup"].update(new_config["sumup"])
        SUMUP_API_KEY = config["sumup"].get("api_key", SUMUP_API_KEY)
        SUMUP_MERCHANT_CODE = config["sumup"].get("merchant_code", SUMUP_MERCHANT_CODE)
        SUMUP_READER_ID = config["sumup"].get("reader_id", SUMUP_READER_ID)

    if not terminal.update_config(config):
        raise HTTPException(status_code=400, detail="Invalid configuration")

    if not terminal.reader_id:
        await terminal.discover_reader()

    return {"success": True, "message": "Configuration updated"}


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="KassaFu Payment Bridge")
    parser.add_argument("--server", action="store_true", help="Run in server mode")
    parser.add_argument("--config", type=str, default="config.json", help="Configuration file path")
    parser.add_argument("--port", type=int, help="Override port (default: 8888)")
    args = parser.parse_args()
    
    # Update CONFIG_FILE if specified
    if args.config != "config.json":
        CONFIG_FILE = args.config
        config = load_config_from_file(CONFIG_FILE)
    
    # Override port if specified
    port = args.port if args.port else 8888
    
    if args.server:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    else:
        print("Usage: python3 kassafu.py --server")
        print("Optional: --config /path/to/config.json")
        print("Optional: --port 8888")
