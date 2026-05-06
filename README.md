# Business case
The Python program will handle communication to the POS computer and to the SumUP server. It is located at the POS computer.
<img width="632" height="424" alt="image" src="https://github.com/user-attachments/assets/4528b4fc-5068-4148-a87e-8f34c3d88c3e" />

# Restaurant overview
Payments for payment terminals like SumUp, interface to Angular website as a backend.
KassaFu — The payment bridge between SumUp terminals and your restaurant system.
<img width="632" height="424" alt="image" src="https://github.com/user-attachments/assets/25eae3c6-bcdf-481e-aab4-350d7b3b29da" />

# Requirements

## Project name
KassaFu means:
    Kassa (Dutch) = cash register
    Fu (付款) = payment 

## R1 - Accept payment requests from Angular (on same PC)
Detail	Specification
Interface	HTTP REST API (not gRPC)
Port	localhost:8888
Endpoint	POST /pay
Request format	JSON
Response format	JSON
Timeout	60 seconds max
Concurrency	One payment at a time (queue others)

Example request from Angular:
```
typescript

// Angular service
const response = await fetch('http://localhost:8888/pay', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    order_id: '#2600000001',
    amount_cents: 1500,
    currency: 'EUR',
    items: [
      {name: 'Pizza Margherita', quantity: 2, price: 1250},
      {name: 'Coke', quantity: 1, price: 250}
    ],
    print_receipt: true
  })
});
const result = await response.json();
```

Example response:
```
json

{
  "success": true,
  "transaction_id": "tran_abc123",
  "status": "completed",
  "message": "Payment successful"
}
```

## R2 - Communicate with SumUp Cloud API
Detail	Specification
API base URL	https://api.sumup.com (live) or sandbox
Authentication	Bearer token (Affiliate Key)
Endpoint	POST /v0.1/checkouts
Required fields	amount, currency, description, pay_to_email
Terminal targeting	Use checkout_reference to route to specific Solo

SumUp API call example:
```
python

import requests

response = requests.post(
    "https://api.sumup.com/v0.1/checkouts",
    headers={"Authorization": f"Bearer {API_KEY}"},
    json={
        "order_id": 2600000001,
        "amount": 1500,
        "currency": "EUR",
        "description": f"Order {order_id}",
        "pay_to_email": merchant_email
    }
)
```

## R3 - Wait for payment and report status
Detail	Specification
Synchronous mode	Python script blocks until payment completes or times out
Polling	Check payment status every 2 seconds
Timeout	60 seconds (customer can walk away)
Status values	pending, successful, failed, cancelled

Status polling loop:
```
python

def wait_for_payment(checkout_id, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        status = get_checkout_status(checkout_id)
        if status == 'successful':
            return {'status': 'paid', 'transaction_id': checkout_id}
        elif status in ['failed', 'cancelled']:
            return {'status': 'failed'}
        time.sleep(2)
    return {'status': 'timeout'}
```

## R4 - Trigger receipt printing on Solo's built-in printer
Detail	Specification
Method	SumUp API after payment confirmation
Printer destination	The same Solo terminal that processed payment
Receipt content	Order details, items, total, timestamp, transaction ID
Format	Plain text + ESC/POS commands for formatting

Print request:
```
python

# After successful payment
receipt = {
    "order_id": order_id,
    "items": items,
    "total": total_cents,
    "timestamp": datetime.now().isoformat(),
    "transaction_id": transaction_id
}
# Send to printer via SumUp's receipt API (if available)
# Or print via terminal's local printer using ESC/POS
```

## R5 - Handle webhooks for async payment confirmation
Detail	Specification
Webhook endpoint	Python script must expose /webhook endpoint
Port	localhost:8888
Event types	payment.succeeded, payment.failed
Verification	Sign webhook with secret to prevent spoofing
Fallback	Polling if webhook fails

Webhook handler:
```
python

@app.post("/webhook")
async def sumup_webhook(request: Request):
    payload = await request.json()
    secret = request.headers.get("x-sumup-signature")
    
    if not verify_signature(payload, secret):
        return {"error": "Invalid signature"}
    
    if payload['type'] == 'payment.succeeded':
        update_order_status(payload['data']['checkout_id'], 'paid')
    
    return {"status": "ok"}
```

## R6 - Support sandbox mode
Detail	Specification
Activation	Environment variable SUMUP_MODE=sandbox
Sandbox API URL	https://api.sandbox.sumup.com
Virtual Solo	https://virtual-solo.sumup.com
Test card numbers	Provided by SumUp sandbox
No real money	Transactions are simulated

Configuration:
```
python

SUMUP_API_URL = os.getenv('SUMUP_API_URL', 
    'https://api.sandbox.sumup.com' if SANDBOX else 'https://api.sumup.com'
)

## R7 - Log all transactions
Detail	Specification
Log file	kassafu.log in same directory
Format	JSON lines (one per transaction)
Logged data	timestamp, order_id, amount, status, transaction_id, error (if any)
Rotation	Keep 30 days of logs
```

Log entry example:
```
json

{"timestamp":"2026-05-06T14:30:00","order_id":"ORD-1234","amount_cents":1500,"status":"successful","transaction_id":"tran_abc123","duration_sec":12.5}

## R8 - Test script: 10 cent sandbox payment (Highest priority)
Detail	Specification
File	test_kassafu.py
Amount	€0.10 (10 cents)
Mode	Sandbox only (must fail if in live mode)
Automated	No manual intervention needed
Success criteria	Creates checkout, Virtual Solo shows amount, simulates payment, confirms success
Output	Prints "✅ Test passed" or "❌ Test failed"
```

Test script skeleton:
```
python

#!/usr/bin/env python3
"""Test script for KassaFu - 10 cent sandbox payment"""

def test_payment():
    print("🧪 KassaFu Test: 10 cent sandbox payment")
    
    # 1. Initialize sandbox client
    # 2. Create checkout for €0.10
    # 3. Wait for payment (Virtual Solo needs manual tap)
    # 4. Verify success
    # 5. Print receipt
    
    print("✅ Test passed")

if __name__ == "__main__":
    test_payment()
```

## R9 - Reusable for other applications (C++, terminal, etc.)
Detail	Specification
CLI interface	python kassafu.py --pay --amount 1500 --order ORD-123
Exit codes	0 = success, 1 = failure
JSON output	When --json flag used
HTTP API	Already exposed on localhost:8888 → usable by any language
C++ usage	system() call or HTTP client library
Terminal usage	curl commands

CLI examples:
```
bash

### Simple payment
python kassafu.py --pay --amount 1500 --order ORD-123

### With receipt printing
python kassafu.py --pay --amount 1500 --order ORD-123 --print

### JSON output for scripting
python kassafu.py --status --transaction tran_abc123 --json

### Check terminal status
python kassafu.py --status-terminal
```

### C++ integration example:
```
cpp

#include <cstdlib>
std::string cmd = "python kassafu.py --pay --amount 1500 --order ORD-123";
int result = system(cmd.c_str());
if (result == 0) {
    // Payment successful
}
```

