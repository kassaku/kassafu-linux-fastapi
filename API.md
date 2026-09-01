# KassaFu API Documentation

KassaFu is a payment bridge between a POS system and payment terminals (**SumUp** and **myPOS**).
It exposes a REST API built with FastAPI to process payments, monitor terminal status, and manage configuration.

# Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Server](#running-the-server)
- [API Endpoints](#api-endpoints)
  - [POST /pay](#post-pay)
  - [GET /payment/history](#get-paymenthistory)
  - [GET /payment/status](#get-paymentstatus)
  - [GET /payment/cancel](#get-paymentcancel)
  - [GET /health](#get-health)
  - [GET /reader/status](#get-readerstatus)
  - [GET /config](#get-config)
  - [POST /config](#post-config)
- [Payment Flow](#payment-flow)
- [Error Handling](#error-handling)
- [Logging](#logging)
- [Security Notes](#security-notes)
- [License](#license)
  
---

# Features

* FastAPI-powered REST API
* Queue-based payment handling
* SumUp Solo integration
* myPOS ePOS Gateway integration
* Live payment status polling
* Dynamic configuration update (hot-swap between SumUp / myPOS)
* Health and terminal monitoring
* Async payment processing

---

# Requirements

* Python 3.10+
* FastAPI
* Uvicorn
* SumUp Solo terminal or myPOS terminal
* Valid SumUp or myPOS API credentials

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Configuration

## Installation
Run `./install.sh` (installs KassaFu to `/usr/share/kassafu` and enables the `kassafu` systemd service), or build and install the Debian package:

```bash
./create_deb
sudo dpkg -i kassafu.deb
```

To check if this works, see if port 8888 is used and call : sudo service kassafu status

## Runtime Configuration

KassaFu exposes a runtime configuration API. All changes are **in-memory only** and do not persist across server restarts. KassaFu starts unconfigured and receives its terminal configuration (SumUp or myPOS) at runtime via `POST /config`. See the [POST /config](#post-config) endpoint below.

See the [GET /config](#get-config) and [POST /config](#post-config) endpoints below.

---

# Running the Server

```bash
python3 kassafu.py --server
```

Optional arguments:

```bash
--config /path/to/config.json
--port 8888
```

Default server:

```text
http://127.0.0.1:8888
```

---

# API Endpoints

## POST `/pay`

Start a payment request.

### Request Body

```json
{
  "order_id": "ORDER-1001",
  "amount_cents": 1250,
  "currency": "EUR"
}
```

### Parameters

| Field        | Type    | Required | Description             |
| ------------ | ------- | -------- | ----------------------- |
| order_id     | string  | Yes      | Unique order identifier |
| amount_cents | integer | Yes      | Amount in cents         |
| currency     | string  | Yes      | Currency code           |

### Example

```
curl -X POST http://127.0.0.1:8888/pay \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORDER-2026-0001",
    "amount_cents": 1599,
    "currency": "EUR"
  }'
```
---

### Success Response

```json
{
  "status": "paid",
  "order_id": "ORDER-1001",
  "amount": 12.5,
  "currency": "EUR",
  "message": "Payment completed successfully",
  "error_code": 0
}
```

---

### Queued Response

If another payment is already active:

```json
{
  "success": false,
  "status": "queued",
  "message": "Payment in progress, request queued",
  "error_code": 108012
}
```

---

### Error Responses

#### Missing Fields

```json
{
  "detail": "Missing field: order_id"
}
```

#### Terminal Not Ready

```json
{
  "detail": "Terminal not ready"
}
```

---

## GET `/payment/history`

Return the last N transactions from the transaction log (`transactions.log`).

### Query Parameters

| Parameter | Type   | Required | Description                          |
| --------- | ------ | -------- | ------------------------------------ |
| limit     | int    | No       | Number of transactions to return (default 20) |

---

### Example Request

```http
GET /payment/history?limit=5
```

### Example Curl
```
curl "http://127.0.0.1:8888/payment/history?limit=5"
```

### Example Response

```json
{
  "items": [
    {
      "timestamp": "2026-08-01T12:00:00",
      "order_id": "ORDER-1001",
      "amount_cents": 1250,
      "currency": "EUR",
      "status": "successful",
      "transaction_id": "tran_abc123"
    }
  ],
  "error_code": 0
}
```

---

## GET `/payment/status`

Check the status of a payment. After starting any payment, do this for 32 seconds every 2 seconds until an issue happened or until it is payed.
The python file **test_real_payment.py** has a good example of this behavior.

### Query Parameters

| Parameter | Type   | Required | Description       |
| --------- | ------ | -------- | ----------------- |
| order_id  | string | Yes      | Order ID to check |

---

### Example Request

```http
GET /payment/status?order_id=ORDER-1001
```

---
### Example Curl
```
curl "http://127.0.0.1:8888/payment/status?order_id=ORDER-1001"
```

### Pending Response

```json
{
  "status": "pending",
  "order_id": "ORDER-1001",
  "amount": 12.5,
  "currency": "EUR",
  "error_code": 0
}
```

---

### Paid Response

```json
{
  "status": "paid",
  "order_id": "ORDER-1001",
  "amount": 12.5,
  "currency": "EUR",
  "message": "Payment completed successfully",
  "error_code": 0
}
```

---

### Failed Response

```json
{
  "status": "failed",
  "order_id": "ORDER-1001",
  "amount": 12.5,
  "currency": "EUR",
  "message": "Card rejected - please try another payment method",
  "error_code": 108009
}
```

---

### Idle Response

```json
{
  "status": "idle",
  "message": "No active payment",
  "error_code": 0
}
```

---

## GET / DELETE `/payment/cancel`

Cancel an active payment. Accepts both `GET` and `DELETE`.

### Query Parameters

| Parameter | Type   | Required | Description       |
| --------- | ------ | -------- | ----------------- |
| order_id  | string | Yes      | Order ID to cancel |

### Example Request

```http
GET /payment/cancel?order_id=ORDER-1001
```

### Example Curl
```
curl "http://127.0.0.1:8888/payment/cancel?order_id=ORDER-1001"
```

### Success Response

```json
{
  "success": true,
  "status": "cancelled",
  "message": "Payment cancelled",
  "error_code": 0
}
```

### Not Found Response (HTTP 404)

```json
{
  "success": false,
  "status": "not_found",
  "message": "No active payment found for order ORDER-1001",
  "error_code": 108002
}
```

### Terminal Not Ready Response (HTTP 503)

```json
{
  "status": "error",
  "message": "Terminal not ready",
  "error_code": 108008
}
```

---

## GET `/health`

Just to check if the service is running correct. This does not communicate with any terminal.

### Example
At start of the program you should check if the service is activated. If not, installation is failed or start the service.  

```
curl http://127.0.0.1:8888/health
```
Health check endpoint.

### Example Response

```json
{
  "status": "unconfigured",
  "mode": null,
  "terminal_ready": false,
  "error_code": 0
}
```

When configured, `mode` reports the active terminal type (`"mypos"` or `"sumup"`):

```json
{
  "status": "healthy",
  "mode": "mypos",
  "terminal_ready": true,
  "error_code": 0
}
```

---

## GET `/reader/status`

Check the configured terminal (SumUp or myPOS) status.

### Example Response (myPOS)

```json
{
  "online": true,
  "ready": true,
  "terminal_id": "80581413",
  "terminal_name": "utra2601",
  "model": "N96",
  "serial_number": "N96N960WC69104",
  "device_currency": "EUR",
  "error_code": 0
}
```

### Example Response (SumUp)

```json
{
  "status": "online",
  "battery": 95,
  "reader_id": "SOLO-123456",
  "error_code": 0
}
```
---

## GET `/config`

Return the current runtime configuration. The `api_key`/`client_secret` are intentionally excluded from the response.

### Example

```
curl http://127.0.0.1:8888/config
```

### Example Response (myPOS)

```json
{
  "app": {
    "mode": "mypos"
  },
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "terminal_id": "80581413"
  }
}
```

### Example Response (SumUp)

```json
{
  "app": {
    "mode": "sumup"
  },
  "sumup": {
    "merchant_code": "MN2RA8M1",
    "reader_id": "rdr_6P0860A4S186MV3FHM2Q185AD7",
    "timeout_seconds": 30
  }
}
```

When no configuration has been pushed yet:

```json
{
  "app": {
    "mode": null
  }
}
```

---

## POST `/config`

Update configuration at runtime and **hot-swap the terminal implementation** (SumUp ↔ myPOS). The posted object replaces the runtime configuration entirely; the previous terminal is swapped out and the new one initialized in its place. Changes are **in-memory only** and do not persist across restarts.

If `reader_id` (SumUp) or `terminal_id` (myPOS) is omitted, the server attempts to auto-discover a terminal on the account.

The request is rejected (HTTP 409) while a payment is in progress.

### Request Body — myPOS

```json
{
  "app": {
    "name": "KassaFu",
    "mode": "mypos"
  },
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "partner": {
      "client_id": "client_...",
      "client_secret": "secret_...",
      "application_id": "mps-app-...",
      "partner_id": "mps-p-..."
    },
    "merchant": {
      "client_id": "cli_...",
      "client_secret": "sec_..."
    },
    "terminal_id": "80581413"
  }
}
```

### Request Body — SumUp

```json
{
  "app": {
    "name": "KassaFu",
    "mode": "sumup"
  },
  "sumup": {
    "api_key": "sup_sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "merchant_code": "MN2RA8M1",
    "reader_id": "rdr_6P0860A4S186MV3FHM2Q185AD7"
  }
}
```

### Example — switch to myPOS

```
curl -X POST http://127.0.0.1:8888/config \
  -H "Content-Type: application/json" \
  -d @config.mypos.json
```

### Example — switch to SumUp

```
curl -X POST http://127.0.0.1:8888/config \
  -H "Content-Type: application/json" \
  -d @config.sumup.json
```

### Success Response

```json
{
  "success": true,
  "terminal_type": "mypos"
}
```

### Error Response

```json
{
  "detail": "Invalid configuration"
}
```

---

# Payment Flow

<img width="2528" height="1696" alt="openart-image_1778071063732_b27b5707_1778071063856_cae207be" src="https://github.com/user-attachments/assets/4ef3b4b4-70d9-49bc-a926-f2e65f2531ae" />

```text
POS System
    |
    | POST /pay
    v
KassaFu API
    |
    | Queue handling
    v
Payment terminal (SumUp Solo / myPOS)
    |
    | Payment result
    v
/payment/status
```

---
# Logging

Logs are written to:

```text
kassafu.log
```

Log output includes:

* Payment processing
* Queue events
* Terminal initialization
* Errors and warnings
* Configuration udate

---

# Error Handling

KassaFu returns standard HTTP status codes.

| Code | Meaning               |
| ---- | --------------------- |
| 200  | Success               |
| 202  | Payment queued        |
| 400  | Bad request           |
| 500  | Internal server error |
| 503  | Terminal unavailable  |

## Error Codes

Every JSON response includes an `error_code` field. `0` means success. Non-zero values indicate a specific error condition:

| Error Code | Description |
|------------|-------------|
| 0 | Success / no error |
| 108001 | General error |
| 108002 | Not found |
| 108003 | Missing or invalid configuration |
| 108004 | Connection error |
| 108005 | Timeout |
| 108006 | Initialization error |
| 108007 | Validation error |
| 108008 | Not ready / offline |
| 108009 | Payment failed / rejected |
| 108010 | Reader / terminal error |
| 108011 | API error (HTTP error from upstream) |
| 108012 | Payment queued |
| 108013 | Cancelled |
| 108051 | File / input error (scripts) |

---

# Security Notes

* Never commit your `config.json` with real credentials.
* Restrict API access to trusted POS systems.
* Use firewall rules when exposing the API.
* Consider reverse proxy authentication in production.

---

# License

MIT License

Copyright (c) 2026 Houkes Horeca Applications
