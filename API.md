# KassaFu API Documentation

KassaFu is a payment bridge between a POS system and a SumUp Solo terminal.
It exposes a REST API built with FastAPI to process payments, monitor terminal status, and manage configuration.

---

# Features

* FastAPI-powered REST API
* Queue-based payment handling
* SumUp Solo integration
* Live payment status polling
* Dynamic configuration reload
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

Create a `config.json` file:

```json
{
  "app": {
    "mode": "real"
  },
  "sumup": {
    "api_key": "YOUR_API_KEY",
    "merchant_code": "YOUR_MERCHANT_CODE",
    "reader_id": "OPTIONAL_READER_ID"
  }
}
```

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

---

### Success Response

```json
{
  "status": "paid",
  "order_id": "ORDER-1001",
  "amount": 12.5,
  "currency": "EUR",
  "message": "Payment completed successfully"
}
```

---

### Queued Response

If another payment is already active:

```json
{
  "success": false,
  "status": "queued",
  "message": "Payment in progress, request queued"
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

Check the status of a payment.

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

### Pending Response

```json
{
  "status": "pending",
  "order_id": "ORDER-1001",
  "amount": 12.5,
  "currency": "EUR"
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
  "message": "Payment completed successfully"
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
  "message": "Card rejected - please try another payment method"
}
```

---

### Idle Response

```json
{
  "status": "idle",
  "message": "No active payment"
}
```

---

## GET `/health`

Health check endpoint.

### Example Response

```json
{
  "status": "healthy",
  "mode": "real",
  "terminal_ready": true,
  "reader_id": "SOLO-123456"
}
```

---

## GET `/reader/status`

Check the SumUp Solo terminal status.

### Example Response

```json
{
  "status": "online",
  "battery": 95,
  "reader_id": "SOLO-123456"
}
```

---

## POST `/config/reload`

Reload the configuration file without restarting the application.

### Success Response

```json
{
  "success": true,
  "message": "Configuration reloaded"
}
```

---

### Failure Response

```json
{
  "success": false,
  "message": "Failed to reinitialize terminal"
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

# Example POS Integration

## Start Payment

```bash
curl -X POST http://127.0.0.1:8888/pay \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORDER-1001",
    "amount_cents": 1250,
    "currency": "EUR"
  }'
```

---

## Poll Payment Status

```bash
curl "http://127.0.0.1:8888/payment/status?order_id=ORDER-1001"
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
* Configuration reloads

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
