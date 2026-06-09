# KassaFu API Documentation

KassaFu is a payment bridge between a POS system and a SumUp Solo terminal.
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
  - [GET /payment/status](#get-paymentstatus)
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
* Live payment status polling
* Dynamic configuration update
* Health and terminal monitoring
* Async payment processing

---

# Requirements

* Python 3.10+
* FastAPI
* Uvicorn
* SumUp Solo terminal
* Valid SumUp API credentials

Install dependencies:

```bash
pip install fastapi uvicorn
```

---

# Configuration

## Installation
Create the ~/zhongcan directory.
Run ./install.sh 
To check if this works, see if port 8888 is used and call : sudo service kassafu status

## Runtime Configuration

KassaFu exposes a runtime configuration API. All changes are **in-memory only** and do not persist across server restarts. To make permanent changes, edit `config.json` directly.

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

## GET `/health`

Just to check if the service is running correct. This does not communicate with SumUp.

### Example
At start of the program you should check if the service is activated. If not, installation is failed or start the service.  

```
curl http://127.0.0.1:8888/health
```
Health check endpoint.

### Example Response

```json
{
  "status": "healthy",
  "mode": "real",
  "terminal_ready": true,
  "reader_id": "SOLO-123456",
  "error_code": 0
}
```curl http://127.0.0.1:8888/health

---

## GET `/reader/status`

Check the SumUp Solo terminal status.

### Example Response

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

Return the current runtime configuration. The `api_key` is intentionally excluded from the response.

### Example

```
curl http://127.0.0.1:8888/config
```

### Example Response

```json
{
  "app": {
    "mode": "real"
  },
  "sumup": {
    "merchant_code": "MN2RA8M1",
    "reader_id": "rdr_6P0860A4S186MV3FHM2Q185AD7",
    "timeout_seconds": 30
  }
}
```

---

## POST `/config`

Update configuration at runtime. Accepts a full or partial configuration object. Only the provided fields are updated; omitted fields retain their current values. Changes are **in-memory only** — edit `config.json` to make permanent changes.

If `reader_id` is omitted, the server will attempt to auto-discover a Solo terminal on the merchant account.

### Request Body

```json
{
  "app": {
    "mode": "real"
  },
  "sumup": {
    "api_key": "sup_sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "merchant_code": "MN2RA8M1",
    "reader_id": "rdr_6P0860A4S186MV3FHM2Q185AD7"
  }
}
```

### Example

Send a full configuration update:

```
curl -X POST http://127.0.0.1:8888/config \
  -H "Content-Type: application/json" \
  -d '{
    "app": {
      "mode": "real"
    },
    "sumup": {
      "api_key": "sup_sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "merchant_code": "MN2RA8M1",
      "reader_id": "rdr_6P0860A4S186MV3FHM2Q185AD7"
    }
  }'
```

Send only the fields you want to change (partial update):

```
curl -X POST http://127.0.0.1:8888/config \
  -H "Content-Type: application/json" \
  -d '{
    "sumup": {
      "api_key": "sup_sk_new_key_here"
    }
  }'
```

Send from a file:

```
curl -X POST http://127.0.0.1:8888/config \
  -H "Content-Type: application/json" \
  -d @config.json
```

### Success Response

```json
{
  "success": true,
  "message": "Configuration updated"
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
SumUp Solo Terminal
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
