# Business case
The Python program will handle communication to the POS computer and to the payment terminal servers: **SumUp** and **myPOS**. It is located at the POS computer.
<img width="632" height="424" alt="image" src="https://github.com/user-attachments/assets/4528b4fc-5068-4148-a87e-8f34c3d88c3e" />

- License: https://github.com/kassaku/kassafu-linux-fastapi/blob/main/LICENSE.md 
- Software: https://github.com/kassaku/kassafu-linux-fastapi/blob/main/SOFTWARE.md
- API: https://github.com/kassaku/kassafu-linux-fastapi/blob/main/API.md
- Example: https://github.com/kassaku/kassafu-linux-fastapi/blob/main/test_real_payment.py  

# Restaurant overview
Payments for payment terminals like **SumUp** and **myPOS**, interface to Angular website as a backend.
KassaFu — The payment bridge between payment terminals (SumUp / myPOS) and your restaurant system.
<img width="623" height="424" alt="openart-image_1778505829245_5fb4cac4_1778505829356_c09c6fd8" src="https://github.com/user-attachments/assets/68ef0a0a-2006-4fc3-adbe-d1087c6f08e8" />

# Installation

Two installation methods are supported:

### 1. Debian package (recommended)

Build and install a `.deb` package that installs to `/usr/share/kassafu`, creates a venv, sets up the systemd service and starts it:

```bash
./create_deb          # builds kassafu.deb
sudo dpkg -i kassafu.deb
```

The service runs as the installing user (`$SUDO_USER`/`$USER`) and always restarts on boot.

### 2. Manual / development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 kassafu.py --server
```

The server listens on `http://127.0.0.1:8888`.

Optional CLI flags (mainly for testing):

```bash
python3 kassafu.py --server --client-url "http://www.kassaku.nl/restaurants/install/config.80581413" \
  --client-key "your-client-secret" --partner-key "your-partner-secret" --id 80581413
python3 kassafu.py --server --port 8888
```

# Configuration

KassaFu starts **unconfigured** and does not decide the terminal type from a default config file. Configuration is pushed at runtime via **`POST /config`** and can be swapped between myPOS and SumUp at any time (hot-swap, in-memory only). The `--client-url`/`--client-key` CLI flags are optional and used for seeding/testing.

### myPOS

```json
POST /config
{
  "partner_url": "http://www.kassaku.nl/restaurants/install/config.partner",
  "client_url": "http://www.kassaku.nl/restaurants/install/config.80581413",
  "partner_key": "your-partner-secret",
  "client_key": "your-client-secret",
  "id": "80581413"
}
```

### Hosting myPOS partner credentials

The myPOS credentials live in two encrypted files hosted on kassaku.nl:

- `config.partner` — the provider/partner credentials (`partner` object).
- `config.<id>` — the customer/merchant credentials (the `mypos` or `sumup` object, one file per terminal id).

Build them from plaintext JSON with `encrypt_partner.py`:

```bash
python3 encrypt_partner.py --key "your-partner-secret" --input config.partner.json --output config.partner
python3 encrypt_partner.py --key "your-client-secret" --input config.80581413.json --output config.80581413
# upload both to the hosted directory
```

Alternatively, create the files interactively — the `create_*.py` scripts ask for
the credentials, an encryption key, and the output filename, write the plaintext
`<name>.json`, and encrypt it to `<name>` in one go:

```bash
python3 create_partner.py     # myPOS provider credentials -> config.partner
python3 create_mypos.py       # myPOS merchant credentials -> config.<terminal_id>
python3 create_sumup.py       # SumUp merchant credentials -> config.<reader_id>
```

> **Note:** Plaintext source files (`config.partner.json`, `config.<id>.json`) are listed in `.gitignore` and will not be committed.

Keys are never stored in code, config, or git. They are supplied at runtime via `POST /config` (or the matching CLI flags) and never returned by `GET /config`.

### SumUp

The interface is identical for SumUp — `client_url` points at a `config.<id>` blob containing a `sumup` section (with `api_key` / `merchant_code`) instead of a `mypos` section.

### Pushing configuration

```bash
curl -X POST http://127.0.0.1:8888/config -H "Content-Type: application/json" -d @config.mypos.json
curl http://127.0.0.1:8888/health        # → "mode": "mypos", "terminal_ready": true
```

The pushed JSON must be the 5-field interface above (`partner_url`, `client_url`, `partner_key`, `client_key`, `id`).

Switching terminal type is also possible on a live server, e.g. swap myPOS → SumUp by posting the SumUp config the same way.

# Supported payment terminals

| Provider | Type | Readers / terminals |
| --- | --- | --- |
| SumUp | Cloud API | Solo, Solo Lite, Air, 3G/4G readers |
| myPOS | ePOS API Gateway | Combo, Mini, Pro, Pad, Virtual |

The active terminal type is resolved from the config section that is sent (`sumup` or `mypos`); the server hot-swaps the implementation on every `POST /config`.

> Note: An earlier CCV Cloud Connect handler (`ccv.py`) was an unused shell and
> has been removed. To add a terminal back: implement one module exposing the
> terminal interface (`init`, `process_payment`, `check_status`, `get_config`,
> `is_ready`, ...) and add a `TERMINAL_CLASSES` entry keyed by its config
> section name; the server auto-detects it from the pushed config.

# Testing

Check whether the server is running and the configured terminal is online:

```bash
python3 test_reader_status_mypos.py     # myPOS terminal status
python3 test_reader_status_sumup.py     # SumUp terminal status
```

Run a real €0.10 payment (requires a live/online terminal):

```bash
python3 test_real_payment.py
```

# API overview

| Endpoint | Description |
| --- | --- |
| `POST /pay` | Start a payment |
| `GET /payment/status?order_id=...` | Poll payment status |
| `GET /payment/cancel?order_id=...` | Cancel an active payment |
| `GET /payment/history` | Last transactions |
| `GET /health` | Server health + active mode |
| `GET /reader/status` | Terminal online/ready status |
| `GET /config` | Current runtime config |
| `POST /config` | Update config / swap terminal type |
| `GET /version` | `{"app": "KassaFu", "version": "1.0.0"}` |

Full documentation: [API.md](API.md)

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

## R2 - Communicate with SumUp Cloud API (or myPOS ePOS Gateway)
Detail	Specification
API base URL	https://api.sumup.com (live) or sandbox
Authentication	Bearer token (Affiliate Key)
Endpoint	POST /v0.1/checkouts
Required fields	amount, currency, description, pay_to_email
Terminal targeting	Use checkout_reference to route to specific Solo

myPOS alternatively uses the **ePOS API Gateway** (`https://api-gateway.mypos.com`) with partner/merchant OAuth credentials and its own `/payment-initialization`, `/payment-execution` endpoints.

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

## R4 - Trigger receipt printing on terminal's built-in printer
Detail	Specification
Method	Payment provider API after payment confirmation (SumUp / myPOS)
Printer destination	The same terminal that processed payment
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
# Send to printer via SumUp's or myPOS's receipt API (if available)
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

myPOS offers a demo gateway (`https://demo-api-gateway.mypos.com`) for testing without real money.

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

