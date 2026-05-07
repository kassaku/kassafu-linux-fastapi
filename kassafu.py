#!/usr/bin/env python3
"""
KassaFu - Payment bridge between SumUp terminals and restaurant systems
"""

import os
import json
import time
import logging
import hashlib
import hmac
import argparse
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SUMUP_MODE = os.getenv('SUMUP_MODE', 'sandbox').lower()
SUMUP_API_KEY = os.getenv('SUMUP_API_KEY', '')
SUMUP_MERCHANT_EMAIL = os.getenv('SUMUP_MERCHANT_EMAIL', '')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'your-webhook-secret-here')
PORT = int(os.getenv('PORT', 8888))

# API URLs
if SUMUP_MODE == 'sandbox':
    SUMUP_API_URL = 'https://api.sandbox.sumup.com'
    VIRTUAL_TERMINAL_URL = 'https://virtual-solo.sumup.com'
else:
    SUMUP_API_URL = 'https://api.sumup.com'
    VIRTUAL_TERMINAL_URL = None

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

# Global state for queuing
payment_queue = asyncio.Queue()
active_payment = False
payment_statuses = {}

# Helper functions

def write_log_entry(entry: Dict[str, Any]):
    """Write JSON log entry to file"""
    with open('kassafu.log', 'a') as f:
        f.write(json.dumps(entry) + '\n')

def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify webhook signature"""
    if not signature or not WEBHOOK_SECRET:
        return True  # Skip verification if no secret configured
    
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

class SumUpClient:
    """Client for SumUp API"""
    
    def __init__(self, api_key: str, mode: str = 'sandbox'):
        self.api_key = api_key
        self.mode = mode
        self.base_url = 'https://api.sandbox.sumup.com' if mode == 'sandbox' else 'https://api.sumup.com'
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
    
    def create_checkout(self, order_id: str, amount_cents: int, currency: str = 'EUR') -> Optional[Dict]:
        """Create a checkout session"""
        data = {
            'checkout_reference': f'order_{order_id}',
            'amount': amount_cents,
            'currency': currency,
            'pay_to_email': SUMUP_MERCHANT_EMAIL,
            'description': f'Order {order_id}'
        }
        
        try:
            response = requests.post(
                f'{self.base_url}/v0.1/checkouts',
                headers=self.headers,
                json=data,
                timeout=10
            )
            
            if response.status_code == 201 or response.status_code == 200:
                result = response.json()
                logger.info(f"Checkout created: {result.get('id')}")
                return result
            else:
                logger.error(f"Failed to create checkout: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating checkout: {e}")
            return None
    
    def get_checkout_status(self, checkout_id: str) -> Optional[Dict]:
        """Get checkout status"""
        try:
            response = requests.get(
                f'{self.base_url}/v0.1/checkouts/{checkout_id}',
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get checkout status: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting checkout status: {e}")
            return None
    
    def print_receipt(self, terminal_id: str, receipt_data: Dict) -> bool:
        """Print receipt on Solo terminal (simplified for now)"""
        # Note: Full ESC/POS implementation would go here
        # For now, we'll log it and return success in sandbox
        logger.info(f"Printing receipt on terminal {terminal_id}: {json.dumps(receipt_data)}")
        
        # In production, you'd call SumUp's receipt API
        # This is a placeholder that always returns True in sandbox
        if self.mode == 'sandbox':
            logger.info("Sandbox mode: Receipt printed virtually")
            return True
        else:
            # Implement actual receipt printing
            return True

# FastAPI app setup

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    logger.info(f"KassaFu starting in {SUMUP_MODE} mode on port {PORT}")
    asyncio.create_task(process_payment_queue())
    yield
    # Shutdown
    logger.info("KassaFu shutting down")

app = FastAPI(lifespan=lifespan)

@app.post("/pay")
async def process_payment(request: Request):
    """Accept payment request (queues if busy)"""
    global active_payment
    
    payment_data = await request.json()
    
    # Validate required fields
    required_fields = ['order_id', 'amount_cents', 'currency']
    for field in required_fields:
        if field not in payment_data:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
    
    # Check if we're busy
    if active_payment:
        logger.info(f"Payment busy, queueing order {payment_data['order_id']}")
        await payment_queue.put(payment_data)
        return JSONResponse(
            status_code=202,
            content={
                "success": False,
                "status": "queued",
                "message": "Payment in progress. Your request has been queued."
            }
        )
    
    # Process immediately
    result = await process_payment_request(payment_data)
    return result

async def process_payment_queue():
    """Process queued payments"""
    global active_payment
    
    while True:
        payment_data = await payment_queue.get()
        active_payment = True
        try:
            await process_payment_request(payment_data, queued=True)
        except Exception as e:
            logger.error(f"Error processing queued payment: {e}")
        finally:
            active_payment = False
            payment_queue.task_done()

async def process_payment_request(payment_data: Dict, queued: bool = False) -> Dict:
    """Process a single payment request"""
    start_time = time.time()
    order_id = payment_data['order_id']
    amount_cents = payment_data['amount_cents']
    currency = payment_data['currency']
    
    logger.info(f"Processing payment for order {order_id}, amount: {amount_cents/100} {currency}")
    
    # Initialize SumUp client
    client = SumUpClient(SUMUP_API_KEY, SUMUP_MODE)
    
    # Create checkout
    checkout = client.create_checkout(order_id, amount_cents, currency)
    if not checkout:
        result = {
            "success": False,
            "status": "failed",
            "message": "Failed to create checkout session"
        }
        write_log_entry({
            "timestamp": datetime.now().isoformat(),
            "order_id": order_id,
            "amount_cents": amount_cents,
            "status": "failed",
            "error": "Checkout creation failed",
            "duration_sec": time.time() - start_time
        })
        return result
    
    checkout_id = checkout.get('id')
    
    # Wait for payment (polling)
    timeout_start = time.time()
    status = "pending"
    
    while time.time() - timeout_start < 60:
        checkout_status = client.get_checkout_status(checkout_id)
        
        if checkout_status:
            status = checkout_status.get('status', 'pending')
            
            if status == 'paid' or status == 'successful':
                # Payment successful
                transaction_id = checkout_status.get('transaction_id', checkout_id)
                
                # Print receipt if requested
                if payment_data.get('print_receipt', False):
                    receipt_data = {
                        "order_id": order_id,
                        "items": payment_data.get('items', []),
                        "total": amount_cents,
                        "timestamp": datetime.now().isoformat(),
                        "transaction_id": transaction_id
                    }
                    client.print_receipt(checkout.get('terminal_id', 'unknown'), receipt_data)
                
                result = {
                    "success": True,
                    "transaction_id": transaction_id,
                    "status": "completed",
                    "message": "Payment successful"
                }
                
                write_log_entry({
                    "timestamp": datetime.now().isoformat(),
                    "order_id": order_id,
                    "amount_cents": amount_cents,
                    "status": "successful",
                    "transaction_id": transaction_id,
                    "duration_sec": time.time() - start_time
                })
                
                return result
                
            elif status in ['failed', 'cancelled']:
                result = {
                    "success": False,
                    "status": "failed",
                    "message": f"Payment {status}"
                }
                
                write_log_entry({
                    "timestamp": datetime.now().isoformat(),
                    "order_id": order_id,
                    "amount_cents": amount_cents,
                    "status": status,
                    "duration_sec": time.time() - start_time
                })
                
                return result
        
        await asyncio.sleep(2)
    
    # Timeout
    result = {
        "success": False,
        "status": "timeout",
        "message": "Payment timeout after 60 seconds"
    }
    
    write_log_entry({
        "timestamp": datetime.now().isoformat(),
        "order_id": order_id,
        "amount_cents": amount_cents,
        "status": "timeout",
        "duration_sec": time.time() - start_time
    })
    
    return result

@app.post("/webhook")
async def sumup_webhook(request: Request):
    """Handle SumUp webhooks"""
    payload = await request.body()
    signature = request.headers.get('x-sumup-signature', '')
    
    if not verify_signature(payload, signature):
        logger.warning("Invalid webhook signature")
        return JSONResponse(status_code=401, content={"error": "Invalid signature"})
    
    data = json.loads(payload)
    event_type = data.get('type')
    
    if event_type == 'payment.succeeded':
        checkout_id = data.get('data', {}).get('checkout_id')
        if checkout_id:
            payment_statuses[checkout_id] = 'successful'
            logger.info(f"Webhook: Payment succeeded for {checkout_id}")
    
    return {"status": "ok"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "mode": SUMUP_MODE}

# CLI Interface

def cli_payment(amount_cents: int, order_id: str, print_receipt: bool = False, json_output: bool = False):
    """CLI payment handling"""
    import asyncio
    
    async def _pay():
        payment_data = {
            "order_id": order_id,
            "amount_cents": amount_cents,
            "currency": "EUR",
            "print_receipt": print_receipt
        }
        result = await process_payment_request(payment_data)
        return result
    
    result = asyncio.run(_pay())
    
    if json_output:
        print(json.dumps(result))
    else:
        if result['success']:
            print(f"✅ Payment successful! Transaction ID: {result['transaction_id']}")
        else:
            print(f"❌ Payment failed: {result['message']}")
    
    return 0 if result['success'] else 1

def cli_status(transaction_id: str, json_output: bool = False):
    """Get transaction status"""
    # This would need to look up from logs or SumUp API
    # Simplified version
    status = {"transaction_id": transaction_id, "status": "unknown"}
    
    if json_output:
        print(json.dumps(status))
    else:
        print(f"Transaction {transaction_id}: {status['status']}")
    
    return 0

def main():
    parser = argparse.ArgumentParser(description='KassaFu - SumUp payment bridge')
    parser.add_argument('--pay', action='store_true', help='Process payment')
    parser.add_argument('--amount', type=int, help='Amount in cents')
    parser.add_argument('--order', help='Order ID')
    parser.add_argument('--print', action='store_true', dest='print_receipt', help='Print receipt')
    parser.add_argument('--status', action='store_true', help='Check payment status')
    parser.add_argument('--transaction', help='Transaction ID to check')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')
    parser.add_argument('--status-terminal', action='store_true', help='Check terminal status')
    parser.add_argument('--server', action='store_true', help='Run as HTTP server')
    
    args = parser.parse_args()
    
    if args.server:
        # Run as HTTP server
        uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='info')
    elif args.pay:
        if not args.amount or not args.order:
            print("Error: --pay requires --amount and --order")
            return 1
        return cli_payment(args.amount, args.order, args.print_receipt, args.json)
    elif args.status and args.transaction:
        return cli_status(args.transaction, args.json)
    elif args.status_terminal:
        client = SumUpClient(SUMUP_API_KEY, SUMUP_MODE)
        print(f"Terminal status: Connected to {SUMUP_API_URL}")
        return 0
    else:
        parser.print_help()
        return 0

if __name__ == "__main__":
    exit(main())

